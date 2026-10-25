"""Explicit fixture OAuth transport plus real isolated SQL; no Coinbase writes."""

import base64
import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
import psycopg
import pytest
from cryptography.fernet import Fernet
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_postgres import identity
from test_finance_postgres import (
    state as state,  # noqa: PLC0414 -- pytest fixture registration
)

from app.config import Settings
from app.payments import authorization_connect as oauth

METADATA={"issuer":oauth.SERVER,"authorization_endpoint":oauth.SERVER+"/authorize","token_endpoint":oauth.SERVER+"/token",
    "registration_endpoint":oauth.SERVER+"/register","response_types_supported":["code"],"grant_types_supported":["authorization_code","refresh_token"],
    "code_challenge_methods_supported":["S256"],"token_endpoint_auth_methods_supported":["none"],"scopes_supported":oauth.SCOPES.split()}


class FixtureDB:
    def __init__(self,org,run,user):
        self.org,self.run,self.user=str(org),str(run),str(user)
        self.pending=[]
        self.connections=[]
        self.secret=[]
        self.active=True
        self.demo=False
        self.calls=[]

    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass

    async def select(self,table,**kwargs):
        if table=="memberships": return [{"organization_id":self.org,"user_id":self.user,"role":"director","active":True}] if self.active else []
        if table=="demo_runs": return [{"id":self.run,"organization_id":self.org,"is_demo":self.demo,"status":"active","expires_at":None}]
        if table=="connections": return copy.deepcopy(self.connections)
        if table=="connector_secrets": return copy.deepcopy(self.secret)
        raise AssertionError(table)

    async def insert(self,table,values):
        assert table=="oauth_pending"
        self.pending.append(copy.deepcopy(values))
        return [values]

    async def update(self,table,values,*,filters):
        assert table=="oauth_pending"
        rows=[row for row in self.pending if all(str(row.get(key))==value[3:] for key,value in filters.items() if value.startswith("eq."))
            and row["expires_at"]>filters["expires_at"][3:]]
        for row in rows: row.update(values)
        return copy.deepcopy(rows)

    async def rpc(self,name,args):
        self.calls.append(name)
        if name=="connect_coinbase_wallet":
            assert self.active and not self.demo
            self.secret=[{"organization_id":self.org,"run_id":self.run,"provider":oauth.PROVIDER,"encrypted_token":args["p_encrypted_token"],"updated_at":"2026-01-01T00:00:00+00:00"}]
            self.connections=[{"organization_id":self.org,"run_id":self.run,"provider":oauth.PROVIDER,"status":"connected","data":{"connected_by":self.user}}]
            self.pending=[]
            return {"status":"connected"}
        if name=="claim_coinbase_token_refresh":
            if self.secret[0].get("claim_id"): return {"claimed":False}
            self.secret[0]["claim_id"]=str(uuid4())
            return {"claimed":True,"claim_id":self.secret[0]["claim_id"]}
        if name=="rotate_coinbase_wallet_token":
            assert args["p_refresh_claim_id"]==self.secret[0].pop("claim_id")
            self.secret[0]["encrypted_token"]=args["p_encrypted_token"]
            self.secret[0]["updated_at"]="2026-01-02T00:00:00+00:00"
            return {"status":"refreshed"}
        raise AssertionError(name)


