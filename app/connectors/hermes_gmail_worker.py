"""Private, single-request Google Workspace bridge; only stdlib imports at startup.

The parent supplies secrets on stdin and owns this process's temporary profile.
Never invoke the upstream CLI, gws, installers, or the Hermes agent/plugin loader.
"""

from __future__ import annotations

import contextlib
import hmac
import importlib.util
import io
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URIS = {
    "https://accounts.google.com/o/oauth2/auth",
    "https://accounts.google.com/o/oauth2/v2/auth",
}
REDIRECT_URI = "http://localhost:1"
PENDING_TTL_SECONDS = 600
MAX_INPUT_BYTES = 262_144
MAX_OUTPUT_BYTES = 16_000_000


class BridgeFailure(Exception):
    """Contains only a fixed safe failure code, never upstream text."""


def _text(value, *, maximum=4096):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise BridgeFailure("invalid_request")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise BridgeFailure("invalid_request")
    return value


def validate_client(value):
    if not isinstance(value, dict) or set(value) != {"installed"}:
        raise BridgeFailure("invalid_desktop_client")
    client = value["installed"]
    allowed = {
        "client_id",
        "client_secret",
        "auth_uri",
        "token_uri",
        "redirect_uris",
        "project_id",
        "auth_provider_x509_cert_url",
    }
    if not isinstance(client, dict) or set(client) - allowed:
        raise BridgeFailure("invalid_desktop_client")
    if not re.fullmatch(
        r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", str(client.get("client_id", ""))
    ):
        raise BridgeFailure("invalid_desktop_client")
    _text(client.get("client_secret"))
    if client.get("auth_uri") not in AUTH_URIS or client.get("token_uri") != TOKEN_URI:
        raise BridgeFailure("invalid_oauth_endpoint")
    redirects = client.get("redirect_uris")
    if (
        not isinstance(redirects, list)
        or not redirects
        or any(
            uri not in {"http://localhost", "http://127.0.0.1", REDIRECT_URI} for uri in redirects
        )
    ):
        raise BridgeFailure("invalid_desktop_client")
    if (
        "auth_provider_x509_cert_url" in client
        and client["auth_provider_x509_cert_url"] != "https://www.googleapis.com/oauth2/v1/certs"
    ):
        raise BridgeFailure("invalid_oauth_endpoint")
    if "project_id" in client:
        _text(client["project_id"], maximum=256)
    return {"installed": dict(client)}


def validate_token(value):
    allowed = {
        "type",
        "client_id",
        "client_secret",
        "refresh_token",
        "token",
        "token_uri",
        "scopes",
        "expiry",
        "rapt_token",
        "universe_domain",
        "account",
    }
    if (
        not isinstance(value, dict)
        or set(value) - allowed
        or value.get("type") != "authorized_user"
    ):
        raise BridgeFailure("invalid_credentials")
    if (
        value.get("token_uri") != TOKEN_URI
        or value.get("universe_domain", "googleapis.com") != "googleapis.com"
    ):
        raise BridgeFailure("invalid_oauth_endpoint")
    if value.get("scopes") != [READ_SCOPE]:
        raise BridgeFailure("invalid_gmail_scope")
    if not re.fullmatch(
        r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", str(value.get("client_id", ""))
    ):
        raise BridgeFailure("invalid_credentials")
    for name in ("client_secret", "refresh_token", "token"):
        _text(value.get(name), maximum=32_768)
    for name in ("rapt_token", "account"):
        if value.get(name):
            _text(value[name], maximum=32_768)
    if "expiry" in value:
        try:
            datetime.fromisoformat(_text(value["expiry"], maximum=64))
        except ValueError:
            raise BridgeFailure("invalid_credentials") from None
    return dict(value)


def validate_pending(pending, *, now=None):
    if not isinstance(pending, dict) or set(pending) != {
        "state",
        "code_verifier",
        "redirect_uri",
        "created_at",
    }:
        raise BridgeFailure("invalid_pending_authorization")
    if pending.get("redirect_uri") != REDIRECT_URI:
        raise BridgeFailure("invalid_pending_authorization")
    _text(pending.get("state"), maximum=512)
    if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", str(pending.get("code_verifier", ""))):
        raise BridgeFailure("invalid_pending_authorization")
    created = pending.get("created_at")
    current = time.time() if now is None else now
    if type(created) not in (float, int) or not 0 <= current - created <= PENDING_TTL_SECONDS:
        raise BridgeFailure("expired_pending_authorization")
    return dict(pending)


