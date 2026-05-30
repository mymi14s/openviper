.. _tasks:

Background Tasks
================

The ``openviper.tasks`` package provides async-native background task processing
backed by `Dramatiq <https://dramatiq.io/>`_.  It includes the ``@task``
decorator, a ``@periodic`` scheduler, Redis/RabbitMQ broker configuration,
an in-process worker runner, and optional database-backed task tracking.

Overview
--------

Background tasks are defined with the ``@task`` decorator and enqueued by
calling ``.send()`` on the decorated function.  Tasks run in a dedicated
worker process started with ``openviper viperctl start-worker .``.

Periodic tasks are defined with the ``@periodic`` decorator, which registers
them with the built-in :class:`~openviper.tasks.core.Scheduler`.  The
scheduler ticks inside the worker process - no separate "beat" process is
required.

Key Classes & Functions
-----------------------

``openviper.tasks.decorators``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: task(queue_name="default", priority=0, max_retries=3, min_backoff=15000, max_backoff=300000, time_limit=None, actor_name=None)

   Decorator that registers a coroutine (or regular function) as a Dramatiq
   actor.

   - ``queue_name`` - the queue to route the message to.  Workers can be
     restricted to specific queues with ``--queues``.
   - ``priority`` - higher priority messages are processed first.
   - ``max_retries`` - automatic retry count on failure (0 to disable).
   - ``min_backoff`` / ``max_backoff`` - retry back-off bounds in ms.
     Default: 15 000 ms / 300 000 ms.
   - ``time_limit`` - hard execution timeout in ms, or ``None`` for unlimited.
   - ``actor_name`` - explicit actor name.  Defaults to ``fn.__name__``.
     Override when two apps define functions with the same name.

   Decorated functions gain three enqueue methods:

   - ``.send(*args, **kwargs)`` - fire-and-forget.
   - ``.delay(*args, **kwargs)`` - alias for ``.send()``.
   - ``.send_with_options(args=(), kwargs={}, delay=0)`` - enqueue with a
     delay in **milliseconds**.

``openviper.tasks.scheduler``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: periodic(every=None, cron=None, *, run_on_start=False, name=None, args=(), kwargs=None)

   Decorator that registers a task for periodic execution.

   Provide **exactly one** of:

   - ``every`` - interval in seconds (``int`` or ``float``).
   - ``cron`` - five-field cron expression string (e.g. ``"0 8 * * 1-5"``).

   Optional arguments:

   - ``run_on_start`` - enqueue once immediately when the worker starts.
   - ``name`` - override the scheduler entry name.
   - ``args`` / ``kwargs`` - fixed arguments passed to the actor on every run.

   If the decorated function is **not** already a Dramatiq actor, ``@periodic``
   automatically applies ``@task()`` so that the simple form just works.
   Stack ``@task()`` explicitly only when you need custom queue / retry /
   time_limit options.

``openviper.tasks.core``
~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: Scheduler(registry=None)

   Periodic task scheduler.

   .. py:method:: add(name, actor, schedule, *, args=(), kwargs=None, enabled=True, replace=False) -> ScheduleEntry

      Register an actor for periodic execution.

   .. py:method:: tick(now=None) -> list[str]

      Evaluate the schedule and enqueue any due tasks.  Returns a
      sorted list of enqueued entry names.

   .. py:method:: run_now(actor, /, *args, **kwargs) -> None

      Enqueue *actor* immediately, outside any schedule.  Raises
      ``TypeError`` if *actor* is not a Dramatiq actor.

   .. py:method:: remove(name) -> None

      Unregister the entry named *name*.  No-op if not found.

   .. py:method:: get_registry() -> ScheduleRegistry

      Return the underlying registry.

   .. py:method:: all_entries() -> list[ScheduleEntry]

      Return all registered entries.

``openviper.tasks.schedule``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: IntervalSchedule(seconds)

   Fire the task every *seconds* seconds.  Raises ``ValueError`` when
   ``seconds <= 0``.

   .. py:method:: is_due(last_run_at, now=None) -> bool

      Return ``True`` when at least *seconds* have elapsed since
      *last_run_at*.

