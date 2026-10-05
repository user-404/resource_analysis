# Kubernetes Resource Analysis

FastAPI API and a separate MySQL-backed worker for collecting Kubernetes allocation and Prometheus usage, then producing per-workload resource recommendations and optional request-based cost estimates.

For component diagrams, request-to-result data flow, database tables, and calculation details, see [Architecture and how it works](docs/architecture-and-working.md).

## Current behavior

- The API accepts environment, namespace, lookback days, kubeconfig and Prometheus secret references, and recommendation settings. It does not accept or store user, organization, or config IDs.
- The worker discovers namespace pods and associates ReplicaSet pods with Deployments and Job pods with CronJobs when their owner resources are still available.
- Prometheus range queries collect CPU cores and memory working-set bytes by pod. Query templates can be changed with `PROMETHEUS_CPU_QUERY_TEMPLATE` and `PROMETHEUS_MEMORY_QUERY_TEMPLATE`; templates must return a `pod` label.
- Existing requests and limits are read from pod container specs and summed across observed pods. Raw points are stored in `raw_usage_samples`; workload averages, peaks, allocations, and recommendations are stored in `workload_aggregates`.
- Requests are rounded up to 1 millicore or 1 MiB using `peak / targetUtilization` (default 80%). Limits are rounded up from `peak * limitHeadroomMultiplier` (default 1.2x). These values are configurable per run.
- Optional cost estimates compare current with suggested CPU/memory requests using user-supplied per-vCPU-hour and per-GiB-hour rates. There are no assumed provider prices. Estimates assume requests are continuously allocated for 730 hours/month and 8,760 hours/year; they are capacity-cost estimates, not cloud-bill guarantees. CronJob estimates need runtime-aware pricing to reflect intermittent execution.
- Secret references and endpoint are saved with the run for worker pickup; resolved secret values are not saved. The local provider accepts only `env://NAME`, resolved from `APP_SECRET_NAME`. Implement a cloud secret-manager provider before production deployment.

## Setup A: synthetic demo (recommended first test)

This path uses fake, clearly labeled sample measurements. It needs no Python, `.env`, kubeconfig, Kubernetes cluster, Prometheus, or credentials.

### Prerequisites

- A computer running macOS, Windows, or Linux.
- Git, to clone the repository.
- Docker Desktop on macOS/Windows, or Docker Engine plus the Docker Compose plugin on Linux.
- Internet access for the first clone and container-image downloads.

Install Git and Docker using the official instructions for your OS:

- Git: <https://git-scm.com/downloads>
- Docker Desktop: <https://docs.docker.com/get-started/get-docker/>
- Docker Engine / Compose on Linux: <https://docs.docker.com/engine/install/>

After installing Docker, open Docker Desktop (macOS/Windows) or start the Docker service (Linux). Check the tools are available:

```sh
git --version
docker --version
docker compose version
```

### Start the application

Replace `<repository-url>` with the Git clone URL:

```sh
git clone <repository-url>
cd resource_analysis
docker compose up --build
```

The first build can take several minutes. Wait until the logs show MySQL is healthy and Uvicorn has started, then open **http://localhost:8000**. Click **Load synthetic demo data**. To show cost estimates too, expand **Optional cost rates**, enter both rates below, and then load a new demo:

| Input | Demo-only example |
| --- | --- |
| Currency | `USD` |
| Cost per vCPU-hour | `0.04` |
| Cost per GiB-hour | `0.005` |

These are illustrative test values, **not default or current cloud-provider prices**. The estimate assumes requested resources are allocated continuously. Replace them with rates appropriate to your provider, region, discounts, and billing model before interpreting the savings. The application itself does not assume any rates.

API documentation is available at **http://localhost:8000/docs**.

### Stop and restart

Stop the foreground Compose command with **Ctrl+C**, or from another terminal run:

```sh
docker compose down
```

This stops containers but retains the MySQL named volume and run history. To restart without rebuilding, use `docker compose up`. Do not run `docker compose down -v` unless you intentionally want to permanently delete the local MySQL data.

### Optional: run tests

Install Python 3.11 or later from <https://www.python.org/downloads/>. From the repository:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
```

On Windows PowerShell, use `py -3 -m venv .venv` and `.venv\Scripts\Activate.ps1` instead of the first two commands.

## Setup B: collect live data from a local Kubernetes cluster

This optional path collects actual metrics from a local Kind cluster and Prometheus. It is for development only; do not point it at production clusters.

### Install the extra tools

Prerequisite: complete the Docker installation above, then install:

- `kubectl`: <https://kubernetes.io/docs/tasks/tools/>
- Helm 3: <https://helm.sh/docs/intro/install/>
- Kind: <https://kind.sigs.k8s.io/docs/user/quick-start/#installation>

Confirm they are available:

```sh
kind version
kubectl version --client
helm version
```

### Create a local cluster, Prometheus, and test workloads

From the repository root:

```sh
kind create cluster --name resource-demo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set grafana.enabled=false \
  --set alertmanager.enabled=false \
  --set prometheus.prometheusSpec.retention=3d
