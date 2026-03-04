.. _quickstart:

===========
Quick Start
===========

OpenViper supports two ways to start a project. Choose the one that fits your
use case.

.. contents:: Approaches
   :local:
   :depth: 1

----

Flexible — Single File
======================

The fastest way to get something running. Everything lives in one ``.py`` file:
routes, handlers, and the server start-up. Ideal for quick microservices,
prototypes, or standalone endpoints where a full project layout would be
overkill.

**Install:**

.. code-block:: bash

   pip install openviper

**Create** ``main.py``:

.. code-block:: python

   from openviper import OpenViper
   from openviper.http.request import Request

   app = OpenViper(title="My Microservice", version="1.0.0")


   @app.get("/")
   async def index(request: Request):
       return {"message": "Hello, World!"}


   @app.get("/items/{item_id}")
   async def get_item(request: Request, item_id: int):
       return {"item_id": item_id}


   @app.post("/items")
   async def create_item(request: Request):
       data = await request.json()
       return {"created": data}, 201

**Run:**

.. code-block:: bash

   openviper run main
   # INFO:     Uvicorn running on http://127.0.0.1:8000

**Try it:**

.. code-block:: bash

   curl http://127.0.0.1:8000/
   curl http://127.0.0.1:8000/items/42
   curl -X POST http://127.0.0.1:8000/items \
        -H "Content-Type: application/json" \
        -d '{"name": "widget"}'

   # OpenAPI docs
   open http://127.0.0.1:8000/open-api/docs

When your microservice grows, you can split handlers into separate files and
mount them with ``app.include_router()``. When it outgrows a single module
entirely, migrate to the Standard layout below.

----

Standard — Project Structure
=============================

The recommended layout for production services. Code is organised into *apps*
(feature modules) with dedicated files for models, serializers, views, routes,
and admin. Scaffolded by the ``openviper`` CLI.

Create a Project
----------------

.. code-block:: bash

   openviper create-project myproject
   cd myproject

The generated layout:

.. code-block:: text

   myproject/
   ├── myproject/
   │   ├── __init__.py
   │   ├── asgi.py          ← ASGI entry-point
   │   ├── settings.py      ← Settings dataclass
   │   └── routes.py        ← Top-level router
   └── viperctl.py

Configure the Database
----------------------

Open ``myproject/settings.py`` and set a database URL:

.. code-block:: python

   DATABASE_URL = "sqlite+aiosqlite:///./db.sqlite3"

Run the Development Server
--------------------------

.. code-block:: bash

   python viperctl.py runserver
   # INFO:     Uvicorn running on http://127.0.0.1:8000

You should see the default OpenViper landing page at ``http://127.0.0.1:8000``.

Create an App
-------------

OpenViper organises code into *apps* (feature modules):

.. code-block:: bash

   python viperctl.py create-app blog

This creates:

.. code-block:: text

   blog/
   ├── __init__.py
   ├── models.py
   ├── serializers.py
   ├── views.py
   ├── routes.py
   ├── admin.py
   └── migrations/

Define a Model
--------------

Edit ``blog/models.py``:

.. code-block:: python

   from openviper.db.models import Model
   from openviper.db.fields import (
       CharField, TextField, BooleanField, DateTimeField
   )

   class Post(Model):
       title      = CharField(max_length=255)
       body       = TextField()
       published  = BooleanField(default=False)
       created_at = DateTimeField(auto_now_add=True)
       updated_at = DateTimeField(auto_now=True)

       class Meta:
           table_name = "blog_posts"

Create and apply the migration:

.. code-block:: bash

   python viperctl.py makemigrations blog
   python viperctl.py migrate

Define a Serializer
-------------------

Edit ``blog/serializers.py``:

.. code-block:: python

   from openviper.serializers import ModelSerializer
   from .models import Post

   class PostSerializer(ModelSerializer):
       class Meta:
           model            = Post
           fields           = "__all__"
           read_only_fields = ("id", "created_at", "updated_at")

Write Views
-----------

Edit ``blog/views.py``:

.. code-block:: python

   from openviper import JSONResponse
   from openviper.http.request import Request
   from openviper.exceptions import NotFound
   from .models import Post
   from .serializers import PostSerializer

   async def list_posts(request: Request):
       posts = await Post.objects.filter(published=True).all()
       return JSONResponse(PostSerializer.serialize_many(posts))

   async def create_post(request: Request):
       data = await request.json()
       serializer = PostSerializer.validate(data)
       post_data = await serializer.save()
       return JSONResponse(post_data, status_code=201)

   async def get_post(request: Request, post_id: int):
       post = await Post.objects.get_or_none(id=post_id)
       if post is None:
           raise NotFound("Post not found")
       return JSONResponse(PostSerializer.from_orm(post).serialize())

Register Routes
---------------

Edit ``blog/routes.py``:

.. code-block:: python

   from openviper.routing.router import Router
   from . import views

   router = Router()

   router.get("/posts",            views.list_posts)
   router.post("/posts",           views.create_post)
   router.get("/posts/{post_id}",  views.get_post)

Then include the blog router in your project's ``myproject/routes.py``:

.. code-block:: python

   from openviper.routing.router import Router
   from blog.routes import router as blog_router

   router = Router()
   router.include_router(blog_router)

Register with Admin
-------------------

Edit ``blog/admin.py``:

.. code-block:: python

   from openviper.admin import admin
   from openviper.admin.options import ModelAdmin
   from .models import Post

   @admin.register(Post)
   class PostAdmin(ModelAdmin):
       list_display  = ["id", "title", "published", "created_at"]
       list_filter   = ["published"]
       search_fields = ["title"]

Create a Superuser and Visit the Admin
--------------------------------------

.. code-block:: bash

   python viperctl.py createsuperuser

Navigate to ``http://127.0.0.1:8000/admin`` in your browser and log in.

Test the API
------------

.. code-block:: bash

   # List posts
   curl http://127.0.0.1:8000/posts

   # Create a post
   curl -X POST http://127.0.0.1:8000/posts \
        -H "Content-Type: application/json" \
        -d '{"title":"Hello","body":"World","published":true}'

   # OpenAPI docs
   open http://127.0.0.1:8000/open-api/docs

.. seealso::

   :ref:`tutorial_blog` for a full step-by-step tutorial covering authentication,
   background tasks, periodic scheduling, and AI integration.
