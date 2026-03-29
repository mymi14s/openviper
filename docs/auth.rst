.. _auth:

Authentication & Authorization
===============================

The ``openviper.auth`` package provides JWT-based and session-based authentication,
password hashing, view-level access control decorators, a pluggable backend pipeline,
and a full permission/role system backed by the ORM.

Overview
--------

Authentication in OpenViper is *async-first* and built around three pillars:

1. **Tokens** — short-lived access JWTs and longer-lived refresh JWTs issued via
   :mod:`openviper.auth.jwt`; or long-lived opaque bearer tokens via
   :class:`~openviper.auth.authentications.TokenAuthentication`.
2. **Sessions** — server-side sessions, identified by a cryptographically random cookie.
3. **Backends** — a configurable pipeline (``AUTH_BACKENDS`` setting) that tries
   each backend in order and attaches the resolved user to the request scope.

The built-in ``User``, ``Role``, and ``Permission`` ORM models live in
:mod:`openviper.auth.models`.

Key Classes & Functions
-----------------------

``openviper.auth.jwt``
~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: create_access_token(user_id, extra_claims=None) -> str

   Issue a signed JWT access token for *user_id*.  Expiry is controlled by
   ``settings.JWT_ACCESS_TOKEN_EXPIRE`` (default: 24 hours).  The token
   includes ``sub``, ``jti`` (unique ID), ``iat``, ``exp``, and ``type="access"``
   claims.  Pass *extra_claims* to embed custom data.

.. py:function:: create_refresh_token(user_id) -> str

   Issue a signed JWT refresh token.  Expiry defaults to 7 days
   (``settings.JWT_REFRESH_TOKEN_EXPIRE``).  Token type is ``"refresh"``.

.. py:function:: decode_access_token(token) -> dict

   Verify and decode an access token.  Raises
   :class:`~openviper.exceptions.TokenExpired` or
   :class:`~openviper.exceptions.AuthenticationFailed` on failure.

.. py:function:: decode_refresh_token(token) -> dict

   Verify and decode a refresh token.  Raises
   :class:`~openviper.exceptions.TokenExpired` or
   :class:`~openviper.exceptions.AuthenticationFailed` on failure.

.. py:function:: decode_token_unverified(token) -> dict

   Return claims without verifying signature or expiry.  Used only on the
   logout path to extract ``jti`` / ``exp`` for blocklisting.

**Supported algorithms** (configured via ``JWT_ALGORITHM``):
``HS256``, ``HS384``, ``HS512``, ``RS256``, ``RS384``, ``RS512``,
``ES256``, ``ES384``, ``ES512``, ``PS256``, ``PS384``, ``PS512``.

``openviper.auth.hashers``
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:function:: make_password(raw_password, algorithm="argon2") -> Awaitable[str]

   Hash a plaintext password.  CPU-intensive work runs in a thread pool.

   - ``"argon2"`` (default) — Argon2id with ``time_cost=2``,
     ``memory_cost=65536``, ``parallelism=2``.
   - ``"bcrypt"`` — bcrypt with ``rounds=12``.
   - ``"plain"`` — plaintext (testing only; disabled in production).

.. py:function:: check_password(raw_password, hashed_password) -> Awaitable[bool]

   Verify a plaintext password against a stored hash.  Constant-time
   comparison prevents timing attacks.

.. py:function:: is_password_usable(hashed_password) -> bool

   Return ``True`` if the hash is usable (not a ``"!"``-prefixed sentinel).

.. py:function:: make_unusable_password() -> str

   Return a sentinel string that will never match any real password.

``openviper.auth.sessions``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

High-level session management is provided by
:class:`~openviper.auth.session.manager.SessionManager`.

.. py:class:: openviper.auth.session.manager.SessionManager(store=None)

   .. py:method:: login(request, user) -> Awaitable[str]

      Create (or rotate) a session for the authenticated *user*.  Returns
      the new session key.  Caller must set ``Set-Cookie`` on the response.
      Old sessions are rotated on login to prevent session fixation.

   .. py:method:: logout(request) -> Awaitable[None]

      Delete the current session and reset ``request.user`` to
      :class:`~openviper.auth.models.AnonymousUser`.

The underlying :class:`~openviper.auth.session.store.DatabaseSessionStore`
stores sessions in the ``openviper_sessions`` table.

``openviper.auth.decorators``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All decorators work on both ``async def`` and regular ``def`` view functions.
The ``Request`` object is located automatically from positional or keyword
arguments.

.. py:function:: login_required(func)

   Raise :class:`~openviper.exceptions.Unauthorized` (401) when
   ``request.user.is_authenticated`` is ``False``.

.. py:function:: permission_required(codename)

   Raise :class:`~openviper.exceptions.Unauthorized` (401) when not
   authenticated, or :class:`~openviper.exceptions.PermissionDenied` (403)
   when ``request.user.has_perm(codename)`` returns ``False``.

.. py:function:: role_required(role_name)

   Raise :class:`~openviper.exceptions.PermissionDenied` (403) when
   ``request.user.has_role(role_name)`` returns ``False``.

.. py:function:: superuser_required(func)

   Raise :class:`~openviper.exceptions.PermissionDenied` (403) when
   ``request.user.is_superuser`` is ``False``.

.. py:function:: staff_required(func)

   Raise :class:`~openviper.exceptions.PermissionDenied` (403) when
   ``request.user.is_staff`` is ``False``.

``openviper.auth.models``
~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: AbstractUser

   Abstract base for custom user models.  Fields:

   - ``username`` — ``CharField(max_length=150, unique=True)``
   - ``email`` — ``EmailField(unique=True)``
   - ``password`` — ``CharField(max_length=255)`` (always hashed)
   - ``first_name``, ``last_name`` — ``CharField(max_length=150, null=True)``
   - ``is_active`` — ``BooleanField(default=True)``
   - ``is_superuser`` — ``BooleanField(default=False)``
   - ``is_staff`` — ``BooleanField(default=False)``
   - ``role_profile`` — optional FK to ``RoleProfile``
   - ``created_at``, ``updated_at``, ``last_login`` — datetimes

   **Properties:**

   - ``is_authenticated`` — always ``True`` for a real user.
   - ``is_anonymous`` — always ``False`` for a real user.
   - ``full_name`` — ``f"{first_name} {last_name}".strip()``.
   - ``pk`` — alias for ``id``.

   **Methods:**

   .. py:method:: set_password(raw_password) -> Awaitable[None]

      Hash and store a password (Argon2id by default).

   .. py:method:: check_password(raw_password) -> Awaitable[bool]

      Verify a password against the stored hash.

   .. py:method:: get_roles() -> Awaitable[list[Role]]

      Return all roles assigned to this user.  Respects ``role_profile``
      if set.

   .. py:method:: get_permissions() -> Awaitable[set[str]]

      Return all permission codenames available to this user (via roles).
      Superusers receive all permissions.  Cached per-request.

   .. py:method:: has_perm(codename) -> Awaitable[bool]

      Check whether the user holds a specific permission codename.

   .. py:method:: has_model_perm(model_label, action) -> Awaitable[bool]

      Check whether the user can perform *action* (``"create"``, ``"read"``,
      ``"update"``, ``"delete"``) on the given model (``"app.ModelName"``).

   .. py:method:: has_role(role_name) -> Awaitable[bool]

      Return ``True`` if the user is assigned a role with the given name.

   .. py:method:: assign_role(role) -> Awaitable[None]

      Assign a :class:`Role` to this user (creates a ``UserRole`` record).

   .. py:method:: remove_role(role) -> Awaitable[None]

      Remove a :class:`Role` from this user.

