"""Example API-backed virtual backend."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode, urlparse

from openviper.db.backends.base import VirtualBackend, VirtualBackendCapabilities
from openviper.db.exceptions import VirtualBackendOperationError

if TYPE_CHECKING:
    from openviper.db.models import Model
    from openviper.db.queryspec import QuerySpec

# Schemes permitted for API backend URLs to prevent SSRF attacks.
_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Regex for hostnames that resolve to private/internal networks.
_PRIVATE_HOST_RE: re.Pattern[str] = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+"
    r"|192\.168\.\d+\.\d+|0\.0\.0\.0|::1|fd[0-9a-f]{2}:)"
)

HostResolver = Callable[[str], Sequence[str]]


def resolve_host_addresses(hostname: str) -> Sequence[str]:
    """Return all network addresses currently resolved for *hostname*."""
    records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    return tuple({str(record[4][0]) for record in records})


def is_private_address(address: str) -> bool:
    """Return whether *address* is outside public internet routing."""
    ip_address = ipaddress.ip_address(address)
    return (
        ip_address.is_private
        or ip_address.is_loopback
        or ip_address.is_link_local
        or ip_address.is_multicast
        or ip_address.is_reserved
        or ip_address.is_unspecified
    )


class APIVirtualBackend(VirtualBackend):
    """Map virtual model CRUD to REST API calls.

    Uses ``model_class._meta.table_name`` as the resource path segment.
    For example, a model with ``table_name = "users"`` will issue requests
    to ``{base_url}/users/``.

    This is an example implementation.  Replace ``http_get``, ``http_post``,
    ``http_patch``, and ``http_delete`` with your project's async HTTP
    client (e.g. ``httpx``, ``aiohttp``).
    """

    def __init__(
        self,
        base_url: str,
        capabilities: VirtualBackendCapabilities | None = None,
        *,
        resolve_hostname: bool = True,
        host_resolver: HostResolver = resolve_host_addresses,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(
                f"APIVirtualBackend: unsupported scheme {parsed.scheme!r}. "
                f"Allowed schemes: {', '.join(sorted(_ALLOWED_SCHEMES))}."
            )
        hostname = parsed.hostname or ""
        self.validate_hostname(
            hostname,
            resolve_hostname=resolve_hostname,
            host_resolver=host_resolver,
        )
        self.base_url = base_url.rstrip("/")
        self.capabilities = capabilities or VirtualBackendCapabilities()

    def validate_hostname(
        self,
        hostname: str,
        *,
        resolve_hostname: bool,
        host_resolver: HostResolver,
    ) -> None:
        """Reject hostnames that can route requests to internal networks."""
        if not hostname:
            raise ValueError("APIVirtualBackend: base_url must include a hostname.")
        if _PRIVATE_HOST_RE.match(hostname):
            raise ValueError(
                f"APIVirtualBackend: base_url hostname {hostname!r} resolves to a "
                f"private/internal network address, which is not permitted."
            )
        try:
            is_private = is_private_address(hostname)
        except ValueError:
            if not resolve_hostname:
                return
        else:
            if is_private:
                raise ValueError(
                    f"APIVirtualBackend: base_url hostname {hostname!r} is a private "
                    f"IP address, which is not permitted."
                )
            return

        try:
            addresses = host_resolver(hostname)
        except OSError as exc:
            raise ValueError(
                f"APIVirtualBackend: base_url hostname {hostname!r} could not be resolved."
            ) from exc
        if not addresses:
            raise ValueError(f"APIVirtualBackend: base_url hostname {hostname!r} did not resolve.")
        for address in addresses:
            if is_private_address(address):
                raise ValueError(
                    f"APIVirtualBackend: base_url hostname {hostname!r} resolves to "
                    f"a private/internal network address."
                )

    def resource_url(self, model_class: type[Model]) -> str:
        """Return the API collection URL for a virtual model."""
        resource = quote(model_class._meta.table_name.strip("/"), safe="")
        return f"{self.base_url}/{resource}"

    def item_url(self, model_class: type[Model], primary_key: object) -> str:
        """Return the API detail URL for a virtual model instance."""
        key = quote(str(primary_key), safe="")
        return f"{self.resource_url(model_class)}/{key}"

    def query_url(self, url: str, query: QuerySpec) -> str:
        """Append supported QuerySpec values as URL query parameters."""
        params: dict[str, str] = {}
        if query.limit is not None:
            params["limit"] = str(query.limit)
        if query.offset is not None:
            params["offset"] = str(query.offset)
        if query.order_by:
            params["order_by"] = ",".join(query.order_by)
        if query.distinct:
            params["distinct"] = "true"
        if query.only_fields:
            params["only"] = ",".join(query.only_fields)
        if query.defer_fields:
            params["defer"] = ",".join(query.defer_fields)
        for key, value in query.filters.items():
            params[key] = str(value)
        for fc in query.filter_clauses:
            params[f"{fc.field}__{fc.op.value}"] = self.serialize_filter_value(fc.value)
        if not params:
            return url
        return f"{url}?{urlencode(params)}"

    @staticmethod
    def serialize_filter_value(value: object) -> str:
        """Serialize a filter clause value for URL query parameter encoding."""
        if isinstance(value, (list, tuple, set, frozenset)):
            return ",".join(str(v) for v in value)
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    async def http_get(
        self, url: str
    ) -> Sequence[Mapping[str, object]] | Mapping[str, object] | None:
        """Replace with your async HTTP GET implementation."""
        raise NotImplementedError("Replace with your async HTTP client.")

    async def http_post(self, url: str, data: Mapping[str, object]) -> Mapping[str, object]:
        """Replace with your async HTTP POST implementation."""
        raise NotImplementedError("Replace with your async HTTP client.")

    async def http_patch(self, url: str, data: Mapping[str, object]) -> Mapping[str, object]:
        """Replace with your async HTTP PATCH implementation."""
        raise NotImplementedError("Replace with your async HTTP client.")

    async def http_delete(self, url: str) -> None:
        """Replace with your async HTTP DELETE implementation."""
        raise NotImplementedError("Replace with your async HTTP client.")

    async def get(
        self,
        model_class: type[Model],
        primary_key: object,
    ) -> Mapping[str, object] | None:
        url = self.item_url(model_class, primary_key)
        try:
            result = await self.http_get(url)
        except Exception as exc:
            raise VirtualBackendOperationError(
                f"Virtual backend API get failed for {model_class.__name__}."
            ) from exc
        if result is None:
            return None
        if isinstance(result, Mapping):
            return result
        raise VirtualBackendOperationError(
            f"Virtual backend API get returned an invalid payload for {model_class.__name__}."
        )

    async def list(
        self,
        model_class: type[Model],
        query: QuerySpec,
    ) -> Sequence[Mapping[str, object]]:
        url = self.query_url(self.resource_url(model_class), query)
        try:
            result = await self.http_get(url)
        except Exception as exc:
            raise VirtualBackendOperationError(
                f"Virtual backend API list failed for {model_class.__name__}."
            ) from exc
        if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)):
            return list(result)
        raise VirtualBackendOperationError(
            f"Virtual backend API list returned an invalid payload for {model_class.__name__}."
        )

    async def create(
        self,
        model_class: type[Model],
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        url = self.resource_url(model_class)
        try:
            result = await self.http_post(url, data)
        except Exception as exc:
            raise VirtualBackendOperationError(
                f"Virtual backend API create failed for {model_class.__name__}."
            ) from exc
        if isinstance(result, Mapping):
            return result
        raise VirtualBackendOperationError(
            f"Virtual backend API create returned an invalid payload for {model_class.__name__}."
        )

    async def update(
        self,
        model_class: type[Model],
        primary_key: object,
        data: Mapping[str, object],
    ) -> Mapping[str, object]:
        url = self.item_url(model_class, primary_key)
        try:
            result = await self.http_patch(url, data)
        except Exception as exc:
            raise VirtualBackendOperationError(
                f"Virtual backend API update failed for {model_class.__name__}."
            ) from exc
        if isinstance(result, Mapping):
            return result
        raise VirtualBackendOperationError(
            f"Virtual backend API update returned an invalid payload for {model_class.__name__}."
        )

    async def delete(
        self,
        model_class: type[Model],
        primary_key: object,
    ) -> None:
        url = self.item_url(model_class, primary_key)
        try:
            await self.http_delete(url)
        except Exception as exc:
            raise VirtualBackendOperationError(
                f"Virtual backend API delete failed for {model_class.__name__}."
            ) from exc
