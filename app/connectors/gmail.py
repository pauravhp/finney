"""Live Gmail intake with explicit scope, durable cursor semantics and safe errors.

The caller persists returned evidence/cursor atomically only after a complete scan.
This connector cannot send email or modify the director's mailbox.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

import httpx

from .errors import ConnectionRequired, ProviderError

GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


class HistoryExpired(ProviderError):
    def __init__(self):
        super().__init__("gmail_history", 404)


class ScanLimitReached(RuntimeError):
    """No cursor may advance when an intake scan is incomplete."""


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._hidden += 1
        elif tag in ("br", "p", "div", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._hidden = max(0, self._hidden - 1)

    def handle_data(self, data):
        if not self._hidden:
            self.parts.append(data)


def decode_body(value: str) -> bytes:
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid Gmail body encoding") from exc


def parse_message(message: dict[str, Any]) -> dict[str, Any]:
    """Preserve source identities; never interpret email instructions as authority."""
    payload = message.get("payload", {})
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}
    plain: list[str] = []
    html: list[str] = []
    attachments: list[dict[str, Any]] = []

    def walk(part: dict):
        body = part.get("body", {})
        mime = part.get("mimeType", "")
        if part.get("filename") or body.get("attachmentId"):
            attachments.append(
                {
                    "filename": part.get("filename", ""),
                    "mime_type": mime,
                    "attachment_id": body.get("attachmentId"),
                    "size": body.get("size", 0),
                    "inline_data": body.get("data"),
                }
            )
        elif body.get("data") and mime in ("text/plain", "text/html"):
            text = decode_body(body["data"]).decode("utf-8", errors="replace")
            (plain if mime == "text/plain" else html).append(text)
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    if plain:
        text = "\n".join(plain)
    else:
        parser = _TextOnly()
        parser.feed("\n".join(html))
        text = "".join(parser.parts)
    evidence = {
        "provider": "gmail",
        "external_id": message["id"],
        "thread_id": message.get("threadId"),
        "history_id": str(message.get("historyId", "")),
        "received_at_ms": message.get("internalDate"),
        "headers": {k: headers.get(k, "") for k in ("from", "to", "subject", "date", "message-id")},
        "text": text,
        "attachments": attachments,
        "evidence_state": "reported",
    }
    # Message body, not label/history changes, defines document revision identity.
    stable = {k: v for k, v in evidence.items() if k != "history_id"}
    evidence["content_hash"] = hashlib.sha256(
        json.dumps(stable, sort_keys=True).encode()
    ).hexdigest()
    return evidence


@dataclass(frozen=True)
class OAuthAttempt:
    authorization_url: str = field(repr=False)
    state: str = field(repr=False)
    verifier: str = field(repr=False)


class GmailOAuth:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        if not client_id or not client_secret:
            raise ConnectionRequired("Configure the dedicated Gmail OAuth client")
        self.client_id = client_id
        self._secret = client_secret
        self.redirect_uri = redirect_uri

    def begin(self) -> OAuthAttempt:
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": GMAIL_READ_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return OAuthAttempt(
            "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params), state, verifier
        )

    async def exchange(self, client: httpx.AsyncClient, *, code: str, verifier: str) -> dict:
        return await self._token(
            client,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": verifier,
            },
        )

    async def refresh(self, client: httpx.AsyncClient, refresh_token: str) -> dict:
        return await self._token(
            client, {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def _token(self, client: httpx.AsyncClient, params: dict) -> dict:
        try:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    **params,
                    "client_id": self.client_id,
                    "client_secret": self._secret,
                },
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise ProviderError("google_oauth", retryable=True) from exc
        if response.status_code != 200:
            raise ProviderError(
                "google_oauth", response.status_code, retryable=response.status_code >= 500
            )
        data = response.json()
        if not data.get("access_token"):
            raise ProviderError("google_oauth", response.status_code)
        return data


@dataclass
class SyncBatch:
    messages: list[dict]
    history_id: str
    deleted_ids: list[str] = field(default_factory=list)


class GmailClient:
    def __init__(self, client: httpx.AsyncClient, access_token: str):
        if not access_token:
            raise ConnectionRequired("Director must connect the event mailbox")
        self._client = client
        self._headers = {"Authorization": "Bearer " + access_token}

    async def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            response = await self._client.get(
                GMAIL_BASE_URL + path, params=params, headers=self._headers, follow_redirects=False
            )
        except httpx.HTTPError as exc:
            raise ProviderError("gmail", retryable=True) from exc
        if response.status_code == 404 and path == "/history":
            raise HistoryExpired()
        if response.status_code != 200:
            raise ProviderError(
                "gmail",
                response.status_code,
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        return response.json()

    async def profile(self) -> dict:
        return await self._get("/profile")

    async def read_message(self, message_id: str) -> dict:
        if not message_id.isalnum():
            raise ValueError("Invalid Gmail message identity")
        return parse_message(await self._get(f"/messages/{message_id}", {"format": "full"}))

    async def attachment(
        self, message_id: str, attachment_id: str, *, max_bytes=10_000_000
    ) -> bytes:
        if not message_id.isalnum() or not all(c.isalnum() or c in "-_" for c in attachment_id):
            raise ValueError("Invalid Gmail attachment identity")
        data = await self._get(f"/messages/{message_id}/attachments/{attachment_id}")
        if int(data.get("size", 0)) > max_bytes:
            raise ValueError("Attachment exceeds intake size limit")
        value = decode_body(data["data"])
        if len(value) > max_bytes:
            raise ValueError("Attachment exceeds intake size limit")
        return value

    async def full_sync(
        self, *, query: str, label_id: str | None = None, max_messages: int = 200
    ) -> SyncBatch:
        if not query.strip():
            raise ValueError("Explicit scoped Gmail query is required")
        # Capture cursor before listing; subsequent history sync catches concurrent arrivals.
        cursor = str((await self.profile())["historyId"])
        ids: list[str] = []
        page: str | None = None
        while True:
            params = {"q": query, "maxResults": min(max_messages, 100)}
            if label_id:
                params["labelIds"] = label_id
            if page:
                params["pageToken"] = page
            data = await self._get("/messages", params)
            ids.extend(m["id"] for m in data.get("messages", []))
            page = data.get("nextPageToken")
            if len(ids) > max_messages or (page and len(ids) >= max_messages):
                raise ScanLimitReached("Narrow intake query; cursor was not advanced")
            if not page:
                break
        messages = []
        for mid in dict.fromkeys(ids):
            raw = await self._get(f"/messages/{mid}", {"format": "full"})
            if label_id and label_id not in raw.get("labelIds", []):
                continue
            messages.append(parse_message(raw))
        return SyncBatch(messages, cursor)

    async def history_sync(
        self, start_history_id: str, *, label_id: str, max_pages=20
    ) -> SyncBatch:
        if not label_id:
            raise ValueError("Incremental intake requires an explicit finance label")
        page: str | None = None
        changed: set[str] = set()
        deleted: set[str] = set()
        cursor = start_history_id
        for _ in range(max_pages):
            params = {"startHistoryId": start_history_id, "labelId": label_id, "maxResults": 100}
            if page:
                params["pageToken"] = page
            data = await self._get("/history", params)
            cursor = str(data.get("historyId", cursor))
            for entry in data.get("history", []):
                for key in ("messagesAdded", "labelsAdded"):
                    for item in entry.get(key, []):
                        changed.add(item["message"]["id"])
                for item in entry.get("messagesDeleted", []):
                    deleted.add(item["message"]["id"])
            page = data.get("nextPageToken")
            if not page:
                messages = []
                for mid in sorted(changed - deleted):
                    raw = await self._get(f"/messages/{mid}", {"format": "full"})
                    if label_id in raw.get("labelIds", []):
                        messages.append(parse_message(raw))
                return SyncBatch(messages, cursor, sorted(deleted))
        raise ScanLimitReached("History scan incomplete; cursor was not advanced")
