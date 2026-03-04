.. _scheduler:

==================
Periodic Scheduler
==================

The :class:`~openviper.tasks.core.Scheduler` runs periodic tasks on cron or
interval schedules.  It is backed by the same Dramatiq workers used for ad-hoc
background tasks, so no separate scheduler daemon is required.

.. contents:: On this page
   :local:
   :depth: 2

----

How It Works
-------------

1. You register a Dramatiq actor (a ``@task``-decorated function) with the
   scheduler using a :class:`~openviper.tasks.schedule.CronSchedule` or
   :class:`~openviper.tasks.schedule.IntervalSchedule`.
2. The scheduler loop calls :meth:`~openviper.tasks.core.Scheduler.tick` at
   a fixed interval.  On each tick, any task whose schedule is *due* is
   enqueued into the broker.
3. Worker processes pick up and execute the messages.

----

Schedule Types
---------------

CronSchedule
~~~~~~~~~~~~

Standard cron expression with five fields (minute, hour, day-of-month,
month, day-of-week):

.. code-block:: python

   from openviper.tasks.schedule import CronSchedule

   # Every day at 08:00
   CronSchedule("0 8 * * *")

   # Every Monday at 09:30
   CronSchedule("30 9 * * 1")

   # First day of every month at midnight
   CronSchedule("0 0 1 * *")

IntervalSchedule
~~~~~~~~~~~~~~~~

Fixed time interval between executions:

.. code-block:: python

   from openviper.tasks.schedule import IntervalSchedule

   IntervalSchedule(seconds=30)
   IntervalSchedule(minutes=5)
   IntervalSchedule(hours=1)
   IntervalSchedule(days=1)

----

Registering Periodic Jobs
--------------------------

.. code-block:: python

   # myproject/scheduler.py
   from openviper.tasks.core import Scheduler
   from openviper.tasks.schedule import CronSchedule, IntervalSchedule
   from blog.tasks import (
       auto_publish_due_posts,
       send_daily_digest,
       cleanup_old_drafts,
   )

   scheduler = Scheduler()

   # Publish scheduled posts every 5 minutes
   scheduler.add(
       name     = "auto-publish",
       actor    = auto_publish_due_posts,
       schedule = IntervalSchedule(minutes=5),
   )

   # Daily digest every day at 07:00
   scheduler.add(
       name     = "daily-digest",
       actor    = send_daily_digest,
       schedule = CronSchedule("0 7 * * *"),
       kwargs   = {"format": "html"},
   )

   # Clean up drafts older than 30 days — runs on the 1st of each month
   scheduler.add(
       name     = "cleanup-drafts",
       actor    = cleanup_old_drafts,
       schedule = CronSchedule("0 2 1 * *"),
       enabled  = True,
   )

``scheduler.add`` parameters:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Parameter
     - Description
   * - ``name``
     - Unique identifier for the scheduled job
   * - ``actor``
     - The ``@task``-decorated function (Dramatiq actor)
   * - ``schedule``
     - ``CronSchedule`` or ``IntervalSchedule`` instance
   * - ``args``
     - Positional arguments forwarded to the actor (default ``()``)
   * - ``kwargs``
     - Keyword arguments forwarded to the actor (default ``{}``)
   * - ``enabled``
     - If ``False``, the job is registered but never enqueued (default ``True``)
   * - ``replace``
     - If ``True``, overwrite an existing job with the same name (default ``False``)

----

@periodic — Shorthand Decorator
----------------------------------

``@periodic`` is the quickest way to schedule a function.  It wraps your
function with ``@task()`` automatically (unless you stack your own) and
registers it with the scheduler — no ``Scheduler`` import required.

.. code-block:: python

   from openviper.tasks import periodic

   # Run every 5 minutes
   @periodic(every=300)
   async def sync_feeds():
       ...

   # Run at 08:00 on weekdays
   @periodic(cron="0 8 * * 1-5")
   async def morning_report():
       ...

   # Run immediately when the worker starts, then every hour
   @periodic(every=3600, run_on_start=True)
   async def hourly_cleanup():
       ...

``@periodic`` parameters:

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Parameter
     - Description
   * - ``every``
     - Interval in **seconds** between runs (mutually exclusive with ``cron``)
   * - ``cron``
     - Five-field cron expression, e.g. ``"0 8 * * 1-5"`` (mutually exclusive with ``every``)
   * - ``run_on_start``
     - If ``True``, enqueue the task once immediately when the worker starts (default ``False``)
   * - ``name``
     - Registry name for this entry; defaults to the function name
   * - ``args``
     - Positional arguments forwarded to ``actor.send()``
   * - ``kwargs``
     - Keyword arguments forwarded to ``actor.send()``

Stack ``@task()`` explicitly only when you need a custom queue, retry
policy, or time limit:

.. code-block:: python

   from openviper.tasks import task, periodic

   @periodic(every=3600, run_on_start=True)
   @task(queue_name="maintenance", time_limit=30_000)
   async def purge_tmp_files():
       ...

.. note::

   ``@periodic`` is equivalent to registering via ``scheduler.add()``;
   both approaches share the same scheduler registry at runtime.

----

Removing a Job
---------------

.. code-block:: python

   scheduler.remove("auto-publish")

----

Running the Scheduler
----------------------

The scheduler tick loop must run in a long-lived process.  The simplest way
is to run it inside a worker:

.. code-block:: bash

   # The scheduler runs automatically when you start the worker
   python viperctl.py runworker --queues scheduler

Alternatively, run a dedicated scheduler process:

.. code-block:: python

   # run_scheduler.py
   import asyncio
   from myproject.scheduler import scheduler

   async def main():
       while True:
           scheduler.tick()
           await asyncio.sleep(60)   # check every 60 seconds

   asyncio.run(main())

.. code-block:: bash

   python run_scheduler.py

----

One-Shot Execution
-------------------

Enqueue an actor immediately without waiting for its next scheduled slot:

.. code-block:: python

   from myproject.scheduler import scheduler
   from blog.tasks import send_daily_digest

   # Run now, fire-and-forget
   scheduler.run_now(send_daily_digest, format="html")

----

Listing Registered Jobs
------------------------

.. code-block:: python

   from myproject.scheduler import scheduler

   for entry in scheduler.all_entries():
       print(entry.name, entry.schedule, "enabled:", entry.enabled)

----

ScheduleRegistry
-----------------

Behind the scenes, ``Scheduler`` delegates to
:class:`~openviper.tasks.registry.ScheduleRegistry`, which holds the ordered
list of :class:`~openviper.tasks.scheduler.ScheduleEntry` objects.  Direct
access is rarely needed:

.. code-block:: python

   registry = scheduler.get_registry()
   entry    = registry.get("auto-publish")
   print(entry.last_run, entry.next_run)

.. seealso::

   :ref:`tasks` — ad-hoc background tasks, retry policies, and model event hooks.