@pytest.fixture
def flow(monkeypatch):
    org,run,user=uuid4(),uuid4(),uuid4()
    settings=Settings(_env_file=None,supabase_url="https://fixture.invalid",supabase_service_role_key="fixture-only-key",
        organization_id=org,run_id=run,finance_token_encryption_key=Fernet.generate_key().decode())
    db=FixtureDB(org,run,user)
    monkeypatch.setattr(oauth,"SupabaseClient",lambda *args,**kwargs:db)
    actual_client=httpx.AsyncClient
    state={"metadata":copy.deepcopy(METADATA),"requests":[],"refreshes":0,"registration_status":201,"token_status":200}
    def handler(request):
        state["requests"].append((request.method,str(request.url),request.content))
        assert request.url.host=="wallet-mcp.coinbase.com"
        if request.url.path.endswith("oauth-authorization-server"): return httpx.Response(200,json=state["metadata"])
        if request.url.path=="/register":
            if state["registration_status"]!=201:
                return httpx.Response(state["registration_status"],json={"error":"invalid_redirect_uri","error_description":"fixture-secret-bearer"})
            return httpx.Response(state["registration_status"],json={"client_id":"fixture-public-client",**json.loads(request.content)})
        assert request.url.path=="/token"
        form=parse_qs(request.content.decode())
        assert form["client_id"]==["fixture-public-client"] and "client_secret" not in form
        if form["grant_type"]==["refresh_token"]:
            state["refreshes"]+=1
            return httpx.Response(state["token_status"],json={"access_token":"fixture-refreshed-token","expires_in":3600,"refresh_token":"fixture-rotated-refresh","scope":oauth.SCOPES})
        assert form["grant_type"]==["authorization_code"] and form["code"]==["fixture-authorization-code"]
        state["verifier"]=form["code_verifier"][0]
        return httpx.Response(state["token_status"],json={"access_token":"fixture-access-token","refresh_token":"fixture-refresh-token","expires_in":3600,"scope":oauth.SCOPES})
    monkeypatch.setattr(oauth.httpx,"AsyncClient",lambda **kwargs:actual_client(transport=httpx.MockTransport(handler),**kwargs))
    return settings,user,db,state


async def connect(flow):
    settings,user,_db,_state=flow
    started=await oauth.begin(settings,user)
    params=parse_qs(urlsplit(started["authorization_url"]).query)
    callback=oauth.REDIRECT_URI+"?"+urlencode({"code":"fixture-authorization-code","state":params["state"][0]})
    result=await oauth.finish(settings,callback)
    return started,result,callback


@pytest.mark.asyncio
async def test_app_owned_begin_complete_encrypts_every_secret_and_never_calls_wallet_tools(flow):
    settings,user,db,state=flow
    started=await oauth.begin(settings,user)
    assert len(db.pending)==1 and "code_verifier" not in json.dumps(db.pending)
    params=parse_qs(urlsplit(started["authorization_url"]).query)
    assert params["redirect_uri"]==[oauth.REDIRECT_URI] and params["code_challenge_method"]==["S256"]
    callback=oauth.REDIRECT_URI+"?"+urlencode({"code":"fixture-authorization-code","state":params["state"][0]})
    result=await oauth.finish(settings,callback)
    assert result=={"status":"connected","auth_backend":"mcp_oauth","wallet_identity_verified":False,"refresh_available":True}
    assert params["code_challenge"]==[base64.urlsafe_b64encode(hashlib.sha256(state["verifier"].encode()).digest()).decode().rstrip("=")]
    assert await oauth.load_access_token(settings)=="fixture-access-token"
    assert "fixture-access-token" not in json.dumps(db.secret) and "fixture-refresh-token" not in json.dumps(db.secret)
    assert not db.pending and all(urlsplit(url).path in {"/.well-known/oauth-authorization-server","/register","/token"} for _,url,_ in state["requests"])
    with pytest.raises(oauth.CoinbaseAuthorizationError,match="already_used"):
        await oauth.finish(settings,callback)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value",[("issuer","https://evil.invalid"),("token_endpoint","https://evil.invalid/token"),("registration_endpoint",None),
    ("code_challenge_methods_supported",["plain"]),("token_endpoint_auth_methods_supported",["client_secret_post"]),("scopes_supported",[])])
