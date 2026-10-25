"""Fixture SDK/subprocess tests, plus explicitly offline pinned-helper smoke tests.

No test contacts Google, a database, or a model, or uses an actual OAuth grant.
"""

import asyncio
import copy
import importlib.util
import json
import stat
import sys
import time
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from app.config import Settings
from app.connectors import hermes_gmail as bridge
from app.connectors import hermes_gmail_worker as worker
from app.connectors.errors import ConnectionRequired, ProviderError
from app.connectors.gmail import HistoryExpired, ScanLimitReached
from app.models.providers import ModelError


@pytest.fixture
def client_json():
    return {
        "installed": {
            "client_id": "fixture-desktop.apps.googleusercontent.com",
            "client_secret": "fixture-client-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": worker.TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }
    }


@pytest.fixture
def token():
    return {
        "type": "authorized_user",
        "client_id": "fixture-desktop.apps.googleusercontent.com",
        "client_secret": "fixture-client-secret",
        "refresh_token": "fixture-refresh-secret",
        "token": "fixture-access-secret",
        "token_uri": worker.TOKEN_URI,
        "scopes": [worker.READ_SCOPE],
        "expiry": "2040-01-01T00:00:00Z",
    }


@pytest.fixture
def pending():
    return {
        "state": "fixture-state",
        "code_verifier": "f" * 64,
        "redirect_uri": worker.REDIRECT_URI,
        "created_at": time.time(),
    }


@pytest.fixture
def settings():
    return Settings(_env_file=None, finance_hermes_source="", finance_hermes_python="")


@pytest.mark.parametrize(
    "path,params",
    [
        ("https://attacker.invalid/messages", {}),
        ("/messages/../send", {}),
        ("/messages/abc/send", {}),
        ("/messages/abc/attachments/../../token", {}),
        ("/threads", {}),
        ("/messages/abc%2fsend", {}),
        ("/labels", {"body": {}}),
        ("/messages", {"url": "https://attacker.invalid"}),
        ("/messages", {"maxResults": True}),
        ("/messages", {"maxResults": 501}),
        ("/messages", {"includeSpamTrash": "true"}),
        ("/messages/abc", {"format": "send"}),
        ("/history", {}),
        ("/history", {"startHistoryId": "1", "historyTypes": ["send"]}),
    ],
)
def test_only_explicit_readonly_routes_and_params(path, params):
    with pytest.raises(worker.BridgeFailure):
        worker.validate_get({"path": path, "params": params})


@pytest.mark.parametrize(
    "route,params,method,expected",
    [
        ("/profile", {}, "users.getProfile", {"userId": "me"}),
        ("/labels", {}, "users.labels.list", {"userId": "me"}),
        (
            "/messages",
            {"q": "label:finance", "maxResults": 10, "pageToken": "next"},
            "users.messages.list",
            {"userId": "me", "q": "label:finance", "maxResults": 10, "pageToken": "next"},
        ),
        (
            "/messages/abc123",
            {"format": "full"},
            "users.messages.get",
            {"userId": "me", "id": "abc123", "format": "full"},
        ),
        (
            "/history",
            {"startHistoryId": "10", "labelId": "Label_fixture"},
            "users.history.list",
            {"userId": "me", "startHistoryId": "10", "labelId": "Label_fixture"},
        ),
        (
            "/messages/abc123/attachments/fixture_id-1",
            {},
            "users.messages.attachments.get",
            {"userId": "me", "messageId": "abc123", "id": "fixture_id-1"},
        ),
    ],
)
def test_sdk_dispatch_preserves_raw_json_without_cli(route, params, method, expected):
    calls = []

    class SDKFixture:
        def __init__(self, name=""):
            self.name = name

        def __getattr__(self, name):
            return SDKFixture(self.name + "." + name if self.name else name)

        def __call__(self, **kwargs):
            if kwargs:
                calls.append((self.name, kwargs))
            return self

        def execute(self, *, num_retries):
            assert num_retries == 0
            return {"fixtureRaw": {"nested": [1, 2]}, "historyId": "17"}

    def build(api, version):
        assert (api, version) == ("gmail", "v1")
        return SDKFixture()

    raw = worker._gmail_get(SimpleNamespace(build_service=build), {"path": route, "params": params})
    assert raw == {"fixtureRaw": {"nested": [1, 2]}, "historyId": "17"}
    assert calls == [(method, expected)]