.. py:class:: CronSchedule(expr, *, use_seconds=False)

   Fire the task according to a standard 5-field cron expression
   (``"minute hour day month weekday"``).

   Uses ``croniter`` when installed for full cron semantics (including
   ``@hourly`` shorthand).  Falls back to a built-in evaluator for simple
   patterns when ``croniter`` is not available.

   .. py:method:: is_due(last_run_at, now=None) -> bool

      Return ``True`` if the cron expression matches the current minute.

``openviper.tasks.broker``
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: get_broker() -> dramatiq.Broker

   Return (or lazily create) the configured Dramatiq broker singleton.

.. py:function:: setup_broker() -> dramatiq.Broker

   Alias for :func:`get_broker`.  Called automatically by the worker
   runner.  Kept for backwards compatibility.

.. py:function:: reset_broker() -> None

   Close and forget the current broker.  Primarily for tests.

.. py:function:: create_broker() -> dramatiq.Broker

   Build and return a new broker from ``settings.TASKS``.  Attaches
   :class:`~dramatiq.middleware.asyncio.AsyncIO`,
   :class:`~openviper.tasks.middleware.TaskTrackingMiddleware`, and
   :class:`~openviper.tasks.middleware.SchedulerMiddleware` as
   configured.

.. py:function:: read_task_settings() -> dict

   Return the ``TASKS`` dict from project settings.

.. py:data:: BACKEND_REGISTRY
   :no-index:

   Module-level ``dict[str, object]`` mapping lowercase dialect
   strings to singleton broker instances.  Used by :func:`get_broker`.

**Supported backends** (set ``TASKS["broker"]``):

- ``"redis"`` - ``dramatiq.brokers.redis.RedisBroker`` (default).
- ``"rabbitmq"`` - ``dramatiq.brokers.rabbitmq.RabbitmqBroker``.
- ``"stub"`` - ``dramatiq.brokers.stub.StubBroker`` (testing only).

Optional broker backends (Redis, RabbitMQ, Stub, Results) are imported
lazily via ``importlib.import_module`` so the framework does not crash
when an optional driver is not installed.

``openviper.tasks.results``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

When ``TASKS["tracking"]`` is ``True`` (the default), task execution is tracked in
the ``openviper_task_results`` table.  The table is created automatically
on first use (``CREATE TABLE IF NOT EXISTS``) so no migration is required.

.. py:function:: get_task_result(message_id) -> Awaitable[dict | None]

   Fetch the result record for a given message UUID.

   Result dict keys: ``message_id``, ``actor_name``, ``queue_name``,
   ``status`` (``pending | running | success | failure | skipped | dead``),
   ``args``, ``kwargs``, ``result``, ``error``, ``traceback``, ``retries``,
   ``enqueued_at``, ``started_at``, ``completed_at``.

.. py:function:: list_task_results(status=None, actor_name=None, queue_name=None, limit=50, offset=0) -> Awaitable[list[dict]]

   List recent task result records, optionally filtered by status,
   actor name, or queue.

.. py:function:: get_task_result_sync(message_id) -> dict | None

   Synchronous version for use in management commands or middleware.

.. py:function:: list_task_results_sync(status=None, actor_name=None, queue_name=None, limit=50, offset=0) -> list[dict]

   Synchronous version of :func:`list_task_results`.

.. py:function:: delete_task_result(message_id) -> bool

   Delete a single result record.  Returns ``True`` if a row was deleted.

.. py:function:: clean_old_results(days=7) -> int

   Delete results older than *days* days.  Also removes orphaned rows
   where ``completed_at`` is ``NULL`` and ``enqueued_at`` is older than
   the cutoff.  Returns the number of rows deleted.

.. py:function:: get_task_stats() -> Awaitable[dict[str, int]]

   Return counts grouped by status:
   ``{"total": N, "success": N, "failure": N, "pending": N, "running": N}``.

.. py:function:: upsert_result(message_id, **fields) -> None

   Create or update a task result row.  Only the supplied *fields* are
   written; omitted columns keep their existing value.  Uses native
   UPSERT on PostgreSQL, SQLite, and MySQL.

.. py:function:: batch_upsert_results(events) -> None

   Write multiple ``(message_id, fields)`` pairs in a single transaction.
   Used internally by :class:`~openviper.tasks.middleware.EventBuffer`.

