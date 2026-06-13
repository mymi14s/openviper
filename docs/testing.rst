.. _testing:

Testing
=======

OpenViper TestKit is the pytest-based testing layer for OpenViper
projects.  It lives in ``openviper.testing`` and is exposed as the
``pytest-openviper`` plugin entry point.

The TestKit is designed to feel like normal pytest: application startup,
HTTP clients, database setup, settings overrides, and common framework test
doubles are provided through fixtures and small helper functions.

Overview
--------

OpenViper applications are async-first, so tests usually need an async HTTP
client, predictable application lifespan handling, and isolated state for
database and framework side effects.  TestKit provides:

* pytest fixtures for apps, clients, databases, users, auth, and service
  doubles.
* An async HTTP client that calls the ASGI app without a live server.
* Test database configuration with safety checks and reset helpers.
* Model factories for building and creating test data.
* Authentication helpers for bearer tokens, forced authentication, roles,
  and permissions.
* Assertion helpers for HTTP responses, JSON payloads, validation errors,
  model state, OpenAPI schemas, events, tasks, mail, cache, and snapshots.
* Multi-database test configuration and alias tracking.
* Standalone helper functions that can be used outside the fixture mechanism.

For request and response behavior, see :doc:`http`.  For model and database
behavior, see :doc:`db`.

Installation and Setup
----------------------

Install the testing extra to pull in pytest and related dependencies:

.. code-block:: bash

   pip install openviper[testing]

This installs ``pytest``, ``pytest-asyncio``, and ``httpx`` alongside OpenViper.
The testing utilities are also available without the extra if these packages
are already installed, but the extra ensures compatible versions are present.

When OpenViper is installed with its pytest entry point, pytest can discover
the plugin automatically.  Projects may also enable it explicitly in
``tests/conftest.py``:

.. code-block:: python

   pytest_plugins = ["openviper.testing.plugin"]

The plugin registers OpenViper markers and makes the fixtures from
``openviper.testing.fixtures`` available to tests.

Configuration
-------------

Configure TestKit in ``pyproject.toml`` under ``[tool.openviper.testing]``:

.. code-block:: toml

   [tool.openviper.testing]
   app = "myproject.main:app"
   settings = "myproject.settings.testing"
   database_url = "sqlite+aiosqlite:///:memory:"
   database_isolation = "transaction"
   migrate = true

``app`` is required unless ``OPENVIPER_TEST_APP`` is set.  It may point to an
``OpenViper`` instance or a zero-argument app factory.

Available options:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Option
     - Description
   * - ``app``
     - Import path to the OpenViper app instance or factory.
   * - ``settings``
     - Optional settings module loaded through ``OPENVIPER_SETTINGS_MODULE``.
   * - ``database_url``
     - Test database URL.  Defaults to in-memory SQLite.
   * - ``database_isolation``
     - One of ``transaction``, ``truncate``, ``recreate``, or ``in_memory``.
   * - ``migrate``
     - When true, creates registered tables before each database fixture.
   * - ``use_test_settings``
     - When true, loads the configured test settings module.
   * - ``disable_real_email``
     - When true, patches email delivery to prevent real sends.
   * - ``disable_real_tasks``
     - When true, patches task enqueuing to prevent real broker calls.
   * - ``disable_real_cache``
     - When false (default), the real cache backend is used unless the
       ``cache`` fixture replaces it.

The ``OPENVIPER_TEST_APP`` environment variable overrides the ``app`` option.

``OpenViperTestConfig`` is the resolved configuration dataclass.  It is
available as the ``openviper_test_config`` session-scoped fixture.
``OpenViperTestingConfigError`` is raised for invalid configuration.

Core Fixtures
-------------

``app``
   Imports the configured OpenViper application, enables debug mode, rebuilds
   middleware, and runs startup and shutdown handlers around the test.

``client``
   Provides an ``httpx.AsyncClient`` bound to the app through ASGI transport.
   It supports regular HTTP methods, JSON payloads, query params, headers,
   cookies, and redirects.

``db``
   Configures the test database, creates registered tables when ``migrate`` is
   enabled, and resets state after the test.