@pytest.mark.parametrize(
    "changes",
    [
        {"token_uri": "https://attacker.invalid/token"},
        {"token_uri": "https://oauth2.googleapis.com/token?other=1"},
        {"scopes": [worker.READ_SCOPE, "https://www.googleapis.com/auth/gmail.send"]},
        {"scopes": []},
        {"type": "service_account"},
        {"universe_domain": "attacker.invalid"},
        {"client_secret": "bad\nsecret"},
    ],
)
def test_tokens_cannot_change_endpoint_or_scope(token, changes):
    with pytest.raises(worker.BridgeFailure):
        worker.validate_token({**token, **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"auth_uri": "https://attacker.invalid/auth"},
        {"token_uri": "https://attacker.invalid/token"},
        {"redirect_uris": ["https://attacker.invalid/callback"]},
        {"auth_provider_x509_cert_url": "https://attacker.invalid/certs"},
    ],
)
def test_desktop_endpoints_and_redirects_are_canonical(client_json, changes):
    client_json["installed"].update(changes)
    with pytest.raises(worker.BridgeFailure):
        worker.validate_client(client_json)


def test_web_client_is_rejected(client_json):
    with pytest.raises(worker.BridgeFailure):
        worker.validate_client({"web": client_json["installed"]})


@pytest.mark.parametrize(
    "callback",
    [
        "fixture-code",
        "http://localhost:1?code=fixture-code",
        "http://localhost:1?code=fixture-code&state=wrong",
        "http://localhost:1?code=fixture-code&state=fixture-state&state=fixture-state",
        "https://localhost:1?code=fixture-code&state=fixture-state",
        "http://localhost:1/extra?code=fixture-code&state=fixture-state",
        "http://localhost:2?code=fixture-code&state=fixture-state",
        "http://localhost:1.attacker.invalid?code=fixture-code&state=fixture-state",
        "http://localhost:1?code=fixture-code&state=fixture-state#fragment",
        "http://localhost:1?code=fixture-code&state=fixture-state&scope=gmail.send",
        "http://localhost:1?code=fixture-code&state=fixture-state&iss=https://attacker.invalid",
    ],
)
def test_callback_requires_exact_redirect_state_and_readonly_scope(pending, callback):
    with pytest.raises(worker.BridgeFailure):
        worker.validate_callback(pending, callback)


def test_pending_ttl_and_full_callback_are_required(pending):
    url = (
        worker.REDIRECT_URI
        + "?"
        + urlencode({"code": "fixture-code", "state": pending["state"], "scope": worker.READ_SCOPE})
    )
    assert worker.validate_callback(pending, url) == pending
    assert worker.validate_callback(pending, url.replace(":1?", ":1/?")) == pending
    for created in (time.time() - 601, time.time() + 60, True, float("nan")):
        with pytest.raises(worker.BridgeFailure):
            worker.validate_callback({**pending, "created_at": created}, url)


def test_credentials_files_are_private_and_never_overwritten(tmp_path, token):
    path = tmp_path / "token.json"
    worker._write_secret(path, token)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == token
    with pytest.raises(FileExistsError):
        worker._write_secret(path, token)


def test_worker_returns_refreshed_token_without_logs(tmp_path, monkeypatch, token, capsys):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    refreshed = {**token, "token": "fixture-refreshed-secret"}

    def get(api, arguments):
        print("upstream output containing fixture-access-secret")
        (tmp_path / "google_token.json").write_text(json.dumps(refreshed))
        return {"historyId": "19"}

    monkeypatch.setattr(worker, "_load_upstream", lambda source: (object(), object()))
    monkeypatch.setattr(worker, "_gmail_get", get)
    result = worker.handle_request(
        {
            "source": str(tmp_path),
            "operation": "get",
            "arguments": {"path": "/profile"},
            "credentials": token,
        }
    )
    assert result == {"data": {"historyId": "19"}, "credentials": refreshed}
    assert capsys.readouterr() == ("", "")