.. py:function:: setup_cleanup_task() -> None

   Register a periodic cleanup task (daily at 03:00 UTC) when
   ``TASKS["cleanup_enabled"]`` is set.  Cleans results older than
   ``TASKS["cleanup_days"]`` (default: 7 days).

.. py:function:: reset_engine() -> None

   Dispose and forget the results engine.  Primarily for tests.

.. py:function:: shutdown_async_executor(wait=True) -> None

   Shut down the internal ``ThreadPoolExecutor``.  Call in application
   teardown.

.. py:function:: to_sync_url(url) -> str

   Convert an async-driver database URL (e.g. ``postgresql+asyncpg://``)
   to its synchronous equivalent for the results engine.

Example Usage
-------------

.. seealso::

   Working projects that use background tasks:

   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ - ``@periodic`` tasks for content moderation
   - `examples/tp/ <https://github.com/mymi14s/openviper/tree/master/examples/tp>`_ - ``TASKS`` config with broker switching, event-driven task wiring
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ - ``TASKS`` config with Redis broker

Defining & Enqueuing a Task
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # myapp/tasks.py
    from openviper.tasks import task

    @task(queue_name="emails", max_retries=5)
    async def send_welcome_email(user_id: int) -> None:
        user = await User.objects.get(id=user_id)
        # send email to user.email ...

    # In a view - fire and forget:
    send_welcome_email.send(user.id)

    # Alias .delay():
    send_welcome_email.delay(user.id)

    # With a 5-second delay:
    send_welcome_email.send_with_options(args=(user.id,), delay=5_000)

    # Explicit actor name to avoid name collisions:
    @task(actor_name="users.send_welcome_email", queue_name="emails")
    async def send_welcome_email(user_id: int) -> None:
        ...

Periodic Tasks
~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.auth.sessions import delete_session
    from openviper.tasks import task, periodic

    # Simple form - @periodic adds @task automatically
    @periodic(every=3600)                  # run every hour
    async def purge_expired_sessions() -> None:
        # delete expired sessions (application-specific logic)
        ...

    @periodic(cron="0 8 * * 1-5")         # weekdays at 08:00 UTC
    async def send_daily_report() -> None:
        ...

    # With fixed arguments
    @periodic(every=60, args=(42,), kwargs={"dry_run": True})
    @task()
    async def poll(user_id: int, *, dry_run: bool = False) -> None:
        ...

    # Run once on worker start, then on schedule
    @periodic(every=300, run_on_start=True)
    async def sync_feeds() -> None:
        ...

    # Custom queue + time limit with explicit @task
    @periodic(every=3600)
    @task(queue_name="maintenance", time_limit=30_000)
    async def cleanup_tmp_files() -> None:
        ...

CronSchedule and IntervalSchedule
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.tasks.schedule import CronSchedule, IntervalSchedule

    every_minute = CronSchedule("* * * * *")
    top_of_hour  = CronSchedule("0 * * * *")
    every_15min  = CronSchedule("*/15 * * * *")
    every_5s     = IntervalSchedule(5)

Starting the Worker
~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Start worker with all queues
    openviper viperctl start-worker .

    # Start worker for a specific queue
    openviper viperctl start-worker . --queues emails

Checking Task Results
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.tasks.results import get_task_result

    async def example():
        # After enqueuing a task:
        msg = send_welcome_email.send(user.id)
        message_id = msg.message_id

        # Later, check the result:
        result = await get_task_result(message_id)
        if result and result["status"] == "success":
            print("Task completed:", result["result"])
        elif result and result["status"] == "failure":
            print("Task failed:", result["error"])

Broker Configuration
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import os, dataclasses
    from openviper.conf import Settings

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        TASKS: dict = dataclasses.field(default_factory=lambda: {
            "broker": "redis",
            "url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            "result_backend_url": os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/1"),
            "log_level": "DEBUG",
            "log_format": "json",    # "text" (default) or "json"
        })