``transactional_db``
   Uses the recreate reset path for tests that need committed data or behavior
   spanning multiple database connections.

``migrated_db`` and ``isolated_db``
   Explicit variants that force migrations and database recreation.

``setup_test_database``
   Session-scoped fixture that migrates once and keeps the engine alive for
   the entire test session.  Yields a ``SessionDatabase`` handle.

``override_settings``
   Temporarily replaces OpenViper's frozen settings object.  Overrides are
   restored at test cleanup even if the test fails.

.. code-block:: python

   async def test_feature_flag(client, override_settings):
       override_settings(DEBUG=False)

       response = await client.get("/")

       assert response.status_code in {200, 404}

Testing Routes
--------------

Use ``client`` for route tests.  No live server is started.

.. code-block:: python

   async def test_homepage(client):
       response = await client.get("/")

       assert response.status_code == 200

JSON requests work through the usual ``httpx`` interface:

.. code-block:: python

   async def test_create_user(client):
       response = await client.post(
           "/users",
           json={
               "email": "user@example.com",
               "name": "Test User",
           },
       )

       assert response.status_code == 201

Testing the Database
--------------------

The database fixtures configure OpenViper's async engine with the configured
test database URL.  TestKit rejects empty URLs and production-looking database
names such as ``prod``, ``production``, ``main``, and ``live``.

.. code-block:: python

   async def test_create_user(db):
       user = await User.objects.create(email="user@example.com")

       found = await User.objects.get_or_none(id=user.id)

       assert found is not None

Isolation strategies:

``transaction``
   Fast default strategy.  In the current implementation it resets registered
   metadata after the test because OpenViper ORM operations may use their own
   connections.

``truncate``
   Deletes rows from registered tables without dropping metadata.

``recreate``
   Drops and recreates registered tables.  This is slower but useful for
   integration tests.

``in_memory``
   Forces ``sqlite+aiosqlite:///:memory:`` for small, local test suites.

Use ``migrate_database()`` and ``truncate_database()`` from
``openviper.testing.database`` when a test needs to control those operations
manually.

``resolve_test_database_url()`` resolves a database URL from config values,
applying the ``in_memory`` override and defaulting to SQLite when no URL is
provided.

``assert_safe_database_url()`` rejects empty or production-looking database
URLs and warns on SQLite file databases whose name does not contain ``test``.

Multi-Database Testing
^^^^^^^^^^^^^^^^^^^^^^^

``openviper.testing.database`` provides helpers for projects that use
multiple database aliases:

* ``MultiDatabaseConfig`` is a frozen dataclass holding a ``databases`` dict
  keyed by alias.  ``primary()`` returns the default config and
  ``replicas()`` returns all replica configs.
* ``build_multi_database_config(primary_url, replica_urls)`` builds a
  ``MultiDatabaseConfig`` from a primary URL and optional replica URLs.
* ``setup_test_databases(config)`` configures and initializes all aliases.
* ``teardown_test_databases()`` disconnects all backends and resets routing.
* ``DatabaseAliasTracker`` records which alias was used for read/write
  operations.  Call ``record_read(alias, model)`` and
  ``record_write(alias, model)``, then assert with
  ``assert_db_used(alias, for_read=True, for_write=True)``.

Model Factories
---------------

Factories build unsaved model instances or create saved records.

.. code-block:: python

   from openviper.testing.factories import LazyAttribute, ModelFactory, Sequence


   class UserFactory(ModelFactory[User]):
       class Meta:
           model = User

       email = Sequence(lambda index: f"user{index}@example.com")
       name = LazyAttribute(lambda values: values["email"].split("@")[0])


   async def test_user_factory(db):
       user = await UserFactory.create()

       assert user.email.startswith("user")

Available factory helpers:

* ``build(**overrides)`` returns an unsaved instance.
* ``create(**overrides)`` saves the instance with ``ignore_permissions=True``.
* ``build_batch(size, **overrides)`` and ``create_batch(size, **overrides)``
  create multiple instances.
* ``Sequence`` generates incrementing values via ``itertools.count``.
* ``LazyAttribute`` derives values from attributes already evaluated.
* ``RelatedFactory`` builds a related object from another factory.
* ``PostGeneration`` runs a callback after ``create``.

