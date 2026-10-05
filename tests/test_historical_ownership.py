from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.collector import _historical_job_owners, _owner_at, _pod_usage_series, collect


def test_prometheus_pod_owner_samples_can_be_joined_to_historical_cronjob():
    sampled_at = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    pod_owners = [
        (
            {"pod": "cpu-cron-demo-123-pod-a", "owner_name": "cpu-cron-demo-123", "owner_kind": "Job"},
            {sampled_at: 1.0},
        ),
        (
            {"pod": "cpu-cron-demo-456-pod-b", "owner_name": "cpu-cron-demo-456", "owner_kind": "Job"},
            {sampled_at: 1.0},
        ),
        (
            {"pod": "standalone-pod", "owner_name": "standalone", "owner_kind": "ReplicaSet"},
            {sampled_at: 1.0},
        ),
    ]
    job_owners = [
        (
            {"job_name": "cpu-cron-demo-123", "owner_name": "cpu-cron-demo", "owner_kind": "CronJob"},
            {sampled_at: 1.0},
        ),
        (
            {"job_name": "cpu-cron-demo-456", "owner_name": "cpu-cron-demo", "owner_kind": "CronJob"},
            {sampled_at: 1.0},
        ),
    ]

    jobs_by_pod_time, cronjobs_by_job_time = _historical_job_owners(pod_owners, job_owners)

    job_name = _owner_at(jobs_by_pod_time, "cpu-cron-demo-123-pod-a", sampled_at)
    assert job_name == "cpu-cron-demo-123"
    assert _owner_at(cronjobs_by_job_time, job_name, sampled_at) == "cpu-cron-demo"
    second_job = _owner_at(jobs_by_pod_time, "cpu-cron-demo-456-pod-b", sampled_at)
    assert _owner_at(cronjobs_by_job_time, second_job, sampled_at) == "cpu-cron-demo"
    assert _owner_at(jobs_by_pod_time, "standalone-pod", sampled_at) is None


def test_historical_owner_mapping_uses_recent_sample_but_rejects_stale_owner():
    owner_sample = datetime(2026, 10, 5, 12, 0)
    owners = {"pod-a": [(owner_sample, "job-a")]}

    assert _owner_at(owners, "pod-a", datetime(2026, 10, 5, 12, 4, 59)) == "job-a"
    assert _owner_at(owners, "pod-a", datetime(2026, 10, 5, 12, 5, 1)) is None


def test_usage_query_parser_keeps_each_pod_series():
    sampled_at = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    results = [
        ({"pod": "pod-a", "container": "app"}, {sampled_at: 0.12}),
        ({"pod": "pod-b", "container": "app"}, {sampled_at: 0.08}),
        ({"container": "missing-pod-label"}, {sampled_at: 0.3}),
    ]

    assert _pod_usage_series(results) == {
        "pod-a": {sampled_at: 0.12},
        "pod-b": {sampled_at: 0.08},
    }


def test_unattributed_samples_are_returned_raw_without_workload_aggregate():
    sampled_at = datetime(2026, 10, 5, 12, 0)
    core = Mock()
    core.list_namespaced_pod.return_value.items = []
    apps = Mock()
    apps.list_namespaced_replica_set.return_value.items = []
    batch = Mock()
    batch.list_namespaced_job.return_value.items = []
    input_data = {
        "kubeconfig_secret_ref": "env://KUBECONFIG_DEV",
        "prometheus_secret_ref": None,
        "namespace": "demo",
        "days_to_collect": 1,
        "step_seconds": 300,
        "prometheus_url": "http://prometheus.example",
        "target_utilization": 0.8,
        "limit_headroom_multiplier": 1.2,
    }

    with (
        patch("app.collector.secret_provider.resolve", return_value="apiVersion: v1"),
        patch("app.collector.load_kube_config_from_dict"),
        patch("app.collector.client.CoreV1Api", return_value=core),
        patch("app.collector.client.AppsV1Api", return_value=apps),
        patch("app.collector.client.BatchV1Api", return_value=batch),
        patch("app.collector.get_settings", return_value=SimpleNamespace(
            prometheus_cpu_query_template="cpu",
            prometheus_memory_query_template="memory",
        )),
        patch("app.collector._prometheus_range", side_effect=[
            [({"pod": "old-cron-pod"}, {sampled_at: 0.02})],
            [({"pod": "old-cron-pod"}, {sampled_at: 600000.0})],
            [],
            [],
        ]),
    ):
        raw_rows, aggregates = collect(input_data)

    assert len(raw_rows) == 1
    assert raw_rows[0]["workload_type"] == "UnattributedPod"
    assert raw_rows[0]["pod_name"] == "old-cron-pod"
    assert raw_rows[0]["cpu_cores"] == 0.02
    assert raw_rows[0]["memory_bytes"] == 600000.0
    assert aggregates == []
