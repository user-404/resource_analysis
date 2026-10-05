from datetime import datetime, timezone
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collector import collect
from app.models import CollectionRun, RawUsageSample, WorkloadAggregate

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue_collection(db: Session, payload: dict) -> CollectionRun:
    run = CollectionRun(
        id=str(uuid.uuid4()),
        environment=payload["environment"],
        namespace=payload["namespace"],
        lookback_days=payload["days_to_collect"],
        status="queued",
        input_json=payload,
        created_at=utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def process_next_run(db: Session) -> bool:
    run = db.execute(
        select(CollectionRun)
        .where(CollectionRun.status == "queued")
        .order_by(CollectionRun.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()
    if run is None:
        db.rollback()
        return False
    run.status = "running"
    run.started_at = utcnow()
    db.commit()

    try:
        raw_rows, aggregates = collect(run.input_json)
        for row in raw_rows:
            db.add(RawUsageSample(run_id=run.id, **row))
        for row in aggregates:
            db.add(WorkloadAggregate(run_id=run.id, **row))
        run.status = "completed"
        run.completed_at = utcnow()
        run.error_message = None
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_run = db.get(CollectionRun, run.id)
        if failed_run:
            failed_run.status = "failed"
            failed_run.completed_at = utcnow()
            failed_run.error_message = str(exc)[:4000]
            db.commit()
        logger.exception("Collection run %s failed", run.id)
    return True
