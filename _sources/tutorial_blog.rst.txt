.. _tutorial_blog:

============================
Tutorial: Building a Blog
============================

This tutorial builds a complete blog application from scratch.  By the end
you will have:

* A ``Post`` model with full lifecycle hooks
* A role-protected :class:`~openviper.serializers.ModelSerializer`
* Authenticated create/update/delete views
* Admin registration for the Post model
* A background task that sends a notification when a post is published
* A periodic task that auto-publishes scheduled posts
* An optional AI endpoint that generates post content

.. note::

   Assumes you have already installed OpenViper and have a working
   project skeleton (see :ref:`quickstart`).

----

Step 1 — Create the Project
----------------------------

.. code-block:: bash

   openviper create-project myblog
   cd myblog

   # Set a real secret key and database URL in myblog/settings.py
   SECRET_KEY = "change-this-in-production"
   DATABASE_URL = "sqlite+aiosqlite:///./blog.sqlite3"

----

Step 2 — Create the Blog App
------------------------------

.. code-block:: bash

   python viperctl.py create-app blog

Edit ``myblog/settings.py`` to add the app:

.. code-block:: python

   INSTALLED_APPS = (
       "openviper.auth",
       "blog",
   )

----

Step 3 — Define the Post Model
-------------------------------

Edit ``blog/models.py``:

.. code-block:: python

   from openviper.db.models import Model
   from openviper.db.fields import (
       CharField, TextField, BooleanField,
       DateTimeField, ForeignKey
   )
   from openviper.auth.models import User


   class Post(Model):
       """A blog post authored by a registered user."""

       title        = CharField(max_length=255)
       slug         = CharField(max_length=255, unique=True, null=True)
       body         = TextField()
       author       = ForeignKey(to="auth.User", on_delete="CASCADE")
       published    = BooleanField(default=False)
       published_at = DateTimeField(null=True)
       created_at   = DateTimeField(auto_now_add=True)
       updated_at   = DateTimeField(auto_now=True)

       class Meta:
           table_name = "blog_posts"

       # ── Lifecycle hooks ─────────────────────────────────────────────────

       async def before_save(self) -> None:
           """Automatically derive slug from title if not set."""
           if not self.slug and self.title:
               import re
               self.slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")

       async def after_insert(self) -> None:
           """Fire background notification on first save."""
           from blog.tasks import notify_new_post
           notify_new_post.send(post_id=self.pk)

       async def on_update(self) -> None:
           """Stamp published_at when a post first goes live."""
           from openviper.utils.timezone import now
           if self.published and not self.published_at:
               self.published_at = now()

Create and apply the migration:

.. code-block:: bash

   python viperctl.py makemigrations blog
   python viperctl.py migrate

----

Step 4 — Create the Serializer
-------------------------------

Edit ``blog/serializers.py``:

.. code-block:: python

   from openviper.serializers import ModelSerializer, field_validator
   from .models import Post


   class PostSerializer(ModelSerializer):
       """Serializer for the Post model."""

       class Meta:
           model            = Post
           fields           = "__all__"
           read_only_fields = ("id", "slug", "published_at", "created_at", "updated_at")
           extra_kwargs     = {
               "author": {"required": False},   # set from request.user in view
           }

       @field_validator("title")
       @classmethod
       def title_not_empty(cls, v: str) -> str:
           if not v.strip():
               raise ValueError("Title must not be blank.")
           return v.strip()


   class PostListSerializer(ModelSerializer):
       """Lightweight serializer for list views (omits body)."""

       class Meta:
           model   = Post
           fields  = ["id", "title", "slug", "published", "published_at", "created_at"]

----

Step 5 — Write the Views
--------------------------

Edit ``blog/views.py``:

.. code-block:: python

   from openviper import JSONResponse
   from openviper.http.request import Request
   from openviper.exceptions import NotFound, PermissionDenied
   from openviper.auth.decorators import login_required
   from .models import Post
   from .serializers import PostSerializer, PostListSerializer


   async def list_posts(request: Request):
       """Public endpoint — returns published posts."""
       posts = await Post.objects.filter(published=True).order_by("-published_at").all()
       return JSONResponse(PostListSerializer.serialize_many(posts))


   @login_required
   async def create_post(request: Request):
       """Authenticated users can create posts."""
       data = await request.json()
       data["author"] = request.user.pk          # inject authenticated author
       serializer = PostSerializer.validate(data)
       post_data = await serializer.save()
       return JSONResponse(post_data, status_code=201)


   async def get_post(request: Request, post_id: int):
       """Public endpoint — returns a single published post."""
       post = await Post.objects.get_or_none(id=post_id, published=True)
       if post is None:
           raise NotFound("Post not found.")
       return JSONResponse(PostSerializer.from_orm(post).serialize())


   @login_required
   async def update_post(request: Request, post_id: int):
       """Authors can update their own posts."""
       post = await Post.objects.get_or_none(id=post_id)
       if post is None:
           raise NotFound("Post not found.")
       if post.author != request.user.pk:
           raise PermissionDenied("You are not the author of this post.")
       data = await request.json()
       serializer = PostSerializer.validate(data)
       post_data = await serializer.save(instance=post)
       return JSONResponse(post_data)


   @login_required
   async def delete_post(request: Request, post_id: int):
       """Authors can delete their own posts."""
       post = await Post.objects.get_or_none(id=post_id)
       if post is None:
           raise NotFound("Post not found.")
       if post.author != request.user.pk:
           raise PermissionDenied("You are not the author of this post.")
       await post.delete()
       return JSONResponse({"detail": "Deleted."}, status_code=204)

