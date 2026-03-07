"""FastAPI blog app for the performance benchmark.

Usage:
    cd performance_matrix/benchmark_frameworks/fastapi_blog
    uvicorn main:app --port 8001
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session, init_db
from models import BlogPost, PostCreate, PostResponse


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(title="FastAPI Blog Benchmark", version="1.0.0", lifespan=lifespan)


@app.post("/posts", response_model=PostResponse, status_code=201)
async def create_post(
    payload: PostCreate,
    session: AsyncSession = Depends(get_session),
) -> BlogPost:
    post = BlogPost(title=payload.title, content=payload.content)
    session.add(post)
    await session.commit()
    await session.refresh(post)
    return post


@app.get("/posts/{id}", response_model=PostResponse)
async def get_post(
    id: int,
    session: AsyncSession = Depends(get_session),
) -> BlogPost:
    result = await session.execute(select(BlogPost).where(BlogPost.id == id))
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Not found")
    return post
