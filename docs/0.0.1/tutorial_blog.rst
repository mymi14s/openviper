.. _tutorial_blog:

============================
Tutorial: Building a Blog
============================

This tutorial builds a complete blog application from scratch.  By the end
you will have:

* A ``CustomUser`` model
* A ``Post`` model event hooks
* A role-protected :class:`~openviper.serializers.ModelSerializer`
* Authenticated create/update/delete views
* Admin registration for the Post model
* A background task that sends a notification when a post is published
* A periodic task that auto-publishes scheduled posts
* An optional AI endpoint that generates post content

.. note::

   Assumes you have already installed OpenViper and have a working
   project skeleton (see :doc:`installation`).

----

Step 1 — Create the Project
----------------------------

.. code-block:: bash

   openviper create-project myblog
   cd myblog

   # Set a real secret key and change the database URL in myblog/settings.py if you want to use Postgres or Mariadb
   SECRET_KEY = "change-this-in-production"
   DATABASE_URL = "sqlite+aiosqlite:///blog.sqlite3" # for SQLite
   DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/dbname" # for Postgres
   DATABASE_URL="mysql+aiomysql://user:password@localhost/dbname" # for Mariadb

   # Set the admin configuration in myblog/settings.py
   ADMIN_HEADER_TITLE = "My Blog Admin"
   ADMIN_FOOTER_TITLE = "Footer Admin"

   # Set the custom user model in myblog/settings.py
   USER_MODEL = "users.modelsUser"

----

Step 2 — Create the Users App
------------------------------

.. code-block:: bash

   python viperctl.py create-app users

Edit ``myblog/settings.py`` to add the app:

.. code-block:: python

    INSTALLED_APPS: tuple[str, ...] = (
        "openviper.auth",
        "openviper.admin",
        "users",
    )

----

Create the custom user model:

.. code-block:: python

   from openviper.auth.models import AbstractUser
   from openviper.db.fields import CharField, EmailField


   class User(AbstractUser):
       """Custom user model."""

       hobby = CharField(max_length=255, null=True, blank=True)

       class Meta:
           table_name = "users_user"

       # ── Lifecycle hooks ─────────────────────────────────────────────────

       async def after_insert(self) -> None:
           """Send a welcome email to the user."""
           print("User created: %s" % self.username) # there are more hooks available

        async def on_update(self) -> None:
            """Log when a user's email is changed."""
            print("User updated: %s" % self.username)

------------------------------------------
Create Migrations and Migrate the Database
------------------------------------------

.. code-block:: bash

   python viperctl.py makemigrations users
   python viperctl.py migrate # apply migrations

-----------------------
Add User model to admin
-----------------------

Edit ``users/admin.py``:

.. code-block:: python

    """Admin registration for the users app."""

    from __future__ import annotations

    from openviper.admin import register
    from openviper.admin.options import ModelAdmin
    from openviper.auth.admin import UserRoleInline

    from .models import User


    @register(User)
    class UserAdmin(ModelAdmin):
        list_display = ["username", "email", "full_name", "is_active", "is_staff", "is_superuser"]
        search_fields = ["username", "email", "first_name", "last_name"]
        list_filter = ["is_active", "is_staff", "is_superuser"]
        child_tables = [UserRoleInline] #Role management inline, for restriction users to specific roles, not important right now

        def get_sensitive_fields(self, request=None, obj=None):
            return super().get_sensitive_fields(request, obj) + ["password"] # fields ro remove from admin


------------------
Create a Superuser
------------------

.. code-block:: bash

   python viperctl.py createsuperuser

------------------------
Login to the admin panel
------------------------

.. code-block:: bash

   python viperctl.py runserver --reload # optional --host [IP_ADDRESS] --port 8000 --reload

Navigate to http://localhost:8000/admin/ and login with the superuser credentials.


Step 3 — Create the Blog App
------------------------------

.. code-block:: bash

   python viperctl.py create-app blog

Edit ``myblog/settings.py`` to add the app:

.. code-block:: python

    INSTALLED_APPS: tuple[str, ...] = (
        "openviper.auth",
        "openviper.admin",
        "users",
        "blogs" # add the blog app
    )

----

Define the Post Model
---------------------

Edit ``blog/models.py``:

.. code-block:: python

   import re
   from openviper.utils.timezone import now
   from openviper.db.models import Model
   from openviper.db.fields import (
       CharField, TextField, BooleanField,
       DateTimeField, ForeignKey
   )
   from openviper.auth import get_user_model


   User = get_user_model()

   class Post(Model):
       """A blog post authored by a registered user."""

       title        = CharField(max_length=255)
       slug         = CharField(max_length=255, unique=True, null=True)
       body         = TextField()
       author       = ForeignKey(to=User, on_delete="CASCADE")
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
               self.slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
           print("Post before save: %s" % self.title)

       async def after_insert(self) -> None:
           """Fire background notification on first save."""
           print("Post after inserted: %s" % self.title)

       async def on_update(self) -> None:
           """Stamp published_at when a post first goes live."""
           if self.published and not self.published_at:
               self.published_at = now()

       async def on_delete(self) -> None:
           """Called before the DELETE is issued.  Raise to abort deletion."""
           print("Post on deleted: %s" % self.title)

       async def after_delete(self) -> None:
           """Called after a successful DELETE."""
           print("Post after deleted: %s" % self.title)

Create and apply the migration:

.. code-block:: bash

   python viperctl.py makemigrations blog
   python viperctl.py migrate blog

----


Create the Serializer (Optional)
--------------------------------

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

Step 4 — Write the Views
--------------------------

Edit ``blog/views.py``:

.. code-block:: python

    from openviper import JSONResponse
    from openviper.http.request import Request
    from openviper.exceptions import NotFound, PermissionDenied
    from openviper.auth.decorators import login_required
    from .models import Post
    from .serializers import PostSerializer, PostListSerializer


    async def list_posts(request: Request) -> JSONResponse:
        """Public endpoint — returns published posts."""
        posts = await Post.objects.filter(published=True).order_by("-published_at").all()
        return JSONResponse(PostListSerializer.serialize_many(posts))


    @login_required
    async def create_post(request: Request) -> JSONResponse: # return type is optional
        """Authenticated users can create posts."""
        data = await request.json()
        data["author"] = request.user.pk          # inject authenticated author
        serializer = PostSerializer.validate(data)
        post_data = await serializer.save()
        return JSONResponse(post_data, status_code=201)


    async def get_post(request: Request, post_id: int) -> JSONResponse:
        """Public endpoint — returns a single published post."""
        post = await Post.objects.get_or_none(id=post_id, published=True)
        if post is None:
            raise NotFound("Post not found.")
        return JSONResponse(PostSerializer.from_orm(post).serialize())


    @login_required
    async def update_post(request: Request, post_id: int) -> JSONResponse:
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
    async def delete_post(request: Request, post_id: int) -> JSONResponse:
        """Authors can delete their own posts."""
        post = await Post.objects.get_or_none(id=post_id)
        if post is None:
            raise NotFound("Post not found.")
        if post.author != request.user.pk:
            raise PermissionDenied("You are not the author of this post.")
        await post.delete()
        return JSONResponse({"detail": "Deleted."}, status_code=204)

----

Step 5 — Register Routes
--------------------------

Edit ``blog/routes.py``:

.. code-block:: python

    from openviper.routing import Router
    from . import views

    router = Router(prefix="")

    router.add("/posts", views.list_posts, methods=["GET"]) # methods can be GET, POST, PUT, PATCH, DELETE
    router.add("/posts/create", views.create_post, methods=["POST"])

    router.add("/posts/id/{post_id:int}", views.get_post, methods=["GET"])
    router.add("/posts/update/{post_id:int}", views.update_post, methods=["PUT"])
    router.add("/posts/delete/{post_id:int}", views.delete_post, methods=["DELETE"])