def validate_callback(pending, callback):
    pending = validate_pending(pending)
    parsed = urlsplit(_text(callback, maximum=16_384))
    expected = urlsplit(REDIRECT_URI)
    if (
        (parsed.scheme, parsed.netloc)
        != (
            expected.scheme,
            expected.netloc,
        )
        or parsed.path not in {"", "/"}
        or parsed.fragment
    ):
        raise BridgeFailure("invalid_oauth_callback")
    params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=16)
    if set(params) - {"code", "state", "scope", "authuser", "prompt", "hd", "iss"}:
        raise BridgeFailure("invalid_oauth_callback")
    if (
        any(len(items) != 1 for items in params.values())
        or not params.get("code")
        or not params.get("state")
    ):
        raise BridgeFailure("invalid_oauth_callback")
    _text(params["code"][0], maximum=8192)
    if not hmac.compare_digest(params["state"][0], pending["state"]):
        raise BridgeFailure("oauth_state_mismatch")
    if "scope" in params and params["scope"][0].split() != [READ_SCOPE]:
        raise BridgeFailure("invalid_gmail_scope")
    if "iss" in params and params["iss"] != ["https://accounts.google.com"]:
        raise BridgeFailure("invalid_oauth_endpoint")
    return pending


def validate_get(arguments):
    if not isinstance(arguments, dict) or set(arguments) - {"path", "params"}:
        raise BridgeFailure("invalid_gmail_route")
    path = arguments.get("path")
    params = arguments.get("params")
    if params is None:
        params = {}
    if not isinstance(path, str) or not isinstance(params, dict):
        raise BridgeFailure("invalid_gmail_route")
    if path in {"/profile", "/labels"}:
        allowed = set()
    elif path == "/messages":
        allowed = {"q", "maxResults", "labelIds", "pageToken", "includeSpamTrash"}
    elif path == "/history":
        allowed = {"startHistoryId", "labelId", "maxResults", "pageToken", "historyTypes"}
    elif re.fullmatch(r"/messages/[A-Za-z0-9]+", path):
        allowed = {"format", "metadataHeaders"}
    elif re.fullmatch(r"/messages/[A-Za-z0-9]+/attachments/[A-Za-z0-9_-]+", path):
        allowed = set()
    else:
        raise BridgeFailure("invalid_gmail_route")
    if set(params) - allowed:
        raise BridgeFailure("invalid_gmail_parameters")
    for name, value in params.items():
        if name == "maxResults":
            if type(value) is not int or not 1 <= value <= 500:
                raise BridgeFailure("invalid_gmail_parameters")
        elif name == "includeSpamTrash":
            if type(value) is not bool:
                raise BridgeFailure("invalid_gmail_parameters")
        elif name == "format":
            if value not in {"full", "metadata", "minimal", "raw"}:
                raise BridgeFailure("invalid_gmail_parameters")
        elif name == "historyTypes":
            if (
                not isinstance(value, list)
                or not value
                or any(
                    v not in {"messageAdded", "messageDeleted", "labelAdded", "labelRemoved"}
                    for v in value
                )
            ):
                raise BridgeFailure("invalid_gmail_parameters")
        elif name in {"labelIds", "metadataHeaders"} and isinstance(value, list):
            if not 1 <= len(value) <= 100:
                raise BridgeFailure("invalid_gmail_parameters")
            for item in value:
                _text(item, maximum=1024)
        else:
            _text(value, maximum=8192 if name == "q" else 2048)
        if name == "startHistoryId" and not str(value).isdigit():
            raise BridgeFailure("invalid_gmail_parameters")
    if path == "/history" and not params.get("startHistoryId"):
        raise BridgeFailure("invalid_gmail_parameters")
    return path, dict(params)


def validate_request(operation, arguments, credentials):
    if operation == "get":
        validate_get(arguments)
        validate_token(credentials)
    elif operation == "auth_begin":
        if arguments != {}:
            raise BridgeFailure("invalid_request")
        validate_client(credentials)
    elif operation == "auth_finish":
        if not isinstance(arguments, dict) or set(arguments) != {"pending", "callback_url"}:
            raise BridgeFailure("invalid_request")
        validate_client(credentials)
        validate_callback(arguments["pending"], arguments["callback_url"])
    else:
        raise BridgeFailure("invalid_operation")


