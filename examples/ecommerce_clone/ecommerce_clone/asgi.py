"""ASGI application for Ecommerce Clone."""

from __future__ import annotations

import os
import sys

import openviper
from openviper.app import OpenViper
# from openviper.db import init_db

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "ecommerce_clone.settings")

openviper.setup()



try:
    from .routes import route_paths
except ImportError:
    route_paths = []

app = OpenViper(title="Ecommerce Clone", version="1.0.0")

for prefix, router in route_paths:
    app.include_router(router, prefix=prefix)



# @app.on_startup
# async def startup() -> None:
#     """Create database tables on startup."""
#     await init_db()
