.. _tasks:

==================
Background Tasks
==================

OpenViper integrates **Dramatiq** as its background task library.  The
``openviper.tasks`` package wraps Dramatiq with an async-compatible decorator,
a configurable broker, result tracking, and model lifecycle event hooks.

.. contents:: On this page
   :local:
   :depth: 2

----

How It Works
-------------

1. You decorate a function with ``@task(...)`` — this registers it as a
   Dramatiq *actor*.
2. Call ``.send()`` (or ``.delay()``) to enqueue the message in the broker.
3. One or more worker processes consume messages from the broker and execute
   the handler function.

OpenViper uses **Redis** as the default broker backend.

----

Declaring a Task
-----------------

.. code-block:: python

   # myapp/tasks.py
   from openviper.tasks import task

   @task(queue_name="emails", max_retries=5)
   async def send_welcome_email(user_id: int) -> None:
       from openviper.auth.models import User
       user = await User.objects.get_or_none(id=user_id)
       if user is None:
           return
       # ... send email logic ...
       print(f"Sent welcome email to {user.email}")

``@task`` parameters:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Parameter
     - Description
   * - ``queue_name``
     - Broker queue to publish to (default ``"default"``)
   * - ``priority``
     - Integer priority; higher values processed first (default ``0``)
   * - ``max_retries``
     - Maximum retry attempts before marking as dead-letter (default ``3``)
   * - ``min_backoff``
     - Minimum retry backoff in milliseconds (default ``15 000``)
   * - ``max_backoff``
     - Maximum retry backoff in milliseconds (default ``300 000``)
   * - ``time_limit``
     - Hard execution time limit in milliseconds (``None`` = unlimited)
   * - ``actor_name``
     - Override the actor name in the broker (default: function name)

----

Enqueuing Tasks
----------------

.. code-block:: python

   # Fire and forget (enqueue immediately)
   send_welcome_email.send(user_id=42)

   # Alias
   send_welcome_email.delay(user_id=42)

   # With options — e.g. delay execution by 5 seconds
   send_welcome_email.send_with_options(args=(42,), delay=5_000)

   # With options — override max_retries for this invocation
   send_welcome_email.send_with_options(args=(42,), max_retries=1)

The ``.send()`` call is **synchronous** and non-blocking — it serialises the
message and writes it to Redis; the handler runs in a separate worker process.

----

Async Support
--------------

The ``@task`` decorator transparently wraps async handlers.  You can use
``await`` freely inside a task function:

.. code-block:: python

   @task(queue_name="reports")
   async def generate_report(report_id: int) -> None:
       from myapp.models import Report
       report = await Report.objects.get(id=report_id)

       # async ORM, async HTTP calls, etc.
       data = await fetch_external_data()
       report.result = data
       await report.save()

----

Starting the Worker
--------------------

.. code-block:: bash

   # All queues
   python viperctl.py runworker

   # Specific queues only
   python viperctl.py runworker --queues emails,reports

   # Custom thread count
   python viperctl.py runworker --threads 4

In development, run the worker in a separate terminal alongside the web server.

----

Retry Behaviour
----------------

When a task raises an exception, Dramatiq automatically retries it with
exponential backoff between ``min_backoff`` and ``max_backoff`` milliseconds.
After ``max_retries`` attempts the message is moved to the dead-letter queue.

Log the retry count inside a task:

.. code-block:: python

   import dramatiq

   @task(max_retries=3)
   async def risky_task(item_id: int) -> None:
       message = dramatiq.get_current_message()
       retries = message.options.get("retries", 0)
       print(f"Attempt {retries + 1} for item {item_id}")
       # ...

To abort retries explicitly raise ``dramatiq.exceptions.Retry``:

.. code-block:: python

   import dramatiq

   @task(max_retries=5)
   async def conditional_task(item_id: int) -> None:
       from myapp.models import Item
       item = await Item.objects.get_or_none(id=item_id)
       if item is None:
           raise dramatiq.RateLimitExceeded   # will NOT retry
       ...

----

Broker Configuration
---------------------

Configure the Dramatiq broker in ``settings.py``:

.. code-block:: python

    TASKS: dict[str, Any] = dataclasses.field(
        default_factory=lambda: {
            "enabled": 1,
            "scheduler_enabled": 1,
            "tracking_enabled": 1,
            "log_to_file": 1,
            "log_dir": "logs",
            "broker": "redis",
            "broker_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            "backend_url": os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/1"),
        }
    )

OpenViper initialises the broker lazily when the first ``.send()`` is called
or when the worker process starts.

----

Model Event Hooks
------------------

Model events let you trigger tasks automatically on ORM lifecycle events
*without* placing the task call inside the model itself.

Configure in ``settings.py``:

.. code-block:: python

   MODEL_EVENTS = {
       "blog.models.Post": {
           "after_insert":  ["blog.events.on_post_created"],
           "on_update":     ["blog.events.on_post_updated"],
           "after_delete":  ["blog.events.on_post_deleted"],
           "on_change":     ["blog.events.reindex_post"],
       },
   }

Then define the handlers:

.. code-block:: python

   # blog/events.py

   async def on_post_created(post) -> None:
       """Fires after every new Post is saved."""
       from blog.tasks import send_new_post_notification
       send_new_post_notification.send(post_id=post.pk)

   async def on_post_updated(post) -> None:
       """Fires after every Post update."""
       print(f"Post {post.pk} was updated")

   async def reindex_post(post) -> None:
       """Fires after every change (insert or update)."""
       from blog.tasks import index_post_in_search
       index_post_in_search.send(post_id=post.pk)

The handler functions receive the model instance as their only argument.

----

Decorator-Based Event Handlers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

