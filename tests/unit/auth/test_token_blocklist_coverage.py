"""Cover the datetime.datetime expiry path in openviper/auth/token_blocklist.py."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_is_token_revoked_db_hit_with_datetime_expiry():
    from unittest.mock import patch

    from openviper.auth.token_blocklist import _JTI_CACHE, is_token_revoked

    jti = "test-jti-datetime-expiry"
    _JTI_CACHE.pop(jti, None)

    future_expiry = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)

    mock_result = MagicMock()
    mock_result.fetchone.return_value = (future_expiry,)

    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value=mock_result)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn

    with (
        patch("openviper.auth.token_blocklist._ensure_table", new=AsyncMock()),
        patch("openviper.auth.token_blocklist.get_engine", new=AsyncMock(return_value=mock_engine)),
    ):
        result = await is_token_revoked(jti)

    assert result is True
    assert jti in _JTI_CACHE
    assert isinstance(_JTI_CACHE[jti], float)

    # Cleanup
    _JTI_CACHE.pop(jti, None)