Full TASKS settings reference
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 15 45

   * - Key
     - Default
     - Description
   * - ``broker``
     - ``redis``
     - Broker backend: ``redis``, ``rabbitmq``, or ``stub``.
   * - ``url``
     - —
     - Redis or RabbitMQ connection URL.
   * - ``result_backend_url``
     - —
     - Redis URL for Dramatiq's native result backend.
   * - ``scheduler``
     - ``True``
     - Enable the periodic task scheduler.
   * - ``tracking``
     - ``True``
     - Record task results in the database.
   * - ``tracking_flush_threshold``
     - ``20``
     - Buffer size before flushing events.
   * - ``cleanup_enabled``
     - ``0``
     - Enable automatic daily cleanup of old results.
   * - ``cleanup_days``
     - ``7``
     - Delete results older than this many days.
   * - ``results_db_url``
     - —
     - Separate DB URL for task results. Falls back to ``DATABASE_URL``.
   * - ``log_level``
     - ``INFO``
     - Worker log level.
   * - ``log_format``
     - ``text``
     - ``"text"`` or ``"json"``.
   * - ``log_to_file``
     - ``False``
     - Write logs to ``logs/worker.log``.
   * - ``log_dir``
     - ``logs/``
     - Directory for log files.
   * - ``redis_max_connections``
     - ``50``
     - Redis connection pool size.
   * - ``redis_socket_timeout``
     - —
     - Redis socket timeout (seconds).
   * - ``redis_socket_connect_timeout``
     - —
     - Redis connect timeout (seconds).
   * - ``redis_socket_keepalive``
     - —
     - Enable TCP keepalive.

Database broker settings (when using ``DatabaseBroker``):

.. list-table::
   :header-rows: 1
   :widths: 40 15 45

   * - Key
     - Default
     - Description
   * - ``db_poll_min_sleep``
     - ``0.1``
     - Minimum poll sleep (seconds).
   * - ``db_poll_max_sleep``
     - ``2.0``
     - Maximum poll sleep (seconds).
   * - ``db_pool_size``
     - ``20``
     - SQLAlchemy pool size.
   * - ``db_max_overflow``
     - ``30``
     - SQLAlchemy max overflow connections.
   * - ``db_pool_recycle``
     - ``1800``
     - Recycle connections after N seconds.
   * - ``db_pool_timeout``
     - ``30``
     - Pool timeout (seconds).
   * - ``db_query_timeout``
     - ``30``
     - Per-query timeout (seconds).
   * - ``db_sqlite_busy_timeout``
     - ``30``
     - SQLite busy timeout (seconds).

Middleware
----------

``openviper.tasks.middleware``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: TaskTrackingMiddleware

   Dramatiq :class:`~dramatiq.middleware.Middleware` subclass that
   records task lifecycle events (enqueue, start, success, failure,
   skip, dead-letter) to the ``openviper_task_results`` table.

   Events are buffered in an :class:`EventBuffer` and flushed to the
   database in a single transaction when the buffer reaches
   ``tracking_flush_threshold`` entries or when a terminal event is
   received.  This avoids one DB round-trip per lifecycle hook.

.. py:class:: SchedulerMiddleware

   Starts the periodic scheduler when the worker boots and stops it
   on shutdown.  Attached automatically when
   ``TASKS["scheduler"]`` is ``True`` (the default).

.. py:class:: EventBuffer(flush_threshold=20)

   Thread-safe buffer that batches :class:`TrackingEvent` objects.
   Flushing calls :func:`~openviper.tasks.results.batch_upsert_results`
   in a background thread.

.. py:function:: reset_tracking_buffer() -> None

   Clear the event buffer and shut down its executor.  Call in test
   teardown.

Registry
--------

``openviper.tasks.registry``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: ScheduleEntry

   Dataclass holding all state for one scheduled task.

   .. py:attribute:: name

      Unique human-readable identifier.

   .. py:attribute:: actor

      The Dramatiq actor (registered via ``@task``).

   .. py:attribute:: schedule

      A :class:`~openviper.tasks.schedule.Schedule` instance.

   .. py:attribute:: args

      Positional arguments forwarded to ``actor.send()``.

   .. py:attribute:: kwargs

      Keyword arguments forwarded to ``actor.send()``.

   .. py:attribute:: enabled

      When ``False`` the entry is never enqueued.

   .. py:attribute:: last_run_at

      UTC datetime of the most recent enqueue; ``None`` initially.

   .. py:method:: is_due(now=None) -> bool

      Delegate to ``self.schedule.is_due`` if the entry is enabled.

