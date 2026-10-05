from datetime import timedelta
import math
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.models import CollectionRun, RawUsageSample, WorkloadAggregate
from app.recommendations import recommend
from app.service import utcnow

MIB = 1024**2

WORKLOADS = [
    {
        "name": "checkout",
        "type": "Deployment",
        "pods": ["checkout-7c9d4f6b8d-a1b2c", "checkout-7c9d4f6b8d-d3e4f"],
        "cpu_request": 0.25,
        "cpu_limit": 0.5,
        "memory_request": 256 * MIB,
        "memory_limit": 512 * MIB,
        "peak_cpu": 0.34,
        "peak_memory": 310 * MIB,
    },
    {
        "name": "catalog",
        "type": "Deployment",
        "pods": ["catalog-55b7f8c44f-a1b2c", "catalog-55b7f8c44f-d3e4f"],
        "cpu_request": 0.2,
        "cpu_limit": 0.6,
        "memory_request": 192 * MIB,
        "memory_limit": 512 * MIB,
        "peak_cpu": 0.48,
        "peak_memory": 225 * MIB,
    },
    {
        "name": "payments",
        "type": "StatefulSet",
        "pods": ["payments-0", "payments-1"],
        "cpu_request": 0.5,
        "cpu_limit": 1.0,
        "memory_request": 512 * MIB,
        "memory_limit": 1024 * MIB,
        "peak_cpu": 0.62,
        "peak_memory": 720 * MIB,
    },
    {
        "name": "email-dispatch",
        "type": "CronJob",
        "pods": ["email-dispatch-28840120-5k2mx", "email-dispatch-28841560-m9x4p"],
        "cpu_request": 0.1,
        "cpu_limit": 0.5,
        "memory_request": 128 * MIB,
        "memory_limit": 384 * MIB,
        "peak_cpu": 0.39,
        "peak_memory": 280 * MIB,
    },
    {
        "name": "daily-reconciliation",
        "type": "CronJob",
        "pods": ["daily-reconciliation-28840800-h7q2k"],
        "cpu_request": 0.25,
        "cpu_limit": 1.0,
        "memory_request": 256 * MIB,
        "memory_limit": 768 * MIB,
        "peak_cpu": 0.77,
        "peak_memory": 590 * MIB,
    },
]


def create_demo_collection(
    db: Session,
    namespace: str,
    days: int,
    currency: str,
    cpu_rate_per_core_hour: float | None,
    memory_rate_per_gib_hour: float | None,
) -> CollectionRun:
    run_id = str(uuid.uuid4())
    created_at = utcnow()
    run = CollectionRun(
        id=run_id,
        environment="DEMO (synthetic)",
        namespace=namespace,
        lookback_days=days,
        status="running",
        input_json={
            "demo": True,
            "synthetic": True,
            "namespace": namespace,
            "days_to_collect": days,
            "target_utilization": 0.8,
            "limit_headroom_multiplier": 1.2,
            "currency": currency,
            "cpu_rate_per_core_hour": cpu_rate_per_core_hour,
            "memory_rate_per_gib_hour": memory_rate_per_gib_hour,
        },
        created_at=created_at,
        started_at=created_at,
    )
    db.add(run)
    try:
        db.flush()
        _write_demo_data(db, run_id, namespace, days)
        run.status = "completed"
        run.completed_at = utcnow()
        db.commit()
        db.refresh(run)
        return run
    except Exception:
        db.rollback()
        raise


def _write_demo_data(db: Session, run_id: str, namespace: str, days: int) -> None:
    end = utcnow().replace(minute=0, second=0, microsecond=0)
    sample_count_per_pod = days * 24

    for workload in WORKLOADS:
        samples: list[dict[str, Any]] = []
        unique_pods = workload["pods"]
        for sample_index in range(sample_count_per_pod):
            sampled_at = end - timedelta(hours=sample_count_per_pod - sample_index)
            phase = (sample_index % 24) / 24 * math.tau
            daily_factor = 0.62 + 0.16 * (1 + math.sin(phase - math.pi / 2))
            weekly_factor = 0.92 + 0.08 * math.sin(sample_index / max(sample_count_per_pod, 1) * math.tau)
            factor = min(0.92, daily_factor * weekly_factor)
            if sample_index == sample_count_per_pod // 2:
                factor = 1.0

            pod_name = unique_pods[sample_index % len(unique_pods)]
            cpu = workload["peak_cpu"] * factor
            memory = workload["peak_memory"] * min(0.98, 0.72 + 0.22 * factor)
            if factor == 1.0:
                memory = workload["peak_memory"]

            samples.append({"at": sampled_at, "cpu": cpu, "memory": memory})
            db.add(
                RawUsageSample(
                    run_id=run_id,
                    namespace=namespace,
                    workload_name=workload["name"],
                    workload_type=workload["type"],
                    pod_name=pod_name,
                    sampled_at=sampled_at,
                    cpu_cores=cpu / len(unique_pods),
                    memory_bytes=memory / len(unique_pods),
                    allocated_cpu_request_cores=workload["cpu_request"],
                    allocated_cpu_limit_cores=workload["cpu_limit"],
                    allocated_memory_request_bytes=workload["memory_request"],
                    allocated_memory_limit_bytes=workload["memory_limit"],
                )
            )

        cpu_values = [sample["cpu"] for sample in samples]
        memory_values = [sample["memory"] for sample in samples]
        cpu_request, cpu_limit = recommend(max(cpu_values), 0.8, 1.2, 0.001)
        memory_request, memory_limit = recommend(max(memory_values), 0.8, 1.2, MIB)
        pod_count = len(unique_pods)
        db.add(
            WorkloadAggregate(
                run_id=run_id,
                namespace=namespace,
                workload_name=workload["name"],
                workload_type=workload["type"],
                pod_count=pod_count,
                sample_count=len(samples),
                average_cpu_cores=sum(cpu_values) / len(cpu_values),
                peak_cpu_cores=max(cpu_values),
                average_memory_bytes=sum(memory_values) / len(memory_values),
                peak_memory_bytes=max(memory_values),
                allocated_cpu_request_cores=workload["cpu_request"] * pod_count,
                allocated_cpu_limit_cores=workload["cpu_limit"] * pod_count,
                allocated_memory_request_bytes=workload["memory_request"] * pod_count,
                allocated_memory_limit_bytes=workload["memory_limit"] * pod_count,
                suggested_cpu_request_cores=cpu_request,
                suggested_cpu_limit_cores=cpu_limit,
                suggested_memory_request_bytes=memory_request,
                suggested_memory_limit_bytes=memory_limit,
                recommendation_policy={
                    "statistic": "peak",
                    "targetUtilization": 0.8,
                    "limitHeadroomMultiplier": 1.2,
                    "cpuRounding": "1 millicore",
                    "memoryRounding": "1 MiB",
                    "dataSource": "synthetic demo data",
                },
            )
        )
