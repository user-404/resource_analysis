from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Any

from kubernetes import client
from kubernetes.config import load_kube_config_from_dict
import requests
import yaml

from app.config import get_settings
from app.recommendations import recommend
from app.secrets import secret_provider

MIB = 1024**2
MILLICORE = 0.001


def _resource_quantity(value: str | None, resource: str) -> float:
    if not value:
        return 0.0
    if resource == "cpu":
        units = {"m": 0.001, "u": 0.000001, "n": 0.000000001}
        for suffix, multiplier in units.items():
            if value.endswith(suffix):
                return float(value[: -len(suffix)]) * multiplier
        return float(value)
    suffixes = {
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
    }
    for suffix, multiplier in suffixes.items():
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * multiplier
    return float(value)


def _pod_allocation(pod: Any) -> dict[str, float]:
    totals = {
        "cpu_request": 0.0,
        "cpu_limit": 0.0,
        "memory_request": 0.0,
        "memory_limit": 0.0,
    }
    for container in pod.spec.containers or []:
        resources = container.resources
        requests = resources.requests or {} if resources else {}
        limits = resources.limits or {} if resources else {}
        totals["cpu_request"] += _resource_quantity(requests.get("cpu"), "cpu")
        totals["cpu_limit"] += _resource_quantity(limits.get("cpu"), "cpu")
        totals["memory_request"] += _resource_quantity(requests.get("memory"), "memory")
        totals["memory_limit"] += _resource_quantity(limits.get("memory"), "memory")
    return totals


def _workload_for_pod(pod: Any, replica_sets: dict[str, Any], jobs: dict[str, Any]) -> tuple[str, str]:
    owners = pod.metadata.owner_references or []
    if not owners:
        return pod.metadata.name, "Pod"
    owner = owners[0]
    if owner.kind == "ReplicaSet" and owner.name in replica_sets:
        rs_owner = (replica_sets[owner.name].metadata.owner_references or [None])[0]
        if rs_owner and rs_owner.kind == "Deployment":
            return rs_owner.name, "Deployment"
    if owner.kind == "Job" and owner.name in jobs:
        job_owner = (jobs[owner.name].metadata.owner_references or [None])[0]
        if job_owner and job_owner.kind == "CronJob":
            return job_owner.name, "CronJob"
        return owner.name, "Job"
    return owner.name, owner.kind


def _prometheus_range(
    url: str,
    token: str | None,
    query: str,
    start: datetime,
    end: datetime,
    step: int,
) -> list[tuple[dict[str, str], dict[datetime, float]]]:
    endpoint = url.rstrip("/") + "/api/v1/query_range"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(
        endpoint,
        params={"query": query, "start": start.timestamp(), "end": end.timestamp(), "step": step},
        headers=headers,
        timeout=(10, 120),
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload.get('error', 'unknown error')}")
    series = []
    for result in payload.get("data", {}).get("result", []):
        labels = result.get("metric", {})
        points: dict[datetime, float] = {}
        for timestamp, value in result.get("values", []):
            numeric = float(value)
            if math.isfinite(numeric):
                points[datetime.fromtimestamp(float(timestamp), timezone.utc).replace(tzinfo=None)] = numeric
        if points:
            series.append((labels, points))
    return series


def _pod_usage_series(
    results: list[tuple[dict[str, str], dict[datetime, float]]],
) -> dict[str, dict[datetime, float]]:
    series: dict[str, dict[datetime, float]] = defaultdict(dict)
    for labels, points in results:
        pod_name = labels.get("pod")
        if pod_name:
            series[pod_name].update(points)
    return series


def _historical_job_owners(
    pod_owner_results: list[tuple[dict[str, str], dict[datetime, float]]],
    job_owner_results: list[tuple[dict[str, str], dict[datetime, float]]],
) -> tuple[dict[str, list[tuple[datetime, str]]], dict[str, list[tuple[datetime, str]]]]:
    jobs_by_pod_time: dict[str, dict[datetime, str]] = defaultdict(dict)
    cronjobs_by_job_time: dict[str, dict[datetime, str]] = defaultdict(dict)

    for labels, points in pod_owner_results:
        if labels.get("owner_kind") != "Job":
            continue
        pod_name = labels.get("pod")
        job_name = labels.get("owner_name")
        if pod_name and job_name:
            jobs_by_pod_time[pod_name].update({timestamp: job_name for timestamp in points})

    for labels, points in job_owner_results:
        if labels.get("owner_kind") != "CronJob":
            continue
        job_name = labels.get("job_name")
        cronjob_name = labels.get("owner_name")
        if job_name and cronjob_name:
            cronjobs_by_job_time[job_name].update({timestamp: cronjob_name for timestamp in points})

    return (
        {name: sorted(points.items()) for name, points in jobs_by_pod_time.items()},
        {name: sorted(points.items()) for name, points in cronjobs_by_job_time.items()},
    )


