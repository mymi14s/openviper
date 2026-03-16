.. _template:

Templates
=========

The ``openviper.template`` package integrates Jinja2 into OpenViper, providing
a cached environment factory and a plugin auto-loader for custom filters and
global functions.

Overview
--------

Template rendering is available directly from response classes — use
:class:`~openviper.http.response.TemplateResponse` in any view handler and
the framework resolves and renders the named template automatically.

The :mod:`~openviper.template.environment` module maintains a
``functools.lru_cache``-backed :class:`~jinja2.Environment` keyed by the tuple
of template search paths.  Every subsequent render with the same paths returns
the same environment at zero cost.

Autoescape is enabled for ``.html`` and ``.jinja2`` extensions by default.

Key Classes & Functions
-----------------------

.. py:function:: openviper.template.environment.get_jinja2_env(search_paths) -> jinja2.Environment

   Return a cached Jinja2 :class:`~jinja2.Environment` for *search_paths*
   (a tuple of directory strings).  Calls
   :func:`~openviper.template.plugin_loader.load` on first construction so
   that all configured filters and globals are available immediately.

   Raises :exc:`ImportError` if ``jinja2`` is not installed.

``openviper.template.plugin_loader``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The plugin loader discovers and registers custom Jinja2 filters and globals
from two locations on startup (once per process):

1. ``<app_dir>/jinja_plugins/`` for each app in ``INSTALLED_APPS``.
2. The project-level directory configured by ``settings.JINJA_PLUGINS["path"]``
   (default: ``"jinja_plugins"``).

Expected directory layout::

    jinja_plugins/
        filters/
            slugify.py      # def slugify(value): ...
            truncate.py     # def truncate(value, length=100): ...
        globals/
            now.py          # def now(): ...

Each callable in a discovered module is registered under its own name.
Private names (starting with ``_``) and unsafe built-ins (``eval``, ``exec``,
etc.) are always skipped.

.. py:function:: openviper.template.plugin_loader.load(env) -> None

   Discover and register all plugins into *env*.  Idempotent — calling it
   multiple times is safe.

Example Usage
-------------

.. seealso::

   Working projects that use templates:

   - `examples/todoapp/ <https://github.com/mymi14s/openviper/tree/master/examples/todoapp>`_ — HTML templates with form handling
   - `examples/ai_smart_recipe_generator/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_smart_recipe_generator>`_ — Jinja2 HTML rendering with static assets
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ — Jinja2 templates with plugins

TemplateResponse in a View
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.routing.router import Router
    from openviper.http.request import Request
    from openviper.http.response import TemplateResponse

    router = Router()

    @router.get("/")
    async def home(request: Request) -> TemplateResponse:
        posts = await Post.objects.filter(is_published=True).limit(10).all()
        return TemplateResponse("home.html", {
            "request": request,
            "posts": posts,
        })

Template Structure
~~~~~~~~~~~~~~~~~~

Place templates in a ``templates/`` directory at the project root or inside
any installed app:

.. code-block:: text

    myproject/
        templates/
            base.html
            home.html
        blog/
            templates/
                blog/
                    post_detail.html

``templates/home.html``:

.. code-block:: html+jinja

    {% extends "base.html" %}
    {% block content %}
    <ul>
      {% for post in posts %}
        <li><a href="/posts/{{ post.id }}">{{ post.title }}</a></li>
      {% endfor %}
    </ul>
    {% endblock %}

Custom Filter Plugin
~~~~~~~~~~~~~~~~~~~~~

Create ``jinja_plugins/filters/truncate_words.py``:

.. code-block:: python

    def truncate_words(value: str, count: int = 20) -> str:
        """Truncate *value* to at most *count* words."""
        words = value.split()
        if len(words) <= count:
            return value
        return " ".join(words[:count]) + "…"

The filter is available in all templates automatically:

.. code-block:: html+jinja

    {{ post.body | truncate_words(15) }}

Configuration
-------------

.. code-block:: python

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        TEMPLATES_DIR: str = "templates"   # base template search path
        JINJA_PLUGINS: dict = dataclasses.field(default_factory=lambda: {
            "enable": 1,
            "path": "jinja_plugins",
        })
