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
worker process started with ``openviper viperctl runworker .``.

Periodic tasks are defined with the ``@periodic`` decorator, which registers
them with the built-in :class:`~openviper.tasks.core.Scheduler`.  The
scheduler ticks inside the worker process — no separate "beat" process is
required.

Key Classes & Functions
-----------------------

``openviper.tasks.decorators``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: task(queue_name="default", priority=0, max_retries=3, min_backoff=15000, max_backoff=300000, time_limit=None, actor_name=None)

   Decorator that registers a coroutine (or regular function) as a Dramatiq
   actor.

   - ``queue_name`` — the queue to route the message to.  Workers can be
     restricted to specific queues with ``--queues``.
   - ``priority`` — higher priority messages are processed first.
   - ``max_retries`` — automatic retry count on failure (0 to disable).
   - ``min_backoff`` / ``max_backoff`` — retry back-off bounds in ms.
     Default: 15 000 ms / 300 000 ms.
   - ``time_limit`` — hard execution timeout in ms, or ``None`` for unlimited.
   - ``actor_name`` — explicit actor name.  Defaults to ``fn.__name__``.
     Override when two apps define functions with the same name.

   Decorated functions gain three enqueue methods:

   - ``.send(*args, **kwargs)`` — fire-and-forget.
   - ``.delay(*args, **kwargs)`` — alias for ``.send()``.
   - ``.send_with_options(args=(), kwargs={}, delay=0)`` — enqueue with a
     delay in **milliseconds**.

``openviper.tasks.scheduler``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: periodic(every=None, cron=None, *, run_on_start=False, name=None, args=(), kwargs=None)

   Decorator that registers a task for periodic execution.

   Provide **exactly one** of:

   - ``every`` — interval in seconds (``int`` or ``float``).
   - ``cron`` — five-field cron expression string (e.g. ``"0 8 * * 1-5"``).

   Optional arguments:

   - ``run_on_start`` — enqueue once immediately when the worker starts.
   - ``name`` — override the scheduler entry name.
   - ``args`` / ``kwargs`` — fixed arguments passed to the actor on every run.

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

   .. py:method:: tick() -> list[str]

      Evaluate the schedule and enqueue any due tasks.  Returns the names
      of enqueued tasks.  Call this at most once per minute for cron tasks.

   .. py:method:: run_now(actor, *args, **kwargs) -> None

      Enqueue *actor* immediately, outside any schedule.

``openviper.tasks.schedule``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: IntervalSchedule(seconds)

   Fire the task every *seconds* seconds.  Raises ``ValueError`` when
   ``seconds <= 0``.

.. py:class:: CronSchedule(expression)

   Fire the task according to a standard 5-field cron expression
   (``"minute hour day month weekday"``).

   Uses ``croniter`` when installed for full cron semantics (including
   ``@hourly`` shorthand).  Falls back to a built-in evaluator for simple
   patterns when ``croniter`` is not available.

``openviper.tasks.broker``
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: get_broker() -> dramatiq.Broker

   Return (or lazily create) the configured Dramatiq broker singleton.

.. py:function:: setup_broker() -> dramatiq.Broker

   Initialize the broker from ``settings.TASKS``.  Called automatically by
   the worker runner.

**Supported backends** (set ``TASKS["broker"]``):

- ``"redis"`` — ``dramatiq.brokers.redis.RedisBroker`` (default).
- ``"rabbitmq"`` — ``dramatiq.brokers.rabbitmq.RabbitmqBroker``.
- ``"stub"`` — ``dramatiq.brokers.stub.StubBroker`` (testing only).

``openviper.tasks.results``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

When ``TASKS["tracking_enabled"]`` is ``1``, task execution is tracked in
the ``openviper_task_results`` table.

.. py:function:: get_task_result(message_id) -> Awaitable[dict | None]

   Fetch the result record for a given message UUID.

   Result dict keys: ``message_id``, ``actor_name``, ``queue_name``,
   ``status`` (``pending | running | success | failure | skipped | dead``),
   ``args``, ``kwargs``, ``result``, ``error``, ``traceback``, ``retries``,
   ``enqueued_at``, ``started_at``, ``completed_at``.

.. py:function:: list_task_results(status=None, actor_name=None, limit=50) -> Awaitable[list[dict]]

   List recent task result records, optionally filtered by status or actor.

.. py:function:: get_task_result_sync(message_id) -> dict | None

   Synchronous version for use in management commands or middleware.

Example Usage
-------------

Defining & Enqueuing a Task
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # myapp/tasks.py
    from openviper.tasks import task

    @task(queue_name="emails", max_retries=5)
    async def send_welcome_email(user_id: int) -> None:
        user = await User.objects.get(id=user_id)
        # send email to user.email ...

    # In a view — fire and forget:
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

    from openviper.tasks import task, periodic

    # Simple form — @periodic adds @task automatically
    @periodic(every=3600)                  # run every hour
    async def purge_expired_sessions() -> None:
        from openviper.auth.sessions import purge_expired
        await purge_expired()

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
    openviper viperctl runworker .

    # Start worker for a specific queue
    openviper viperctl runworker . --queues emails

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
            "enabled": 1,            # required — worker will not start without this
            "broker": "redis",
            "broker_url": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            "backend_url": os.environ.get("REDIS_BACKEND_URL", "redis://localhost:6379/1"),
            "scheduler_enabled": 1,  # enable the periodic task scheduler
            "tracking_enabled": 1,   # record task results in openviper_task_results
            "log_level": "DEBUG",
            "log_format": "json",    # "text" (default) or "json"
        })