Pre-built factories:

* ``UserFactory`` builds the active user model (supports custom user models).
  Pass ``password="raw"`` to ``create()`` to set a hashed password.
* ``SuperuserFactory`` extends ``UserFactory`` with ``is_staff`` and
  ``is_superuser`` set to ``True``.
* ``PermissionFactory`` builds ``Permission`` records.
* ``RoleFactory`` builds ``Role`` records.

Authentication Helpers
----------------------

The plugin provides simple user-like fixtures and authenticated clients:

``user``
   A ``TestUser`` object with ``id``, ``pk``, ``email``, ``permissions``, and
   ``roles``.

``admin_user``
   A staff/superuser variant with an ``admin`` role and ``admin.access``
   permission.

``user_factory``
   A callable that creates ``TestUser`` instances with auto-incrementing IDs
   and emails.

``auth_client`` and ``admin_client``
   Clients with a bearer token attached for ``user`` or ``admin_user``.  These
   use stub users without database records.

``db_user`` and ``db_admin_user``
   Create real ``User`` and superuser records in the test database via
   ``UserFactory`` and ``SuperuserFactory``.

``authenticated_client`` and ``admin_authenticated_client``
   Clients with bearer tokens backed by real database user records.  Use
   these when route handlers perform a database lookup from the JWT ``sub``
   claim.

Helper functions:

* ``token_for_user(user)`` creates a JWT access token.
* ``force_authenticate(client, user)`` attaches a bearer token to a client.
* ``attach_bearer_token(client, token)`` attaches an explicit token.
* ``attach_session_cookie(client, value)`` attaches a session cookie.
* ``login_user(client, path, **credentials)`` posts credentials to a login
  route.
* ``with_permissions(user, permissions)`` and ``with_roles(user, roles)`` set
  test-only permission metadata in-place.

.. code-block:: python

   from openviper.testing.auth import force_authenticate


   async def test_dashboard_allows_user(client, user):
       force_authenticate(client, user)

       response = await client.get("/dashboard")

       assert response.status_code == 200

Settings Overrides
------------------

``override_openviper_settings(**overrides)`` is a context manager that
temporarily replaces OpenViper's frozen settings object.  It validates field
names against the ``Settings`` dataclass and raises
``OpenViperTestingConfigError`` for unknown fields.

``override_settings(**overrides)`` is a decorator form that works on sync
functions, async functions, and test classes (wrapping every method whose name
begins with ``test``).

.. code-block:: python

   from openviper.testing.settings import override_settings


   @override_settings(DEBUG=False, ALLOWED_HOSTS=("testserver",))
   async def test_secure_mode(client):
       response = await client.get("/")

       assert response.status_code != 500

Assertion Helpers
-----------------

HTTP and JSON helpers live in ``openviper.testing.assertions``:

* ``assert_status(response, expected)``
* ``assert_header(response, name, expected=None)``
* ``assert_cookie(response, name)``
* ``assert_redirects(response, expected_location=None)``
* ``assert_response_json(response, expected)``
* ``assert_json_contains(response, expected)``
* ``assert_json_path(payload, path, expected)``

Validation and model helpers:

* ``assert_validation_error(response, field)``
* ``assert_field_error(response, field)``
* ``assert_error_code(response, code)``
* ``assert_model_exists(Model, **filters)``
* ``assert_model_count(Model, expected, **filters)``
* ``assert_queryset_count(queryset, expected)``
* ``assert_field_value(instance, field, expected)``

.. code-block:: python

   from openviper.testing.assertions import assert_status, assert_validation_error


   async def test_create_user_requires_email(client):
       response = await client.post("/users", json={})

       assert_status(response, 422)
       assert_validation_error(response, "email")

Testing Mail, Events, Tasks, Cache, and Storage
-----------------------------------------------

TestKit includes lightweight service doubles for common side effects:

``mailoutbox``
   A list that captures ``TestEmail`` records.  Patches ``send_now`` and
   suppresses background delivery.

``event_recorder``
   Records named events and payloads.  Use ``assert_event_emitted()``,
   ``assert_event_count()``, and ``assert_event_payload()``.

