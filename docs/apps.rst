.. _apps:

App Lifecycle
=============

The ``openviper.apps`` package provides hook discovery and execution for
application lifecycle events.  Apps declare optional ``ready()``, ``startup()``,
and ``shutdown()`` hooks in a ``lifecycle.py`` module; the framework discovers
and runs them automatically based on ``INSTALLED_APPS`` ordering.

Overview
--------

Each installed app may contain a ``lifecycle.py`` module that defines zero or
more of the following hooks:

- **ready()** - synchronous, called once during bootstrapping before the
  event loop starts.  Use for one-time setup such as registering signals or
  warming caches.
- **startup()** - async, called when the ASGI server starts accepting
  requests.  Use for opening connections, starting background listeners, or
  any async initialisation that must complete before traffic arrives.
- **shutdown()** - async, called in reverse order on graceful shutdown.
  Use for closing connections, flushing buffers, or releasing resources.

If an app does not define ``lifecycle.py``, it is silently skipped.

Hook Discovery
---------------

:class:`~openviper.apps.lifecycle.AppLifecycleManager` iterates over
``INSTALLED_APPS`` and attempts to import ``<app_name>.lifecycle`` for each
entry.  Discovered hooks are validated at import time:

- ``ready`` must be a **plain synchronous function** (not a coroutine, not a
  class method).
- ``startup`` and ``shutdown`` must be **async coroutine functions**.

Invalid hooks raise :class:`~openviper.apps.exceptions.AppLifecycleConfigError`.

Execution Order
---------------

Hooks execute in ``INSTALLED_APPS`` order, with one critical exception:
``shutdown()`` runs in **reverse** order so that dependencies are torn down
after their dependants.

If a ``startup()`` hook fails, the framework immediately runs ``shutdown()``
for all apps that already started successfully (in reverse order), then raises
:class:`~openviper.apps.exceptions.AppStartupError` with any
``shutdown_errors`` collected during cleanup.

Key Classes
-----------

``openviper.apps.lifecycle``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: AppLifecycle(app_name, ready=None, startup=None, shutdown=None)

   Data container for a single app's lifecycle hooks.

   :param app_name: dotted app module path.
   :param ready: synchronous ``ready()`` callable, or ``None``.
   :param startup: async ``startup()`` callable, or ``None``.
   :param shutdown: async ``shutdown()`` callable, or ``None``.

.. py:class:: AppLifecycleManager

   Discovers, validates, and executes lifecycle hooks across all installed
   apps.

   .. py:method:: discover(app_names) -> list[AppLifecycle]

      Import ``<app_name>.lifecycle`` for each name in *app_names*, validate
      hooks, and return the resulting :class:`AppLifecycle` list.

   .. py:method:: run_ready() -> None

      Call every discovered ``ready()`` hook synchronously.  Raises
      :class:`AppReadyError` on the first failure.

   .. py:method:: async run_startup() -> None

      Await every discovered ``startup()`` hook.  On failure, runs
      ``shutdown()`` for already-started apps and raises
      :class:`AppStartupError`.

   .. py:method:: async run_shutdown() -> None

      Await every ``shutdown()`` hook in reverse startup order.  Raises
      :class:`AppShutdownError` if any hook fails.

``openviper.apps.exceptions``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:exception:: AppLifecycleError

   Base exception for all app lifecycle errors.

.. py:exception:: AppLifecycleConfigError(AppLifecycleError)

   Raised when a ``lifecycle.py`` module defines an invalid hook (wrong
   callable type, async/sync mismatch).

.. py:exception:: AppLifecycleImportError(AppLifecycleError)

   Raised when ``lifecycle.py`` exists but cannot be imported.

.. py:exception:: AppReadyError(AppLifecycleError)

   Raised when a ``ready()`` hook raises an exception.  Carries
   ``app_name`` and ``original_exception`` attributes.

.. py:exception:: AppStartupError(AppLifecycleError)

   Raised when a ``startup()`` hook raises an exception.  Carries
   ``app_name``, ``original_exception``, and ``shutdown_errors`` (a list of
   :class:`AppShutdownError` from cleanup).

.. py:exception:: AppShutdownError(AppLifecycleError)

   Raised when one or more ``shutdown()`` hooks fail.  Carries ``errors``,
   a list of ``(app_name, exception)`` pairs.

Example
-------

A typical ``lifecycle.py`` inside an app package:

.. code-block:: python

   # myapp/lifecycle.py

   async def startup():
       await db_pool.connect()

   async def shutdown():
       await db_pool.disconnect()

The app is registered in settings:

.. code-block:: python

   # settings.py
   INSTALLED_APPS = [
       "myapp",
   ]