As an alternative to the ``MODEL_EVENTS`` dictionary you can register
handlers inline with the ``@model_event.trigger`` decorator.  This is
useful when the handler lives in the same module as the model, or when you
prefer explicit registration over configuration:

.. code-block:: python

   # posts/events.py
   from openviper.db.events import model_event

   @model_event.trigger("posts.models.Post.after_insert")
   async def send_email(post, *, event):
       from posts.tasks import send_new_post_notification
       send_new_post_notification.send(post_id=post.pk)

   @model_event.trigger("posts.models.Post.on_change")
   async def reindex_post(post, *, event):
       from posts.tasks import index_post_in_search
       index_post_in_search.send(post_id=post.pk)

   @model_event.trigger("posts.models.Comment.after_insert")
   async def notify_author(comment, *, event):
       from posts.tasks import send_comment_notification
       send_comment_notification.send(comment_id=comment.pk)

The decorator path format is ``"{module}.{ClassName}.{event_name}"``
— the last segment is the event name and everything before it is the
model's dotted module path.

**Handler signature** — both sync and async functions are supported:

.. code-block:: python

   # async handler — scheduled as a fire-and-forget task via asyncio.create_task
   async def my_handler(instance, *, event: str) -> None:
       # instance — the model object that triggered the event
       # event    — the lifecycle hook name, e.g. "after_insert"
       ...

   # sync handler — called directly in the same thread
   def my_sync_handler(instance, *, event: str) -> None:
       ...

The ``*`` before ``event`` makes it keyword-only; always pass it as
``event=`` if calling manually.  Async handlers are dispatched with
``asyncio.get_running_loop().create_task()``, so they run concurrently
and do not block the model save.  If there is no running event loop at
dispatch time (e.g. in a sync context) the handler is skipped and a
warning is logged.

**Key differences vs** ``MODEL_EVENTS``:

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Feature
     - ``MODEL_EVENTS`` (settings)
     - ``@model_event.trigger`` (decorator)
   * - Where handlers live
     - Any importable dotted path
     - Same file or any module that is imported at startup
   * - Works without TASKS enabled
     - No
     - Yes — fires even when ``TASKS['enabled']`` is ``False``
   * - Multiple handlers per event
     - Yes — list of dotted paths
     - Yes — multiple decorators on different functions
   * - Handler ordering
     - Order of list entries
     - Order of decoration (import order)

Both approaches can be used together; settings-based handlers always run
before decorator-registered handlers for the same event.

Import the ``model_event`` singleton from:

.. code-block:: python

   from openviper.db.events import model_event

Make sure the module containing the decorated functions is imported at
application startup (e.g. import it in your app's ``__init__.py`` or
``apps.py``) so the handlers are registered before any model events fire.

----

Task Logging
-------------

OpenViper captures ``stdout``/``stderr`` per task execution.  Logs are stored in
the ``tasks_log`` database table and are visible in the admin panel under
**Tasks → Logs**.

----

Result Tracking
----------------

When result tracking is enabled (``TASKS["tracking_enabled"] = 1``), every
task's lifecycle is stored in the ``openviper_task_results`` table.  The
table is created automatically on first use — no migration required.

Enable a result backend in settings:

.. code-block:: python

   TASKS: dict = {
       "enabled": 1,
       "tracking_enabled": 1,
       "broker": "redis",
       "broker_url": "redis://localhost:6379/0",
       # Optional: save results to a separate DB (default: same as DATABASE_URL)
       "results_db_url": "sqlite:///task_results.db",
   }

Query results from an async view:

.. code-block:: python

   from openviper.tasks.results import get_task_result, list_task_results

   @app.get("/tasks/{message_id}")
   async def task_status(request, message_id: str):
       result = await get_task_result(message_id)
       if result is None:
           return {"error": "Not found"}, 404
       return result
   # Returns: {"message_id": "...", "status": "success",
   #           "result": "...", "actor_name": "...",
   #           "enqueued_at": "...", "completed_at": "..."}

   @app.get("/tasks/")
   async def list_failed_tasks(request):
       failures = await list_task_results(status="failure", limit=20)
       return failures

``list_task_results`` filter parameters:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Parameter
     - Description
   * - ``status``
     - Filter by status: ``pending``, ``running``, ``success``, ``failure``, ``skipped``, ``dead``
   * - ``actor_name``
     - Filter by actor name (e.g. ``"blog.tasks.send_welcome_email"``)
   * - ``queue_name``
     - Filter by queue name
   * - ``limit``
     - Maximum number of rows to return (default ``50``)
   * - ``offset``
     - Skip the first N rows (for pagination)

Sync variants are available for use outside of async contexts (e.g. management commands):

.. code-block:: python

   from openviper.tasks.results import get_task_result_sync, list_task_results_sync

   row = get_task_result_sync("message-uuid")
   rows = list_task_results_sync(status="failure", limit=100)

Each result row contains:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Field
     - Description
   * - ``message_id``
     - Dramatiq UUID (primary key for look-ups)
   * - ``actor_name``
     - Fully-qualified actor name
   * - ``queue_name``
     - Queue the message was sent to
   * - ``status``
     - ``pending`` \| ``running`` \| ``success`` \| ``failure`` \| ``skipped`` \| ``dead``
   * - ``args`` / ``kwargs``
     - Arguments the task was called with (Python objects, decoded from JSON)
   * - ``result``
     - Return value on success
   * - ``error``
     - ``str(exception)`` on failure
   * - ``traceback``
     - Full traceback on failure
   * - ``retries``
     - Number of retries consumed
   * - ``enqueued_at``
     - UTC ISO datetime when enqueued
   * - ``started_at``
     - UTC ISO datetime when worker picked it up
   * - ``completed_at``
     - UTC ISO datetime when it finished

.. seealso::

   :ref:`scheduler` for periodic / cron-based task scheduling.
