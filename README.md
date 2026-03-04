<div align="center">

# 🐍 OpenViper

**A production-ready, async-first Python web framework.**

*The freedom of a minimal core. The power of a full stack.*

[![Python](https://img.shields.io/badge/python-3.14%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.0.1-orange)](pyproject.toml)

</div>

---

**OpenViper** is a production-ready, async-first Python web framework designed to be both flexible and batteries-included. It gives you the freedom of a minimal, unopinionated core when you want control, while also providing a rich, fully integrated stack when you want to move fast.

Out of the box it includes a powerful ORM with model lifecycle and events, built-in authentication and authorization, an Admin UI, background task processing, a pluggable AI provider registry, and automatic OpenAPI documentation.

Whether you're building lean APIs or full-scale platforms, OpenViper scales with you — without forcing you into rigid architectural constraints.

---

## ✨ Features

| | |
|---|---|
| 🔀 **Routing** | Function-based and class-based (`View`) routes, path params, route groups |
| 🗄️ **ORM** | Async models, QuerySet API, migrations, lifecycle hooks, model events |
| 🔐 **Auth** | Session + JWT, password hashing, roles, permissions, `@login_required` |
| 🖥️ **Admin UI** | Auto-discovered SPA — CRUD, bulk actions, change history, inlines |
| 🔧 **Middleware** | Auth, CORS, CSRF, rate-limiting, security headers |
| ⚙️ **Background Tasks** | Task queue with retry, priorities, model-event hooks |
| 🕐 **Scheduler** | Cron and interval periodic jobs built into the framework |
| 🤖 **AI Registry** | Unified async API — OpenAI, Anthropic, Gemini, Ollama, Grok, custom |
| 📦 **Serializers** | `ModelSerializer`, `Serializer`, nested, partial updates, role-aware |
| 📄 **OpenAPI** | Live Swagger + ReDoc UIs auto-generated from your routes |

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

app = OpenViper(title="My API")


@app.get("/")
async def index(request: Request):
    return JSONResponse({"message": "Hello, OpenViper!"})


@app.get("/users/{user_id}")
async def get_user(request: Request, user_id: int):
    return JSONResponse({"id": user_id, "name": "Alice"})


@app.post("/users")
async def create_user(request: Request):
    body = await request.json()
    return JSONResponse({"created": True, **body}, status_code=201)
```

```bash
openviper run app
```

| URL | Description |
|---|---|
| `http://localhost:8000` | API root |
| `http://localhost:8000/open-api/docs` | Swagger UI |
| `http://localhost:8000/open-api/redoc` | ReDoc |

### Full project (with DB, auth, admin)

```bash
# Scaffold a new project
openviper create-project myproject
cd myproject
openviper create-app blog
```

Add `"blog"` to `INSTALLED_APPS` in `myproject/settings.py`, then:

```bash
python viperctl.py makemigrations
python viperctl.py migrate
python viperctl.py createsuperuser
python viperctl.py runserver    # start the web server
python viperctl.py runworker    # start the task worker (separate terminal)
```

---

## 📚 Core Concepts

### Models & ORM

```python
# blog/models.py
from openviper.db import Model
from openviper.db.fields import BooleanField, CharField, DateTimeField, ForeignKey, TextField
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
        send_welcome_email.send_with_options(args=(self.id,), delay=5_000)

    async def on_update(self):
        ...

    async def on_delete(self):
        ...
```

**QuerySet API:**

```python
# All published posts, newest first
posts = await Post.objects.filter(published=True).order_by("-created_at").all()

# Single record (None if not found)
post = await Post.objects.get_or_none(id=42)

# Count
drafts = await Post.objects.filter(published=False).count()

# Async iteration
async for post in Post.objects.filter(author_id=user.id):
    print(post.title)

# Bulk update
await Post.objects.filter(author_id=user.id).update(published=True)
```

### Admin Panel

Register models in `blog/admin.py` — OpenViper auto-discovers it from `INSTALLED_APPS`:

```python
from openviper.admin import ActionResult, ModelAdmin, action, register
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

```bash
python viperctl.py runserver
# Admin: http://localhost:8000/admin
```

### Background Tasks

```python
# blog/tasks.py
from openviper.tasks import task


@task()
async def send_welcome_email(post_id: int):
    post = await Post.objects.get_or_none(id=post_id)
    # send email, push notification, etc.
```

```bash
python viperctl.py runworker
```

### Periodic Scheduler

```python
from openviper.tasks.scheduler import periodic


@periodic(every=60)
async def refresh_feed():
    ...


@periodic(every=300)
async def cleanup_old_sessions():
    ...
```

```bash
python viperctl.py runworker
```

---

## 📂 Examples

| Example | Description |
|---|---|
| [`examples/flexible/`](examples/flexible/) | Minimal decorator-based API — no DB, no auth |
| [`examples/todoapp/`](examples/todoapp/) | Single-file app — auth, admin, SQLite, HTML templates |
| [`examples/ai_moderation_platform/`](examples/ai_moderation_platform/) | Multi-app platform — AI moderation, tasks, Docker, PostgreSQL |
| [`examples/custom_provider_demo/`](examples/custom_provider_demo/) | Writing a custom AI provider plugin |

---

## 📖 Documentation

Full reference documentation lives in [`docs/0.0.1/`](docs/0.0.1/).

---

## ⚙️ Requirements

- **Python** ≥ 3.14
- **Supported databases** — PostgreSQL, MySQL/MariaDB, SQLite

---

## 📜 License

MIT — see [LICENSE](LICENSE).