.. py:class:: User

   Concrete user model (``table_name = "auth_users"``).  Use as-is or swap
   via ``USER_MODEL`` setting.

.. py:class:: AnonymousUser

   Sentinel object for unauthenticated visitors.  Has ``is_authenticated=False``,
   ``is_superuser=False``, ``pk=None``.  All permission checks return ``False``.

.. py:class:: Permission

   Named permission: ``codename`` (unique), ``name``, ``content_type`` (optional).

.. py:class:: Role

   Named role: ``name`` (unique), ``description``.  Links to
   :class:`Permission` via the ``RolePermission`` junction table.

.. py:class:: RoleProfile

   Optional profile grouping multiple roles.  When a user's
   ``role_profile`` is set, ``get_roles()`` uses ``RoleProfileDetail``
   instead of ``UserRole``.

``openviper.auth.authentications`` (token storage)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: TokenAuthentication

   Authentication scheme that reads an ``Authorization: Token <token>`` header.
   Derives from :class:`~openviper.auth.authentications.BaseAuthentication` and
   can be used globally (via ``DEFAULT_AUTHENTICATION_CLASSES``) or per-view
   (via ``authentication_classes`` on a :class:`~openviper.http.views.View`
   subclass).

   Token values are **never stored in plain text**; only their SHA-256 digest is
   persisted in the ``auth_tokens`` table.  The raw token is returned once by
   :func:`create_token` and cannot be recovered afterwards.

   An in-process TTL cache (10-minute window, 4 096-entry capacity) prevents a
   DB round-trip on every request.

   Returns ``(user, {"type": "token", "token": raw})`` on success, or ``None``
   when the header is absent / invalid.

.. py:function:: create_token(user_id, expires_at=None) -> Awaitable[tuple[str, dict]]

   Generate a new opaque auth token for *user_id* and persist its hash.

   Returns a ``(raw_token, record)`` 2-tuple.  *raw_token* is a 40-character
   hex string — save it immediately, as it cannot be retrieved later.
   *record* is a plain ``dict`` with ``id``, ``key_hash``, ``user_id``,
   ``created_at``, ``expires_at``, and ``is_active``.

   *expires_at* is an optional timezone-aware (UTC) :class:`~datetime.datetime`.
   Pass ``None`` for a token that never expires.

.. py:function:: revoke_token(raw) -> Awaitable[None]

   Revoke the token with the given raw value.  Sets ``is_active = False`` in
   the database and immediately evicts the entry from the in-process cache.

.. py:function:: clear_token_auth_cache() -> None

   Clear the in-process token cache.  Intended for tests and clean shutdown.

``openviper.auth.middleware``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: AuthenticationMiddleware(app, manager=None)

   ASGI middleware that runs the auth backend pipeline on every HTTP
   request, attaching the resolved user to ``request.user`` and auth info to
   ``request.auth``.

Auth Backends
~~~~~~~~~~~~~

The pipeline tries each backend in ``AUTH_BACKENDS`` order.

- ``JWTBackend`` — looks for ``Authorization: Bearer <token>`` header.
- ``SessionBackend`` — reads ``sessionid`` cookie and looks up the session.

Custom backends must implement ``async authenticate(scope) -> (user, auth_info) | None``.

Token Blocklist
~~~~~~~~~~~~~~~

JWT tokens can be revoked by adding their ``jti`` to the blocklist table
(``openviper_token_blocklist``).  The blocklist is checked automatically by
``JWTBackend`` on every request.

.. code-block:: python

    from openviper.auth.token_blocklist import revoke_token

    async def logout(request):
        # Revoke a token (e.g. on logout)
        claims = decode_token_unverified(token)
        if claims.get("jti"):
            await revoke_token(claims["jti"], claims.get("exp"))

Opaque Token Auth
~~~~~~~~~~~~~~~~~

Opaque tokens are stored in the ``auth_tokens`` table (created by the
initial auth migration).  Each row holds:

- ``key_hash`` — SHA-256 digest of the raw token.
- ``user_id`` — FK to the user table.
- ``created_at``, ``expires_at`` — optional expiry datetime.
- ``is_active`` — set to ``False`` on revocation.

Use :func:`~openviper.auth.authentications.revoke_token` to invalidate a token;
the in-process cache is evicted immediately so revocation takes effect within
the current process instantly.

Example Usage
-------------

.. seealso::

   Working projects that use authentication:

   - `examples/todoapp/ <https://github.com/mymi14s/openviper/tree/master/examples/todoapp>`_ — session-based login/logout with ``authenticate``
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ — JWT auth, RBAC roles, ``role_required`` decorator
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ — JWT auth, custom ``User`` extending ``AbstractUser``
   - `examples/ai_smart_recipe_generator/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_smart_recipe_generator>`_ — session-based cookie auth

Token Authentication (opaque tokens)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Opaque tokens are a good fit for CLI clients, API keys, or long-lived service
credentials where JWT expiry / refresh cycles are unwanted.

**Issuing a token on login:**

.. code-block:: python

    from openviper.routing.router import Router
    from openviper.http.request import Request
    from openviper.http.response import JSONResponse
    from openviper.auth.hashers import check_password
    from openviper.auth.models import User
    from openviper.auth.authentications import create_token, revoke_token

    router = Router()

    @router.post("/auth/token/login")
    async def token_login(request: Request) -> JSONResponse:
        body = await request.json()
        user = await User.objects.get_or_none(username=body["username"])
        if user is None or not await check_password(body["password"], user.password):
            return JSONResponse({"error": "Invalid credentials"}, status_code=401)

        raw_token, _ = await create_token(user.id)
        # raw_token is the value the client must send — store it now,
        # it cannot be retrieved again.
        return JSONResponse({"token": raw_token})