def _write_secret(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        json.dump(value, target)


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _no_install():
    raise BridgeFailure("google_dependencies_missing")


def _check_granted_scopes(credentials):
    # to_json() can retain requested scopes even when the response says otherwise.
    granted = getattr(credentials, "granted_scopes", None)
    if granted is not None and list(granted) != [READ_SCOPE]:
        raise BridgeFailure("invalid_gmail_scope")


def _load_upstream(source):
    scripts = source / "skills/productivity/google-workspace/scripts"
    # Only this explicit trusted directory is importable; no entire Hermes runtime,
    # user site-packages, current directory, gws, or plugin discovery is needed.
    sys.path.insert(0, str(scripts))
    setup = _load_module("finance_google_workspace_setup", scripts / "setup.py")
    setup.SCOPES = [READ_SCOPE]
    setup.install_deps = _no_install
    setup._ensure_deps()  # Exact upstream dependency pins, with installs prohibited.
    api = _load_module("finance_google_workspace_api", scripts / "google_api.py")
    api.SCOPES = [READ_SCOPE]
    upstream_get_credentials = api.get_credentials

    def readonly_credentials():
        credentials = upstream_get_credentials()
        _check_granted_scopes(credentials)
        api._finance_credentials = credentials
        return credentials

    api.get_credentials = readonly_credentials
    return setup, api


def _gmail_get(api, arguments):
    path, params = validate_get(arguments)
    users = api.build_service("gmail", "v1").users()
    if path == "/profile":
        call = users.getProfile(userId="me")
    elif path == "/labels":
        call = users.labels().list(userId="me")
    elif path == "/messages":
        call = users.messages().list(userId="me", **params)
    elif path == "/history":
        call = users.history().list(userId="me", **params)
    else:
        parts = path.split("/")
        if len(parts) == 3:
            call = users.messages().get(userId="me", id=parts[2], **params)
        else:
            call = users.messages().attachments().get(userId="me", messageId=parts[2], id=parts[4])
    return call.execute(num_retries=0)


class _BoundedCapture(io.StringIO):
    def write(self, value):
        if self.tell() + len(value) > 32_768:
            raise BridgeFailure("upstream_output_limit")
        return super().write(value)


def handle_request(request):
    operation, arguments, credentials = (
        request.get(k) for k in ("operation", "arguments", "credentials")
    )
    validate_request(operation, arguments, credentials)
    source = Path(request["source"])
    profile = Path(os.environ["HERMES_HOME"])
    with (
        open(os.devnull, "w") as quiet,
        contextlib.redirect_stdout(quiet),
        contextlib.redirect_stderr(quiet),
    ):
        setup, api = _load_upstream(source)
        if operation == "get":
            _write_secret(profile / "google_token.json", validate_token(credentials))
            data = _gmail_get(api, arguments)
            used_credentials = getattr(api, "_finance_credentials", None)
            if used_credentials is not None:
                # AuthorizedHttp may refresh during execute() after a provider 401,
                # in addition to the explicit expiry refresh in get_credentials().
                _check_granted_scopes(used_credentials)
                token = json.loads(used_credentials.to_json())
                token.setdefault("type", "authorized_user")
            else:
                token = json.loads((profile / "google_token.json").read_text())
            token = validate_token(token)
            if (
                token["client_id"] != credentials["client_id"]
                or token["client_secret"] != credentials["client_secret"]
            ):
                raise BridgeFailure("invalid_provider_response")
            if not isinstance(data, dict):
                raise BridgeFailure("invalid_provider_response")
            result = {"data": data}
            if token != credentials:
                result["credentials"] = token
            return result
        _write_secret(profile / "google_client_secret.json", validate_client(credentials))
        # Upstream creates these with write_text; restrictive umask preserves 0600.
        if operation == "auth_begin":
            capture = _BoundedCapture()
            with contextlib.redirect_stdout(capture):
                setup.get_auth_url()
            authorization_url = capture.getvalue().strip()
            pending = json.loads((profile / "google_oauth_pending.json").read_text())
            pending["created_at"] = time.time()
            validate_pending(pending)
            parsed = urlsplit(authorization_url)
            params = parse_qs(parsed.query)
            if (
                parsed.scheme + "://" + parsed.netloc + parsed.path not in AUTH_URIS
                or params.get("scope") != [READ_SCOPE]
                or params.get("state") != [pending["state"]]
                or params.get("redirect_uri") != [REDIRECT_URI]
                or params.get("client_id") != [credentials["installed"]["client_id"]]
                or params.get("code_challenge_method") != ["S256"]
            ):
                raise BridgeFailure("invalid_provider_response")
            return {"authorization_url": authorization_url, "pending": pending}
        _write_secret(profile / "google_oauth_pending.json", arguments["pending"])
        setup.exchange_auth_code(arguments["callback_url"])
        token = validate_token(json.loads((profile / "google_token.json").read_text()))
        client = credentials["installed"]
        if (
            token["client_id"] != client["client_id"]
            or token["client_secret"] != client["client_secret"]
        ):
            raise BridgeFailure("invalid_provider_response")
        return {"credentials": token}


def main():
    os.umask(0o077)
    request = {}
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise BridgeFailure("request_size_limit")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise BridgeFailure("invalid_request")
        result = handle_request(request)
        output = json.dumps({"result": result}, separators=(",", ":"), allow_nan=False)
        if len(output.encode()) > MAX_OUTPUT_BYTES:
            raise BridgeFailure("response_size_limit")
    except BridgeFailure as error:
        output = json.dumps({"error": str(error)})
    except BaseException as error:  # noqa: BLE001 -- no upstream bodies or exceptions cross the boundary.
        status = getattr(getattr(error, "resp", None), "status", None)
        status = status if type(status) is int and 400 <= status <= 599 else None
        operation = request.get("operation") if isinstance(request, dict) else None
        output = json.dumps(
            {
                "error": "google_oauth" if operation in {"auth_begin", "auth_finish"} else "gmail",
                "status": status,
            }
        )
    sys.stdout.write(output + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
