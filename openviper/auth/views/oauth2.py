"""Generic OAuth2 class-based views for OpenViper.

Provides two extensible base classes:

* :class:`BaseOAuth2InitView` - redirects the browser to a provider's
  authorisation endpoint and stores a CSRF state token in a short-lived
  ``HttpOnly`` cookie.

* :class:`BaseOAuth2CallbackView` - handles the provider callback: validates
  the CSRF state, exchanges the authorisation code for tokens, fetches
  userinfo, creates or retrieves the local ``User`` record, fires
  :class:`~openviper.auth.authentications.OAuth2Authentication` lifecycle
  events, and logs the user in.

Both classes are designed to be subclassed. Concrete provider implementations
set provider-specific class attributes and override hook methods as needed.
"""

from __future__ import annotations

import abc
import hmac
import logging
import os
import secrets
import urllib.parse
from typing import TYPE_CHECKING, cast

import httpx

from openviper.auth.authentications import OAuth2Authentication
from openviper.auth.backends import login
from openviper.auth.constants import (
    OAUTH2_HTTPX_TIMEOUT,
    OAUTH2_STATE_COOKIE,
    OAUTH2_STATE_MAX_AGE,
)
from openviper.conf import settings
from openviper.http.permissions import AllowAny
from openviper.http.response import HTMLResponse, RedirectResponse
from openviper.http.views import View

if TYPE_CHECKING:
    from openviper.auth.types import AuthPayload
    from openviper.http.request import Request

from openviper.auth import get_user_model

logger = logging.getLogger("openviper.auth.oauth2")

GOOGLE_OAUTH_ENDPOINTS: dict[str, str] = {
    "token": "https://oauth2.googleapis.com/token",
    "userinfo": "https://www.googleapis.com/oauth2/v3/userinfo",
}
GOOGLE_OAUTH_SETTING_NAMES: dict[str, str] = {
    "client_id": "GOOGLE_OAUTH_CLIENT_ID",
    "client_secret": "GOOGLE_OAUTH_CLIENT_SECRET",
    "redirect_uri": "GOOGLE_OAUTH_REDIRECT_URI",
}


def is_safe_redirect_url(url: str, allowed_hosts: frozenset[str] | None = None) -> bool:
    """Reject open-redirect targets that are not same-origin or whitelisted.

    Validates that *url* is either a relative path starting with ``/`` (but not
    ``//``) or an absolute URL whose host appears in *allowed_hosts*.  This
    prevents the class of open-redirect attacks.  The URL is decoded only once
    so double-encoded sequences cannot bypass the path checks.
    """
    sanitized = url.strip()
    if not sanitized:
        return False
    decoded = urllib.parse.unquote(sanitized)
    # Reject protocol-relative URLs and encoded traversal sequences.
    if (
        decoded.startswith("/")
        and not decoded.startswith("//")
        and "\\" not in decoded
        and ".." not in decoded
        and "/../" not in decoded
        and "%2f" not in sanitized.lower()
        and "%5c" not in sanitized.lower()
    ):
        return True
    parsed = urllib.parse.urlparse(decoded)
    if parsed.scheme not in {"http", "https"}:
        return False
    if "@" in parsed.netloc:
        return False
    if allowed_hosts and urllib.parse.unquote(parsed.netloc) not in allowed_hosts:
        return False
    return bool(allowed_hosts)


def safe_redirect_url(
    target: str, allowed_hosts: frozenset[str] | None = None, fallback: str = "/"
) -> str:
    """Return *target* if safe, otherwise *fallback*."""
    return target if is_safe_redirect_url(target, allowed_hosts) else fallback


def oauth_error_redirect(
    error_redirect: str, code: str, allowed_hosts: frozenset[str]
) -> RedirectResponse:
    """Build a guarded OAuth2 error redirect response."""
    target = safe_redirect_url(error_redirect, allowed_hosts, "/login")
    separator = "&" if urllib.parse.urlparse(target).query else "?"
    return RedirectResponse(f"{target}{separator}oauth_error={code}", status_code=302)


