from pathlib import Path

import yaml


def test_local_real_data_fixture_has_services_jobs_and_resource_bounds():
    manifest = Path(__file__).parents[1] / "examples" / "real-test-workloads.yaml"
    resources = [resource for resource in yaml.safe_load_all(manifest.read_text()) if resource]

    named = {(resource["kind"], resource["metadata"]["name"]): resource for resource in resources}
    assert ("Deployment", "cpu-memory-demo") in named
    assert ("Deployment", "api-gateway") in named
    assert ("Deployment", "catalog-service") in named
    assert ("CronJob", "cpu-cron-demo") in named
    assert ("CronJob", "report-generator") in named
    assert ("CronJob", "cleanup-worker") in named
    assert ("Job", "initial-index-build") in named
    assert ("Service", "api-gateway") in named
    assert ("Service", "catalog-service") in named

    for (kind, name), resource in named.items():
        if kind not in {"Deployment", "Job", "CronJob"}:
            continue
        template = resource["spec"].get("template") or resource["spec"]["jobTemplate"]["spec"]["template"]
        for container in template["spec"]["containers"]:
            resources = container.get("resources", {})
            assert resources.get("requests"), f"{name}/{container['name']} needs resource requests"
            limits = resources.get("limits", {})
            assert limits.get("cpu"), f"{name}/{container['name']} needs a CPU limit"
            assert limits.get("memory"), f"{name}/{container['name']} needs a memory limit"
