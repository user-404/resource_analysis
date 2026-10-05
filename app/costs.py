from typing import Any

from app.models import WorkloadAggregate
from app.schemas import CostEstimate

GIB = 1024**3
MONTHLY_HOURS = 730
YEARLY_HOURS = 8760


def estimate_cost(aggregate: WorkloadAggregate, run_input: dict[str, Any]) -> CostEstimate | None:
    cpu_rate = run_input.get("cpu_rate_per_core_hour")
    memory_rate = run_input.get("memory_rate_per_gib_hour")
    if cpu_rate is None or memory_rate is None:
        return None
    if (
        aggregate.suggested_cpu_request_cores is None
        or aggregate.suggested_memory_request_bytes is None
    ):
        return None

    current_hourly = (
        aggregate.allocated_cpu_request_cores * cpu_rate
        + aggregate.allocated_memory_request_bytes / GIB * memory_rate
    )
    suggested_hourly = (
        aggregate.suggested_cpu_request_cores * cpu_rate
        + aggregate.suggested_memory_request_bytes / GIB * memory_rate
    )
    current_monthly = current_hourly * MONTHLY_HOURS
    suggested_monthly = suggested_hourly * MONTHLY_HOURS
    current_yearly = current_hourly * YEARLY_HOURS
    suggested_yearly = suggested_hourly * YEARLY_HOURS
    return CostEstimate(
        currency=run_input.get("currency", "USD"),
        basis="request-based estimate, assuming continuous allocation",
        cpu_rate_per_core_hour=cpu_rate,
        memory_rate_per_gib_hour=memory_rate,
        current_monthly=round(current_monthly, 2),
        suggested_monthly=round(suggested_monthly, 2),
        savings_monthly=round(current_monthly - suggested_monthly, 2),
        current_yearly=round(current_yearly, 2),
        suggested_yearly=round(suggested_yearly, 2),
        savings_yearly=round(current_yearly - suggested_yearly, 2),
        monthly_hours=MONTHLY_HOURS,
        yearly_hours=YEARLY_HOURS,
    )