.. py:class:: ScheduleRegistry

   In-process store of :class:`ScheduleEntry` objects.

   .. py:method:: register(name, actor, schedule, *, args=(), kwargs=None, enabled=True, replace=False) -> ScheduleEntry

      Add a new entry.  Raises ``ValueError`` if *name* already exists
      and *replace* is ``False``.

   .. py:method:: unregister(name) -> None

      Remove the entry named *name*.  No-op if not found.

   .. py:method:: get(name) -> ScheduleEntry | None

      Return the entry with *name*, or ``None``.

   .. py:method:: all_entries() -> list[ScheduleEntry]

      Return all registered entries.

   .. py:method:: all_due(now=None) -> list[ScheduleEntry]

      Return entries whose schedule is currently due.

   .. py:method:: clear() -> None

      Remove all entries.  Primarily for tests.

.. py:function:: get_registry() -> ScheduleRegistry

   Return the process-level singleton.

.. py:function:: reset_registry() -> None

   Replace the singleton with a fresh registry.  Primarily for tests.

Worker & Runner
---------------

``openviper.tasks.worker``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: discover_tasks(extra_modules=None) -> list[str]

   Import task modules from every app in ``INSTALLED_APPS`` using
   parallel ``ThreadPoolExecutor`` imports.  Returns sorted list of
   successfully imported module paths.

.. py:function:: create_worker(threads=8, queues=None, extra_modules=None) -> dramatiq.Worker

   Initialize and return a Dramatiq worker instance.  Discovers task
   modules before creating the broker.

.. py:function:: run_worker(processes=1, threads=8, queues=None, extra_modules=None) -> None

   Start the Dramatiq worker and block until ``SIGINT`` / ``SIGTERM``.
   Sets ``OPENVIPER_WORKER=1``, configures logging, discovers tasks,
   and starts the scheduler if enabled.

``openviper.tasks.runner``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: run_scheduler(scheduler=None, tick_interval=1.0) -> None

   Start the scheduler loop and block until ``SIGINT`` / ``SIGTERM``.
   Ticks at *tick_interval* second intervals.

Database Broker
---------------

``openviper.tasks.db_broker``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: DatabaseBroker

   A Dramatiq :class:`~dramatiq.broker.Broker` that stores messages in
   a database table (``openviper_tasks``).  Uses ``FOR UPDATE SKIP
   LOCKED`` on PostgreSQL and MySQL for concurrent worker safety.
   Falls back to plain ``SELECT`` on SQLite.

   .. py:method:: enqueue(message, delay=None) -> Message

      Store the message in the database with an optional ETA.

   .. py:method:: consume(queue_name, prefetch=1, timeout=5000) -> Consumer

      Return a :class:`DatabaseConsumer` that polls for pending
      messages with exponential back-off.

   .. py:method:: get_declared_queues() -> set[str]

      Return declared queue names.

.. py:function:: require_dependency(package) -> None

   Raise ``ImportError`` if *package* is not importable.

ORM Model & Admin
-----------------

``openviper.tasks.models``
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: TaskResult

   ORM model (table: ``openviper_task_results``) tracking the lifecycle
   of every background task message.

   .. py:attribute:: message_id

      Dramatiq UUID (``CharField(64)``, unique).

   .. py:attribute:: actor_name

      Fully-qualified actor name (``CharField(255)``).

   .. py:attribute:: queue_name

      Queue the message was sent to (``CharField(100)``).

   .. py:attribute:: status

      ``pending | running | success | failure | skipped | dead``
      (``CharField(20)``).

   .. py:attribute:: retries

      Number of retries consumed (``IntegerField``).

   .. py:attribute:: args / kwargs

      JSON-encoded positional / keyword arguments (``TextField``).

   .. py:attribute:: result

      JSON-encoded return value on success (``TextField``).

   .. py:attribute:: error / traceback

      Exception string and full traceback on failure (``TextField``).

   .. py:attribute:: enqueued_at / started_at / completed_at

      UTC timestamps (``DateTimeField``).

   .. py:property:: duration_ms -> float | None

      Wall-clock execution time in milliseconds, or ``None`` if unknown.