def test_worker_auth_uses_upstream_exchange_after_validation(
    tmp_path, monkeypatch, client_json, token, pending, capsys
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    callback = (
        worker.REDIRECT_URI + "?" + urlencode({"code": "fixture-code", "state": pending["state"]})
    )

    def exchange(value):
        assert value == callback
        assert json.loads((tmp_path / "google_oauth_pending.json").read_text()) == pending
        print("fixture upstream token and secret must never escape")
        worker._write_secret(tmp_path / "google_token.json", token)

    monkeypatch.setattr(
        worker,
        "_load_upstream",
        lambda source: (SimpleNamespace(exchange_auth_code=exchange), object()),
    )
    result = worker.handle_request(
        {
            "source": str(tmp_path),
            "operation": "auth_finish",
            "arguments": {"pending": pending, "callback_url": callback},
            "credentials": client_json,
        }
    )
    assert result == {"credentials": token}
    assert capsys.readouterr() == ("", "")


def test_upstream_dependency_check_cannot_install(tmp_path, monkeypatch):
    setup = SimpleNamespace(install_deps=lambda: pytest.fail("installer invoked"))

    def check():
        setup.install_deps()

    setup._ensure_deps = check
    monkeypatch.setattr(worker, "_load_module", lambda name, path: setup)
    monkeypatch.setattr(sys, "path", list(sys.path))
    with pytest.raises(worker.BridgeFailure, match="google_dependencies_missing"):
        worker._load_upstream(tmp_path)


@pytest.mark.parametrize(
    "grants", [[], [worker.READ_SCOPE, "https://www.googleapis.com/auth/gmail.send"]]
)
def test_sdk_actual_grants_are_checked_even_if_serialization_claims_readonly(grants):
    credentials = SimpleNamespace(
        granted_scopes=grants, to_json=lambda: json.dumps({"scopes": [worker.READ_SCOPE]})
    )
    with pytest.raises(worker.BridgeFailure, match="invalid_gmail_scope"):
        worker._check_granted_scopes(credentials)


def test_refresh_during_api_execute_is_returned(tmp_path, monkeypatch, token):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    refreshed = {**token, "token": "fixture-refreshed-during-request"}
    credentials = SimpleNamespace(
        granted_scopes=[worker.READ_SCOPE], to_json=lambda: json.dumps(refreshed)
    )
    api = SimpleNamespace(_finance_credentials=credentials)
    monkeypatch.setattr(worker, "_load_upstream", lambda source: (object(), api))
    monkeypatch.setattr(worker, "_gmail_get", lambda api, arguments: {"historyId": "20"})
    result = worker.handle_request(
        {
            "source": str(tmp_path),
            "operation": "get",
            "arguments": {"path": "/profile"},
            "credentials": token,
        }
    )
    assert result == {"data": {"historyId": "20"}, "credentials": refreshed}


@pytest.fixture
def subprocess_fixture(tmp_path, monkeypatch, settings):
    """Execute fixture scripts through a real process; preserve launch inspection."""
    original = asyncio.create_subprocess_exec
    launches = []
    # These tests execute their own stdlib-only fixture script, not Hermes.
    # Give that explicit fixture a temporary runtime layout so a clean clone
    # need not install the actual Hermes runtime to test subprocess isolation.
    fixture_root = tmp_path / "fixture-application"
    fixture_python = fixture_root / ".runtime/hermes-venv/bin/python"
    fixture_python.parent.mkdir(parents=True)
    fixture_python.symlink_to(Path(sys.executable).resolve())
    monkeypatch.setattr(bridge, "APP_ROOT", fixture_root)
    monkeypatch.setattr(bridge, "verify_source", lambda source: None)

    def create(code, **limits):
        script = tmp_path / "fixture_worker.py"
        script.write_text(code)

        async def launch(*args, **kwargs):
            process = await original(*args[:-1], str(script), **kwargs)
            launches.append((args, kwargs, process))
            return process

        monkeypatch.setattr(bridge.asyncio, "create_subprocess_exec", launch)
        return bridge.HermesGmailRuntime(settings, **limits), launches

    return create


async def test_subprocess_environment_and_cli_have_no_credentials(
    subprocess_fixture, monkeypatch, token
):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "fixture-inherited-secret")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "fixture-inherited-model-key")
    monkeypatch.setenv("PYTHONPATH", "fixture-untrusted-path")
    monkeypatch.setenv("HERMES_HOME", "/fixture/personal/hermes")
    runtime, launches = subprocess_fixture(
        "import json,os,sys\n"
        "payload=json.load(sys.stdin)\n"
        "assert payload['credentials']['token']=='fixture-access-secret'\n"
        "print(json.dumps({'result':{'data':{'env':dict(os.environ),'path':sys.path,'isolated':sys.flags.isolated}}}))\n"
    )
    response = await runtime.request("get", {"path": "/profile"}, token)
    args, kwargs, process = launches[0]
    assert args[1:3] == ("-I", "-B")
    assert "fixture-access-secret" not in repr(args) + repr(kwargs)
    env = response["data"]["env"]
    assert set(env) <= {"PATH", "HOME", "HERMES_HOME", "XDG_CONFIG_HOME", "LANG", "LC_CTYPE"}
    assert env["HOME"] not in response["data"]["path"]
    assert env["HERMES_HOME"] != "/fixture/personal/hermes"
    assert env["PATH"] == "/usr/bin:/bin"
    assert response["data"]["isolated"] == 1
    assert not Path(env["HOME"]).exists()
    assert process.returncode == 0


