from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, field_validator, model_validator
from typing_extensions import Annotated


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Namespace = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    ),
]


class CollectionCreate(BaseModel):
    environment: Identifier
    namespace: Namespace
    days_to_collect: int = Field(alias="daysToCollect", ge=1, le=90)
    kubeconfig_secret_ref: Identifier = Field(alias="kubeconfigSecretRef")
    prometheus_url: HttpUrl = Field(alias="prometheusUrl")
    prometheus_secret_ref: Identifier | None = Field(default=None, alias="prometheusSecretRef")
    target_utilization: float = Field(default=0.8, alias="targetUtilization", gt=0, le=1)
    limit_headroom_multiplier: float = Field(default=1.2, alias="limitHeadroomMultiplier", ge=1, le=5)
    step_seconds: int = Field(default=300, alias="stepSeconds", ge=60, le=3600)
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    cpu_rate_per_core_hour: float | None = Field(default=None, alias="cpuRatePerCoreHour", gt=0)
    memory_rate_per_gib_hour: float | None = Field(default=None, alias="memoryRatePerGiBHour", gt=0)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def validate_cost_rates(self):
        if (self.cpu_rate_per_core_hour is None) != (self.memory_rate_per_gib_hour is None):
            raise ValueError("Provide both CPU and memory rates to enable cost estimates")
        return self

    @field_validator("prometheus_url")
    @classmethod
    def reject_embedded_prometheus_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            raise ValueError("Prometheus credentials must use prometheusSecretRef, not URL userinfo")
        return value


class DemoCollectionCreate(BaseModel):
    namespace: Namespace = "payments"
    days_to_collect: int = Field(default=7, alias="daysToCollect", ge=1, le=30)
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    cpu_rate_per_core_hour: float | None = Field(default=None, alias="cpuRatePerCoreHour", gt=0)
    memory_rate_per_gib_hour: float | None = Field(default=None, alias="memoryRatePerGiBHour", gt=0)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def validate_cost_rates(self):
        if (self.cpu_rate_per_core_hour is None) != (self.memory_rate_per_gib_hour is None):
            raise ValueError("Provide both CPU and memory rates to enable cost estimates")
        return self


class CollectionAccepted(BaseModel):
    run_id: str = Field(serialization_alias="runId")
    status: str

    model_config = ConfigDict(populate_by_name=True)


class CollectionStatus(BaseModel):
    run_id: str = Field(validation_alias="id", serialization_alias="runId")
    environment: str
    namespace: str
    lookback_days: int = Field(serialization_alias="lookbackDays")
    status: str
    created_at: datetime = Field(serialization_alias="createdAt")
    started_at: datetime | None = Field(serialization_alias="startedAt")
    completed_at: datetime | None = Field(serialization_alias="completedAt")
    error_message: str | None = Field(serialization_alias="errorMessage")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class CostEstimate(BaseModel):
    currency: str
    basis: str
    cpu_rate_per_core_hour: float = Field(serialization_alias="cpuRatePerCoreHour")
    memory_rate_per_gib_hour: float = Field(serialization_alias="memoryRatePerGiBHour")
    current_monthly: float = Field(serialization_alias="currentMonthly")
    suggested_monthly: float = Field(serialization_alias="suggestedMonthly")
    savings_monthly: float = Field(serialization_alias="savingsMonthly")
    current_yearly: float = Field(serialization_alias="currentYearly")
    suggested_yearly: float = Field(serialization_alias="suggestedYearly")
    savings_yearly: float = Field(serialization_alias="savingsYearly")
    monthly_hours: int = Field(serialization_alias="monthlyHours")
    yearly_hours: int = Field(serialization_alias="yearlyHours")

    model_config = ConfigDict(populate_by_name=True)


class AggregateResponse(BaseModel):
    workload_name: str = Field(serialization_alias="workloadName")
    workload_type: str = Field(serialization_alias="workloadType")
    pod_count: int = Field(serialization_alias="podCount")
    sample_count: int = Field(serialization_alias="sampleCount")
    average_cpu_cores: float | None = Field(serialization_alias="averageCpuCores")
    peak_cpu_cores: float | None = Field(serialization_alias="peakCpuCores")
    average_memory_bytes: float | None = Field(serialization_alias="averageMemoryBytes")
    peak_memory_bytes: float | None = Field(serialization_alias="peakMemoryBytes")
    allocated_cpu_request_cores: float = Field(serialization_alias="allocatedCpuRequestCores")
    allocated_cpu_limit_cores: float = Field(serialization_alias="allocatedCpuLimitCores")
    allocated_memory_request_bytes: float = Field(serialization_alias="allocatedMemoryRequestBytes")
    allocated_memory_limit_bytes: float = Field(serialization_alias="allocatedMemoryLimitBytes")
    suggested_cpu_request_cores: float | None = Field(serialization_alias="suggestedCpuRequestCores")
    suggested_cpu_limit_cores: float | None = Field(serialization_alias="suggestedCpuLimitCores")
    suggested_memory_request_bytes: float | None = Field(serialization_alias="suggestedMemoryRequestBytes")
    suggested_memory_limit_bytes: float | None = Field(serialization_alias="suggestedMemoryLimitBytes")
    recommendation_policy: dict[str, Any] = Field(serialization_alias="recommendationPolicy")
    cost_estimate: CostEstimate | None = Field(default=None, serialization_alias="costEstimate")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RawUsageSampleResponse(BaseModel):
    pod_name: str = Field(serialization_alias="podName")
    sampled_at: datetime = Field(serialization_alias="sampledAt")
    cpu_cores: float | None = Field(serialization_alias="cpuCores")
    memory_bytes: float | None = Field(serialization_alias="memoryBytes")
    allocated_cpu_request_cores: float = Field(serialization_alias="allocatedCpuRequestCores")
    allocated_cpu_limit_cores: float = Field(serialization_alias="allocatedCpuLimitCores")
    allocated_memory_request_bytes: float = Field(serialization_alias="allocatedMemoryRequestBytes")
    allocated_memory_limit_bytes: float = Field(serialization_alias="allocatedMemoryLimitBytes")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RawUsageSamplesPage(BaseModel):
    workload_name: str = Field(serialization_alias="workloadName")
    workload_type: str = Field(serialization_alias="workloadType")
    total: int
    offset: int
    limit: int
    items: list[RawUsageSampleResponse]

    model_config = ConfigDict(populate_by_name=True)
