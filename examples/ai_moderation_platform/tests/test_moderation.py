"""Tests for AI moderation workflow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from moderation.ai_service import ModerationResult
from moderation.models import ModerationLog
from posts.models import Post, moderate

from openviper.auth.jwt import create_access_token


@pytest.mark.anyio
async def test_create_safe_post(auth_client):
    """Test creating a safe post that is NOT hidden."""
    mock_result = ModerationResult(
        classification="safe", confidence=0.1, reason="Looks good", is_safe=True
    )

    with patch(
        "moderation.ai_service.AIContentModerator.moderate_content", return_value=mock_result
    ):
        response = await auth_client.post(
            "/posts",
            json={
                "title": "A happy post",
                "content": "This is a very nice and safe post about puppies.",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "A happy post"
        assert data["is_hidden"] is False


@pytest.mark.anyio
async def test_create_abusive_post(auth_client):
    """Test creating an abusive post that gets hidden."""
    mock_result = ModerationResult(
        classification="abusive",
        confidence=0.9,
        reason="Contains offensive language",
        is_safe=False,
    )

    with patch(
        "moderation.ai_service.AIContentModerator.moderate_content",
        return_value=mock_result,
    ):
        with patch("posts.models.moderate.send_with_options") as mock_send:
            response = await auth_client.post(
                "/posts",
                json={
                    "title": "Mean post",
                    "content": "I am being very mean here!!!",
                },
            )

            assert response.status_code == 201
            mock_send.assert_called_once()

            # Extract post_id from args tuple
            _, call_kwargs = mock_send.call_args
            post_id = call_kwargs["args"][0]

            # Since task is queued, run the logic explicitly for the test
            await moderate.fn.__wrapped__(post_id)

        # Verify it's hidden in DB
        post = await Post.objects.get(id=post_id)
        assert post.is_hidden is True


@pytest.mark.anyio
async def test_moderator_approve_post(auth_client, moderator_user):
    """Test that a moderator can approve a hidden post."""

    # Create a hidden post
    post = Post(title="Flagged", content="Bad content", author=1, is_hidden=True)
    await post.save()

    # Create log entry
    log = ModerationLog(
        content_type="post",
        object_id=post.id,
        classification="abusive",
        confidence=0.9,
        reason="Flagged by AI",
    )
    await log.save()

    # Authenticate as moderator
    token = create_access_token(moderator_user.id, {"username": moderator_user.username})
    auth_client.headers["Authorization"] = f"Bearer {token}"

    # Approve it
    response = await auth_client.post(
        f"/moderation/logs/{log.id}/action",
        json={"action": "approve", "reason": "It's actually fine"},
    )

    assert response.status_code == 200

    # Verify unhidden
    await post.refresh_from_db()
    assert post.is_hidden is False

    # Verify log updated
    await log.refresh_from_db()
    assert log.reviewed is True
    assert log.approved is True
    assert log.moderator == moderator_user.id
