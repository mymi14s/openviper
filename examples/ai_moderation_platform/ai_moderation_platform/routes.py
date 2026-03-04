# Routes for apps

from frontend.routes import router as frontend_router
from moderation.routes import router as moderation_router
from posts.routes import router as posts_router
from users.routes import router as users_router

from openviper.admin import get_admin_site

route_paths = [
    ("/admin", get_admin_site()),
    ("/users", users_router),
    ("/posts", posts_router),
    ("/moderation", moderation_router),
    ("/", frontend_router),
]
