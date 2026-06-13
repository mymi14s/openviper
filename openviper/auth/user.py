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
from typing import TYPE_CHECKING, Protocol, cast

from openviper.auth.utils import get_user_model
from openviper.db.utils import cast_to_pk_type

if TYPE_CHECKING:
    from openviper.auth.types import Authenticable

logger = logging.getLogger("openviper.auth.backends")


class UserLookupManager(Protocol):
    """Structural query interface required by auth user loading."""

    async def get_or_none(self, **filters: object) -> Authenticable | None: ...


async def get_user_by_id(user_id: int | str) -> Authenticable | None:
    """Load a user by primary key.

    Args:
        user_id: The user's primary key (int, str, or UUID).

    Returns:
        User instance or ``None`` if not found.
    """
    if user_id is None or user_id == "":
        logger.debug("get_user_by_id called with empty user_id")
        return None

    try:
        user_model = get_user_model()
        casted_id = cast_to_pk_type(user_model, user_id)
        objects = cast("UserLookupManager", user_model.objects)
        return await objects.get_or_none(id=casted_id, ignore_permissions=True)
    except (ValueError, TypeError) as exc:
        # Reject values that cannot match integer primary keys.
        logger.debug("get_user_by_id invalid format: %s (user_id=%s)", exc, user_id)
        return None
    except Exception as exc:
        logger.warning("get_user_by_id unexpected exception: %s (user_id=%s)", exc, user_id)
        return None
