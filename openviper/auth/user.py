"""Low-level user-loading utility for OpenViper.

Isolated in its own module so that both :mod:`openviper.auth.sessions` and
:mod:`openviper.auth.backends` can import :func:`get_user_by_id` without
creating a circular dependency between those two modules.

Dependency graph (this module sits at the bottom)::

    sessions ──┐
               ├──> user  (this module)
    backends ──┘

"""

from __future__ import annotations

import logging
from typing import Any

from openviper.auth.utils import get_user_model
from openviper.db.utils import cast_to_pk_type

logger = logging.getLogger("openviper.auth.backends")


async def get_user_by_id(user_id: Any) -> Any | None:
    """Load a user by primary key.

    Args:
        user_id: The user's primary key (int, str, or UUID).

    Returns:
        User instance or ``None`` if not found.
    """
    # Validate user_id is not None/empty
    if user_id is None or user_id == "":
        logger.debug("get_user_by_id called with empty user_id")
        return None

    try:
        User = get_user_model()  # noqa: N806
        casted_id = cast_to_pk_type(User, user_id)
        return await User.objects.get_or_none(id=casted_id, ignore_permissions=True)  # type: ignore[attr-defined]
    except (ValueError, TypeError) as exc:
        # Invalid format for user_id (e.g., non-numeric string for int PK)
        logger.debug("get_user_by_id invalid format: %s (user_id=%s)", exc, user_id)
        return None
    except Exception as exc:
        logger.warning("get_user_by_id unexpected exception: %s (user_id=%s)", exc, user_id)
        return None
