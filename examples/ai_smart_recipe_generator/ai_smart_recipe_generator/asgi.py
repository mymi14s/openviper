
"""ASGI application for ai_smart_recipe_generator."""

from __future__ import annotations

import os
import sys

import openviper
from openviper.app import OpenViper

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "ai_smart_recipe_generator.settings")


try:
    from .routes import route_paths
except ImportError:
    route_paths = []

# Create application
app = OpenViper()

# Include routers
for prefix, router in route_paths:
    app.include_router(router, prefix=prefix)
