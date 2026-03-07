"""OpenViper blog app for the performance benchmark.

Usage:
    cd performance_matrix/benchmark_frameworks/openviper_blog
    openviper viperctl --settings settings makemigrations .
    openviper viperctl --settings settings migrate .
    openviper run app:app --port 8000
"""

from __future__ import annotations

import os

# Must be set before any openviper imports that touch settings.
os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "settings")

from openviper import OpenViper  # noqa: E402
from openviper.db.connection import init_db  # noqa: E402
from openviper.http.request import Request  # noqa: E402
from openviper.http.response import JSONResponse  # noqa: E402

from models import BlogPost  # noqa: E402

app = OpenViper(title="OpenViper Blog Benchmark", version="1.0.0")


@app.on_startup
async def create_tables() -> None:
    await init_db(drop_first=False)


@app.post("/posts")
async def create_post(request: Request) -> JSONResponse:
    data = await request.json()
    post = BlogPost(title=data["title"], content=data["content"])
    await post.save()
    return JSONResponse(
        {
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "created_at": post.created_at.isoformat() if post.created_at else None,
        },
        status_code=201,
    )


@app.get("/posts/{id:int}")
async def get_post(request: Request, id: int) -> JSONResponse:
    post = await BlogPost.objects.get_or_none(id=id)
    if post is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(
        {
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "created_at": post.created_at.isoformat() if post.created_at else None,
        }
    )
