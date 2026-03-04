"""Admin API module.

Provides REST API endpoints for the admin panel frontend.
"""

from openviper.admin.api.views import get_admin_router

__all__ = ["get_admin_router"]
