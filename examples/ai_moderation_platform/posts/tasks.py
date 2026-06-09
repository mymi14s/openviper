"""Background tasks for the posts app."""

from __future__ import annotations

import logging
import os

from openviper.tasks import periodic

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

log_file = os.path.join(os.getcwd(), "posts.log")
fh = logging.FileHandler(log_file)
fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(fh)


@periodic(every=60)
async def vulgerity_scan() -> None:
    """Re-moderate post 13 every 60 s."""
    logger.info("Periodic vulnerability scan enqueued.")


@periodic(every=300)
def example_sync_task() -> None:
    """Synchronous periodic task example."""
    logger.info("Running example_sync_task.")
    print("This is a synchronous task example.")
    logger.info("Finished example_sync_task.")