kubectl apply -f examples/real-test-workloads.yaml
```

Wait for the Prometheus StatefulSet and Deployment:

```sh
kubectl -n monitoring rollout status statefulset/prometheus-monitoring-kube-prometheus-prometheus --timeout=5m
kubectl -n resource-demo rollout status deployment/cpu-memory-demo --timeout=3m
kubectl -n resource-demo rollout status deployment/api-gateway --timeout=5m
kubectl -n resource-demo rollout status deployment/catalog-service --timeout=5m
kubectl -n resource-demo get pods,jobs,cronjobs
```

Prometheus needs time to scrape the workloads. The fixture creates three continuously running Deployments (`cpu-memory-demo`, `api-gateway`, and `catalog-service`), including two small HTTP services with bounded CPU load and resident memory. It also creates three recurring CronJobs (`cpu-cron-demo` every two minutes, `report-generator` every three minutes, and `cleanup-worker` every five minutes) plus a one-time `initial-index-build` Job. The recurring jobs run for 30–60 seconds, and successful Jobs and pods are retained for up to an hour so the collector can associate their pods with their CronJobs. The extra resource requests/limits are deliberately modest for a local Kind cluster.

### Start database, API, worker, and Prometheus access

In Terminal 1, start the Compose MySQL service:

```sh
docker compose up -d mysql
```

The collector runs on the host in this test. This is intentional: the local Kind kubeconfig points at a host-local Kubernetes API address that an app container generally cannot access without additional networking setup.

In Terminal 2, from the repository root, start a port-forward. Keep this terminal open:

```sh
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
```

The local Prometheus endpoint is **`http://localhost:9090`**. The port-forward provides local access and does not need a Prometheus token. If it exits or loses its pod connection, rerun the port-forward command.

In Terminal 3, from the repository root, prepare the Python environment and start the API:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
export DATABASE_URL='mysql+pymysql://resource_analysis:change-me@127.0.0.1:3307/resource_analysis'
export AUTH_MODE=development
export APP_SECRET_KUBECONFIG_DEV="$(cat "$HOME/.kube/config")"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

If the machine already has several Kubernetes contexts, check that Kind is the active context before running the test:

```sh
kubectl config current-context
```

It should print `kind-resource-demo`. To select that context explicitly, run `kubectl config use-context kind-resource-demo`.

In Terminal 4, from the repository root, start the worker with the same database and kubeconfig environment:

```sh
export DATABASE_URL='mysql+pymysql://resource_analysis:change-me@127.0.0.1:3307/resource_analysis'
export AUTH_MODE=development
export APP_SECRET_KUBECONFIG_DEV="$(cat "$HOME/.kube/config")"
.venv/bin/python -m app.worker
```

Do not put kubeconfig contents in Git, the UI, or a committed `.env` file. These environment-variable commands are only for a trusted local workstation.

### Collect live metrics from the UI

Open **http://localhost:8000**, then fill in the real collection form:

| Field | Local Kind value |
| --- | --- |
| Environment | `local-kind` |
| Namespace | `resource-demo` |
| Prometheus URL | `http://localhost:9090` |
| Kubeconfig secret reference | `env://KUBECONFIG_DEV` |
| Prometheus token secret reference | Leave blank |
| Lookback | `1` day |
| Query step | `60` seconds |
| Request target utilization | `0.8` |
| Limit headroom multiplier | `1.2` |

Click **Start collection**, not **Load synthetic demo data**. Wait for the run to complete, then use **Download Excel** to export all workload aggregates and raw samples for that run. The export is independent of dashboard filters and may contain multiple raw-sample worksheets for large collections. Filter results by one or more workload types and search one or multiple workload names (comma-separated); charts, totals, cost estimates, and the table all follow the selected results. CronJob rows include usage attributed to their associated Jobs. Expected workload rows include the three Deployments, `cpu-cron-demo`, `report-generator`, `cleanup-worker`, and `initial-index-build` when their pods still exist. To check Prometheus is ready, visit <http://localhost:9090/-/ready>. If CPU is blank, wait a few minutes for scrapes and run a new collection.

### Stop local live-data services

To stop the **application and all local live-data services**, press **Ctrl+C** in each terminal running the API, worker, and Prometheus port-forward. These three processes run on the host, outside Docker Compose.

Then stop the Compose-managed MySQL service and the Kind cluster node:

```sh
docker compose stop
docker stop resource-demo-control-plane
```

