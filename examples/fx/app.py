"""Flexible project application.

A minimal ASGI app demonstrating viperctl with a root layout.

Run::

    cd examples/fx
    openviper run app
"""

from __future__ import annotations

# -- Bootstrap ----------------------------------------------------------------
import os
import sys
from importlib import import_module

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "settings")

import openviper

openviper.setup(force=True)

import_module("models")

# -- Application --------------------------------------------------------------
from openviper import JSONResponse, OpenViper, Request

app = OpenViper()


@app.get("/")
async def index(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "project": "fx",
            "description": "Flexible layout demo powered by viperctl",
            "endpoints": ["/", "/notes"],
        }
    )


@app.get("/notes")
async def list_notes(request: Request) -> JSONResponse:
    return JSONResponse({"notes": [], "hint": "Run migrations first, then add data via console."})
