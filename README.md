<div align="center">

# 🐍 OpenViper

**A production-ready, high-performance, async-first Python web framework.**

*The freedom of a minimal core. The power of a full stack.*

[![Python](https://img.shields.io/badge/python-3.14%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/pypi/v/openviper?color=orange&label=version)](pyproject.toml)

</div>

---

**OpenViper** is a production-ready, high-performance, async-first Python web framework designed to be both flexible and batteries-included. It gives you the freedom of a minimal, unopinionated core when you want control, while also providing a rich, fully integrated stack when you want to move fast.

Out of the box it includes a powerful ORM with model lifecycle and events, built-in authentication and authorization, an Admin UI, background task processing, a pluggable AI provider registry, automatic OpenAPI documentation, async email, caching, file storage, database routing, and a full testing toolkit.

Whether you're building lean APIs or full-scale platforms, OpenViper scales with you - without forcing you into rigid architectural constraints.

---

## ✨ Features

| | |
|---|---|
| 🔀 **Routing** | function-based and class-based (`View`) routes, path params, sub-routers, per-route middleware |
| 🗄️ **ORM** | Async models, QuerySet API, migrations, lifecycle hooks, model events, protected queries |
| 🔐 **Auth** | Session + JWT + token auth, Argon2id/bcrypt hashing, roles, permissions, `@login_required`, lifecycle hooks |
| 🖥️ **Admin UI** | Auto-discovered Vue 3 SPA - CRUD, bulk actions, change history, inlines, role-based visibility |
| 🔧 **Middleware** | Auth, CORS, CSRF, rate-limiting, security headers, DB connection pinning |
| ⚙️ **Background Tasks** | Dramatiq-backed task queue with retry, priorities, model-event hooks |
| 🕐 **Scheduler** | Cron and interval periodic jobs built into the framework |
| 🤖 **AI Registry** | Unified async API - OpenAI, Anthropic, Gemini, Ollama, Grok, custom providers, streaming, moderation |
| 📦 **Serializers** | Pydantic v2-based, `ModelSerializer`, `Serializer`, nested, partial updates, role-aware, readonly/writeonly fields |
| 📄 **OpenAPI** | Live Swagger + ReDoc UIs auto-generated from your routes and type hints |
| 📧 **Email** | Async email delivery with Jinja2 templates, Markdown rendering, SMTP/Console backends, attachments |
| 💾 **Cache** | In-memory, Redis, Dragonfly, Memcached, and database cache backends with async API |
| 📁 **Storage** | Pluggable file storage API - FileSystemStorage, async uploads, media serving |
| 🌐 **Static Files** | Development static serving, `collectstatic` for production, ETag/range support |
| 🗺️ **Geolocation** | PostGIS-compatible `PointField` with haversine distance, WKT/EWKT/GeoJSON serialization |
| 🏳️ **Country Field** | ISO 3166-1 alpha-2 `CountryField` with O(1) validation, OpenAPI enum |
| 🛡️ **Database Routing** | Read/write replicas, multi-database routing, pluggable backends |
| 🧪 **Testing** | pytest-based TestKit with async HTTP client, model factories, auth helpers, assertion utilities |
| 🖥️ **Templates** | Jinja2 sandboxed environment with auto-escape, plugin auto-loader, path traversal protection |
| 🔌 **Plugins** | `ready()`/`startup()`/`shutdown()` lifecycle hooks, third-party extension API |
| 🐛 **Debug Page** | Rich HTML traceback with credential redaction in DEBUG mode |
| ⚙️ **CLI** | `openviper` for scaffolding, `viperctl` for migrations, superuser, worker, backup, and more |

---

## 🚀 Quick Start

### Install

```bash
pip install openviper
```

Optional extras:

```bash
pip install openviper[postgres]          # PostgreSQL (asyncpg + psycopg2-binary)
pip install openviper[mariadb]          # MariaDB / MySQL (aiomysql)
pip install openviper[mssql]             # MS SQL Server (aioodbc)
pip install openviper[oracle]            # Oracle (oracledb)
pip install openviper[ai]               # OpenAI, Anthropic, Google GenAI SDKs
pip install openviper[tasks]             # Dramatiq 2.1+ task queue, Croniter
pip install openviper[tasks-redis]       # Redis broker for Dramatiq tasks
pip install openviper[tasks-rabbitmq]    # RabbitMQ broker for Dramatiq
pip install openviper[tasks-sqs]          # Amazon SQS broker for Dramatiq
pip install openviper[tasks-postgresql]   # PostgreSQL broker for Dramatiq
pip install openviper[geolocation]       # PostGIS + shapely
pip install openviper[testing]           # pytest, httpx, pytest-asyncio
pip install openviper[all]               # Everything
```

Development extras:

```bash
pip install openviper[dev]          # pytest, black, ruff, mypy, pylint, pre-commit, ...
pip install openviper[docs]         # sphinx, sphinx-rtd-theme, sphinxcontrib-httpdomain
```

### Minimal - single file

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

# Configure DATABASES in myproject/settings.py:
DATABASES = {
    "default": {
        "OPTIONS": {
            "URL": "sqlite+aiosqlite:///./db.sqlite3",
        },
    },
}

# Run migrations and create an admin user
# Using python viperctl.py (from inside the project):
python viperctl.py makemigrations
python viperctl.py migrate
python viperctl.py createsuperuser

# Or using openviper viperctl (from any directory):
openviper viperctl makemigrations .
openviper viperctl migrate .
openviper viperctl createsuperuser .

# Start everything
python viperctl.py start-server    # or: openviper viperctl start-server .
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
        # Lifecycle hook - enqueue moderation task after every new post
        print("Post created:", self.title)
        send_welcome_email.send_with_options(args=(self.id,), delay=5_000)

    async def on_update(self):
        # Lifecycle hook - update timestamp before every update
        print("Post updated:", self.title)

    async def on_delete(self):
        # Lifecycle hook - delete related comments after every post deletion
        print("Post deleted:", self.title)
```

**QuerySet API:**

```python
# All published posts, newest first
posts = await Post.objects.filter(published=True).order_by("-created_at").all()

# Single record - returns None if not found
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

Register models in `blog/admin.py` - OpenViper discovers it automatically:

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

Start the server:

```bash
python viperctl.py start-server    # or: openviper viperctl start-server .
```

Visit `http://localhost:8000/admin`

---

## 📂 Examples

| Example | Description |
|---|---|
| [`todoapp`](https://github.com/mymi14s/openviper/tree/master/examples/todoapp) | Single-file app - auth, admin, SQLite, HTML templates |
| [`ai_moderation_platform`](https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform) | Multi-app platform - AI moderation, Dramatiq tasks, Docker, PostgreSQL |
| [`ai_smart_recipe_generator`](https://github.com/mymi14s/openviper/tree/master/examples/ai_smart_recipe_generator) | AI-powered recipe generator with meal planning and nutrition analysis |
| [`ecommerce_clone`](https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone) | Full e-commerce platform - products, orders, cart, chat, admin |
| [`custom_provider_demo`](https://github.com/mymi14s/openviper/tree/master/examples/custom_provider_demo) | Writing and registering a custom AI provider plugin |
| [`flexible`](https://github.com/mymi14s/openviper/tree/master/examples/flexible) | Minimal decorator-based routing example |
| [`fx`](https://github.com/mymi14s/openviper/tree/master/examples/fx) | FX / financial data example |
| [`tp`](https://github.com/mymi14s/openviper/tree/master/examples/tp) | Minimal project scaffold example |

---

## 📖 Documentation

Full reference documentation lives in [`https://mymi14s.github.io/openviper/`](https://mymi14s.github.io/openviper/).


---

## 🛠️ Management Commands

There are **two ways** to run management commands:

### `python viperctl.py` (from inside a project)

Generated by `openviper create-project`, this script is pre-configured
with your project's settings module:

```bash
cd myproject
python viperctl.py makemigrations
python viperctl.py migrate
python viperctl.py console
python viperctl.py start-server
python viperctl.py start-worker
```

### `openviper viperctl` (from any directory)

Auto-discovers the project layout from the current working directory.
Use `.` to target the current directory:

```bash
# Root-layout projects (e.g. examples/fx)
cd examples/fx
openviper viperctl migrate .
openviper viperctl start-server .

# Module-organized projects (e.g. examples/ai_moderation_platform)
cd examples/ai_moderation_platform
openviper viperctl migrate .
openviper viperctl console .

# Or specify a module name explicitly
openviper viperctl --settings myproject.settings console
```

### Command Reference

| Command | Description |
|---|---|
| `makemigrations` | Generate migration files for changed models |
| `migrate` | Apply pending migrations |
| `createsuperuser` | Interactively create an admin superuser |
| `changepassword` | Change a user's password |
| `console` | Open a Python REPL with models and settings pre-loaded |
| `collectstatic` | Collect static assets into `STATIC_ROOT` |
| `create-app` | Scaffold a new app package |
| `create-provider` | Scaffold a new AI provider package |
| `backup-db` | Create a compressed database backup |
| `restore-db` | Restore a database from backup |
| `start-worker` | Start the background task worker and scheduler |
| `start-server` | Start the ASGI development server |
| `test` | Run the project test suite via pytest |

---

## ⚙️ Requirements

- **Python** ≥ 3.14
- **Supported databases** - PostgreSQL, MySQL/MariaDB, SQLite, Oracle, MS SQL

---

## 📜 License

MIT - see [LICENSE](LICENSE).
