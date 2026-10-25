from __future__ import annotations

import re
from typing import Any, Self
from urllib.parse import quote, urlsplit

import httpx


class SupabaseError(RuntimeError):
    def __init__(self, status: int, code: str = "provider_error"):
        self.status = status
        self.code = code
        # Do not expose raw response bodies, request URLs, tokens or source text.
        super().__init__(f"Supabase request failed ({status}, {code})")


class SupabaseClient:
    """Actual HTTP client. An injected transport is explicitly a test facility."""

    def __init__(self, url: str, key: str, *, access_token: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 30):
        if not url or not key:
            raise ValueError("SUPABASE_URL and an explicit Supabase key are required")
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError("invalid Supabase URL")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
            raise ValueError("Supabase URL must use HTTPS (loopback development excepted)")
        headers = {"apikey": key}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        elif not key.startswith(("sb_secret_", "sb_publishable_")):
            headers["Authorization"] = f"Bearer {key}"
        self._http = httpx.AsyncClient(base_url=url.rstrip("/"), timeout=timeout, transport=transport, headers=headers)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        # Mutations are intentionally not retried here: a network timeout can mean
        # the server committed. The caller resumes using its durable idempotency key.
        response = await self._http.request(method, path, **kwargs)
        if response.is_error:
            try:
                code = str(response.json().get("code", "provider_error"))
            except (ValueError, AttributeError):
                code = "provider_error"
            raise SupabaseError(response.status_code, code if re.fullmatch(r"[\w-]{1,64}", code) else "provider_error")
        return response

    async def rpc(self, name: str, arguments: dict[str, Any]) -> Any:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("invalid RPC name")
        response = await self._request("POST", f"/rest/v1/rpc/{name}", json=arguments)
        return response.json() if response.content else None

    async def select(self, table: str, *, filters: dict[str, str], columns: str = "*", limit: int = 100) -> list[dict[str, Any]]:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", table):
            raise ValueError("invalid table")
        response = await self._request("GET", f"/rest/v1/{table}", params={"select": columns, "limit": str(min(limit, 1000)), **filters})
        return response.json()

    async def insert(self, table: str, values: dict[str, Any], *, upsert: bool = False,
                     on_conflict: str | None = None) -> list[dict[str, Any]]:
        """Trusted service adapter only; never expose this method as an actor tool."""
        if not re.fullmatch(r"[a-z][a-z0-9_]*", table):
            raise ValueError("invalid table")
        headers = {"Prefer": "return=representation" + (",resolution=merge-duplicates" if upsert else "")}
        response = await self._request("POST", f"/rest/v1/{table}", json=values, headers=headers,
                                       params={"on_conflict": on_conflict} if on_conflict else {})
        return response.json()

    async def update(self, table: str, values: dict[str, Any], *, filters: dict[str, str]) -> list[dict[str, Any]]:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", table) or not filters or not values:
            raise ValueError("table, update values and explicit filters required")
        response = await self._request("PATCH", f"/rest/v1/{table}", params=filters, json=values,
                                       headers={"Prefer": "return=representation"})
        return response.json()

    async def upload(self, bucket: str, path: str, content: bytes, content_type: str) -> None:
        await self._request("POST", f"/storage/v1/object/{quote(bucket, safe='')}/{quote(path, safe='/')}",
                            content=content, headers={"Content-Type": content_type, "x-upsert": "false"})

    async def download(self, bucket: str, path: str) -> bytes:
        response = await self._request("GET", f"/storage/v1/object/authenticated/{quote(bucket, safe='')}/{quote(path, safe='/')}")
        return response.content