@pytest.mark.parametrize(
    "status,path,exception,retryable",
    [
        (404, "/history", HistoryExpired, False),
        (404, "/messages/abc", ProviderError, False),
        (429, "/messages", ProviderError, True),
        (503, "/profile", ProviderError, True),
    ],
)
async def test_provider_errors_are_redacted(
    subprocess_fixture, token, status, path, exception, retryable
):
    runtime, launches = subprocess_fixture(
        "import json,sys\njson.load(sys.stdin)\n"
        f"print(json.dumps({{'error':'fixture-secret-error-body','status':{status}}}))\n"
    )
    params = {"startHistoryId": "10"} if path == "/history" else {}
    with pytest.raises(exception) as caught:
        await runtime.request("get", {"path": path, "params": params}, token)
    assert "fixture-secret" not in str(caught.value)
    assert caught.value.retryable is retryable
    assert not Path(launches[0][1]["cwd"]).exists()


async def test_timeout_kills_process_and_removes_profile(subprocess_fixture, token):
    runtime, launches = subprocess_fixture(
        "import json,sys,time\njson.load(sys.stdin)\ntime.sleep(60)\n",
        timeout_seconds=0.05,
    )
    with pytest.raises(ProviderError, match="hermes_gmail_timeout"):
        await runtime.request("get", {"path": "/profile"}, token)
    assert launches[0][2].returncode is not None
    assert not Path(launches[0][1]["cwd"]).exists()


async def test_cancellation_kills_process_and_removes_profile(subprocess_fixture, token):
    runtime, launches = subprocess_fixture(
        "import json,sys,time\njson.load(sys.stdin)\ntime.sleep(60)\n"
    )
    task = asyncio.create_task(runtime.request("get", {"path": "/profile"}, token))
    for _ in range(200):
        if launches:
            break
        await asyncio.sleep(0.005)
    assert launches
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert launches[0][2].returncode is not None
    assert not Path(launches[0][1]["cwd"]).exists()


async def test_output_limit_kills_process_and_removes_profile(subprocess_fixture, token):
    runtime, launches = subprocess_fixture(
        "import json,sys,time\njson.load(sys.stdin)\n"
        "sys.stdout.write('x'*100000);sys.stdout.flush();time.sleep(60)\n",
        max_output_bytes=1024,
    )
    with pytest.raises(ProviderError, match="hermes_gmail_output_limit"):
        await runtime.request("get", {"path": "/profile"}, token)
    assert launches[0][2].returncode is not None
    assert not Path(launches[0][1]["cwd"]).exists()


@pytest.mark.parametrize("response", ["not-json", "[]", '{"result":[]}', '{"result":{"data":[]}}'])
async def test_malformed_protocol_never_exposes_upstream_output(
    subprocess_fixture, token, response
):
    runtime, _ = subprocess_fixture(f"import json,sys\njson.load(sys.stdin)\nprint({response!r})\n")
    with pytest.raises(ProviderError, match="hermes_gmail_protocol"):
        await runtime.request("get", {"path": "/profile"}, token)


async def test_source_mismatch_and_invalid_routes_stop_before_spawn(monkeypatch, settings, token):
    def mismatch(source):
        raise ModelError("fixture source path or secret must not escape")

    async def spawn(*args, **kwargs):
        pytest.fail("unverified source executed")

    monkeypatch.setattr(bridge, "verify_source", mismatch)
    monkeypatch.setattr(bridge.asyncio, "create_subprocess_exec", spawn)
    runtime = bridge.HermesGmailRuntime(settings)
    with pytest.raises(ProviderError, match="hermes_gmail_source"):
        await runtime.request("get", {"path": "/profile"}, token)
    with pytest.raises(ProviderError, match="hermes_gmail_request"):
        await runtime.request("send", {}, token)
    with pytest.raises(ProviderError, match="hermes_gmail_request"):
        await runtime.request("get", {"path": "https://attacker.invalid"}, token)


