"""Top-level routes for ai_smart_recipe_generator."""

from recipe_generator_app.routes import router as recipe_router

from openviper.admin import get_admin_site

route_paths = [
    ("/admin", get_admin_site()),
    ("", recipe_router),
]