def validate_oauth2_endpoint(url: str) -> bool:
    """Ensure OAuth2 token/userinfo endpoints use HTTPS in production.

    Prevents accidental misconfiguration that would send credentials over an
    unencrypted connection. Reads ``OPENVIPER_ENV`` and falls back to
    ``ENVIRONMENT`` for backwards compatibility.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        env = (
            os.environ.get("OPENVIPER_ENV") or os.environ.get("ENVIRONMENT", "")
        ).lower()
        if env in ("production", "prod"):
            return False
    return True


if TYPE_CHECKING:
    from openviper.auth.models import User
else:
    User = get_user_model()


class BaseOAuth2InitView(View):
    """Redirect the browser to an OAuth2 provider's authorisation endpoint.

    Subclass and set ``provider``, ``auth_url``, ``scope``, ``client_id_setting``,
    and ``redirect_uri_setting`` for the target provider.
    """

    permission_classes = [AllowAny]

    provider: str = ""
    auth_url: str = ""
    scope: str = "openid email profile"

    client_id_setting: str = ""
    redirect_uri_setting: str = ""

    error_template: str = "auth/login.html"
    login_redirect: str = "/"

    def get_client_id(self) -> str:
        return getattr(settings, self.client_id_setting, "")

    def get_redirect_uri(self) -> str:
        return getattr(settings, self.redirect_uri_setting, "")

    def get_extra_params(self) -> dict[str, str]:
        """Return additional query-string parameters for the authorisation URL.

        Override to add provider-specific parameters such as ``access_type``
        or ``prompt``.
        """
        return {}

    def build_auth_params(self, client_id: str, redirect_uri: str, state: str) -> dict[str, str]:
        """Assemble query-string parameters for the authorisation redirect.

        Override to change the parameter set entirely.
        """
        params: dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.scope,
            "state": state,
        }
        params.update(self.get_extra_params())
        return params

    async def get(self, request: Request, **kwargs: object) -> RedirectResponse | HTMLResponse:
        """Generate a state token, build the authorisation URL, and redirect."""
        client_id = self.get_client_id()
        redirect_uri = self.get_redirect_uri()

        if not client_id or not redirect_uri:
            logger.error(
                "%s OAuth is not configured - missing %s or %s.",
                self.provider,
                self.client_id_setting,
                self.redirect_uri_setting,
            )
            return HTMLResponse(
                template=self.error_template,
                context={"title": "Login", "error": f"{self.provider} login is not configured."},
                status_code=503,
            )

        state = secrets.token_urlsafe(32)

        params = self.build_auth_params(client_id, redirect_uri, state)
        query_string = urllib.parse.urlencode(params)
        response = RedirectResponse(f"{self.auth_url}?{query_string}", status_code=302)
        response.set_cookie(
            OAUTH2_STATE_COOKIE,
            state,
            max_age=OAUTH2_STATE_MAX_AGE,
            httponly=True,
            samesite="lax",
            path="/",
            secure=request.is_secure(),
        )
        return response


class BaseOAuth2CallbackView(View):
    """Handle the OAuth2 callback from a provider.

    Subclass and set ``provider``, ``token_url``, ``userinfo_url``,
    ``client_id_setting``, ``client_secret_setting``, and
    ``redirect_uri_setting``. Override :meth:`extract_user_info` to map
    the provider's userinfo payload to ``(email, name, provider_user_id)``.
    """

    permission_classes = [AllowAny]

    provider: str = ""
    token_url: str = ""
    userinfo_url: str = ""

    client_id_setting: str = ""
    client_secret_setting: str = ""
    redirect_uri_setting: str = ""

    login_redirect: str = "/"
    error_redirect: str = "/login"

    def get_client_id(self) -> str:
        return getattr(settings, self.client_id_setting, "")

    def get_client_secret(self) -> str:
        return getattr(settings, self.client_secret_setting, "")

    def get_redirect_uri(self) -> str:
        return getattr(settings, self.redirect_uri_setting, "")

    @abc.abstractmethod
    def extract_user_info(self, user_info: AuthPayload) -> tuple[str, str, str]:
        """Map the provider's userinfo JSON to ``(email, name, provider_user_id)``.

        All three values may be empty strings; the callback view will treat an
        empty *email* as a failure.
        """

    def get_token_request_data(
        self, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> dict[str, str]:
        """Build the POST body for the token endpoint.

        Override to add provider-specific fields.
        """
        return {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

    def get_userinfo_headers(self, access_token: str) -> dict[str, str]:
        """Return headers for the userinfo request.

        Override for providers that use a different authentication scheme.
        """
        return {"Authorization": f"Bearer {access_token}"}

    def validate_user_info(self, user_info: AuthPayload) -> str | None:
        """Validate the raw userinfo payload before processing.

        Return a non-empty error string if the payload is unacceptable, or
        ``None`` if it is valid.  Override in provider subclasses to add
        provider-specific checks (e.g. ``email_verified`` for Google).
        """
        email = str(user_info.get("email") or "").strip()
        if not email or "@" not in email:
            return "missing_or_invalid_email"
        return None

    async def get_or_create_user(
        self, email: str, name: str, provider_user_id: str
    ) -> tuple[User, bool]:
        """Return ``(user, first_login)`` for the given email.

        Creates a new :class:`~openviper.auth.models.User` when none exists.
        Override to customise user creation (e.g. assign a default role, set
        extra fields).

        Args:
            email: Verified email returned by the provider.
            name: Display name returned by the provider.
            provider_user_id: Provider-specific user identifier.

        Returns:
            2-tuple of ``(user_instance, first_login)`` where *first_login* is
            ``True`` when a new account was just created.
        """
        email = email.strip().lower()
        user = await User.objects.get_or_none(email=email)
        if user is not None:
            return cast("User", user), False

        username = email.split("@")[0]
        base = username
        counter = 1
        while await User.objects.get_or_none(username=username) is not None:
            if counter > 20:
                # Avoid unbounded DB queries under adversarial username collisions.
                username = f"{base}_{secrets.token_hex(4)}"
                break
            username = f"{base}{counter}"
            counter += 1

        parts = name.split() if name else []
        user = await User.objects.create(
            username=username,
            email=email,
            first_name=parts[0] if parts else "",
            last_name=" ".join(parts[1:]) if len(parts) > 1 else "",
            is_active=True,
        )
        return cast("User", user), True

    def get_allowed_redirect_hosts(self) -> frozenset[str]:
        """Return the set of hosts considered safe for post-login redirects.

        Reads from ``settings.ALLOWED_REDIRECT_HOSTS``.  Subclasses may
        override to provide a custom host set.  Used by the open-redirect
        guard in :meth:`get`.
        """
        return frozenset(getattr(settings, "ALLOWED_REDIRECT_HOSTS", ()))

    async def get(self, request: Request, **kwargs: object) -> RedirectResponse:
        """Validate state, exchange code, fetch userinfo, and log the user in."""
        oauth_auth = OAuth2Authentication()
        allowed_hosts = self.get_allowed_redirect_hosts()

        error_param = request.query_params.get("error")
        if error_param:
            await oauth_auth.trigger_event(
                "on_fail",
                {
                    "error": error_param,
                    "request": request,
                    "provider": self.provider,
                    "authentication_type": "oauth2",
                },
            )
            return oauth_error_redirect(self.error_redirect, "access_denied", allowed_hosts)

        code = request.query_params.get("code") or ""
        state = request.query_params.get("state") or ""
        stored_state = request.cookies.get(OAUTH2_STATE_COOKIE, "")

        state_valid = bool(state and stored_state and hmac.compare_digest(state, stored_state))
        if not code or not state_valid:
            logger.error(
                "OAuth2 invalid_state [%s]: code=%s state_match=%s",
                self.provider,
                "present" if code else "missing",
                state_valid,
            )
            await oauth_auth.trigger_event(
                "on_fail",
                {
                    "error": "invalid_state",
                    "request": request,
                    "provider": self.provider,
                    "authentication_type": "oauth2",
                },
            )
            return oauth_error_redirect(self.error_redirect, "invalid_state", allowed_hosts)

        client_id = self.get_client_id()
        client_secret = self.get_client_secret()
        redirect_uri = self.get_redirect_uri()

        for endpoint in (self.token_url, self.userinfo_url):
            if endpoint and not validate_oauth2_endpoint(endpoint):
                logger.error(
                    "OAuth2 endpoint %r is not HTTPS - rejected in production",
                    endpoint,
                )
                return oauth_error_redirect(self.error_redirect, "invalid_endpoint", allowed_hosts)

        try:
            async with httpx.AsyncClient(timeout=OAUTH2_HTTPX_TIMEOUT) as http:
                token_resp = await http.post(
                    self.token_url,
                    data=self.get_token_request_data(code, client_id, client_secret, redirect_uri),
                )
                token_resp.raise_for_status()
                token_data = cast("AuthPayload", token_resp.json())

                access_token = str(token_data.get("access_token") or "")
                if not access_token:
                    raise ValueError("OAuth2 token response missing access_token field.")
                userinfo_resp = await http.get(
                    self.userinfo_url,
                    headers=self.get_userinfo_headers(access_token),
                )
                userinfo_resp.raise_for_status()
                user_info = cast("AuthPayload", userinfo_resp.json())

        except httpx.HTTPError as exc:
            logger.error("OAuth token exchange failed [%s]: %s", self.provider, exc)
            await oauth_auth.trigger_event(
                "on_error",
                {
                    "provider": self.provider,
                    "user_info": {},
                    "email": "",
                    "name": "",
                    "provider_user_id": "",
                    "request": request,
                    "authentication_type": "oauth2",
                    "error": str(exc),
                },
            )
            return oauth_error_redirect(self.error_redirect, "token_exchange", allowed_hosts)

        validation_error = self.validate_user_info(user_info)
        if validation_error:
            logger.warning(
                "OAuth userinfo validation failed [%s]: %s", self.provider, validation_error
            )
            await oauth_auth.trigger_event(
                "on_fail",
                {
                    "error": validation_error,
                    "request": request,
                    "provider": self.provider,
                    "authentication_type": "oauth2",
                },
            )
            return oauth_error_redirect(self.error_redirect, "unverified_email", allowed_hosts)

        email, name, provider_user_id = self.extract_user_info(user_info)

        payload: AuthPayload = {
            "provider": self.provider,
            "user_info": user_info,
            "email": email,
            "name": name,
            "provider_user_id": provider_user_id,
            "request": request,
            "authentication_type": "oauth2",
            "error": "",
        }

        if not email:
            await oauth_auth.trigger_event("on_fail", {**payload, "error": "no_email"})
            return oauth_error_redirect(self.error_redirect, "no_email", allowed_hosts)

        try:
            user, first_login = await self.get_or_create_user(email, name, provider_user_id)
        except (ValueError, LookupError, RuntimeError) as exc:
            logger.error("OAuth user lookup/creation failed [%s]: %s", self.provider, exc)
            await oauth_auth.trigger_event("on_error", {**payload, "error": str(exc)})
            return oauth_error_redirect(self.error_redirect, "user_create", allowed_hosts)

        if first_login:
            await oauth_auth.trigger_event("on_initial", payload)

        await oauth_auth.trigger_event("on_success", payload)

        login_redirect = safe_redirect_url(self.login_redirect, allowed_hosts)
        if login_redirect != self.login_redirect:
            logger.warning(
                "OAuth2 login_redirect %r rejected - not in allowed hosts",
                self.login_redirect,
            )

        response = RedirectResponse(login_redirect, status_code=302)
        response.delete_cookie(OAUTH2_STATE_COOKIE, path="/")
        return await self.complete_login(request, user, response)

    async def complete_login(
        self, request: Request, user: User, response: RedirectResponse
    ) -> RedirectResponse:
        """Finalise authentication after the user has been verified.

        Establishes a session cookie via :func:`~openviper.auth.backends.login`.
        Override to use a different authentication scheme.

        Args:
            request: The current HTTP request.
            user: The authenticated or newly created user instance.
            response: Redirect response pre-pointed at :attr:`login_redirect`
                with the state cookie cleared. Modify in-place and return.

        Returns:
            The (optionally modified) redirect response.
        """
        await login(request, user, response=response)
        return response


class GoogleOAuthInitView(BaseOAuth2InitView):
    """Redirect the browser to Google's OAuth2 authorisation endpoint.

    Reads ``GOOGLE_OAUTH_CLIENT_ID`` and ``GOOGLE_OAUTH_REDIRECT_URI`` from
    project settings.
    """

    provider = "google"
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    scope = "openid email profile"
    client_id_setting = "GOOGLE_OAUTH_CLIENT_ID"
    redirect_uri_setting = "GOOGLE_OAUTH_REDIRECT_URI"

    def get_extra_params(self) -> dict[str, str]:
        return {"access_type": "offline", "prompt": "select_account"}


class GoogleOAuthCallbackView(BaseOAuth2CallbackView):
    """Handle the OAuth2 callback from Google.

    Reads ``GOOGLE_OAUTH_CLIENT_ID``, ``GOOGLE_OAUTH_CLIENT_SECRET``, and
    ``GOOGLE_OAUTH_REDIRECT_URI`` from project settings.
    """

    provider = "google"
    token_url = GOOGLE_OAUTH_ENDPOINTS["token"]
    userinfo_url = GOOGLE_OAUTH_ENDPOINTS["userinfo"]
    client_id_setting = GOOGLE_OAUTH_SETTING_NAMES["client_id"]
    client_secret_setting = GOOGLE_OAUTH_SETTING_NAMES["client_secret"]
    redirect_uri_setting = GOOGLE_OAUTH_SETTING_NAMES["redirect_uri"]

    def validate_user_info(self, user_info: AuthPayload) -> str | None:
        """Reject userinfo payloads where Google has not verified the email address."""
        if not user_info.get("email_verified", False):
            return "email_not_verified"
        return None

    def extract_user_info(self, user_info: AuthPayload) -> tuple[str, str, str]:
        return (
            str(user_info.get("email", "")),
            str(user_info.get("name", "")),
            str(user_info.get("sub", "")),
        )


google_oauth_routes: list[tuple[str, object, list[str]]] = [
    ("/auth/google", GoogleOAuthInitView.as_view(), ["GET"]),
    ("/auth/google/callback", GoogleOAuthCallbackView.as_view(), ["GET"]),
]
"""Pre-built route tuples for Google OAuth2 login."""

__all__ = [
    "BaseOAuth2InitView",
    "BaseOAuth2CallbackView",
    "GoogleOAuthInitView",
    "GoogleOAuthCallbackView",
    "google_oauth_routes",
]