`docker compose stop` stops all Compose services (MySQL, and any API/worker containers if you started those through Compose). In the live Kind instructions above, the API and worker were started directly on the host, so **Ctrl+C is required to stop those processes**. This stop sequence preserves both the MySQL volume and the Kind cluster data.

To restart later, run `docker start resource-demo-control-plane`, `docker compose up -d mysql`, then start the Prometheus port-forward, API, and worker again as described above. To permanently remove the Kind cluster and its workloads/monitoring, use `kind delete cluster --name resource-demo`. Do not run `docker compose down -v` unless you also intend to delete saved MySQL data.

## Using production cluster and Prometheus data

**Production collection is not ready to enable in this version.** The application currently only supports `env://NAME` secret references in development; the environment-backed secret provider intentionally refuses to resolve secrets when `ENVIRONMENT=production`. Do not work around that guard by placing production kubeconfigs or tokens into the UI, source code, Docker image, or an unencrypted `.env`.

There is also no tenant isolation: run history and results are shared across all authenticated users. OIDC currently authenticates a subject but does not limit which collections it can read. Do not expose this app to multiple untrusted users or to the public internet. The following work is required before a production rollout:

1. **Choose and implement a secret manager integration.** Store only secret identifiers in collection input; have the worker resolve narrowly scoped Kubernetes credentials and Prometheus credentials using workload identity/managed identity. Never log resolved values. Restrict the collector's Kubernetes service account or kubeconfig to read-only access to only the intended namespaces and workload resources.
2. **Restore authorization and tenant boundaries.** Reintroduce an authenticated organization/project scope and enforce it on collection creation, history, run status, raw samples, and aggregate results. Remove development-mode authentication from production configuration.
3. **Deploy inside the correct network boundary.** Run API and worker in a private network with TLS ingress, firewall restrictions, and access to the Kubernetes API, Prometheus query API, and managed MySQL. Do not expose a local port-forward as a production Prometheus endpoint.
4. **Use production infrastructure settings.** Configure durable managed MySQL, encrypted backups, least-privilege DB credentials, secret rotation, monitoring, log redaction, resource limits, and retention/deletion policies for raw samples. Replace development Compose passwords and the local database volume.
5. **Verify data and cost assumptions.** Confirm Prometheus has the expected CPU and memory series, `pod`/`namespace` labels, lookback retention, and authentication mode. Enter actual provider/contract rates for cost estimates; request-based monthly/yearly figures are estimates, not bill reconciliation.
6. **Test before rollout.** Exercise RBAC denial, wrong-namespace access, invalid and expired credentials, Prometheus outages, large lookbacks, retry behavior, and data retention. Do not treat the current local demo configuration as a production deployment recipe.

Production data requires the API/worker to reach both the selected cluster's Kubernetes API and Prometheus' range-query endpoint. The UI currently accepts a Prometheus URL and secret reference per run; those values must be restricted/validated in a production design to avoid unauthorized endpoint access.

## API reference

Queue a collection with `POST /v1/collections`, poll `GET /v1/collections/{runId}` for status, fetch `GET /v1/collections/{runId}/aggregates` for results, or list recent runs with `GET /v1/collections`. The interactive OpenAPI docs are at `/docs`. A synthetic run can also be created with `POST /v1/demo/collections` in development; its environment is marked `DEMO (synthetic)`.

The UI and API do not accept user, organization, or config IDs. Run history/results are shared. Cost-rate inputs are optional, but both CPU and memory rates are needed for cost estimates. Use actual provider rates; reported savings assume continuous allocation and are not invoice predictions.

## Data and operational limitations

- On first startup against a fresh MySQL database, SQLAlchemy creates the current three application tables. The app does not create or use a configuration table.
- Prometheus must retain the requested period, expose the configured CPU and memory metrics, and provide `namespace` and `pod` labels. Query templates can be changed with `PROMETHEUS_CPU_QUERY_TEMPLATE` and `PROMETHEUS_MEMORY_QUERY_TEMPLATE`. Historical CronJob attribution also uses the `kube_pod_owner` and `kube_job_owner` series from kube-state-metrics, including ownership samples from the preceding five minutes; these must be scraped and retained.
- Current allocation values come from pods that exist when collection runs; deleted/evicted pods cannot supply historical Kubernetes requests or limits. Historical Prometheus usage is grouped under its CronJob when retained owner metrics identify the pod→Job→CronJob chain. Samples that remain `UnattributedPod` are retained in raw data and excluded from workload aggregates and recommendations.
- A run with no usage samples fails instead of generating zero-based recommendations. Configure Kubernetes RBAC for read access to pods, ReplicaSets, and Jobs in the target namespace.
- The development secret resolver supports only `env://NAME`; it does not integrate with a cloud secret manager.


## session copilot
`copilot --resume=38a2afa5-63b8-4a81-a034-e8980fdfb33b`