**Revoking a token on logout:**

.. code-block:: python

    from openviper.auth.decorators import login_required
    from openviper.auth.authentications import revoke_token

    @router.post("/auth/token/logout")
    @login_required
    async def token_logout(request: Request) -> JSONResponse:
        raw = request.headers.get("authorization", "")[6:]  # strip "Token "
        if raw:
            await revoke_token(raw)
        return JSONResponse({"status": "logged out"})

**Protecting an endpoint — per-view:**

.. code-block:: python

    from openviper.http.views import View
    from openviper.auth.authentications import TokenAuthentication

    class ProfileView(View):
        authentication_classes = [TokenAuthentication]

        async def get(self, request: Request) -> JSONResponse:
            return JSONResponse({"username": request.user.username})

**Protecting an endpoint — global middleware:**

Add ``TokenAuthentication`` to ``DEFAULT_AUTHENTICATION_CLASSES`` in settings
so that every request is checked:

.. code-block:: python

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        DEFAULT_AUTHENTICATION_CLASSES: tuple = (
            "openviper.auth.authentications.TokenAuthentication",
            "openviper.auth.authentications.JWTAuthentication",
            "openviper.auth.authentications.SessionAuthentication",
        )

The client sends the token in the ``Authorization`` header::

    Authorization: Token 4a7c92fd1e3b8d05f2...

**Creating a token with an expiry:**

.. code-block:: python

    import datetime
    from openviper.utils import timezone
    from openviper.auth.token_auth import create_token

    # Token valid for 30 days
    expires = timezone.now() + datetime.timedelta(days=30)
    raw_token, record = await create_token(user.id, expires_at=expires)

JWT Login & Protected Endpoint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.routing.router import Router
    from openviper.http.request import Request
    from openviper.http.response import JSONResponse
    from openviper.auth.hashers import check_password
    from openviper.auth.jwt import create_access_token, create_refresh_token
    from openviper.auth.decorators import login_required
    from openviper.auth.models import User

    router = Router()

    @router.post("/auth/login")
    async def login(request: Request) -> JSONResponse:
        body = await request.json()
        user = await User.objects.get_or_none(username=body["username"])
        if user is None or not await check_password(body["password"], user.password):
            return JSONResponse({"error": "Invalid credentials"}, status_code=401)

        access = create_access_token(user.id)
        refresh = create_refresh_token(user.id)
        return JSONResponse({"access": access, "refresh": refresh})

    @router.get("/me")
    @login_required
    async def me(request: Request) -> JSONResponse:
        return JSONResponse({"username": request.user.username})

Token Refresh
~~~~~~~~~~~~~

.. code-block:: python

    from openviper.auth.jwt import decode_refresh_token, create_access_token
    from openviper.exceptions import TokenExpired, AuthenticationFailed

    @router.post("/auth/refresh")
    async def refresh_token(request: Request) -> JSONResponse:
        body = await request.json()
        try:
            claims = decode_refresh_token(body["refresh"])
        except (TokenExpired, AuthenticationFailed) as exc:
            return JSONResponse({"error": str(exc)}, status_code=401)
        new_access = create_access_token(claims["sub"])
        return JSONResponse({"access": new_access})

Session Login & Logout
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.auth.session.manager import SessionManager

    session_manager = SessionManager()

    @router.post("/auth/session-login")
    async def session_login(request: Request) -> JSONResponse:
        body = await request.json()
        user = await User.objects.get_or_none(username=body["username"])
        if user is None or not await check_password(body["password"], user.password):
            return JSONResponse({"error": "Invalid credentials"}, status_code=401)

        session_key = await session_manager.login(request, user)
        response = JSONResponse({"status": "ok"})
        response.set_cookie("sessionid", session_key, httponly=True, samesite="lax")
        return response

    @router.post("/auth/session-logout")
    @login_required
    async def session_logout(request: Request) -> JSONResponse:
        await session_manager.logout(request)
        response = JSONResponse({"status": "logged out"})
        response.set_cookie("sessionid", "", max_age=0)
        return response

Middleware Setup
~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper import OpenViper
    from openviper.auth.middleware import AuthenticationMiddleware

    app = OpenViper()
    app = AuthenticationMiddleware(app)

Password Hashing
~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.auth.hashers import make_password, check_password

    async def example():
        hashed = await make_password("s3cr3t")          # Argon2id by default
        ok = await check_password("s3cr3t", hashed)     # True
        ok = await check_password("wrong", hashed)      # False

        hashed_bcrypt = await make_password("s3cr3t", algorithm="bcrypt")

Role & Permission Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.auth.models import User, Role, Permission

    async def example():
        # Create a permission and role
        perm = await Permission.objects.create(codename="post.publish", name="Can publish posts")
        role = await Role.objects.create(name="editor")

        # Assign permission to role
        from openviper.auth.models import RolePermission
        await RolePermission.objects.create(role=role.pk, permission=perm.pk)

        # Assign role to user
        user = await User.objects.get(id=1)
        await user.assign_role(role)

        # Check permission
        if await user.has_perm("post.publish"):
            ...

        # Check role
        if await user.has_role("editor"):
            ...

Decorator Usage
~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.auth.decorators import (
        login_required, permission_required, role_required,
        superuser_required, staff_required,
    )

    @router.get("/dashboard")
    @login_required
    async def dashboard(request: Request) -> JSONResponse:
        return JSONResponse({"user": request.user.username})

    @router.delete("/admin/posts/{id:int}")
    @permission_required("post.delete")
    async def delete_post(request: Request, id: int) -> JSONResponse:
        post = await Post.objects.get(id=id)
        await post.delete()
        return JSONResponse({"deleted": True})

    @router.get("/reports")
    @role_required("manager")
    async def reports(request: Request) -> JSONResponse:
        return JSONResponse({"data": "..."})

    @router.get("/superadmin")
    @superuser_required
    async def superadmin(request: Request) -> JSONResponse:
        return JSONResponse({"status": "superuser only"})

Configuration
-------------

Add the following keys to your settings class as needed:

.. code-block:: python

    import dataclasses, datetime
    from openviper.conf import Settings

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        SECRET_KEY: str = "change-me-in-production"
        JWT_ALGORITHM: str = "HS256"
        JWT_ACCESS_TOKEN_EXPIRE: datetime.timedelta = datetime.timedelta(hours=24)
        JWT_REFRESH_TOKEN_EXPIRE: datetime.timedelta = datetime.timedelta(days=7)
        SESSION_COOKIE_NAME: str = "sessionid"
        SESSION_TIMEOUT: int = 86400  # seconds
        AUTH_BACKENDS: tuple = (
            "openviper.auth.backends.jwt_backend.JWTBackend",
            "openviper.auth.backends.session_backend.SessionBackend",
        )
        # Authentication classes tried per-request (used by AuthenticationMiddleware):
        DEFAULT_AUTHENTICATION_CLASSES: tuple = (
            "openviper.auth.authentications.JWTAuthentication",
            "openviper.auth.authentications.SessionAuthentication",
            # Uncomment to enable opaque token auth globally:
            # "openviper.auth.authentications.TokenAuthentication",
        )
        # Custom user model (optional):
        USER_MODEL: str = "users.models.User"

----

Built-in Authentication Views and Routes
-----------------------------------------

OpenViper ships a set of ready-to-use class-based views for the three main
authentication flows (JWT, opaque token, session) plus a shared ``/me``
endpoint.  Import them individually or use the pre-built route lists to
wire everything up in one call.

Quick start
~~~~~~~~~~~

.. code-block:: python

    from openviper.routing import Router
    from openviper.auth.views.routes import all_auth_routes

This registers seven endpoints:

+----------------------------+--------+-------------------------------------------+
| Path                       | Method | Description                               |
+============================+========+===========================================+
| ``/auth/jwt/login``        | POST   | Return JWT access + refresh tokens        |
+----------------------------+--------+-------------------------------------------+
| ``/auth/jwt/logout``       | POST   | Blocklist the JWT by ``jti``              |
+----------------------------+--------+-------------------------------------------+
| ``/auth/token/login``      | POST   | Return an opaque auth token               |
+----------------------------+--------+-------------------------------------------+
| ``/auth/token/logout``     | POST   | Mark the opaque token inactive            |
+----------------------------+--------+-------------------------------------------+
| ``/auth/session/login``    | POST   | Set a ``sessionid`` cookie                |
+----------------------------+--------+-------------------------------------------+
| ``/auth/session/logout``   | POST   | Delete the session from the store         |
+----------------------------+--------+-------------------------------------------+
| ``/auth/me``               | GET    | Return the authenticated user's profile   |
+----------------------------+--------+-------------------------------------------+

For finer control, import individual route groups:

.. code-block:: python

    from openviper.auth.views.routes import jwt_routes, token_routes, session_routes

    # Register only JWT login / logout:
    for path, handler, methods in jwt_routes:
        router.add(path, handler, methods=methods)

Adding auth routes to the project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In a typical OpenViper project the top-level ``routes.py`` file defines a
``route_paths`` list of ``(prefix, router)`` tuples that the framework
assembles into the application.  Add a pre-built auth router to that list
using ``all_auth_routes`` (or any of the grouped route lists):

.. code-block:: python

    """Top-level routes for my_project."""

    from openviper.admin import get_admin_site
    from openviper.auth.views.routes import all_auth_routes
    from openviper.routing import Router

    from my_project.views import router as root_router
    from job.routes import router as job_router

    # Build a dedicated auth router
    auth_router = Router()
    for path, handler, methods in all_auth_routes:
        auth_router.add(path, handler, methods=methods)

    route_paths = [
        ("", job_router),
        ("/admin", get_admin_site()),
        ("/root", root_router),
        ("/auth", auth_router),   # mounts at /auth/jwt/login, /auth/me, etc.
    ]

If you only need one authentication scheme, swap ``all_auth_routes`` for
the matching group:

.. code-block:: python

    from openviper.auth.views.routes import jwt_routes   # or token_routes / session_routes

    auth_router = Router()
    for path, handler, methods in jwt_routes:
        auth_router.add(path, handler, methods=methods)

    route_paths = [
        ...
        ("/auth", auth_router),
    ]

Granular view imports
~~~~~~~~~~~~~~~~~~~~~

All views are importable directly from ``openviper.auth`` (or from their
individual modules) and can be registered on any router one at a time:

.. code-block:: python

    from openviper.auth import JWTLoginView, LogoutView, MeView
    from openviper.routing import Router

    router = Router(prefix="/auth")

    router.add("/jwt/login",  JWTLoginView.as_view(),  methods=["POST"])
    router.add("/jwt/logout", LogoutView.as_view(),    methods=["POST"])
    router.add("/me",         MeView.as_view(),        methods=["GET"])

Each view can also be imported from its own module if you prefer:

.. code-block:: python

    from openviper.auth.views.jwt_login     import JWTLoginView
    from openviper.auth.views.token_login   import TokenLoginView
    from openviper.auth.views.session_login import SessionLoginView
    from openviper.auth.views.logout        import LogoutView
    from openviper.auth.views.me            import MeView

    from openviper.routing import Router

    router = Router(prefix="/auth")

    # JWT flow
    router.add("/jwt/login",     JWTLoginView.as_view(),     methods=["POST"])
    router.add("/jwt/logout",    LogoutView.as_view(),       methods=["POST"])

    # Opaque-token flow
    router.add("/token/login",   TokenLoginView.as_view(),   methods=["POST"])
    router.add("/token/logout",  LogoutView.as_view(),       methods=["POST"])

    # Session-cookie flow
    router.add("/session/login",  SessionLoginView.as_view(), methods=["POST"])
    router.add("/session/logout", LogoutView.as_view(),       methods=["POST"])

    # Shared profile endpoint (works with all three auth schemes)
    router.add("/me",             MeView.as_view(),           methods=["GET"])

Extending the built-in views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All five views are ordinary Python classes and can be subclassed to add
extra behaviour — custom response fields, additional validation, post-login
hooks, and so on.  Register the subclass exactly like the original.

**Adding extra fields to the JWT login response:**

.. code-block:: python

    from openviper.auth.views.jwt_login import JWTLoginView

    class MyJWTLoginView(JWTLoginView):
        async def post(self, request, **kwargs):
            result = await super().post(request, **kwargs)
            # Augment the dict returned by the parent
            result["token_type"] = "Bearer"
            return result

**Adding extra fields to the token login response:**

.. code-block:: python

    from openviper.auth.views.token_login import TokenLoginView

    class MyTokenLoginView(TokenLoginView):
        async def post(self, request, **kwargs):
            result = await super().post(request, **kwargs)
            result["scheme"] = "Token"
            return result

**Running a post-login hook after session login:**

.. code-block:: python

    from openviper.auth.views.session_login import SessionLoginView

    class AuditedSessionLoginView(SessionLoginView):
        async def post(self, request, **kwargs):
            response = await super().post(request, **kwargs)
            # request.user is now set; fire an audit event
            await record_login_event(user_id=request.user.pk, ip=request.headers.get("x-forwarded-for"))
            return response

