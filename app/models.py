from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    environment: Mapped[str] = mapped_column(String(255), nullable=False)
    namespace: Mapped[str] = mapped_column(String(253), nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)


class RawUsageSample(Base):
    __tablename__ = "raw_usage_samples"
    __table_args__ = (
        UniqueConstraint("run_id", "pod_name", "sampled_at", name="uq_raw_run_pod_time"),
        Index("ix_raw_run_workload_time", "run_id", "workload_name", "sampled_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("collection_runs.id", ondelete="CASCADE"), nullable=False)
    namespace: Mapped[str] = mapped_column(String(253), nullable=False)
    workload_name: Mapped[str] = mapped_column(String(253), nullable=False)
    workload_type: Mapped[str] = mapped_column(String(32), nullable=False)
    pod_name: Mapped[str] = mapped_column(String(253), nullable=False)
    sampled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cpu_cores: Mapped[float | None] = mapped_column(Float)
    memory_bytes: Mapped[float | None] = mapped_column(Float)
    allocated_cpu_request_cores: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    allocated_cpu_limit_cores: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    allocated_memory_request_bytes: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    allocated_memory_limit_bytes: Mapped[float] = mapped_column(Float, nullable=False, default=0)


class WorkloadAggregate(Base):
    __tablename__ = "workload_aggregates"
    __table_args__ = (
        UniqueConstraint("run_id", "workload_name", "workload_type", name="uq_aggregate_run_workload"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("collection_runs.id", ondelete="CASCADE"), nullable=False)
    namespace: Mapped[str] = mapped_column(String(253), nullable=False)
    workload_name: Mapped[str] = mapped_column(String(253), nullable=False)
    workload_type: Mapped[str] = mapped_column(String(32), nullable=False)
    pod_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    average_cpu_cores: Mapped[float | None] = mapped_column(Float)
    peak_cpu_cores: Mapped[float | None] = mapped_column(Float)
    average_memory_bytes: Mapped[float | None] = mapped_column(Float)
    peak_memory_bytes: Mapped[float | None] = mapped_column(Float)
    allocated_cpu_request_cores: Mapped[float] = mapped_column(Float, nullable=False)
    allocated_cpu_limit_cores: Mapped[float] = mapped_column(Float, nullable=False)
    allocated_memory_request_bytes: Mapped[float] = mapped_column(Float, nullable=False)
    allocated_memory_limit_bytes: Mapped[float] = mapped_column(Float, nullable=False)
    suggested_cpu_request_cores: Mapped[float | None] = mapped_column(Float)
    suggested_cpu_limit_cores: Mapped[float | None] = mapped_column(Float)
    suggested_memory_request_bytes: Mapped[float | None] = mapped_column(Float)
    suggested_memory_limit_bytes: Mapped[float | None] = mapped_column(Float)
    recommendation_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