``task_queue`` and ``task_runner``
   Capture queued tasks with ``TaskQueue`` or run sync/async callables
   immediately with ``EagerTaskRunner``.

``cache`` and ``clear_cache``
   Provide an isolated async in-memory cache.  ``clear_cache`` is a callable
   that clears the cache.

``tmp_storage`` and ``uploaded_file``
   Provide a temporary storage root and in-memory
   :class:`~openviper.http.uploads.UploadFile` objects.

``snapshot``
   Provides optional filesystem-backed snapshot assertions.

Each fixture has a corresponding standalone helper that can be used outside
the pytest fixture mechanism:

* ``create_mailoutbox()`` returns ``(outbox, patches)``.
* ``create_event_recorder()`` returns ``(recorder, patches)``.
* ``create_task_queue()`` returns ``(queue, patches)``.
* ``setup_test_cache()`` returns ``(instance, restore)``.

.. code-block:: python

   from openviper.testing.mail import InMemoryMailBackend, assert_email_count


   async def test_welcome_email(mailoutbox):
       backend = InMemoryMailBackend(mailoutbox)

       await backend.send("Welcome", ["user@example.com"])

       assert_email_count(mailoutbox, 1)

Testing OpenAPI and Admin
-------------------------

``openapi_schema`` returns the app's generated OpenAPI document.  The
``openviper.testing.openapi`` module provides:

* ``assert_openapi_path(schema, path)``
* ``assert_openapi_operation(schema, path, method)``
* ``assert_request_schema(schema, path, method)``
* ``assert_response_schema(schema, path, method, status_code)``

.. code-block:: python

   from openviper.testing.openapi import assert_openapi_path


   def test_openapi_has_users_endpoint(openapi_schema):
       assert_openapi_path(openapi_schema, "/users")

Use ``admin_client`` for admin route tests that need an authenticated
admin-like client.

CLI Testing
-----------

``cli_runner`` returns a Click ``CliRunner`` for isolated command tests.
The helper ``assert_exit_code(result, expected=0)`` checks command results
with a useful failure message.

.. code-block:: python

   from openviper.testing.cli import assert_exit_code


   def test_command(cli_runner):
       result = cli_runner.invoke(["--help"])

       assert_exit_code(result, 0)

Pytest Markers
--------------

The plugin registers these markers:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Marker
     - Purpose
   * - ``openviper``
     - Tests using OpenViper testing features.
   * - ``db``
     - Tests requiring database access.
   * - ``transactional_db``
     - Tests requiring committed data or real transaction behavior.
   * - ``integration``
     - Broader integration tests.
   * - ``slow``
     - Slow tests.
   * - ``admin``
     - Admin UI or admin API tests.
   * - ``openapi``
     - OpenAPI schema tests.
   * - ``auth``
     - Authentication or authorization tests.

Public API Reference
--------------------

The ``openviper.testing`` package exports the following symbols:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Symbol
     - Module
   * - ``DatabaseIsolation``
     - ``openviper.testing.settings``
   * - ``InMemoryCache``
     - ``openviper.cache.memory``
   * - ``LazyAttribute``, ``ModelFactory``, ``PostGeneration``, ``RelatedFactory``, ``Sequence``
     - ``openviper.testing.factories``
   * - ``OpenViperTestClient``
     - ``openviper.testing.client``
   * - ``OpenViperTestConfig``
     - ``openviper.testing.settings``
   * - ``PermissionFactory``, ``RoleFactory``, ``SuperuserFactory``, ``UserFactory``
     - ``openviper.testing.factories``
   * - ``SessionDatabase``, ``TestDatabase``
     - ``openviper.testing.database``
   * - ``Snapshot``
     - ``openviper.testing.snapshot``
   * - ``create_event_recorder``, ``create_mailoutbox``, ``create_task_queue``, ``setup_test_cache``
     - ``openviper.testing.fixtures``
   * - ``migrate_database``, ``truncate_database``
     - ``openviper.testing.database``
   * - ``override_openviper_settings``, ``override_settings``
     - ``openviper.testing.settings``
   * - ``assert_*`` helpers
     - ``openviper.testing.assertions``, ``openviper.testing.openapi``, ``openviper.testing.mail``, ``openviper.testing.events``, ``openviper.testing.tasks``, ``openviper.testing.cache``, ``openviper.testing.storage``, ``openviper.testing.snapshot``

