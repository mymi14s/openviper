<div align="center">

# 🐍 OpenViper

**A production-ready, high-performance, async-first Python web framework.**

*The freedom of a minimal core. The power of a full stack.*

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.0.1-orange)](pyproject.toml)

</div>

---

**OpenViper** is a production-ready, high-performance, async-first Python web framework designed to be
both flexible and batteries-included. It gives you the freedom of a minimal, unopinionated core when
you want control, while also providing a rich, fully integrated stack when you want to move fast.

Out of the box it includes a powerful ORM with model lifecycle and events, built-in authentication and
authorization, an Admin UI, background task processing, a pluggable AI provider registry, and automatic
OpenAPI documentation.

Whether you're building lean APIs or full-scale platforms, OpenViper scales with you — without forcing
you into rigid architectural constraints.

---

## ✨ Features

| | |
|---|---|
| 🔀 **Routing** | Decorator-based and class-based (`View`) routes, path params, route groups |
| 🗄️ **ORM** | Async models, QuerySet API, migrations, lifecycle hooks, model events |
| 🔐 **Auth** | Session + JWT, password hashing, roles, permissions, `@login_required` |
| 🖥️ **Admin UI** | Auto-discovered Vue SPA — CRUD, bulk actions, change history, inlines |
| 🔧 **Middleware** | Auth, CORS, CSRF, rate-limiting, security headers |
| ⚙️ **Background Tasks** | Dramatiq-backed queue with retry, priorities, model-event hooks |
| 🕐 **Scheduler** | Cron and interval periodic jobs built into the framework |
| 🤖 **AI Registry** | Unified async API — OpenAI, Anthropic, Gemini, Ollama, Grok, custom |
| 📦 **Serializers** | Pydantic-based, `ModelSerializer`, nested, partial updates, role-aware |
| 📄 **OpenAPI** | Live Swagger + ReDoc UIs auto-generated from your routes |
| 📁 **Storage** | Built-in static file serving and pluggable storage backends |

---

## 🚀 Quick Start

### Install

```bash
pip install openviper
```

### Minimal — single file

```python
# app.py
from openviper import OpenViper, JSONResponse
from openviper.http.request import Request

app = OpenViper(title="My API", version="1.0.0")

@app.on_startup
async def startup():
    print("Server started.")

@app.get("/")
async def index(request: Request) -> JSONResponse:
    return JSONResponse({"message": "Hello, OpenViper!"})

@app.get("/users/{user_id}")
async def get_user(request: Request, user_id: int) -> JSONResponse:
    return JSONResponse({"id": user_id, "name": "Alice"})

@app.post("/users")
async def create_user(request: Request) -> JSONResponse:
    body = await request.json()
    return JSONResponse({"created": True, **body}, status_code=201)
```

```bash
openviper run app
```

Open in your browser:
- **API** → `http://localhost:8000`
- **Swagger UI** → `http://localhost:8000/open-api/docs`
- **ReDoc** → `http://localhost:8000/open-api/redoc`

### Full project (with DB, auth, admin)

```bash
# Scaffold a new project
openviper create-project myproject
cd myproject
openviper create-app blog

# Configure your database in .env
echo "DATABASE_URL=postgresql+asyncpg://user:pass@localhost/mydb" >> .env

# Run migrations and create an admin user
python viperctl.py makemigrations
python viperctl.py migrate
python viperctl.py createsuperuser

# Start everything
python viperctl.py runserver    # web server
python viperctl.py runworker    # background task worker (separate terminal)
```

---

## 📚 Core Concepts

### Models & ORM

```python
# blog/models.py
from openviper.db import Model
from openviper.db.fields import (
    CharField, TextField, BooleanField, DateTimeField, ForeignKey,
)
from openviper.auth import get_user_model

User = get_user_model()

class Post(Model):
    _app_name = "blog"

    title      = CharField(max_length=255)
    content    = TextField()
    author     = ForeignKey(User, on_delete="CASCADE")
    published  = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        table_name = "blog_posts"

    async def after_insert(self):
        # Lifecycle hook — enqueue moderation task after every new post
        from blog.tasks import moderate_post
        moderate_post.send(self.id)
```

**QuerySet API:**

```python
# All published posts, newest first
posts = await Post.objects.filter(published=True).order_by("-created_at").all()

# Single record — returns None if not found
post = await Post.objects.get_or_none(id=42)

# Count
drafts = await Post.objects.filter(published=False).count()

# Async iteration
async for post in Post.objects.filter(author_id=user.id):
    print(post.title)

# Bulk update
await Post.objects.filter(author_id=user.id).update(published=True)
```