**Running a post-logout hook:**

.. code-block:: python

    from openviper.auth.views.logout import LogoutView

    class AuditedLogoutView(LogoutView):
        async def post(self, request, **kwargs):
            result = await super().post(request, **kwargs)
            await record_logout_event(request)
            return result

**Returning extra fields from the me endpoint:**

.. code-block:: python

    from openviper.auth.views.me import MeView

    class ExtendedMeView(MeView):
        async def get(self, request, **kwargs):
            data = await super().get(request, **kwargs)
            # Attach roles to the profile response
            roles = await request.user.get_roles()
            data["roles"] = [r.name for r in roles]
            return data

**Building a fully custom login from scratch using BaseLoginView:**

.. code-block:: python

    from openviper.auth.views.base_login import BaseLoginView
    from openviper.auth.jwt import create_access_token, create_refresh_token
    from openviper.auth.authentications import create_token

    class DualTokenLoginView(BaseLoginView):
        """Return both a JWT and an opaque token in one response."""

        async def post(self, request, **kwargs):
            user = await self.authenticate_user(request)
            access = create_access_token(user_id=user.pk)
            refresh = create_refresh_token(user_id=user.pk)
            opaque, _ = await create_token(user_id=user.pk)
            return {
                "access": access,
                "refresh": refresh,
                "api_token": opaque,
            }

Register any subclass the same way as the original view:

.. code-block:: python

    from openviper.routing import Router

    router = Router()
    router.add("/auth/login",   DualTokenLoginView.as_view(), methods=["POST"])
    router.add("/auth/me",      ExtendedMeView.as_view(),     methods=["GET"])
    router.add("/auth/logout",  AuditedLogoutView.as_view(),  methods=["POST"])

    # In routes.py — add the router to route_paths as usual:
    route_paths = [
        ("/auth", router),
        ...
    ]

``openviper.auth.views.base_login``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: BaseLoginView

   Abstract base for all built-in login views.  Provides the
   :meth:`authenticate_user` helper that handles credential extraction,
   validation, and the underlying ``authenticate()`` call.

   Subclass this to build a custom login view:

   .. code-block:: python

       from openviper.auth.views.base_login import BaseLoginView
       from openviper.auth.jwt import create_access_token

       class MyLoginView(BaseLoginView):
           async def post(self, request, **kwargs):
               user = await self.authenticate_user(request)
               token = create_access_token(user_id=user.pk)
               return {"access": token, "custom_field": "value"}

   .. py:method:: authenticate_user(request) -> User

      Validate ``{"username": ..., "password": ...}`` from the request body.

      Raises :class:`~openviper.exceptions.Unauthorized` if the body is
      malformed, if either field is empty, credentials are invalid, or the
      account is inactive.

``openviper.auth.views.jwt_login``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: JWTLoginView

   ``POST`` handler that validates credentials and returns a JWT
   access/refresh pair.

   **Request body** (JSON)::

       {"username": "alice", "password": "s3cr3t"}

   **Response** (200)::

       {"access": "<jwt-access-token>", "refresh": "<jwt-refresh-token>"}

   **Errors**:

   - ``401 Unauthorized`` — missing fields or invalid credentials.

``openviper.auth.views.token_login``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: TokenLoginView

   ``POST`` handler that validates credentials and returns an opaque auth
   token.

   **Request body** (JSON)::

       {"username": "alice", "password": "s3cr3t"}

   **Response** (200)::

       {"token": "<opaque-token>"}

   The token should be sent in subsequent requests as
   ``Authorization: Token <token>``.

   **Errors**:

   - ``401 Unauthorized`` — missing fields or invalid credentials.

``openviper.auth.views.session_login``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: SessionLoginView

   ``POST`` handler that validates credentials and sets a ``Set-Cookie``
   session header.

   **Request body** (JSON)::

       {"username": "alice", "password": "s3cr3t"}

   **Response** (200)::

       {"detail": "Logged in."}

   A ``Set-Cookie: sessionid=<key>`` header is included in the response.

   **Errors**:

   - ``401 Unauthorized`` — missing fields or invalid credentials.

``openviper.auth.views.logout``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

   - ``"jwt"`` — extract ``jti`` from the token (without re-verifying) and
     add it to the JWT blocklist.  Works even for already-expired tokens.
   - ``"token"`` — mark the opaque token inactive in the database.
   - ``"session"`` — delete the session from the backing store.

   **Response** (200)::

       {"detail": "Logged out."}

   **Errors**:

   - ``401 Unauthorized`` — request is unauthenticated.

``openviper.auth.views.me``
~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: MeView

   ``GET`` handler that returns the authenticated user's profile.  Accepts
   all three authentication schemes (JWT, Token, Session).

   **Response** (200)::

       {
           "id":           1,
           "username":     "alice",
           "email":        "alice@example.com",
           "first_name":   "Alice",
           "last_name":    "Liddell",
           "is_active":    true,
           "is_staff":     false,
           "is_superuser": false
       }

   **Errors**:

   - ``401 Unauthorized`` — request is unauthenticated.

``openviper.views.routes``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:data:: jwt_routes

   Two-entry list: JWT login (``POST /jwt/login``) and JWT logout
   (``POST /jwt/logout``).

.. py:data:: token_routes

   Two-entry list: token login (``POST /token/login``) and token logout
   (``POST /token/logout``).

.. py:data:: session_routes

   Two-entry list: session login (``POST /session/login``) and session logout
   (``POST /session/logout``).

.. py:data:: all_auth_routes

   Concatenation of ``jwt_routes + token_routes + session_routes`` plus a
   shared ``GET /me`` entry.  Use this list when you want to support all
   three authentication schemes simultaneously.

----

.. _social-login:

OAuth2 / Social Login
=====================

OpenViper ships with two complementary OAuth2 systems:

* **Class-based redirect views** — :class:`~openviper.auth.views.oauth2.BaseOAuth2InitView`
  and :class:`~openviper.auth.views.oauth2.BaseOAuth2CallbackView` handle the full
  browser-redirect flow (state cookie → code exchange → user creation → login).
  Ready-made Google subclasses are included.

* **Authentication backend** — :class:`~openviper.auth.authentications.OAuth2Authentication`
  validates Bearer tokens and fires configurable lifecycle events.

.. contents:: On this page
   :local:
   :depth: 2

----

Google OAuth2 — Quick Start
----------------------------

