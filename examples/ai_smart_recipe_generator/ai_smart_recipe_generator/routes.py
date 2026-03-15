"""Top-level routes for ai_smart_recipe_generator."""

from recipe_generator_app.routes import router as recipe_router

from openviper.admin import get_admin_site
from openviper.conf import settings
from openviper.staticfiles import media, static

route_paths = [
    ("/admin", get_admin_site()),
    ("", recipe_router),
]


# to force static files serving in production, not recommended
if not settings.DEBUG:
    route_paths += static() + media()
