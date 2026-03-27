"""ASGI application for ai_smart_recipe_generator."""

from __future__ import annotations

import os
import sys

from openviper.app import OpenViper

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "ai_smart_recipe_generator.settings")


# Create application
app = OpenViper()
