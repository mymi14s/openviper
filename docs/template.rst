.. _template:

Templates
=========

The ``openviper.template`` package integrates Jinja2 into OpenViper, providing
a cached environment factory and a plugin auto-loader for custom filters and
global functions.

Overview
--------

Template rendering is available directly from response classes - use
:class:`~openviper.http.response.HTMLResponse` with ``template=`` and
``context=`` in any view handler and the framework resolves and renders the
named template automatically.

The :mod:`~openviper.template.environment` module maintains a
``functools.lru_cache``-backed :class:`~jinja2.sandbox.SandboxedEnvironment`
keyed by the tuple of template search paths.  Every subsequent render with
the same paths returns the same environment at zero cost.

Autoescape is enabled for ``.html`` and ``.jinja2`` extensions by default.

All resolved template directories are validated against the project root via
:func:`~openviper.template.environment.validate_path_within_root` to prevent
directory-traversal attacks.  Paths that escape the root are rejected and
logged as warnings.

Key Classes & Functions
-----------------------

.. py:function:: openviper.template.render_to_string(template_name, context=None) -> str

   Render a template by name and return the resulting string.  Resolves
   search paths from ``settings.TEMPLATES_DIR`` and ``templates/`` folders
   in ``settings.INSTALLED_APPS`` automatically.

   :param template_name: Template file name relative to a search path directory.
   :param context: Optional dict of template context variables.
   :returns: Rendered template string.

.. py:function:: openviper.template.environment.get_jinja2_env(search_paths) -> jinja2.sandbox.SandboxedEnvironment

   Return a cached Jinja2 :class:`~jinja2.sandbox.SandboxedEnvironment` for
   *search_paths* (a tuple of directory strings).  Calls
   :func:`~openviper.template.plugin_loader.load` on first construction so
   that all configured filters and globals are available immediately.

   A sandboxed environment prevents template authors from accessing
   dangerous attributes (``__class__``, ``__subclasses__``, etc.) and
   executing arbitrary Python code.

   Raises :exc:`ImportError` if ``jinja2`` is not installed.

.. py:function:: openviper.template.environment.get_template_directories() -> tuple[str, ...]

   Return a deduplicated tuple of absolute paths to template directories.
   Scans ``settings.INSTALLED_APPS`` for ``templates/`` folders and includes
   the project-level ``settings.TEMPLATES_DIR``.  All paths are validated
   against the project root to prevent directory-traversal attacks.

.. py:function:: openviper.template.environment.validate_path_within_root(path, root) -> str | None

   Resolve *path* and return it only if it resides within *root*.  Returns
   ``None`` when the resolved path escapes *root*.  Neutralises
   directory-traversal tokens (``../``), encoded slashes, and
   double-decoding edge cases.

.. py:function:: openviper.template.environment.resolve_project_root() -> str

   Return the absolute path to the project root directory.  Walks up from
   the settings module to find a stable root.  Falls back to the current
   working directory when a settings module path is unavailable.

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
            slugify.py
            truncate.py
        globals/
            now.py

Each callable in a discovered module is registered under its own name.
Private names (starting with ``_``) and unsafe built-ins (``eval``, ``exec``,
etc.) are always skipped.  The full denylist is available as
:data:`~openviper.template.plugin_loader.UNSAFE_CALLABLE_NAMES`.

.. py:function:: openviper.template.plugin_loader.load(env, *, wait=True) -> None

   Discover and register all plugins into *env*.  Idempotent - calling it
   multiple times is safe.  Project-level plugins overwrite app-level
   plugins that share the same name.

   :param env: A :class:`jinja2.Environment` instance.
   :param wait: If ``True`` (default), blocks until discovery completes.
       If ``False``, registers any already-discovered plugins immediately
       and returns.

.. py:function:: openviper.template.plugin_loader.scan_directory(directory) -> dict[str, object]

   Return ``{callable_name: callable}`` for all public callables found in
   *directory*.  Uses :func:`os.scandir` for a single-level, non-recursive
   scan.  Files starting with ``_`` or not ending in ``.py`` are skipped.
   Symlinks are rejected to prevent loading arbitrary code from outside
   the plugin directory.

.. py:function:: openviper.template.plugin_loader.import_plugin_module(path, name) -> types.ModuleType | None

   Load a Python source file directly from *path* via :mod:`importlib`.
   Returns ``None`` and logs a warning if loading fails.  Bytecode writing
   is suppressed during the load to avoid writing transient ``.pyc`` files.

.. py:data:: openviper.template.plugin_loader.UNSAFE_CALLABLE_NAMES

   A :class:`frozenset` of callable names that must never be exposed to
   templates, regardless of source.  Includes ``eval``, ``exec``,
   ``compile``, ``__import__``, ``open``, ``input``, ``breakpoint``,
   ``getattr``, ``hasattr``, ``type``, and ``vars``.

.. py:class:: openviper.template.plugin_loader.State

   Singleton state container for discovered plugins.  Holds ``loaded``,
   ``filters``, ``globals``, and ``future`` attributes.  Uses ``__init__``
   to ensure each instance owns its own mutable collections.

.. py:function:: openviper.template.plugin_loader.discover_plugins(cfg) -> bool

   Discover and merge plugins from app-level and project-level roots.
   Called internally by :func:`~openviper.template.plugin_loader.load`.
   Returns ``True`` on success.

.. py:function:: openviper.template.plugin_loader.reset() -> None

   Reset the singleton state.  For testing only - calling this in
   production will cause plugins to be re-discovered on the next
   ``load()`` call.

Example Usage
-------------

.. seealso::

   Working projects that use templates:

   - `examples/todoapp/ <https://github.com/mymi14s/openviper/tree/master/examples/todoapp>`_ - HTML templates with form handling
   - `examples/ai_smart_recipe_generator/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_smart_recipe_generator>`_ - Jinja2 HTML rendering with static assets
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ - Jinja2 templates with plugins

HTMLResponse with a Template
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.routing.router import Router
    from openviper.http.request import Request
    from openviper.http.response import HTMLResponse

    router = Router()

    @router.get("/")
    async def home(request: Request) -> HTMLResponse:
        posts = await Post.objects.filter(is_published=True).limit(10).all()
        return HTMLResponse(template="home.html", context={
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
        return " ".join(words[:count]) + "..."

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
