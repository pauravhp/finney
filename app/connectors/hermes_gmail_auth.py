"""Director-only consent through the application's isolated Hermes runtime.

Only encrypted, scope-bound pending grants and credentials are persisted. The
caller supplies a Desktop client file explicitly and collects the full callback
URL through hidden terminal input; neither belongs in a chat or ordinary log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from app.config import Settings
from app.storage.supabase import SupabaseClient

from .gmail import GMAIL_READ_SCOPE, GOOGLE_TOKEN_URL
from .hermes_gmail import HermesGmailClient, HermesGmailRuntime
from .hermes_gmail_worker import validate_token
from .tokens import TokenCipher

REDIRECT_URI = "http://localhost:1"
PENDING_PROVIDER = "gmail_hermes"
PENDING_SECONDS = 600
_AUTH_PATHS = {"/o/oauth2/auth", "/o/oauth2/v2/auth"}


def _configuration(settings: Settings) -> tuple[str, str, TokenCipher]:
    if not settings.supabase_url or not settings.backend_key:
        raise ValueError("Supabase configuration is required for mailbox authorization")
    if not settings.organization_id or not settings.run_id:
        raise ValueError("Configure a private organization and event run first")
    _query(settings.finance_gmail_query)
    cipher = TokenCipher(settings.finance_token_encryption_key.get_secret_value())
    return str(settings.organization_id), str(settings.run_id), cipher


def _query(value: str) -> str:
    # One literal label only: Gmail boolean/search syntax must not expand it.
    if not isinstance(value, str) or not re.fullmatch(r"label:[\w./-]+", value):
        raise ValueError("Mailbox intake requires one explicit finance label")
    return value


def _installed_client(value: object) -> dict:
    if (
        not isinstance(value, dict)
        or "web" in value
        or not isinstance(value.get("installed"), dict)
    ):
        raise ValueError("Use a Google Desktop OAuth client JSON file")
    client = value["installed"]
    if any(
        not isinstance(client.get(key), str) or not client[key]
        for key in ("client_id", "client_secret")
    ):
        raise ValueError("The Desktop OAuth client configuration is incomplete")
    auth = urlsplit(client.get("auth_uri", ""))
    if (
        auth.scheme != "https"
        or auth.netloc != "accounts.google.com"
        or auth.path not in _AUTH_PATHS
        or auth.query
        or auth.fragment
        or client.get("token_uri") != GOOGLE_TOKEN_URL
        or not isinstance(client.get("redirect_uris"), list)
        or "http://localhost" not in client["redirect_uris"]
    ):
        raise ValueError("The Desktop OAuth client must use Google's standard endpoints")
    return value


def _read_client(path: Path) -> dict:
    try:
        with Path(path).open("rb") as source:
            content = source.read(65_537)
        if len(content) > 65_536:
            raise ValueError
        value = json.loads(content)
    except (OSError, ValueError, TypeError):
        raise ValueError(
            "Read a valid Desktop OAuth JSON file from the explicit client path"
        ) from None
    return _installed_client(value)


def _one(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key, [])
    if len(values) != 1 or not values[0]:
        raise ValueError("Mailbox authorization response is incomplete")
    return values[0]


def _pending(value: object, *, now: datetime) -> dict:
    if not isinstance(value, dict):
        raise TypeError("Mailbox authorization attempt is invalid")
    if (
        not isinstance(value.get("state"), str)
        or not re.fullmatch(r"[A-Za-z0-9._~-]{20,512}", value["state"])
        or not isinstance(value.get("code_verifier"), str)
        or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", value["code_verifier"])
        or value.get("redirect_uri") != REDIRECT_URI
    ):
        raise ValueError("Mailbox authorization attempt is invalid")
    created = value.get("created_at")
    if (
        isinstance(created, bool)
        or not isinstance(created, (int, float))
        or not math.isfinite(created)
        or not 0 <= now.timestamp() - created < PENDING_SECONDS
    ):
        raise ValueError("Mailbox authorization expired; reconnect")
    return value


def _authorization(result: object, client: dict, *, now: datetime) -> tuple[str, dict]:
    if not isinstance(result, dict) or not isinstance(result.get("authorization_url"), str):
        raise TypeError("Hermes did not return a mailbox authorization URL")
    pending = _pending(result.get("pending"), now=now)
    url = urlsplit(result["authorization_url"])
    if (
        url.scheme != "https"
        or url.netloc != "accounts.google.com"
        or url.path not in _AUTH_PATHS
        or url.fragment
    ):
        raise ValueError("Mailbox authorization must use Google's consent endpoint")
    params = parse_qs(url.query, keep_blank_values=True)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(pending["code_verifier"].encode()).digest())
        .decode()
        .rstrip("=")
    )
    expected = {
        "scope": GMAIL_READ_SCOPE,
        "state": pending["state"],
        "redirect_uri": REDIRECT_URI,
        "client_id": client["installed"]["client_id"],
        "response_type": "code",
        "access_type": "offline",
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if any(_one(params, key) != value for key, value in expected.items()):
        raise ValueError("Mailbox authorization requires Gmail readonly access with PKCE")
    return result["authorization_url"], pending


def _callback(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) > 16_384:
        raise ValueError("Paste the full localhost mailbox authorization URL")
    url = urlsplit(value)
    if (
        url.scheme != "http"
        or url.netloc != "localhost:1"
        or url.path not in {"", "/"}
        or url.fragment
    ):
        raise ValueError("Paste the full localhost mailbox authorization URL")
    params = parse_qs(url.query, keep_blank_values=True, max_num_fields=16)
    if "error" in params:
        raise ValueError("Mailbox authorization was not completed; reconnect")
    if set(params) - {"code", "state", "scope", "authuser", "prompt", "hd", "iss"} or any(
        len(values) != 1 for values in params.values()
    ):
        raise ValueError("Mailbox authorization response is invalid")
    state = _one(params, "state")
    _one(params, "code")
    if not re.fullmatch(r"[A-Za-z0-9._~-]{20,512}", state):
        raise ValueError("Mailbox authorization state is invalid")
    if "scope" in params and _one(params, "scope").split() != [GMAIL_READ_SCOPE]:
        raise ValueError("Mailbox authorization permits only Gmail readonly access")
    if "iss" in params and _one(params, "iss") != "https://accounts.google.com":
        raise ValueError("Mailbox authorization must come from Google")
    return state, hashlib.sha256(state.encode()).hexdigest()


def _credentials(value: object, client: dict) -> dict:
    if (
        not isinstance(value, dict)
        or value.get("type") != "authorized_user"
        or value.get("token_uri") != GOOGLE_TOKEN_URL
        or value.get("scopes") != [GMAIL_READ_SCOPE]
        or value.get("client_id") != client["installed"]["client_id"]
        or value.get("client_secret") != client["installed"]["client_secret"]
        or any(
            not isinstance(value.get(key), str) or not value[key]
            for key in ("token", "refresh_token")
        )
    ):
        raise ValueError("Hermes must return offline Gmail readonly credentials")
    return value


async def _require_director(db: SupabaseClient, org: str, run: str, user: str) -> None:
    members = await db.select(
        "memberships",
        filters={
            "organization_id": "eq." + org,
            "user_id": "eq." + user,
            "role": "eq.director",
            "active": "eq.true",
        },
        limit=1,
    )
    if not any(
        row.get("organization_id") == org
        and row.get("user_id") == user
        and row.get("role") == "director"
        and row.get("active") is True
        for row in members
    ):
        raise ValueError("Only a current director may connect the event mailbox")
    runs = await db.select(
        "demo_runs",
        filters={"organization_id": "eq." + org, "id": "eq." + run},
        limit=1,
    )
    if len(runs) != 1:
        raise ValueError("Use a private active event run for mailbox authorization")
    row = runs[0]
    if (
        row.get("organization_id") != org
        or row.get("id") != run
        or row.get("status") != "active"
        or row.get("is_demo") is not False
    ):
        raise ValueError("Use a private active event run for mailbox authorization")
    if row.get("expires_at") is not None:
        try:
            expiry = datetime.fromisoformat(row["expires_at"])
            valid = expiry.tzinfo is not None and expiry > datetime.now(UTC)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("The private event run expired; reconnect to an active run")


async def begin(settings: Settings, director_user_id: UUID, client_file: Path) -> dict:
    """Create a ten-minute, director/run-bound consent attempt without local tokens."""
    org, run, cipher = _configuration(settings)
    user = str(UUID(str(director_user_id)))
    async with SupabaseClient(settings.supabase_url, settings.backend_key) as db:
        await _require_director(db, org, run, user)
        client = _read_client(client_file)
        result = await HermesGmailRuntime(settings).request("auth_begin", {}, credentials=client)
        now = datetime.now(UTC)
        authorization_url, pending = _authorization(result, client, now=now)
        digest = hashlib.sha256(pending["state"].encode()).hexdigest()
        await db.insert(
            "oauth_pending",
            {
                "state_hash": digest,
                "organization_id": org,
                "run_id": run,
                "provider": PENDING_PROVIDER,
                "user_id": user,
                "encrypted_verifier": cipher.seal(
                    {"client": client, "pending": pending},
                    organization_id=org,
                    connection_id=digest,
                ),
                "redirect_uri": REDIRECT_URI,
                "expires_at": (now + timedelta(seconds=PENDING_SECONDS)).isoformat(),
            },
        )
    return {
        "status": "authorization_required",
        "auth_backend": "hermes",
        "authorization_url": authorization_url,
    }


async def finish(settings: Settings, callback_url: str) -> dict:
    """Consume a callback once and atomically replace the validated connection."""
    org, run, cipher = _configuration(settings)
    state, digest = _callback(callback_url)
    async with SupabaseClient(settings.supabase_url, settings.backend_key) as db:
        rows = await db.update(
            "oauth_pending",
            {"expires_at": "1970-01-01T00:00:00+00:00"},
            filters={
                "state_hash": "eq." + digest,
                "organization_id": "eq." + org,
                "run_id": "eq." + run,
                "provider": "eq." + PENDING_PROVIDER,
                "redirect_uri": "eq." + REDIRECT_URI,
                "expires_at": "gt." + datetime.now(UTC).isoformat(),
            },
        )
        if len(rows) != 1:
            raise ValueError("Mailbox authorization expired or was already used; reconnect")
        attempt = rows[0]
        if (
            attempt.get("state_hash") != digest
            or attempt.get("organization_id") != org
            or attempt.get("run_id") != run
            or attempt.get("provider") != PENDING_PROVIDER
            or attempt.get("redirect_uri") != REDIRECT_URI
        ):
            raise ValueError("Mailbox authorization scope changed; reconnect")
        try:
            user = str(UUID(attempt["user_id"]))
        except (ValueError, TypeError, KeyError):
            raise ValueError("Mailbox authorization director is invalid; reconnect") from None
        await _require_director(db, org, run, user)
        sealed = cipher.open(
            attempt["encrypted_verifier"], organization_id=org, connection_id=digest
        )
        client = _installed_client(sealed.get("client"))
        pending = _pending(sealed.get("pending"), now=datetime.now(UTC))
        if not hmac.compare_digest(pending["state"], state):
            raise ValueError("Mailbox authorization state changed; reconnect")
        runtime = HermesGmailRuntime(settings)
        result = await runtime.request(
            "auth_finish", {"pending": pending, "callback_url": callback_url}, credentials=client
        )
        credentials = _credentials(
            result.get("credentials") if isinstance(result, dict) else None, client
        )
        gmail = HermesGmailClient(runtime, credentials)
        profile = await gmail.profile()
        mailbox = profile.get("emailAddress") if isinstance(profile, dict) else None
        if not isinstance(mailbox, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+", mailbox):
            raise ValueError("Hermes did not return the authorized mailbox profile")
        encrypted = cipher.seal(
            _credentials(gmail.credentials, client),
            organization_id=org,
            connection_id=f"{run}:gmail",
        )
        # The service-only RPC rechecks/locks the director and private run, then
        # commits credentials, cursor resets and notification in one transaction.
        committed = await db.rpc(
            "connect_hermes_gmail",
            {
                "p_organization_id": org,
                "p_run_id": run,
                "p_director_user_id": user,
                "p_encrypted_token": encrypted,
                "p_mailbox": mailbox,
                "p_query": _query(settings.finance_gmail_query),
            },
        )
        if not isinstance(committed, dict) or committed.get("status") != "connected":
            raise RuntimeError("Mailbox connection did not commit")
    return {"status": "connected", "auth_backend": "hermes", "query": settings.finance_gmail_query}


async def import_grant(
    settings: Settings, director_user_id: UUID, token_file: Path, *, expected_mailbox: str
) -> dict:
    """Reuse one explicitly selected grant without writing its source profile.

    No credential discovery or personal-runtime execution occurs. The existing
    grant is copied only into memory, then a fresh isolated runtime verifies it.
    """
    org, run, cipher = _configuration(settings)
    user = str(UUID(str(director_user_id)))
    if not re.fullmatch(r"[^\s@]+@[^\s@]+", expected_mailbox):
        raise ValueError("Expected mailbox address is required")
    async with SupabaseClient(settings.supabase_url, settings.backend_key) as db:
        await _require_director(db, org, run, user)
        descriptor = os.open(token_file, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("The selected grant must be an owner-private regular file")
            content = source.read(65_537)
        if len(content) > 65_536:
            raise ValueError("Selected grant exceeds size limit")
        credentials = validate_token(json.loads(content))
        gmail = HermesGmailClient(HermesGmailRuntime(settings), credentials)
        profile = await gmail.profile()
        mailbox = profile.get("emailAddress")
        if not isinstance(mailbox, str) or mailbox.casefold() != expected_mailbox.casefold():
            raise ValueError("The selected grant belongs to a different mailbox")
        encrypted = cipher.seal(
            validate_token(gmail.credentials), organization_id=org, connection_id=f"{run}:gmail"
        )
        result = await db.rpc(
            "connect_hermes_gmail",
            {"p_organization_id": org, "p_run_id": run, "p_director_user_id": user,
             "p_encrypted_token": encrypted, "p_mailbox": mailbox,
             "p_query": _query(settings.finance_gmail_query)},
        )
        if result.get("status") != "connected":
            raise RuntimeError("Mailbox connection did not commit")
    return {"status": "connected", "auth_backend": "hermes", "query": settings.finance_gmail_query,
            "reused_existing_grant": True, "source_profile_written": False}