1. Create OAuth2 credentials in the `Google Cloud Console`_ (Web Application type).
2. Add your callback URL to the **Authorised redirect URIs** list, e.g.
   ``http://localhost:8000/auth/google/callback``.
3. Add the settings below to your project.
4. Register the two routes.

.. _Google Cloud Console: https://console.cloud.google.com/apis/credentials

Required Settings
~~~~~~~~~~~~~~~~~

.. code-block:: python

    import dataclasses
    import os
    from openviper.conf import Settings

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):

        # ── Google OAuth2 ─────────────────────────────────────────────────
        GOOGLE_OAUTH_CLIENT_ID: str = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
        GOOGLE_OAUTH_CLIENT_SECRET: str = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
        GOOGLE_OAUTH_REDIRECT_URI: str = os.environ.get(
            "GOOGLE_OAUTH_REDIRECT_URI",
            "http://localhost:8000/auth/google/callback",
        )

        # ── OAuth2 lifecycle events (optional) ────────────────────────────
        OAUTH2_EVENTS: dict = dataclasses.field(
            default_factory=lambda: {
                "on_success": "myapp.events.oauth_success",
                "on_fail":    "myapp.events.oauth_fail",
                "on_error":   "myapp.events.oauth_error",
                "on_initial": "myapp.events.oauth_initial",
            }
        )

        # ── Session — must be persistent for OAuth2 callbacks ─────────────
        SESSION_BACKEND: str = "database"       # or "redis"
        SESSION_COOKIE_NAME: str = "sessionid"
        SESSION_COOKIE_HTTPONLY: bool = True
        SESSION_COOKIE_SAMESITE: str = "lax"    # required for cross-site redirects
        SESSION_COOKIE_SECURE: bool = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

        # ── Cache (required when SESSION_BACKEND = "redis") ───────────────
        CACHE_BACKEND: str = "redis"
        CACHE_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

.. list-table:: Required environment variables
   :header-rows: 1
   :widths: 35 65

   * - Variable
     - Description
   * - ``GOOGLE_OAUTH_CLIENT_ID``
     - OAuth2 client ID from Google Cloud Console
   * - ``GOOGLE_OAUTH_CLIENT_SECRET``
     - OAuth2 client secret from Google Cloud Console
   * - ``GOOGLE_OAUTH_REDIRECT_URI``
     - Callback URL registered in Google Cloud Console

Registering the Routes
~~~~~~~~~~~~~~~~~~~~~~

Use the pre-built :data:`~openviper.auth.views.oauth2.google_oauth_routes` list, or
register the views individually:

.. code-block:: python

    # routes.py
    from openviper.auth.views.oauth2 import (
        GoogleOAuthInitView,
        GoogleOAuthCallbackView,
        google_oauth_routes,
    )
    from openviper.routing import Router

    router = Router()

    # Option A — pre-built route list (mounts at /auth/google and /auth/google/callback)
    for path, handler, methods in google_oauth_routes:
        router.add(path, handler, methods=methods)

    # Option B — register individually with custom paths
    router.add("/auth/google",          GoogleOAuthInitView.as_view(),     methods=["GET"])
    router.add("/auth/google/callback", GoogleOAuthCallbackView.as_view(), methods=["GET"])

Customising Redirects
~~~~~~~~~~~~~~~~~~~~~

Override :attr:`~openviper.auth.views.oauth2.BaseOAuth2InitView.login_redirect`,
:attr:`~openviper.auth.views.oauth2.BaseOAuth2CallbackView.error_redirect`, or
the error template by subclassing:

.. code-block:: python

    from openviper.auth.views.oauth2 import GoogleOAuthInitView, GoogleOAuthCallbackView

    class MyGoogleInit(GoogleOAuthInitView):
        error_template = "accounts/login.html"     # shown when CLIENT_ID is missing
        login_redirect = "/dashboard"

    class MyGoogleCallback(GoogleOAuthCallbackView):
        login_redirect = "/dashboard"
        error_redirect = "/accounts/login"

    router.add("/auth/google",          MyGoogleInit.as_view(),     methods=["GET"])
    router.add("/auth/google/callback", MyGoogleCallback.as_view(), methods=["GET"])

----

Google OAuth2 — Authentication Flow
-------------------------------------

1. Browser visits ``/auth/google`` → :class:`~openviper.auth.views.oauth2.GoogleOAuthInitView`
   generates a CSRF ``state`` token, stores it in a short-lived ``HttpOnly`` cookie
   (``oauth2_state``, 10 minutes), and redirects to Google.
2. Google redirects to ``/auth/google/callback`` with ``?code=…&state=…``.
3. :class:`~openviper.auth.views.oauth2.GoogleOAuthCallbackView` validates the ``state``
   cookie, exchanges the code for an access token, and fetches userinfo from Google.
4. The user is looked up by email.  If none exists, a new account is created.
5. ``on_initial`` fires for first-time users; ``on_success`` fires for every successful login.
6. The user is logged in via :func:`~openviper.auth.backends.login` (session cookie set).
7. The ``oauth2_state`` cookie is cleared and the browser is redirected to ``login_redirect``.

On any failure the browser is redirected to ``error_redirect?oauth_error=<reason>`` and
the appropriate event (``on_fail`` / ``on_error``) fires.

.. list-table:: ``oauth_error`` query parameter values
   :header-rows: 1
   :widths: 30 70

   * - Value
     - Cause
   * - ``access_denied``
     - User denied consent on the Google screen
   * - ``invalid_state``
     - CSRF state cookie missing or mismatch
   * - ``token_exchange``
     - Google token endpoint returned an error
   * - ``no_email``
     - Google userinfo did not include a verified email
   * - ``user_create``
     - Database error during user lookup / creation

----

.. _choosing-auth-method:

Choosing an Authentication Method
-----------------------------------

After validating the OAuth2 callback and finding (or creating) the user,
:class:`~openviper.auth.views.oauth2.BaseOAuth2CallbackView` calls ``complete_login``.
The default uses **session** auth.  Override it on your callback subclass to
switch to JWT or opaque-token auth.

Session (default — browser web apps)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No override needed.  A persistent server-side session is created and the
``sessionid`` cookie is set on the redirect response.

.. code-block:: python

    from openviper.auth.views.oauth2 import GoogleOAuthCallbackView

    class MyGoogleCallback(GoogleOAuthCallbackView):
        login_redirect = "/dashboard"
        error_redirect = "/login"
        # complete_login not overridden — session auth is used automatically

Required settings:

.. code-block:: python

    SESSION_BACKEND: str = "database"   # or "redis"
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "lax"
    SESSION_COOKIE_SECURE: bool = True  # always True in production