----

Step 6 — Register Routes
--------------------------

Edit ``blog/routes.py``:

.. code-block:: python

   from openviper.routing.router import Router
   from . import views

   router = Router()

   router.get("/posts",             views.list_posts)
   router.post("/posts",            views.create_post)
   router.get("/posts/{post_id}",   views.get_post)
   router.put("/posts/{post_id}",   views.update_post)
   router.delete("/posts/{post_id}", views.delete_post)

Include the router in ``myblog/routes.py``:

.. code-block:: python

   from openviper.routing.router import Router
   from blog.routes import router as blog_router

   router = Router()
   router.include_router(blog_router)

----

Step 7 — Register with the Admin Panel
---------------------------------------

Edit ``blog/admin.py``:

.. code-block:: python

   from openviper.admin import admin
   from openviper.admin.options import ModelAdmin
   from .models import Post


   @admin.register(Post)
   class PostAdmin(ModelAdmin):
       list_display  = ["id", "title", "author", "published", "created_at"]
       list_filter   = ["published", "created_at"]
       search_fields = ["title", "body"]
       readonly_fields = ["slug", "published_at", "created_at", "updated_at"]
       list_per_page = 20

----

Step 8 — Background Notification Task
---------------------------------------

Create ``blog/tasks.py``:

.. code-block:: python

   from openviper.tasks import task
   from openviper.auth.models import User


   @task(queue_name="notifications", max_retries=3)
   async def notify_new_post(post_id: int) -> None:
       """Send a notification to all staff users when a new post is created."""
       from blog.models import Post

       post = await Post.objects.get_or_none(id=post_id)
       if post is None:
           return

       staff_users = await User.objects.filter(is_staff=True).all()
       for user in staff_users:
           # Replace with your real notification mechanism
           print(f"Notifying {user.email}: new post '{post.title}'")

Start the background worker:

.. code-block:: bash

   python viperctl.py runworker --queues notifications

----

Step 9 — Periodic Publishing Task
------------------------------------

Create the periodic task in ``blog/tasks.py``:

.. code-block:: python

   from openviper.tasks import task
   from openviper.tasks.core import Scheduler
   from openviper.tasks.schedule import IntervalSchedule
   from openviper.utils.timezone import now


   @task(queue_name="scheduler")
   async def auto_publish_due_posts() -> None:
       """Publish posts whose scheduled publish time has arrived."""
       from blog.models import Post
       from openviper.db.connection import get_connection

       due_posts = await Post.objects.filter(
           published=False,
           published_at__lte=now(),
       ).all()

       for post in due_posts:
           post.published = True
           await post.save()
           print(f"Auto-published: {post.title}")


   # Register schedule in your project's startup handler or scheduler module
   scheduler = Scheduler()
   scheduler.add(
       name="auto-publish",
       actor=auto_publish_due_posts,
       schedule=IntervalSchedule(minutes=5),
   )

Start the scheduler:

.. code-block:: bash

   python viperctl.py runworker --queues scheduler

----

Step 10 — Optional: AI Content Generator
------------------------------------------

Enable the AI registry in ``myblog/settings.py``:

.. code-block:: python

   ENABLE_AI_PROVIDERS = True
   AI_PROVIDERS = {
       "openai": {
           "provider": "openai",
           "api_key": "your-openai-key",
           "models": {"gpt-4o": "gpt-4o"},
       },
   }

Add an AI-assisted view in ``blog/views.py``:

.. code-block:: python

   from openviper.ai.registry import provider_registry
   from openviper.auth.decorators import login_required


   @login_required
   async def ai_draft(request: Request):
       """Generate a blog post draft from a topic."""
       body = await request.json()
       topic = body.get("topic", "")
       if not topic:
           return JSONResponse({"error": "topic is required"}, status_code=400)

       provider = provider_registry.get_by_model("gpt-4o")
       draft = await provider.generate(
           f"Write a 200-word blog post introduction about: {topic}"
       )
       return JSONResponse({"draft": draft})

Register the endpoint:

.. code-block:: python

   router.post("/posts/ai-draft", views.ai_draft)

----

Running the Complete Application
----------------------------------

.. code-block:: bash

   # Terminal 1 — web server
   python viperctl.py runserver

   # Terminal 2 — background worker
   python viperctl.py runworker --queues notifications,scheduler

   # Terminal 3 — (optional) scheduler tick every minute
   # The scheduler runs inside the worker process automatically when tasks are enqueued

Create a superuser and visit:

* ``http://127.0.0.1:8000/posts`` — public post list
* ``http://127.0.0.1:8000/open-api/docs`` — Swagger UI
* ``http://127.0.0.1:8000/admin`` — admin panel

.. seealso::

   * :ref:`orm` — Model fields, queries, transactions, and lifecycle events.
   * :ref:`authentication` — Securing views with decorators.
   * :ref:`tasks` — Background task configuration and worker startup.
   * :ref:`scheduler` — Periodic task scheduling.
   * :ref:`ai_registry` — AI provider configuration and custom providers.
