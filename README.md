<div align="center">

# 🐍 OpenViper

**A production-ready, high-performance, async-first Python web framework.**

*The freedom of a minimal core. The power of a full stack.*

[![Python](https://img.shields.io/badge/python-3.14%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.0.1-orange)](pyproject.toml)

</div>

---

**OpenViper** is a production-ready, high-performance, async-first Python web framework designed to be both flexible and batteries-included. It gives you the freedom of a minimal, unopinionated core when you want control, while also providing a rich, fully integrated stack when you want to move fast.

Out of the box it includes a powerful ORM with model lifecycle and events, built-in authentication and authorization, an Admin UI, background task processing, a pluggable AI provider registry, and automatic OpenAPI documentation.

Whether you're building lean APIs or full-scale platforms, OpenViper scales with you — without forcing you into rigid architectural constraints.

---

## ✨ Features

| | |
|---|---|
| 🔀 **Routing** | function-based and class-based (`View`) routes, path params, route groups |
| 🗄️ **ORM** | Async models, QuerySet API, migrations, lifecycle hooks, model events |
| 🔐 **Auth** | Session + JWT, password hashing, roles, permissions, `@login_required` |
| 🖥️ **Admin UI** | Auto-discovered SPA — CRUD, bulk actions, change history, inlines |
| 🔧 **Middleware** | Auth, CORS, CSRF, rate-limiting, security headers |
| ⚙️ **Background Tasks** | Task queue with retry, priorities, model-event hooks |
| 🕐 **Scheduler** | Cron and interval periodic jobs built into the framework |
| 🤖 **AI Registry** | Unified async API — OpenAI, Anthropic, Gemini, Ollama, Grok, custom |
| 📦 **Serializers** | Pydantic-based, `ModelSerializer`, `Serializer`, nested, partial updates, role-aware |
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
openviper run app --reload
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

# Configure your myproject/settings.py


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
        print("Post created:", self.title)
        send_welcome_email.send_with_options(args=(self.id,), delay=5_000)

    async def on_update(self):
        # Lifecycle hook — update timestamp before every update
        print("Post updated:", self.title)

    async def on_delete(self):
        # Lifecycle hook — delete related comments after every post deletion
        print("Post deleted:", self.title)
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

start server

```bash
python viperctl.py runserver
```

Visit `http://localhost:8000/admin`

### Background Tasks

```python
# blog/tasks.py
from openviper.tasks import task

@task()
async def send_welcome_email(post_id: int):
    """
    Do something
    """
```


### Periodic Scheduler

```python
from openviper.tasks.scheduler import periodic
from openviper.tasks.schedule import CronSchedule, IntervalSchedule
from datetime import timedelta

@periodic(every=60)
async def morning_digest():
    ...

@periodic(every=300)
async def refresh_cache():
    ...
```

```bash
python viperctl.py runworker
```

---

## 📂 Examples

| Example | Description |
|---|---|
| [`todoapp`](https://github.com/mymi14s/openviper/tree/master/examples/todoapp) | Single-file app — auth, admin, SQLite, HTML templates |
| [`ai_moderation_platform`](https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform) | Multi-app platform — AI moderation, Dramatiq tasks, Docker, PostgreSQL |
| [`ai_smart_recipe_generator`](https://github.com/mymi14s/openviper/tree/master/examples/ai_smart_recipe_generator) | AI-powered recipe generator with meal planning and nutrition analysis |
| [`ecommerce_clone`](https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone) | Full e-commerce platform — products, orders, cart, chat, admin |
| [`custom_provider_demo`](https://github.com/mymi14s/openviper/tree/master/examples/custom_provider_demo) | Writing and registering a custom AI provider plugin |
| [`flexible`](https://github.com/mymi14s/openviper/tree/master/examples/flexible) | Minimal decorator-based routing example |
| [`fx`](https://github.com/mymi14s/openviper/tree/master/examples/fx) | FX / financial data example |
| [`tp`](https://github.com/mymi14s/openviper/tree/master/examples/tp) | Minimal project scaffold example |

---

## 📖 Documentation

Full reference documentation lives in [`https://mymi14s.github.io/openviper/`](https://mymi14s.github.io/openviper/).


---

## ⚙️ Requirements

- **Python** ≥ 3.14
- **Supported DB driver**   — PostgreSQL, MySQL/MariaDB, SQLite


---

## 📜 License

MIT — see [LICENSE](LICENSE).
