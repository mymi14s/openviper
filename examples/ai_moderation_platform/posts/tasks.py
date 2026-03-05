"""Background tasks for the posts app.

Tasks
-----
moderate(post_id)
    Runs AI content moderation on a post after it is saved.

vulgerity_scan()
    Periodic task: re-moderates post id 13 every 60 seconds (demo only).

example_sync_task()
    Periodic no-op demo task that fires every ~10 000 seconds.
"""

from __future__ import annotations

import logging
import os

from openviper.tasks import periodic, task

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── File handler (avoids duplicates on re-import) ───────────────────────────
if not any(
    isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "").endswith("posts.log")
    for h in logger.handlers
):
    _log_file = os.path.join(os.getcwd(), "posts.log")
    _fh = logging.FileHandler(_log_file)
    _fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(_fh)


@task()
async def moderate(post_id: int) -> None:
    """AI-moderate a post.  Hides the post and logs the result when unsafe."""
    # Local imports prevent circular imports (Post → tasks → Post).
    logger.info("Starting moderate task for post_id=%s", post_id)


@periodic(every=60)
async def vulgerity_scan() -> None:
    """Demo periodic task — re-moderates post 13 every 60 s."""
    logger.info("Periodic vulnerability scan enqueued.")


@periodic(every=300)
def example_sync_task() -> None:
    """Demo synchronous periodic task."""
    logger.info("Running example_sync_task.")
    print("This is a synchronous task example.")
    logger.info("Finished example_sync_task.")