def test_personal_or_system_runtime_paths_are_rejected(settings):
    settings.finance_hermes_source = "/fixture/personal/hermes"
    with pytest.raises(ConnectionRequired):
        bridge.HermesGmailRuntime(settings)
    settings.finance_hermes_source = ""
    settings.finance_hermes_python = sys.executable
    with pytest.raises(ConnectionRequired):
        bridge.HermesGmailRuntime(settings)


async def test_client_reuses_full_sync_pagination_mime_and_label_filtering(token):
    calls = []
    fresh = {**token, "token": "fixture-refreshed-secret"}

    class RuntimeFixture:
        async def request(self, operation, arguments, credentials):
            calls.append((operation, arguments, copy.deepcopy(credentials)))
            path, params = arguments["path"], arguments.get("params") or {}
            if path == "/profile":
                return {"data": {"historyId": "10"}, "credentials": fresh}
            if path == "/messages":
                assert params["labelIds"] == "Label_fixture"
                if params.get("pageToken") == "next":
                    return {"data": {"messages": [{"id": "def"}]}}
                return {"data": {"messages": [{"id": "abc"}], "nextPageToken": "next"}}
            return {
                "data": {
                    "id": path.rsplit("/", 1)[-1],
                    "labelIds": ["Label_fixture"] if path.endswith("abc") else [],
                    "payload": {"mimeType": "text/plain", "body": {"data": "UmVjZWlwdA"}},
                }
            }

    gmail = bridge.HermesGmailClient(RuntimeFixture(), token)
    batch = await gmail.full_sync(query="label:finance", label_id="Label_fixture")
    assert batch.history_id == "10"
    assert [(m["external_id"], m["text"]) for m in batch.messages] == [("abc", "Receipt")]
    assert calls[1][2] == fresh
    assert gmail.credentials == fresh
    copied = gmail.credentials
    copied["scopes"].append("unwanted")
    assert gmail.credentials["scopes"] == [worker.READ_SCOPE]


async def test_client_preserves_incomplete_scan_gate(token):
    class RuntimeFixture:
        async def request(self, operation, arguments, credentials):
            return {
                "data": {"historyId": "10"}
                if arguments["path"] == "/profile"
                else {"messages": [{"id": "abc"}], "nextPageToken": "next"}
            }

    with pytest.raises(ScanLimitReached):
        await bridge.HermesGmailClient(RuntimeFixture(), token).full_sync(
            query="label:finance", max_messages=1
        )


async def test_offline_pinned_upstream_auth_url_generation(settings, client_json):
    """Actual pinned code + app interpreter, dummy client, no token/network/consent."""
    if not (bridge.APP_ROOT / ".runtime/hermes-venv/bin/python").is_file():
        pytest.skip("application-owned Hermes runtime is not installed")
    runtime = bridge.HermesGmailRuntime(settings)
    paths = list((bridge.APP_ROOT / ".runtime/hermes-venv/lib").glob("python*/site-packages"))
    packages = {
        d.metadata["Name"].lower() for d in metadata.distributions(path=[str(p) for p in paths])
    }
    if (
        not {
            "google-api-python-client",
            "google-auth",
            "google-auth-oauthlib",
            "google-auth-httplib2",
            "httplib2",
            "pyasn1",
        }
        <= packages
    ):
        pytest.skip("application-owned pinned Google dependencies are not installed")
    result = await runtime.request("auth_begin", {}, credentials=client_json)
    assert result["authorization_url"].startswith("https://accounts.google.com/o/oauth2/auth?")
    assert result["pending"]["redirect_uri"] == worker.REDIRECT_URI
    assert result["pending"]["code_verifier"] not in result["authorization_url"]
    assert "fixture-client-secret" not in result["authorization_url"]
    worker.validate_pending(result["pending"])


def test_upstream_modules_import_offline_without_credentials(tmp_path, monkeypatch):
    """Pinned helpers import without touching personal Hermes or any provider."""
    scripts = (
        bridge.APP_ROOT / ".runtime/hermes-source/skills/productivity/google-workspace/scripts"
    )
    if not scripts.is_dir():
        pytest.skip("pinned source not installed")
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.syspath_prepend(str(scripts))
    monkeypatch.delitem(sys.modules, "_hermes_home", raising=False)
    for filename in ("setup.py", "google_api.py"):
        spec = importlib.util.spec_from_file_location(
            "fixture_upstream_" + filename[:-3], scripts / filename
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.TOKEN_PATH == tmp_path / "google_token.json"
    assert list(tmp_path.iterdir()) == []