Include the router in ``myblog/routes.py``:

.. code-block:: python

    """Top-level routes for myblog."""

    from openviper.conf import settings
    from openviper.admin import get_admin_site
    from openviper.staticfiles import media, static

    from myblog.views import router as root_router
    from blog.routes import router as blog_router

    route_paths = [
        ("/admin", get_admin_site()),
        ("/root", root_router),
        ("/blog", blog_router)
    ]


    # To force static files serving in production
    # Do not use in production, it is also not required in development
    if not settings.DEBUG:
        route_paths += static() + media()
    


----

Step 6 — Register with the Admin Panel
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

----------------------------------------------------------------------------------
Start the server and navigate to admin, see the left sidebar. create Post records.
----------------------------------------------------------------------------------


Step 7 — Task and Events
---------------------------------------
Ensure redis is installed.
.. code-block:: bash

    sudo apt install redis # Linux
    brew install redis # Mac

Next, setup the broker in ``myblog/settings.py``:

.. code-block:: python

    INSTALLED_APPS: tuple[str, ...] = (
        "openviper.auth",
        "openviper.admin",
        "openviper.tasks", # add tasks app before custom apps
        "users",
        "blog",
    )

    # Background Tasks
    TASKS: dict[str, Any] = dataclasses.field(
        default_factory=lambda: {
            "enabled": 1, # enable background tasks using redis
            "scheduler_enabled": 1, # enable scheduler for periodic tasks
            "tracking_enabled": 1, # enable task tracking, logging to database
            "log_to_file": 1, # log to file
            "log_level": "DEBUG", # log level
            "log_format": "json", # log format
            "log_dir": "logs", # log directory
            "broker": "redis", # broker type
            "broker_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            "backend_url": os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/1"),
        }
    )

Create ``blog/tasks.py``:

.. code-block:: python

    import logging, os
   
    from openviper.tasks import periodic, task
    from openviper.auth import get_user_model
    from .models import Post
   

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
   
    User = get_user_model()  # get the active user model

    @task() # will be run in a background worker, later in events.py
    async def notify_new_post(post_id: int) -> None:
        """Send a notification to all staff users when a new post is created."""

        post = await Post.objects.get_or_none(id=post_id)
        if post is None:
            return

        staff_users = await User.objects.filter(is_staff=True).all()
        for user in staff_users:
            # Replace with your real notification mechanism
            print(f"Notifying {user.email}: new post '{post.title}'")
            logger.info("Notifying about wew blog to {user.name}".format(user=user))


    @periodic(every=60) # 60 seconds
    async def check_something() -> None:
        """Demo periodic task — every 60 s."""
        logger.info("Periodic working next 1 minute")


Create ``blog/events.py``:


.. code-block:: python

    from openviper.db.events import model_event
    from blog.tasks import notify_new_post


    @model_event.trigger("blog.models.Post.after_insert") # same as defining events in the Model to can be used else where
    async def blog_after_insert(obj, event) -> None:
        """Event handler for when a new post is updated."""
        print(f"Post insert event: {event}")
        print("Post title", obj.title)
        # queue tasks
        notify_new_post.send_with_options(args=(obj.id,), delay=5_000) # 5 seconds delay


Start the background worker:

It should be started in a separate terminal from the server.

.. code-block:: bash

   python viperctl.py runworker

----

Step 8 — Optional: AI Content Generator
------------------------------------------

Enable the AI registry in ``myblog/settings.py``:

.. code-block:: python

    ENABLE_AI_PROVIDERS = True
    AI_PROVIDERS: dict[str, Any] = dataclasses.field(
        default_factory=lambda: {
            "ollama": {
                "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                "models": {
                    "Granite Code 3B": "granite-code:3b",
                    "Llama 3": "llama3",
                    "Mistral": "mistral",
                    "Code Llama": "codellama",
                },
            },
            "gemini": {
                "api_key": os.environ.get("GEMINI_API_KEY"),
                "project_number": os.environ.get("GEMINI_PROJECT_NUMBER")
                "models": {
                    "GEMINNI 2.5 FLASH": "gemini-2.5-flash",
                    "GEMINI 3 PRO PREVIEW": "gemini-3-pro-preview",
                    "GEMINI 3 FLASH PREVIEW": "gemini-3-flash-preview",
                    "GEMINI 3.1 PRO PREVIEW": "gemini-3.1-pro-preview",
                    "GEMINI 3.1 FLASH LITE PREVIEW": "gemini-3.1-flash-lite-preview",
                },
                "embed_model": "models/text-embedding-004",
                "temperature": 1.0,
                "max_output_tokens": 2048,
                "candidate_count": 1,
                "top_p": 0.95,
                "top_k": 40,
            },
        }
    )



Explore the Tools
-----------------

OpenViper provides several management tools via the shell.
The framework also provides a registry extension generator to add more AI providers.
See: ``python viperctl.py create-provider --help``

.. note::

   Supported AI providers include Ollama, Gemini, OpenAI, Anthropic, and Grok.

.. code-block:: bash

    python viperctl.py shell

    In [9]: from openviper.ai.registry import provider_registry

    In [10]: provider_registry.list_provider_names()
    Out[10]: ['gemini', 'ollama']

    In [11]: provider_registry.list_models()
    Out[11]: 
    ['codellama',
    'gemini-2.5-flash',
    'gemini-3-flash-preview',
    'gemini-3-pro-image-preview',
    'gemini-3-pro-preview',
    'gemini-3.1-flash-lite-preview',
    'gemini-3.1-pro-preview',
    'gemini-3.1-pro-preview-customtools',
    'granite-code:3b',
    'llama3',
    'mistral']

    In [12]: provider = provider_registry.get_by_model("gemini-2.5-flash")

    In [13]: draft = await provider.generate(
        ...:     f"Write a 50-word blog post introduction about: Python Programming"
        ...: )

    In [14]: draft
    Out[14]: 'Welcome to the exciting world of Python programming! Renowned for its clear syntax and versatility, Python is the perfect language for beginners and seasoned developers alike. From web development and data science to AI and automation, Python simplifies complex tasks, making coding intuitive and fun. Get ready to unlock incredible possibilities and supercharge your projects with this powerful language!'

    In [15]: 

Add an AI-assisted view in ``blog/views.py``:

.. code-block:: python

   from openviper.ai.registry import provider_registry


   @login_required
   async def ai_draft(request: Request):
        """Generate a blog post draft from a topic."""
        body = await request.json()
        topic = body.get("topic", "")
        if not topic:
            return JSONResponse({"error": "topic is required"}, status_code=400)

        provider = provider_registry.get_by_model("gemini-2.5-flash")
        draft = await provider.generate(
            f"Write a 200-word blog post introduction about: {topic}"
        )
       return JSONResponse({"draft": draft})

Register the endpoint:
``blog.routes``

.. code-block:: python

   router.add("/posts/ai/draft", views.ai_draft, methods=["POST"])

----

Testing with Swagger UI (OpenAPI)
---------------------------------

1. Open http://127.0.0.1:8000/open-api/docs
2. Use the admin login endpoint ``/admin/api/auth/login/`` to authenticate:

.. code-block:: json

   {
       "username": "username",
       "password": "password"
   }

3. Copy the ``access_token`` from the response and use it in the ``Authorization`` header.
4. Use the ``/posts/ai/draft`` endpoint to generate a draft:

.. code-block:: json

   {
       "topic": "software engineering"
   }

Well Done!
----------

.. seealso::

   * :doc:`db` — Model fields, queries, transactions, and lifecycle events.
   * :doc:`auth` — Securing views with decorators.
   * :doc:`tasks` — Background task configuration and worker startup.
   * :doc:`tasks` — Periodic task scheduling.
   * :doc:`ai` — AI provider configuration and custom providers.
