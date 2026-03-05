"""MODEL_EVENTS handlers for the blog app.

These functions are called synchronously from ``Model.save()`` /
``Model.delete()`` after the database operation completes, but only when the
task system is enabled (``TASKS['enabled'] = 1``).

Each handler receives the model instance that triggered the event.  Handlers
should be *fast* — for expensive work, enqueue a ``@task`` actor instead of
doing the work inline.

Registration (in settings)::

    MODEL_EVENTS = {
        "blog.models.Post": {
            "after_insert": ["blog.events.create_likes"],
            "after_delete": ["blog.events.cleanup_comments"],
        },
        "blog.models.Comment": {
            "after_insert": ["blog.events.notify_post_author"],
        },
    }
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("posts.events")


# ---------------------------------------------------------------------------
# Post handlers
# ---------------------------------------------------------------------------


def create_likes(post: Any, event: str | None = None) -> None:
    """Initialise a like-counter record when a new Post is created.

    In a real application this would enqueue a background task::

        from blog.tasks import init_like_counter
        init_like_counter.send(post_id=post.pk)
    """
    logger.info(
        "create_likes: initialising like counter for Post pk=%s title=%r",
        post.pk,
        getattr(post, "title", None),
    )
    # Placeholder — replace with your actual task .send() call:
    # init_like_counter.send(post_id=post.pk)


def cleanup_comments(post: Any, event: str | None = None) -> None:
    """Remove all comments when a Post is deleted.

    In a real application this would enqueue a background task::

        from blog.tasks import bulk_delete_comments
        bulk_delete_comments.send(post_id=post.pk)
    """
    logger.info(
        "cleanup_comments: scheduling comment cleanup for Post pk=%s",
        post.pk,
    )
    # Placeholder — replace with your actual task .send() call:
    # bulk_delete_comments.send(post_id=post.pk)


# ---------------------------------------------------------------------------
# Comment handlers
# ---------------------------------------------------------------------------


def notify_post_author(comment: Any, event: str | None = None) -> None:
    """Notify the post author when a new Comment is created.

    In a real application this would enqueue a background task::

        from blog.tasks import send_comment_notification
        send_comment_notification.send(comment_id=comment.pk)
    """
    logger.info(
        "notify_post_author: queuing notification for Comment pk=%s on post_id=%s",
        comment.pk,
        getattr(comment, "post_id", None),
    )
    # Placeholder — replace with your actual task .send() call:
    # send_comment_notification.send(comment_id=comment.pk)


def handle_post_update(post: Any, event: str | None = None) -> None:
    """Handle post update events."""
    print(f"Post {post.pk} updated. Event: {event}")
    logger.info(
        "handle_post_update: Post pk=%s updated. Event: %s",
        post.pk,
        event,
    )
    # Placeholder for handling post updates, e.g., re-moderation or notifications.