Additional public symbols not re-exported from the package root:

* ``MultiDatabaseConfig``, ``DatabaseAliasTracker``, ``build_multi_database_config``, ``setup_test_databases``, ``teardown_test_databases``, ``resolve_test_database_url``, ``assert_safe_database_url`` (``openviper.testing.database``)
* ``OpenViperTestingConfigError``, ``load_testing_config``, ``load_app``, ``import_from_path`` (``openviper.testing.settings``)
* ``TestUser`` (``openviper.testing.fixtures``)
* ``TestEmail``, ``InMemoryMailBackend`` (``openviper.testing.mail``)
* ``EventRecorder``, ``RecordedEvent`` (``openviper.testing.events``)
* ``TaskQueue``, ``QueuedTask``, ``EagerTaskRunner`` (``openviper.testing.tasks``)
* ``TestCache`` (``openviper.testing.cache``)

Project Scaffold
----------------

Generate a minimal test setup with:

.. code-block:: bash

   openviper test init

The command creates:

* ``tests/conftest.py`` with ``pytest_plugins = ["openviper.testing.plugin"]``.
* ``tests/test_health.py`` with a basic async health check.
* ``[tool.openviper.testing]`` in ``pyproject.toml`` when missing.

Existing files are skipped unless ``--force`` is passed.

Running Tests
-------------

The ``openviper test`` command runs the project test suite through pytest:

.. code-block:: bash

   openviper test

Supported flags:

``-v`` / ``--verbose``
   Increase output verbosity. Pass twice for maximum detail.

``-x`` / ``--failfast``
   Stop on the first test failure.

``--create-db``
   Force creation of the test database even if it already exists. Sets the
   ``OPENVIPER_TEST_CREATE_DB=1`` environment variable so that the database
   fixtures run migrations regardless of the current state.

``--reuse-db`` / ``--keepdb``
   Reuse the existing test database instead of dropping and recreating it
   between test runs. Sets ``OPENVIPER_TEST_REUSE_DB=1`` so that the database
   fixtures skip teardown and re-migration. ``--keepdb`` is an alias for
   ``--reuse-db``.

These flags are passed through to the test runner as environment variables
that the database fixtures in ``openviper.testing.database`` read at setup time.

Best Practices
--------------

* Use a dedicated test settings module and test database URL.
* Prefer in-memory SQLite for small library tests and explicit test database
  URLs for integration suites.
* Keep route tests focused on request/response behavior.
* Use factories for model setup instead of copying object creation into every
  test.
* Use ``override_settings`` for feature flags and per-test configuration.
* Use ``authenticated_client`` for routes that load the user from the
  database; use ``auth_client`` when only the token signature is verified.
* Assert framework side effects through ``mailoutbox``, ``event_recorder``,
  ``task_queue``, ``cache``, and ``tmp_storage`` rather than real external
  services.
* Use the standalone helpers (``create_mailoutbox``, ``create_event_recorder``,
  ``create_task_queue``, ``setup_test_cache``) when writing unit tests outside
  the pytest fixture mechanism.
* Do not use production database, mail, task, cache, or storage backends in
  tests.

Limitations
-----------

This release provides the core TestKit surface and lightweight helpers.  The
following areas are intentionally limited:

* True nested transaction rollback is not guaranteed for all ORM operations,
  because OpenViper database calls may acquire independent connections.
  TestKit therefore resets metadata or truncates rows for deterministic
  cleanup.
* The built-in ``user`` and ``admin_user`` fixtures are ``TestUser`` objects,
  not real ORM records.  Use ``db_user`` and ``db_admin_user`` when the route
  handler loads the user from the database.
* Mail, task, cache, event, and storage doubles do not automatically replace
  every possible project-specific backend.  Wire them into custom services
  through fixtures when needed.
* Snapshot testing is optional and intentionally small.
* Advanced pytest-xdist database provisioning is planned but not implemented
  as a stable public API.