async def test_unadvertised_or_wrong_issuer_flow_never_registers(flow,field,value):
    settings,user,db,state=flow
    state["metadata"][field]=value
    with pytest.raises(oauth.CoinbaseAuthorizationError,match="advertised"):
        await oauth.begin(settings,user)
    assert not db.pending and [method for method,_,_ in state["requests"]]==["GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("defect",["revoked_director","public_demo"])
async def test_connection_requires_current_private_director_before_discovery(flow,defect):
    settings,user,db,state=flow
    if defect=="revoked_director": db.active=False
    else: db.demo=True
    with pytest.raises(oauth.CoinbaseAuthorizationError): await oauth.begin(settings,user)
    assert state["requests"]==[]


@pytest.mark.asyncio
async def test_registration_and_token_errors_export_only_safe_codes(flow):
    settings,user,db,state=flow
    state["registration_status"]=400
    with pytest.raises(oauth.CoinbaseAuthorizationError,match="registration_rejected") as failure:
        await oauth.begin(settings,user)
    assert failure.value.status==400 and failure.value.provider_error=="invalid_redirect_uri" and "fixture-secret-bearer" not in str(failure.value)
    state["registration_status"]=201
    started=await oauth.begin(settings,user)
    callback=oauth.REDIRECT_URI+"?"+urlencode({"code":"fixture-authorization-code","state":parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]})
    state["token_status"]=400
    with pytest.raises(oauth.CoinbaseAuthorizationError,match="token_exchange_rejected") as failure:
        await oauth.finish(settings,callback)
    assert "fixture-access-token" not in str(failure.value) and not db.secret
    before=len(state["requests"])
    with pytest.raises(oauth.CoinbaseAuthorizationError,match="already_used"): await oauth.finish(settings,callback)
    assert len(state["requests"])==before


@pytest.mark.asyncio
@pytest.mark.parametrize("url",["https://evil.invalid/callback?code=private-code&state=private-state",oauth.REDIRECT_URI+"?code=x&state=x",
    oauth.REDIRECT_URI+"?error=access_denied",oauth.REDIRECT_URI+"?code=x&state="+"a"*43+"&code=y"])
async def test_callback_validation_rejects_before_token_or_database_claim(flow,url):
    settings,_,_,state=flow
    with pytest.raises(oauth.CoinbaseAuthorizationError): await oauth.finish(settings,url)
    assert not state["requests"]


@pytest.mark.asyncio
async def test_revoked_director_cannot_complete_or_load_an_existing_grant(flow):
    settings,user,db,state=flow
    started=await oauth.begin(settings,user)
    callback=oauth.REDIRECT_URI+"?"+urlencode({"code":"fixture-authorization-code","state":parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]})
    db.active=False
    before=len(state["requests"])
    with pytest.raises(oauth.CoinbaseAuthorizationError,match="current_director"): await oauth.finish(settings,callback)
    assert len(state["requests"])==before
    db.active=True
    await connect(flow)
    db.active=False
    before=len(state["requests"])
    with pytest.raises(oauth.CoinbaseAuthorizationError,match="current_director"): await oauth.load_access_token(settings)
    assert len(state["requests"])==before


def expire(settings,db):
    org,run,cipher=oauth._configuration(settings)
    saved=cipher.open(db.secret[0]["encrypted_token"],organization_id=org,connection_id=run+":"+oauth.PROVIDER)
    saved["expires_at"]=(datetime.now(UTC)-timedelta(seconds=1)).isoformat()
    db.secret[0]["encrypted_token"]=cipher.seal(saved,organization_id=org,connection_id=run+":"+oauth.PROVIDER)


@pytest.mark.asyncio
async def test_expired_token_refreshes_once_and_persists_rotated_credential(flow):
    settings,_,db,state=flow
    await connect(flow)
    expire(settings,db)
    assert await oauth.load_access_token(settings)=="fixture-refreshed-token"
    assert await oauth.load_access_token(settings)=="fixture-refreshed-token"
    assert state["refreshes"]==1 and db.calls[-2:]==["claim_coinbase_token_refresh","rotate_coinbase_wallet_token"]


