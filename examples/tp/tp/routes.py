"""Top-level routes for tp."""

from tp.views import router as root_router

from openviper.admin import get_admin_site

route_paths = [
    ("/admin", get_admin_site()),
    ("/root", root_router),
]
