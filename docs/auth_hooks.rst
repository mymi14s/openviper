.. _auth-hooks:

Auth Lifecycle Hooks
====================

Overview
--------

OpenViper auth lifecycle hooks let applications extend login and logout
behavior without replacing authentication internals. Hooks run around the
built-in authentication flows and receive an ``AuthHookContext`` object with
the authenticated user, request metadata, and safe lifecycle data.

Plaintext passwords, OTP codes, API keys, access tokens, and refresh tokens
are not passed to hooks by default.

Hook Lifecycle
--------------

The built-in login views run hooks in this order:

1. Credentials are validated by the existing authentication backend.
2. ``before_login`` hooks run with the authenticated user and sanitized
   credentials.
3. The session, JWT, or opaque token is created by the existing OpenViper
   behavior.
4. ``on_login`` hooks run with the user and session or token metadata.
5. The normal login response is returned.

Logout builds the context before credential revocation, revokes the active
credential, then runs ``on_logout`` hooks.

before_login
------------

``before_login`` runs after credentials are authenticated and before final
session or token creation. It can reject login by raising
``AuthHookReject``.

.. code-block:: python

   from openviper.auth.hooks import AuthHookReject, auth_hooks


   @auth_hooks.before_login
   async def block_suspended_users(context):
       if context.user and context.user.is_suspended:
           raise AuthHookReject("This account is suspended.")

Unexpected ``before_login`` errors fail closed by default. Configure
``AUTH_HOOKS["before_login_error"] = "log"`` only when you deliberately want
to continue after unexpected hook failures.

on_login
--------

``on_login`` runs after successful session or token creation. It is intended
for side effects such as audit logging, last-login updates, notifications, or
session metadata enrichment.

.. code-block:: python

   from openviper.auth.hooks import AuthHookReject, auth_hooks


   @auth_hooks.on_login
   async def audit_login(context):
       await AuditLog.objects.create(
           user_id=context.user.id,
           action="login",
       )

By default, ``on_login`` errors are logged and login remains successful.
Set ``AUTH_HOOKS["on_login_error"] = "raise"`` to fail login when a post-login
hook fails.

on_logout
---------

``on_logout`` runs during logout after the context is built and after the
active credential is revoked. By default, logout completes even if a hook
fails.

.. code-block:: python

   from openviper.auth.hooks import auth_hooks


   @auth_hooks.on_logout
   async def audit_logout(context):
       await AuditLog.objects.create(
           user_id=context.user.id,
           action="logout",
       )

Set ``AUTH_HOOKS["on_logout_error"] = "raise"`` if logout hook failures should
propagate.

AuthHookContext
---------------

Hooks receive an ``AuthHookContext``:

.. code-block:: python

   @dataclass(slots=True)
   class AuthHookContext:
       user: object | None = None
       credentials: dict[str, object] = field(default_factory=dict)
       request: object | None = None
       session: object | None = None
       token: object | None = None
       auth_backend: str | None = None
       metadata: dict[str, object] = field(default_factory=dict)

``credentials`` contains sanitized values such as username, email, provider,
tenant, or login method. Sensitive values are stripped by default.

``token`` contains token metadata for the built-in JWT and opaque-token login
views, not raw bearer tokens.

Registering Hooks
-----------------

Decorator registration is the primary API:

.. code-block:: python

   from openviper.auth.hooks import auth_hooks


   @auth_hooks.before_login
   def require_known_tenant(context):
       if context.credentials.get("tenant") == "disabled":
           raise AuthHookReject("Login rejected.")

Explicit registration is also supported:

.. code-block:: python

   from openviper.auth.hooks import register_auth_hook

   register_auth_hook("before_login", require_known_tenant)
   register_auth_hook("on_login", audit_login)
   register_auth_hook("on_logout", audit_logout)

Hooks can be synchronous or asynchronous. Hooks run in registration order.
Priority ordering is not implemented in v1.

Using Hooks from Apps
---------------------

A common pattern is to define hooks in ``auth_hooks.py`` and import that
module from an explicit app lifecycle hook.

``auth_hooks.py``:

.. code-block:: python

   from openviper.auth.hooks import AuthHookReject, auth_hooks


   @auth_hooks.before_login
   async def block_suspended_users(context):
       if context.user and context.user.is_suspended:
           raise AuthHookReject("This account is suspended.")


   @auth_hooks.on_login
   async def audit_login(context):
       await AuditLog.objects.create(
           user_id=context.user.id,
           action="login",
       )


   @auth_hooks.on_logout
   async def audit_logout(context):
       await AuditLog.objects.create(
           user_id=context.user.id,
           action="logout",
       )

``lifecycle.py``:

.. code-block:: python

   def ready() -> None:
       from . import auth_hooks

OpenViper does not automatically discover ``auth_hooks.py`` in v1. Import the
module from your app startup path so registration is explicit.

Error Handling
--------------

Configure hook error behavior with ``AUTH_HOOKS``:

.. code-block:: python

   AUTH_HOOKS = {
       "before_login_error": "raise",
       "on_login_error": "log",
       "on_logout_error": "log",
   }

Allowed values are ``"raise"`` and ``"log"``.

``before_login`` rejects should raise ``AuthHookReject``. Unexpected errors
are wrapped in ``AuthHookExecutionError`` when the policy is ``"raise"``.

Security Notes
--------------

Hooks cannot bypass core authentication. They run only after the existing
authentication backend accepts credentials.

The default sanitizer removes these credential fields:

``password``, ``password_confirm``, ``otp``, ``totp``, ``secret``, ``token``,
``refresh_token``, ``access_token``, and ``api_key``.

Do not log raw request bodies or bearer tokens from hooks. Hook error logs
include hook phase and hook name, but not credentials.

Testing Auth Hooks
------------------

Use an isolated ``AuthHookRegistry`` for unit tests that only exercise
registration and execution:

.. code-block:: python

   registry = AuthHookRegistry()

   @registry.before_login
   async def hook(context):
       ...

For integration tests that use the global registry, clear it before and after
each test:

.. code-block:: python

   from openviper.auth.hooks import auth_hooks

   auth_hooks.clear()

Limitations
-----------

Auth hooks v1 does not include priority ordering, hook groups, per-backend
enablement, admin inspection, or automatic ``auth_hooks.py`` discovery.