@pytest.mark.asyncio
async def test_uncertain_refresh_is_not_retried_or_overwritten(flow):
    settings,_,db,state=flow
    await connect(flow)
    expire(settings,db)
    state["token_status"]=503
    with pytest.raises(oauth.CoinbaseAuthorizationError,match="refresh_rejected"): await oauth.load_access_token(settings)
    assert state["refreshes"]==1
    with pytest.raises(oauth.CoinbaseAuthorizationError,match="already_claimed"): await oauth.load_access_token(settings)
    assert state["refreshes"]==1 and "rotate_coinbase_wallet_token" not in db.calls


def sql_director(conn,org,user):
    conn.execute("reset role")
    conn.execute("update memberships set role='director' where organization_id=%s and user_id=%s",(org,user))
    identity(conn,service=True)


def sql_connect(conn,org,run,user,digest=None,redirect_uri=oauth.REDIRECT_URI):
    digest=digest or hashlib.sha256(str(run).encode()).hexdigest()
    conn.execute("insert into oauth_pending(state_hash,organization_id,run_id,provider,user_id,encrypted_verifier,redirect_uri,expires_at) values(%s,%s,%s,%s,%s,'fixture-encrypted-pending',%s,'1970-01-01T00:00:00+00:00')",
        (digest,org,run,oauth.PENDING_PROVIDER,user,redirect_uri))
    return conn.execute("select connect_coinbase_wallet(%s,%s,%s,%s,%s)",(org,run,user,digest,"fixture-ciphertext-"*8)).fetchone()[0]


