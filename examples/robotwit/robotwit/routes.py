"""Top-level routes for robotwit."""

from openviper.admin import get_admin_site

from agents.api import router as agents_router
from notifications.api import router as notifications_router
from robotwit.views import router as root_router
from timeline.api import router as timeline_router
from tweets.api import router as tweets_router

route_paths = [
    ("/admin", get_admin_site()),
    ("/api", tweets_router),
    ("/api", timeline_router),
    ("/api", notifications_router),
    ("/api", agents_router),
    ("/", root_router),
]
