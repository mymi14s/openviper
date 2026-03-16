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
   :mod:`openviper.auth.jwt`.
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

``openviper.auth.middleware``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: AuthenticationMiddleware(app, manager=None)

   ASGI middleware that runs the auth backend pipeline on every HTTP/WebSocket
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

Example Usage
-------------

.. seealso::

   Working projects that use authentication:

   - `examples/todoapp/ <https://github.com/mymi14s/openviper/tree/master/examples/todoapp>`_ — session-based login/logout with ``authenticate``
   - `examples/ai_moderation_platform/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_moderation_platform>`_ — JWT auth, RBAC roles, ``role_required`` decorator
   - `examples/ecommerce_clone/ <https://github.com/mymi14s/openviper/tree/master/examples/ecommerce_clone>`_ — JWT auth, custom ``User`` extending ``AbstractUser``
   - `examples/ai_smart_recipe_generator/ <https://github.com/mymi14s/openviper/tree/master/examples/ai_smart_recipe_generator>`_ — session-based cookie auth

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
        # Custom user model (optional):
        USER_MODEL: str = "users.models.User"