def test_sql_oauth_commit_is_private_scoped_director_only_and_atomic(state):
    conn,org,run,users=state
    sql_director(conn,org,users[0])
    assert sql_connect(conn,org,run,users[0])["status"]=="connected"
    assert conn.execute("select count(*) from oauth_pending where run_id=%s",(run,)).fetchone()[0]==0
    data=conn.execute("select data from connections where run_id=%s and provider=%s",(run,oauth.PROVIDER)).fetchone()[0]
    assert data["connected_by"]==str(users[0]) and data["wallet_identity_verified"] is False and data["wallet_approval_required"] is True
    with pytest.raises(psycopg.errors.CheckViolation,match="claimed"):
        conn.execute("select connect_coinbase_wallet(%s,%s,%s,%s,%s)",(org,run,users[0],"a"*64,"replacement-fixture-"*8))
    identity(conn,users[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select connect_coinbase_wallet(%s,%s,%s,%s,%s)",(org,run,users[0],"a"*64,"fixture-"*20))
    with pytest.raises(psycopg.errors.InsufficientPrivilege): conn.execute("select encrypted_token from connector_secrets")


@pytest.mark.parametrize("defect",["removed_director","demo","foreign_run"])
def test_sql_oauth_rejects_wrong_authority_without_storing_token(state,defect):
    conn,org,run,users=state
    sql_director(conn,org,users[0])
    if defect=="removed_director": conn.execute("update memberships set active=false where user_id=%s",(users[0],))
    elif defect=="demo": conn.execute("update demo_runs set is_demo=true,owner_user_id=%s where id=%s",(users[0],run))
    else:
        other=uuid4()
        conn.execute("insert into demo_runs(id,organization_id,name) values(%s,%s,'Other event run')",(other,org))
        conn.execute("insert into oauth_pending(state_hash,organization_id,run_id,provider,user_id,encrypted_verifier,redirect_uri,expires_at) values(%s,%s,%s,%s,%s,'fixture',%s,'1970-01-01T00:00:00+00:00')",("a"*64,org,other,oauth.PENDING_PROVIDER,users[0],oauth.REDIRECT_URI))
    with pytest.raises((psycopg.errors.InsufficientPrivilege,psycopg.errors.CheckViolation)):
        if defect=="foreign_run": conn.execute("select connect_coinbase_wallet(%s,%s,%s,%s,%s)",(org,run,users[0],"a"*64,"fixture-ciphertext-"*8))
        else: sql_connect(conn,org,run,users[0])
    assert conn.execute("select count(*) from connector_secrets where run_id=%s",(run,)).fetchone()[0]==0


def test_sql_refresh_claim_race_cas_and_reconnect_prevent_stale_overwrite(database,state):
    conn,org,run,users=state
    sql_director(conn,org,users[0]);sql_connect(conn,org,run,users[0])
    version=conn.execute("select updated_at from connector_secrets where run_id=%s and provider=%s",(run,oauth.PROVIDER)).fetchone()[0]
    def claim(_):
        with psycopg.connect(database,autocommit=True) as worker:
            identity(worker,service=True)
            return worker.execute("select claim_coinbase_token_refresh(%s,%s,%s,%s)",(org,run,users[0],version)).fetchone()[0]
    with ThreadPoolExecutor(2) as pool: claims=list(pool.map(claim,range(2)))
    assert sum(item["claimed"] for item in claims)==1
    won=next(item for item in claims if item["claimed"])
    sql_connect(conn,org,run,users[0],"b"*64)
    with pytest.raises(psycopg.errors.SerializationFailure,match="changed"):
        conn.execute("select rotate_coinbase_wallet_token(%s,%s,%s,%s,%s,%s)",(org,run,users[0],version,won["claim_id"],"stale-ciphertext-"*10))
    assert conn.execute("select refresh_claim_id from connector_secrets where run_id=%s and provider=%s",(run,oauth.PROVIDER)).fetchone()[0] is None
    assert conn.execute("select count(*) from payments where run_id=%s",(run,)).fetchone()[0]==0


def test_sql_refresh_rotation_requires_current_director_and_exact_claim(state):
    conn,org,run,users=state
    sql_director(conn,org,users[0]);sql_connect(conn,org,run,users[0])
    version=conn.execute("select updated_at from connector_secrets where run_id=%s and provider=%s",(run,oauth.PROVIDER)).fetchone()[0]
    claim=conn.execute("select claim_coinbase_token_refresh(%s,%s,%s,%s)",(org,run,users[0],version)).fetchone()[0]
    rotate="select rotate_coinbase_wallet_token(%s,%s,%s,%s,%s,%s)"
    with pytest.raises(psycopg.errors.SerializationFailure):
        conn.execute(rotate,(org,run,users[0],version,uuid4(),"fixture-refreshed-ciphertext-"*5))
    conn.execute("update memberships set active=false where user_id=%s",(users[0],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(rotate,(org,run,users[0],version,claim["claim_id"],"fixture-refreshed-ciphertext-"*5))
    conn.execute("update memberships set active=true where user_id=%s",(users[0],))
    assert conn.execute(rotate,(org,run,users[0],version,claim["claim_id"],"fixture-refreshed-ciphertext-"*5)).fetchone()[0]["status"]=="refreshed"
    saved=conn.execute("select encrypted_token,updated_at,refresh_claim_id from connector_secrets where run_id=%s and provider=%s",(run,oauth.PROVIDER)).fetchone()
    assert saved[0]=="fixture-refreshed-ciphertext-"*5 and saved[1]>version and saved[2] is None


@pytest.mark.asyncio
async def test_hosted_callback_is_pinned_through_registration_claim_and_exchange(flow):
    settings, user, db, transport = flow
    settings.coinbase_redirect_uri = "https://finney-beta.vercel.app/oauth/coinbase/callback"
    started = await oauth.begin(settings, user)
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    assert query["redirect_uri"] == [settings.coinbase_redirect_uri]
    assert db.pending[0]["redirect_uri"] == settings.coinbase_redirect_uri
    with pytest.raises(oauth.CoinbaseAuthorizationError):
        await oauth.finish(settings, oauth.REDIRECT_URI + "?" + urlencode({
            "code": "fixture-authorization-code", "state": query["state"][0]}))
    assert db.pending[0]["expires_at"] != "1970-01-01T00:00:00+00:00"
    result = await oauth.finish(settings, settings.coinbase_redirect_uri + "?" + urlencode({
        "code": "fixture-authorization-code", "state": query["state"][0]}))
    assert result["status"] == "connected"
    exchange = next(body for method, url, body in transport["requests"] if url.endswith("/token"))
    assert parse_qs(exchange.decode())["redirect_uri"] == [settings.coinbase_redirect_uri]
    # A later default-config worker can use the encrypted grant. The registered
    # client retains its original exact redirect; no personal runtime edits.
    settings.coinbase_redirect_uri = oauth.REDIRECT_URI
    assert await oauth.load_access_token(settings) == "fixture-access-token"


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect", [
    "http://finney-beta.vercel.app/oauth/coinbase/callback",
    "https://localhost/oauth/coinbase/callback",
    "https://127.0.0.1/oauth/coinbase/callback",
    "https://private.local/oauth/coinbase/callback",
    "https://user:password@finney-beta.vercel.app/oauth/coinbase/callback",
    "https://finney-beta.vercel.app/oauth/coinbase/callback?next=evil",
    "https://finney-beta.vercel.app/oauth/coinbase/callback#secret",
    "https://finney-beta.vercel.app/somewhere-else",
])
async def test_unsafe_configured_callback_is_rejected_before_provider_or_database_writes(flow, redirect):
    settings, user, db, transport = flow
    settings.coinbase_redirect_uri = redirect
    with pytest.raises(oauth.CoinbaseAuthorizationError, match="public_https_callback"):
        await oauth.begin(settings, user)
    assert not db.pending and not transport["requests"]


@pytest.mark.asyncio
async def test_provider_cannot_replace_registered_hosted_redirect(flow, monkeypatch):
    settings, user, db, _transport = flow
    settings.coinbase_redirect_uri = "https://finney-beta.vercel.app/oauth/coinbase/callback"
    original = oauth._json_request

    async def changed(client, step, method, url, **kwargs):
        response = await original(client, step, method, url, **kwargs)
        if step == "registration":
            response["redirect_uris"] = ["https://other.example.org/oauth/coinbase/callback"]
        return response

    monkeypatch.setattr(oauth, "_json_request", changed)
    with pytest.raises(oauth.CoinbaseAuthorizationError, match="registered_public_client_invalid"):
        await oauth.begin(settings, user)
    assert not db.pending


def test_sql_hosted_callback_preserves_private_scope_claim_and_replay_checks(state):
    conn, org, run, users = state
    sql_director(conn, org, users[0])
    assert sql_connect(conn, org, run, users[0], redirect_uri=
        "https://finney-beta.vercel.app/oauth/coinbase/callback")["status"] == "connected"
    assert conn.execute("select count(*) from oauth_pending where run_id=%s", (run,)).fetchone()[0] == 0
    with pytest.raises(psycopg.errors.CheckViolation, match="claimed"):
        conn.execute("select connect_coinbase_wallet(%s,%s,%s,%s,%s)",
            (org, run, users[0], hashlib.sha256(str(run).encode()).hexdigest(), "fixture-ciphertext-" * 8))


@pytest.mark.parametrize("redirect", [
    "http://example.org/oauth/coinbase/callback",
    "https://user:password@example.org/oauth/coinbase/callback",
    "https://example.org/oauth/coinbase/callback?extra=yes",
])
def test_sql_rejects_non_https_or_ambiguous_hosted_callbacks(state, redirect):
    conn, org, run, users = state
    sql_director(conn, org, users[0])
    with pytest.raises(psycopg.errors.CheckViolation, match="claimed"):
        sql_connect(conn, org, run, users[0], redirect_uri=redirect)