``openviper.tasks.admin``
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: TaskResultAdmin

   :class:`~openviper.admin.ModelAdmin` for :class:`TaskResult`.
   Registered automatically when ``openviper.tasks`` is in
   ``INSTALLED_APPS``.  Displays message ID, actor, queue, status,
   retries, and timestamps.  Supports search by message ID, actor, and
   queue; filter by status and timestamps.

Logging
-------

``openviper.tasks.log``
~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: configure_worker_logging(log_dir=None, log_level="INFO", log_format="text", log_to_file=False) -> Path

   Configure file and console handlers for the task worker loggers.
   Idempotent - subsequent calls are no-ops.  Returns the resolved
   log directory path.

.. py:function:: configure_worker_logging_from_settings() -> Path

   Read project settings and call :func:`configure_worker_logging`.

.. py:function:: configure_email_logging(log_dir=None, log_format="text") -> None

   Attach a rotating ``WARNING+`` file handler to the
   ``openviper.email`` logger.  Idempotent.

Log files (when ``log_to_file`` is enabled):

- ``logs/worker.log`` - all messages at the configured level (10 MB, 5 backups)
- ``logs/worker.error.log`` - ``WARNING`` and above only (5 MB, 3 backups)
- ``logs/email.error.log`` - email ``WARNING`` and above (10 MB, 5 backups)

Schedule Helpers
----------------

``openviper.tasks.schedule``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: croniter_available() -> bool

   Return whether the optional ``croniter`` dependency is installed.

.. py:function:: expand_cron_field(token, lo, hi) -> set[int]

   Expand a single cron field token into a set of integers.  Supports
   ``*``, ``*/step``, ``value``, ``start-end``, ``start-end/step``,
   and comma-separated combinations.

Scheduler Lifecycle
-------------------

``openviper.tasks.scheduler``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: start_scheduler() -> None

   Register all pending ``@periodic`` entries and start the tick thread.
   Called by :func:`~openviper.tasks.worker.run_worker` after the
   Dramatiq worker has started.

.. py:function:: stop_scheduler() -> None

   Stop the tick thread.  Called on worker shutdown.

Type Protocols
--------------

``openviper.tasks.types``
~~~~~~~~~~~~~~~~~~~~~~~~~

Structural types used across the task subsystem:

- :class:`ActorProtocol` - Dramatiq actor operations (``send``,
  ``actor_name``).
- :class:`DelayActorProtocol` - Actor with ``.delay()`` alias.
- :class:`BrokerProtocol` - Broker operations (``add_middleware``,
  ``get_declared_queues``, ``close``).
- :class:`SettingsProtocol` - Settings values consumed by the task
  subsystem.
- :class:`TaskMessageProtocol` - Dramatiq message fields.
- :class:`WorkerProtocol` - Worker lifecycle (``start``, ``stop``).
- :class:`SchedulerEventProtocol` - Thread event operations.

Type aliases:

- ``TaskValue`` - ``object`` (any task argument value).
- ``TaskFields`` - ``dict[str, TaskValue]``.
- ``TaskResultRow`` - ``dict[str, TaskValue]``.
- ``TaskDecorator`` - Decorator returning an ``ActorProtocol``.

API Reference
-------------

.. automodule:: openviper.tasks
   :members:

.. automodule:: openviper.tasks.decorators
   :members:

.. automodule:: openviper.tasks.core
   :members:

.. automodule:: openviper.tasks.schedule
   :members:

.. automodule:: openviper.tasks.broker
   :members:

.. automodule:: openviper.tasks.results
   :members:

.. automodule:: openviper.tasks.middleware
   :members:

.. automodule:: openviper.tasks.registry
   :members:

.. automodule:: openviper.tasks.worker
   :members:

.. automodule:: openviper.tasks.runner
   :members:

.. automodule:: openviper.tasks.db_broker
   :members:

.. automodule:: openviper.tasks.models
   :members:

.. automodule:: openviper.tasks.admin
   :members:

.. automodule:: openviper.tasks.log
   :members:

.. automodule:: openviper.tasks.scheduler
   :members:

.. automodule:: openviper.tasks.types
   :members:
