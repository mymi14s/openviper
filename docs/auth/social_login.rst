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