### Authentication & Permissions

```python
from openviper.auth.decorators import login_required, permission_required
from openviper.http.request import Request
from openviper.http.response import JSONResponse

@app.get("/dashboard")
@login_required
async def dashboard(request: Request) -> JSONResponse:
    return JSONResponse({"user": request.user.username})

@app.delete("/posts/{post_id}")
@permission_required("post.delete")
async def delete_post(request: Request, post_id: int) -> JSONResponse:
    ...
```

### Admin Panel

Register models in `blog/admin.py` — OpenViper discovers it automatically:

```python
from openviper.admin import ModelAdmin, ActionResult, action, register
from .models import Post

@register(Post)
class PostAdmin(ModelAdmin):
    list_display  = ["id", "title", "author", "published", "created_at"]
    list_filter   = ["published"]
    search_fields = ["title", "content"]
    actions       = ["publish_selected"]

    @action(description="Publish selected posts")
    async def publish_selected(self, queryset, request):
        count = await queryset.update(published=True)
        return ActionResult(success=True, count=count, message=f"Published {count} posts.")
```

Visit `http://localhost:8000/admin` after running `python viperctl.py createsuperuser`.

### Background Tasks

```python
# blog/tasks.py
from openviper.tasks import task

@task
async def moderate_post(post_id: int):
    from blog.models import Post
    post = await Post.objects.get_or_none(id=post_id)
    if post:
        # call AI, update flags, send notifications …
        pass
```

```bash
python viperctl.py runworker
```

### Periodic Scheduler

```python
from openviper.tasks.scheduler import periodic
from openviper.tasks.schedule import CronSchedule, IntervalSchedule
from datetime import timedelta

@periodic(CronSchedule("0 8 * * *"), name="morning_digest")
async def morning_digest():
    # Runs every day at 08:00
    ...

@periodic(IntervalSchedule(timedelta(minutes=15)), name="refresh_cache")
async def refresh_cache():
    ...
```

```bash
python viperctl.py runscheduler
```

### AI Registry

```python
from openviper.ai.registry import ai_registry

# Generate text
result = await ai_registry.generate(
    prompt="Summarise this article in 3 bullet points: ...",
    provider="openai",
    model="gpt-4o",
)
print(result.text)

# Moderation check
verdict = await ai_registry.moderate(content="...", provider="openai")
print(verdict.flagged, verdict.reason)

# Streaming
async for chunk in ai_registry.stream(prompt="Tell me a story", provider="anthropic"):
    print(chunk, end="", flush=True)
```

Configure providers in your settings:

```python
AI_PROVIDERS = {
    "openai":    {"api_key": os.environ["OPENAI_API_KEY"]},
    "anthropic": {"api_key": os.environ["ANTHROPIC_API_KEY"]},
    "gemini":    {"api_key": os.environ["GEMINI_API_KEY"]},
}
```

---

## 📂 Examples

| Example | Description |
|---|---|
| [`examples/todoapp/`](examples/todoapp/) | Single-file app — auth, admin, SQLite, HTML templates |
| [`examples/ai_moderation_platform/`](examples/ai_moderation_platform/) | Multi-app platform — AI moderation, Dramatiq tasks, Docker, PostgreSQL |
| [`examples/custom_provider_demo/`](examples/custom_provider_demo/) | Writing and registering a custom AI provider plugin |

---

## 📖 Documentation

Full reference documentation lives in [`docs/0.0.1/`](docs/0.0.1/).

Build and open locally:

```bash
pip install sphinx sphinx_rtd_theme
cd docs/0.0.1
sphinx-build -b html . _build/html
open _build/html/index.html
```

---

## ⚙️ Requirements

- **Python** ≥ 3.11
- **Async DB driver** — `asyncpg` (PostgreSQL), `aiomysql` (MySQL), `aiosqlite` (SQLite)
- **uvicorn** — included when you install `openviper`

```bash
pip install openviper asyncpg          # PostgreSQL
pip install openviper aiosqlite        # SQLite (dev/testing)
```

Optional extras:

```bash
pip install openviper[ai]              # OpenAI, Anthropic, Gemini clients
pip install openviper[tasks]           # Dramatiq + RabbitMQ/Redis broker
pip install openviper[all]             # Everything
```

---

## 📜 License

MIT — see [LICENSE](LICENSE).
