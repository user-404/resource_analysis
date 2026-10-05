import logging
import time

from app.config import get_settings
from app.db import SessionLocal, initialize_database
from app.service import process_next_run

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    initialize_database()
    settings = get_settings()
    logger.info("Collection worker started")
    while True:
        with SessionLocal() as db:
            did_work = process_next_run(db)
        if not did_work:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