JWT (SPA / mobile — tokens in cookies)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Issue JWT access and refresh tokens and deliver them as ``HttpOnly`` cookies
so the SPA can authenticate API requests without exposing tokens to JavaScript.

.. code-block:: python

    from openviper.auth.jwt import create_access_token, create_refresh_token
    from openviper.auth.views.oauth2 import GoogleOAuthCallbackView
    from openviper.http.response import RedirectResponse
    from openviper.http.request import Request
    from openviper.auth.models import User

    class JWTGoogleCallback(GoogleOAuthCallbackView):
        login_redirect = "/dashboard"
        error_redirect = "/login"

        async def complete_login(
            self, request: Request, user: User, response: RedirectResponse
        ) -> RedirectResponse:
            access = create_access_token(user_id=user.pk)
            refresh = create_refresh_token(user_id=user.pk)

            response.set_cookie(
                "access_token",
                access,
                httponly=True,
                samesite="lax",
                secure=True,
                path="/",
            )
            response.set_cookie(
                "refresh_token",
                refresh,
                httponly=True,
                samesite="lax",
                secure=True,
                path="/auth/refresh",  # limit refresh cookie to refresh endpoint
            )
            return response

The client reads the token from the ``access_token`` cookie and appends it
to API requests:  ``Authorization: Bearer <token>``.

JWT (SPA — tokens in URL fragment)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Redirect to your SPA with tokens embedded in the URL fragment.  The SPA
reads them from ``window.location.hash`` and stores them in memory or
``sessionStorage`` (never ``localStorage`` for security).

.. code-block:: python

    from openviper.auth.jwt import create_access_token, create_refresh_token
    from openviper.auth.views.oauth2 import GoogleOAuthCallbackView
    from openviper.http.response import RedirectResponse
    from openviper.http.request import Request
    from openviper.auth.models import User

    class JWTFragmentGoogleCallback(GoogleOAuthCallbackView):
        login_redirect = "/app"         # base SPA route
        error_redirect = "/login"

        async def complete_login(
            self, request: Request, user: User, response: RedirectResponse
        ) -> RedirectResponse:
            access = create_access_token(user_id=user.pk)
            refresh = create_refresh_token(user_id=user.pk)

            # Redirect to SPA with tokens in the URL fragment (never sent to server)
            response.headers["location"] = (
                f"{self.login_redirect}#access_token={access}&refresh_token={refresh}"
            )
            response.delete_cookie("oauth2_state", path="/")
            return response

.. warning::

   URL-fragment tokens are visible in browser history if the SPA does not
   immediately replace ``window.location`` after extracting them.

Opaque Token (API clients / CLI tools)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Issue a long-lived opaque bearer token.  Useful when the post-OAuth2 client
is a CLI, mobile app, or server-to-server integration rather than a browser.

.. code-block:: python

    from openviper.auth.authentications import create_token
    from openviper.auth.views.oauth2 import GoogleOAuthCallbackView
    from openviper.http.response import RedirectResponse
    from openviper.http.request import Request
    from openviper.auth.models import User

    class TokenGoogleCallback(GoogleOAuthCallbackView):
        login_redirect = "/dashboard"
        error_redirect = "/login"

        async def complete_login(
            self, request: Request, user: User, response: RedirectResponse
        ) -> RedirectResponse:
            raw_token, _ = await create_token(user_id=user.pk)

            # Deliver the token via a short-lived HttpOnly cookie so the browser
            # can hand it to the client application on the next page load.
            response.set_cookie(
                "api_token",
                raw_token,
                httponly=True,
                samesite="lax",
                secure=True,
                max_age=60,             # one-time pickup — expire quickly
                path="/",
            )
            return response

The receiving page reads the ``api_token`` cookie once, stores it securely
in the native app, then clears the cookie.

.. list-table:: Method comparison
   :header-rows: 1
   :widths: 20 20 20 20 20

   * - Method
     - Storage
     - Stateful on server
     - Best for
     - Override required
   * - **Session**
     - Server DB / Redis
     - Yes
     - Traditional web apps
     - No
   * - **JWT cookie**
     - ``HttpOnly`` cookie
     - No
     - SPAs, server-rendered hybrids
     - Yes — ``complete_login``
   * - **JWT fragment**
     - SPA memory / ``sessionStorage``
     - No
     - Single-page apps
     - Yes — ``complete_login``
   * - **Opaque token**
     - Server DB
     - Yes
     - CLI / mobile / service accounts
     - Yes — ``complete_login``

----

Adding a Custom Provider
------------------------

Subclass both base views and set the required class attributes:

.. code-block:: python

    from openviper.auth.views.oauth2 import BaseOAuth2InitView, BaseOAuth2CallbackView
    from typing import Any

    class GitHubOAuthInitView(BaseOAuth2InitView):
        provider              = "github"
        auth_url              = "https://github.com/login/oauth/authorize"
        scope                 = "read:user user:email"
        client_id_setting     = "GITHUB_OAUTH_CLIENT_ID"
        redirect_uri_setting  = "GITHUB_OAUTH_REDIRECT_URI"
        login_redirect        = "/dashboard"
        error_template        = "auth/login.html"

    class GitHubOAuthCallbackView(BaseOAuth2CallbackView):
        provider              = "github"
        token_url             = "https://github.com/login/oauth/access_token"
        userinfo_url          = "https://api.github.com/user"
        client_id_setting     = "GITHUB_OAUTH_CLIENT_ID"
        client_secret_setting = "GITHUB_OAUTH_CLIENT_SECRET"
        redirect_uri_setting  = "GITHUB_OAUTH_REDIRECT_URI"
        login_redirect        = "/dashboard"
        error_redirect        = "/login"

        def get_userinfo_headers(self, access_token: str) -> dict[str, str]:
            # GitHub requires Accept: application/vnd.github+json
            return {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            }

        def extract_user_info(
            self, user_info: dict[str, Any]
        ) -> tuple[str, str, str]:
            return (
                user_info.get("email", ""),
                user_info.get("name", "") or user_info.get("login", ""),
                str(user_info.get("id", "")),
            )

Customising User Creation
~~~~~~~~~~~~~~~~~~~~~~~~~

Override :meth:`~openviper.auth.views.oauth2.BaseOAuth2CallbackView.get_or_create_user`
to assign default roles or set extra fields:

.. code-block:: python

    from openviper.auth.views.oauth2 import GoogleOAuthCallbackView
    from openviper.auth.models import Role

    class MyGoogleCallback(GoogleOAuthCallbackView):
        async def get_or_create_user(self, email, name, provider_user_id):
            user, created = await super().get_or_create_user(email, name, provider_user_id)
            if created:
                viewer_role = await Role.objects.get_or_none(name="viewer")
                if viewer_role:
                    await user.assign_role(viewer_role)
            return user, created