def _owner_at(
    owners_by_name: dict[str, list[tuple[datetime, str]]],
    name: str,
    sampled_at: datetime,
    max_age_seconds: int = 300,
) -> str | None:
    points = owners_by_name.get(name, [])
    index = bisect_right([timestamp for timestamp, _ in points], sampled_at) - 1
    if index < 0:
        return None
    owner_timestamp, owner_name = points[index]
    if (sampled_at - owner_timestamp).total_seconds() > max_age_seconds:
        return None
    return owner_name


def collect(input_data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kubeconfig_text = secret_provider.resolve(input_data["kubeconfig_secret_ref"])
    prom_token = (
        secret_provider.resolve(input_data["prometheus_secret_ref"])
        if input_data.get("prometheus_secret_ref")
        else None
    )
    kubeconfig = yaml.safe_load(kubeconfig_text)
    if not isinstance(kubeconfig, dict):
        raise ValueError("Resolved kubeconfig secret is not a Kubernetes config document")
    load_kube_config_from_dict(kubeconfig)
    core = client.CoreV1Api()
    apps = client.AppsV1Api()
    batch = client.BatchV1Api()
    namespace = input_data["namespace"]

    pods = core.list_namespaced_pod(namespace).items
    replica_sets = {obj.metadata.name: obj for obj in apps.list_namespaced_replica_set(namespace).items}
    jobs = {obj.metadata.name: obj for obj in batch.list_namespaced_job(namespace).items}
    pod_metadata: dict[str, dict[str, Any]] = {}
    workload_pods: dict[tuple[str, str], set[str]] = defaultdict(set)
    for pod in pods:
        name, workload_type = _workload_for_pod(pod, replica_sets, jobs)
        key = (name, workload_type)
        pod_name = pod.metadata.name
        pod_metadata[pod_name] = {"workload": key, "allocation": _pod_allocation(pod)}
        workload_pods[key].add(pod_name)

    end = datetime.now(timezone.utc)
    start = end.timestamp() - input_data["days_to_collect"] * 86400
    start_dt = datetime.fromtimestamp(start, timezone.utc)
    cpu_template = get_settings().prometheus_cpu_query_template
    memory_template = get_settings().prometheus_memory_query_template
    escaped_namespace = namespace.replace("\\", "\\\\").replace('"', '\\"')
    cpu_series = _pod_usage_series(_prometheus_range(
        input_data["prometheus_url"], prom_token, cpu_template.format(namespace=escaped_namespace),
        start_dt, end, input_data["step_seconds"],
    ))
    memory_series = _pod_usage_series(_prometheus_range(
        input_data["prometheus_url"], prom_token, memory_template.format(namespace=escaped_namespace),
        start_dt, end, input_data["step_seconds"],
    ))

    # Retained kube-state-metrics owner series let us map expired Job pods to
    # their CronJob at each historical sample timestamp.
    pod_owner_query = (
        "max by (pod, owner_name, owner_kind) "
        f'(last_over_time(kube_pod_owner{{namespace="{escaped_namespace}",'
        'owner_kind="Job",owner_is_controller="true"}[5m]))'
    )
    job_owner_query = (
        "max by (job_name, owner_name, owner_kind) "
        f'(last_over_time(kube_job_owner{{namespace="{escaped_namespace}",'
        'owner_kind="CronJob",owner_is_controller="true"}[5m]))'
    )
    historical_pod_owners = _prometheus_range(
        input_data["prometheus_url"], prom_token, pod_owner_query, start_dt, end, input_data["step_seconds"],
    )
    historical_job_owners = _prometheus_range(
        input_data["prometheus_url"], prom_token, job_owner_query, start_dt, end, input_data["step_seconds"],
    )
    historical_jobs_by_pod_time, historical_cronjobs_by_job_time = _historical_job_owners(
        historical_pod_owners,
        historical_job_owners,
    )

    sample_keys = {(pod, timestamp) for pod, points in cpu_series.items() for timestamp in points}
    sample_keys |= {(pod, timestamp) for pod, points in memory_series.items() for timestamp in points}
    if not sample_keys:
        raise RuntimeError("Prometheus returned no pod usage samples for the requested namespace and period")

    raw_rows = []
    series_by_workload: dict[tuple[str, str], dict[datetime, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for pod_name, sampled_at in sorted(sample_keys, key=lambda item: (item[0], item[1])):
        metadata = pod_metadata.get(pod_name)
        historical_job = _owner_at(historical_jobs_by_pod_time, pod_name, sampled_at)
        historical_cronjob = _owner_at(historical_cronjobs_by_job_time, historical_job, sampled_at) if historical_job else None
        if historical_cronjob:
            metadata = {
                "workload": (historical_cronjob, "CronJob"),
                "allocation": (
                    metadata["allocation"]
                    if metadata and metadata["workload"] == (historical_cronjob, "CronJob")
                    else {
                        "cpu_request": 0.0,
                        "cpu_limit": 0.0,
                        "memory_request": 0.0,
                        "memory_limit": 0.0,
                    }
                ),
            }
            pod_metadata[pod_name] = metadata
            workload_pods[metadata["workload"]].add(pod_name)
        if not metadata:
            key = (pod_name, "UnattributedPod")
            metadata = {
                "workload": key,
                "allocation": {
                    "cpu_request": 0.0,
                    "cpu_limit": 0.0,
                    "memory_request": 0.0,
                    "memory_limit": 0.0,
                },
            }
            pod_metadata[pod_name] = metadata
            workload_pods[key].add(pod_name)
        workload_name, workload_type = metadata["workload"]
        cpu = cpu_series.get(pod_name, {}).get(sampled_at)
        memory = memory_series.get(pod_name, {}).get(sampled_at)
        if cpu is not None:
            series_by_workload[(workload_name, workload_type)][sampled_at]["cpu"] = (
                series_by_workload[(workload_name, workload_type)][sampled_at].get("cpu", 0.0) + cpu
            )
        if memory is not None:
            series_by_workload[(workload_name, workload_type)][sampled_at]["memory"] = (
                series_by_workload[(workload_name, workload_type)][sampled_at].get("memory", 0.0) + memory
            )
        allocation = metadata["allocation"]
        raw_rows.append({
            "namespace": namespace,
            "workload_name": workload_name,
            "workload_type": workload_type,
            "pod_name": pod_name,
            "sampled_at": sampled_at,
            "cpu_cores": cpu,
            "memory_bytes": memory,
            "allocated_cpu_request_cores": allocation["cpu_request"],
            "allocated_cpu_limit_cores": allocation["cpu_limit"],
            "allocated_memory_request_bytes": allocation["memory_request"],
            "allocated_memory_limit_bytes": allocation["memory_limit"],
        })

    aggregates = []
    for key, time_series in series_by_workload.items():
        if key[1] == "UnattributedPod":
            continue
        cpu_points = [values["cpu"] for values in time_series.values() if "cpu" in values]
        memory_points = [values["memory"] for values in time_series.values() if "memory" in values]
        workload_name, workload_type = key
        pod_names = workload_pods.get(key, set())
        totals = {
            "allocated_cpu_request_cores": sum(pod_metadata[p]["allocation"]["cpu_request"] for p in pod_names),
            "allocated_cpu_limit_cores": sum(pod_metadata[p]["allocation"]["cpu_limit"] for p in pod_names),
            "allocated_memory_request_bytes": sum(pod_metadata[p]["allocation"]["memory_request"] for p in pod_names),
            "allocated_memory_limit_bytes": sum(pod_metadata[p]["allocation"]["memory_limit"] for p in pod_names),
        }
        policy = {
            "statistic": "peak",
            "targetUtilization": input_data["target_utilization"],
            "limitHeadroomMultiplier": input_data["limit_headroom_multiplier"],
            "cpuRounding": "1 millicore",
            "memoryRounding": "1 MiB",
        }
        cpu_req, cpu_limit = recommend(
            max(cpu_points) if cpu_points else None, input_data["target_utilization"],
            input_data["limit_headroom_multiplier"], MILLICORE,
        )
        mem_req, mem_limit = recommend(
            max(memory_points) if memory_points else None, input_data["target_utilization"],
            input_data["limit_headroom_multiplier"], MIB,
        )
        aggregates.append({
            "namespace": namespace,
            "workload_name": workload_name,
            "workload_type": workload_type,
            "pod_count": len(pod_names),
            "sample_count": len(time_series),
            "average_cpu_cores": sum(cpu_points) / len(cpu_points) if cpu_points else None,
            "peak_cpu_cores": max(cpu_points) if cpu_points else None,
            "average_memory_bytes": sum(memory_points) / len(memory_points) if memory_points else None,
            "peak_memory_bytes": max(memory_points) if memory_points else None,
            **totals,
            "suggested_cpu_request_cores": cpu_req,
            "suggested_cpu_limit_cores": cpu_limit,
            "suggested_memory_request_bytes": mem_req,
            "suggested_memory_limit_bytes": mem_limit,
            "recommendation_policy": policy,
        })
    return raw_rows, aggregates
