"""Flask blog app for the performance benchmark.

Usage:
    cd performance_matrix/benchmark_frameworks/flask_blog
    gunicorn -w 4 -b 127.0.0.1:8002 app:app
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

from flask import Flask, jsonify, request
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_HERE = Path(__file__).parent
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{_HERE / 'db.sqlite3'}")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class BlogPost(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


app = Flask(__name__)


def _serialize(post: BlogPost) -> dict:
    return {
        "id": post.id,
        "title": post.title,
        "content": post.content,
        "created_at": post.created_at.isoformat() if post.created_at else None,
    }


with app.app_context():
    Base.metadata.create_all(engine)


@app.post("/posts")
def create_post():
    data = request.get_json(force=True)
    with SessionLocal() as session:
        post = BlogPost(title=data["title"], content=data["content"])
        session.add(post)
        session.commit()
        session.refresh(post)
        return jsonify(_serialize(post)), 201


@app.get("/posts/<int:id>")
def get_post(id: int):
    with SessionLocal() as session:
        post = session.get(BlogPost, id)
        if post is None:
            return jsonify({"error": "Not found"}), 404
        return jsonify(_serialize(post)), 200