----

OAuth2 Events
-------------

Configure ``OAUTH2_EVENTS`` in your project settings to attach async or sync
callables to any of the four lifecycle points.

.. code-block:: python

    # settings.py
    OAUTH2_EVENTS: dict = dataclasses.field(
        default_factory=lambda: {
            "on_success": "myapp.events.oauth_success",
            "on_fail":    "myapp.events.oauth_fail",
            "on_error":   "myapp.events.oauth_error",
            "on_initial": "myapp.events.oauth_initial",
        }
    )

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Event
     - When it fires
   * - ``on_success``
     - After every successful OAuth2 login
   * - ``on_fail``
     - When authentication fails (bad token, inactive user, invalid state, …)
   * - ``on_error``
     - When an unexpected exception occurs during the flow
   * - ``on_initial``
     - On the very first successful login for a user (account just created)

Event Handler Signature
~~~~~~~~~~~~~~~~~~~~~~~

Each handler receives a single ``payload`` dict:

.. code-block:: python

    payload = {
        "provider":            "google",
        "access_token":        "<raw access token>",
        "user_info":           { ... },           # raw userinfo JSON from provider
        "email":               "user@example.com",
        "name":                "Alice Smith",
        "provider_user_id":    "1234567890",
        "request":             <Request>,
        "authentication_type": "oauth2",
        "error":               "",                # non-empty only in on_fail / on_error
    }

Handlers may be **async or sync**:

.. code-block:: python

    # myapp/events.py
    import logging

    logger = logging.getLogger("myapp.events")

    async def oauth_success(payload: dict) -> None:
        logger.info("OAuth login: %s via %s", payload["email"], payload["provider"])

    async def oauth_initial(payload: dict) -> None:
        logger.info("New user created via OAuth: %s", payload["email"])

    async def oauth_fail(payload: dict) -> None:
        logger.warning(
            "OAuth login failed: provider=%s error=%s",
            payload["provider"],
            payload["error"],
        )

    async def oauth_error(payload: dict) -> None:
        logger.error(
            "OAuth unexpected error: provider=%s error=%s",
            payload["provider"],
            payload["error"],
        )

Safety Guarantees
~~~~~~~~~~~~~~~~~

- A broken or missing event handler **never** interrupts authentication.
  Import errors and handler exceptions are caught, logged, and swallowed.
- Handler paths are validated against a strict dotted-identifier regex before
  import — arbitrary strings cannot be injected via settings.
- Only the four registered event names are dispatched; unknown names are ignored.

----

``openviper.auth.views.oauth2`` Reference
------------------------------------------

.. py:class:: BaseOAuth2InitView

   Abstract base for OAuth2 redirect views.  Set these class attributes:

   .. list-table::
      :header-rows: 1
      :widths: 35 65

      * - Attribute
        - Description
      * - ``provider``
        - Provider name string, used in log messages
      * - ``auth_url``
        - Provider authorisation endpoint URL
      * - ``scope``
        - Space-separated OAuth2 scopes (default: ``"openid email profile"``)
      * - ``client_id_setting``
        - Settings attribute name for the client ID
      * - ``redirect_uri_setting``
        - Settings attribute name for the redirect URI
      * - ``error_template``
        - Template to render when the provider is misconfigured (default: ``"auth/login.html"``)
      * - ``login_redirect``
        - Redirect path after successful login (default: ``"/"``)

   Override :meth:`get_extra_params` to add provider-specific query parameters
   (e.g. ``access_type``, ``prompt``).

.. py:class:: BaseOAuth2CallbackView

   Abstract base for OAuth2 callback views.  Set these class attributes:

   .. list-table::
      :header-rows: 1
      :widths: 35 65

      * - Attribute
        - Description
      * - ``provider``
        - Provider name string
      * - ``token_url``
        - Provider token exchange endpoint
      * - ``userinfo_url``
        - Provider userinfo endpoint
      * - ``client_id_setting``
        - Settings attribute name for the client ID
      * - ``client_secret_setting``
        - Settings attribute name for the client secret
      * - ``redirect_uri_setting``
        - Settings attribute name for the redirect URI
      * - ``login_redirect``
        - Redirect path after successful login (default: ``"/"``)
      * - ``error_redirect``
        - Redirect path on failure (default: ``"/login"``)

   **Abstract method** — must be implemented by subclasses:

   .. py:method:: extract_user_info(user_info) -> tuple[str, str, str]

      Map the provider's userinfo JSON to ``(email, name, provider_user_id)``.

   **Override-friendly hooks:**

   .. py:method:: get_or_create_user(email, name, provider_user_id) -> tuple[User, bool]

      Return ``(user, first_login)``.  Default implementation performs a
      ``get_or_none(email=email)`` lookup and creates a new user when not found.

   .. py:method:: get_token_request_data(code, client_id, client_secret, redirect_uri) -> dict

      Build the POST body for the token endpoint.

   .. py:method:: get_userinfo_headers(access_token) -> dict

      Return headers for the userinfo request (default: ``Authorization: Bearer …``).

   .. py:method:: complete_login(request, user, response) -> RedirectResponse

      Finalise authentication after the user has been verified.

      The default creates a **session** cookie via
      :func:`~openviper.auth.backends.login`.  Override to use JWT or
      opaque-token auth instead.  The *response* argument is a
      :class:`~openviper.http.response.RedirectResponse` already pointed at
      :attr:`login_redirect` with the CSRF state cookie removed — modify it
      in-place and return it.

      See :ref:`choosing-auth-method` for complete examples.

.. py:class:: GoogleOAuthInitView

   Concrete subclass of :class:`BaseOAuth2InitView` for Google.
   Reads ``GOOGLE_OAUTH_CLIENT_ID`` and ``GOOGLE_OAUTH_REDIRECT_URI`` from settings.

.. py:class:: GoogleOAuthCallbackView

   Concrete subclass of :class:`BaseOAuth2CallbackView` for Google.
   Reads ``GOOGLE_OAUTH_CLIENT_ID``, ``GOOGLE_OAUTH_CLIENT_SECRET``, and
   ``GOOGLE_OAUTH_REDIRECT_URI`` from settings.

.. py:data:: google_oauth_routes

   Pre-built list of ``(path, handler, methods)`` tuples::

       [
           ("/auth/google",          GoogleOAuthInitView.as_view(),     ["GET"]),
           ("/auth/google/callback", GoogleOAuthCallbackView.as_view(), ["GET"]),
       ]
