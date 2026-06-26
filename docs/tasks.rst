.. _tasks:

===================
Background Tasks
===================

OpenViper includes a built-in background task queue and periodic scheduler
powered by `Dramatiq <https://dramatiq.io/>`_.  Developer modules never
import Dramatiq directly - the public API surface is :func:`openviper.tasks.actor`
and :func:`openviper.tasks.periodic`.

.. contents:: Contents
   :local:
   :backlinks: none

Installation
============

Install the ``tasks`` extra to pull in Dramatiq and its core dependencies,
then choose a broker-specific extra for your message broker:

.. code-block:: bash

   # Redis broker (default)
   pip install 'openviper[tasks-redis]'

   # RabbitMQ broker
   pip install 'openviper[tasks-rabbitmq]'

   # Amazon SQS broker
   pip install 'openviper[tasks-sqs]'

The ``tasks`` extra installs ``dramatiq``, ``croniter``, and
``cron-descriptor``.  The broker extras add the corresponding driver
(``redis``, ``pika``, or ``dramatiq-sqs``/``boto3``).
For testing, use ``"stub"`` as the broker - no extra packages are needed.

Configuration
=============

Add ``openviper.tasks`` to :data:`INSTALLED_APPS` and configure the
:data:`TASKS` dictionary in your settings module:

.. code-block:: python

   INSTALLED_APPS = [
       "openviper.auth",
       "openviper.admin",
       "openviper.tasks",
       # ... your apps
   ]

   TASKS = {
       "enabled": 1,
       "broker": "redis",
       "broker_url": "redis://localhost:6379",
       "backend_url": "",  # optional: for result retrieval
       "logging": {
           "level": "INFO",
           "file": {
               "log_dir": "logs",
               "file_name": "tasks.log",
               "log_format": "json",
               "max_size": 10,  # MB
           },
           "database": {
               "task": 1,
               "periodic": 1,
           },
       },
   }

Logging is opt-in by default.  When ``logging.file`` and
``logging.database`` are both ``None`` (the default), the worker
outputs only essential startup/shutdown messages.  Set ``file`` to a
dict or ``1`` to enable file logging; set ``database`` to a dict or
``1`` to persist task/periodic execution records.

Configuration reference
-----------------------

=========================  ============  ========================================
Key                        Type          Description
=========================  ============  ========================================
enabled                    int           ``1`` to enable, ``0`` to disable
broker                     str           ``"redis"`` (default), ``"rabbitmq"``, ``"sqs"``, or ``"stub"``
broker_url                 str           Required when enabled (not required for SQS or stub)
backend_url                str           Optional: results backend URL
sqs_namespace              str           SQS namespace (default ``"openviper"``)
sqs_endpoint_url           str           Optional: custom SQS endpoint (e.g. ElasticMQ)
pg_min_connections         int           PostgreSQL pool min connections (default ``2``)
pg_max_connections         int           PostgreSQL pool max connections (default ``10``)
logging.level              str           Log level (default ``"INFO"``)
logging.file               int/dict/None  ``1`` to enable, ``None`` to disable,
                                         or a dict with keys below
logging.file.log_dir       str           Log directory path (default ``"logs"``)
logging.file.file_name     str           Log file name (default ``"tasks.log"``)
logging.file.log_format    str           ``"json"`` or ``"text"`` (default ``"json"``)
logging.file.max_size      float         Max log file size in MB (default ``10``)
logging.database           int/dict/None  ``1`` to enable, ``None`` to disable,
                                          or a dict with keys below
logging.database.task      int           ``1`` to log task results (default ``0``)
logging.database.periodic  int           ``1`` to log periodic results (default ``0``)
=========================  ============  ========================================

Defining Tasks
==============

Use the :func:`@actor <openviper.tasks.actor>` decorator in your app's
``tasks.py`` module:

.. code-block:: python

   # myapp/tasks.py
   from openviper.tasks import actor

   @actor
   async def send_welcome_email(user_id: int) -> None:
       """Send a welcome email to a new user."""
       ...

   @actor(queue_name="emails", actor_name="core.send_email")
   async def send_email(to: str, subject: str) -> None:
       ...

Enqueue a task from anywhere:

.. code-block:: python

   from myapp.tasks import send_welcome_email

   send_welcome_email.send(user_id=42)
   send_welcome_email.send_with_options(args=(42,), delay=5_000)

When ``TASKS['enabled'] == 0``, ``.send()`` falls back to synchronous
execution in the caller's scope.

Periodic Tasks
==============

Use :func:`@periodic <openviper.tasks.periodic>` to register recurring
jobs:

.. code-block:: python

   # myapp/tasks.py
   from openviper.tasks import periodic

   @periodic(every="60s")
   async def health_check() -> None:
       """Run every 60 seconds."""
       ...

   @periodic(cron="0 8 * * *")
   async def morning_report() -> None:
       """Run daily at 8 AM."""
       ...

Supported interval units: ``s`` (seconds), ``m`` (minutes), ``h`` (hours),
``d`` (days).

Periodic tasks are automatically deduplicated across workers: only one
worker will enqueue a given job per interval cycle, even when multiple
workers share a database.

Periodic parameters
-------------------

=================  =======  =================================================
Parameter          Type     Description
=================  =======  =================================================
cron               str      Standard 5-field crontab expression
every              str      Human-readable interval (``"5m"``, ``"1h"``)
startup            bool     Run once immediately when the worker starts
retries            int      Maximum retry attempts on failure (default 3)
=================  =======  =================================================

Running the Worker
==================

Start the unified worker process (scheduler + task consumer):

.. code-block:: bash

   python viperctl.py start-worker

Options:

- ``--processes N`` - Number of worker processes (default: 1)
- ``--threads N`` - Threads per process (default: 8)
- ``--queues queue1 queue2`` - Specific queues to consume
- ``--no-scheduler`` - Disable the periodic scheduler thread

.. note::

   Only one worker should run the scheduler to avoid duplicate periodic
   task enqueues.  When running multiple workers, start one with the
   scheduler enabled (the default) and all others with ``--no-scheduler``:

   .. code-block:: bash

      # Primary worker (scheduler + consumer)
      python viperctl.py start-worker

      # Additional workers (consumer only)
      python viperctl.py start-worker --no-scheduler

Task Discovery
===============

On startup, the worker scans each app in :data:`INSTALLED_APPS` for a
``tasks.py`` module and imports it.  Apps without a ``tasks.py`` are
silently skipped.

Testing
=======

OpenViper provides :class:`TaskQueue` and :class:`EagerTaskRunner` for
testing without a live worker:

.. code-block:: python

   from openviper.testing.tasks import TaskQueue, EagerTaskRunner, assert_task_queued

   def test_task_is_enqueued():
       queue = TaskQueue()
       with queue.patch():
           my_task.send(1, 2)
       assert_task_queued(queue, "my_task")

   async def test_task_executes_eagerly():
       result = await EagerTaskRunner().run(my_task, 1, 2)
       assert result == expected

Fixtures
--------

- ``task_queue`` - :class:`TaskQueue` fixture that intercepts ``.send()`` calls
- ``task_runner`` - :class:`EagerTaskRunner` fixture for immediate execution

Persistence Models
==================

Task results and periodic execution records are tracked in the database:

- :class:`TaskResult` - Tracks task state (pending, running, success, failure, dead)
- :class:`ScheduledJob` - Synchronises in-memory schedules with the database

Admin Integration
=================

The ``RunNowAction`` admin action allows administrators to enqueue a
task directly from the admin panel.
