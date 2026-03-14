"""Top-level routes for tp."""

from openviper.admin import get_admin_site
from tp.views import router as root_router

route_paths = [
    ("/admin", get_admin_site()),
    ("/root", root_router),
]
