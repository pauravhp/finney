"""Isolated Wallet MCP authorization; never creates wallets or financial requests.

The installed MCP SDK's OAuth types and S256 generator are used with a split
begin/complete lifecycle. Tokens, PKCE secrets and public-client registration are
encrypted in Supabase; no personal MCP configuration or bearer extraction.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

import httpx
from mcp.client.auth.oauth2 import PKCEParameters
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
)
from pydantic import ValidationError

from app.config import Settings
from app.connectors.tokens import TokenCipher
from app.storage.supabase import SupabaseClient

SERVER = "https://wallet-mcp.coinbase.com"
REDIRECT_URI = "http://127.0.0.1:8768/oauth/coinbase/callback"
PROVIDER = "coinbase_wallet"
PENDING_PROVIDER = "coinbase_wallet_oauth"
SCOPES = "agent_wallet:transact agent_wallet:escalate"
PENDING_SECONDS = 600
SAFE_OAUTH_ERRORS = {"invalid_client_metadata", "invalid_redirect_uri", "invalid_scope", "unauthorized_client",
    "invalid_client", "invalid_grant", "access_denied", "unsupported_grant_type", "server_error", "temporarily_unavailable"}


class CoinbaseAuthorizationError(ValueError):
    """Only a bounded code/status, never a provider body, code or token."""

    def __init__(self, code: str, status: int | None = None, provider_error: str | None = None):
        self.code, self.status, self.provider_error = code, status, provider_error
        super().__init__(code)


def _configuration(settings: Settings) -> tuple[str, str, TokenCipher]:
    if not settings.supabase_url or not settings.backend_key or not settings.organization_id or not settings.run_id:
        raise CoinbaseAuthorizationError("coinbase_private_event_configuration_required")
    if settings.coinbase_mcp_url and settings.coinbase_mcp_url.rstrip("/") != SERVER:
        raise CoinbaseAuthorizationError("coinbase_official_wallet_mcp_required")
    return str(settings.organization_id), str(settings.run_id), TokenCipher(settings.finance_token_encryption_key.get_secret_value())


async def _require_director(db: SupabaseClient, org: str, run: str, user: str) -> None:
    rows = await db.select("demo_runs", filters={"organization_id":"eq."+org,"id":"eq."+run}, limit=1)
    if len(rows) != 1 or any(rows[0].get(key) != value for key,value in
        (("organization_id",org),("id",run),("status","active"),("is_demo",False))):
        raise CoinbaseAuthorizationError("coinbase_private_active_event_required")
    if rows[0].get("expires_at") is not None:
        try:
            expiry = datetime.fromisoformat(rows[0]["expires_at"])
            valid = expiry.tzinfo is not None and expiry > datetime.now(UTC)
        except (ValueError,TypeError):
            valid = False
        if not valid:
            raise CoinbaseAuthorizationError("coinbase_private_active_event_required")
    members = await db.select("memberships", filters={"organization_id":"eq."+org,"user_id":"eq."+user,"role":"eq.director","active":"eq.true"}, limit=1)
    if not any(row.get("organization_id")==org and row.get("user_id")==user and row.get("role")=="director" and row.get("active") is True for row in members):
        raise CoinbaseAuthorizationError("coinbase_current_director_required")


async def _json_request(client: httpx.AsyncClient, step: str, method: str, url: str, **kwargs) -> dict:
    if url not in {SERVER+"/register",SERVER+"/token",SERVER+"/.well-known/oauth-authorization-server"}:
        raise CoinbaseAuthorizationError("coinbase_oauth_endpoint_not_allowed")
    try:
        response = await client.request(method,url,**kwargs)
    except httpx.HTTPError:
        raise CoinbaseAuthorizationError("coinbase_oauth_"+step+"_unavailable") from None
    if response.status_code not in ({200,201} if step=="registration" else {200}):
        try:
            error=response.json().get("error")
            provider_error=error if isinstance(error,str) and error in SAFE_OAUTH_ERRORS else None
        except (ValueError,TypeError,AttributeError):
            provider_error=None
        raise CoinbaseAuthorizationError("coinbase_oauth_"+step+"_rejected",response.status_code,provider_error)
    try:
        if len(response.content)>131072:
            raise ValueError
        result=response.json()
        if not isinstance(result,dict):
            raise TypeError
        return result
    except (ValueError,TypeError):
        raise CoinbaseAuthorizationError("coinbase_oauth_"+step+"_invalid_response") from None


async def _metadata(client: httpx.AsyncClient) -> OAuthMetadata:
    raw=await _json_request(client,"discovery","GET",SERVER+"/.well-known/oauth-authorization-server")
    try:
        metadata=OAuthMetadata.model_validate(raw)
        valid=(str(metadata.issuer).rstrip("/")==SERVER and str(metadata.authorization_endpoint)==SERVER+"/authorize"
            and str(metadata.token_endpoint)==SERVER+"/token" and str(metadata.registration_endpoint)==SERVER+"/register"
            and "S256" in (metadata.code_challenge_methods_supported or [])
            and "none" in (metadata.token_endpoint_auth_methods_supported or [])
            and "authorization_code" in (metadata.grant_types_supported or [])
            and "refresh_token" in (metadata.grant_types_supported or [])
            and "code" in metadata.response_types_supported
            and set(SCOPES.split()).issubset(set(metadata.scopes_supported or [])))
    except (ValidationError,TypeError,AttributeError):
        valid=False
    if not valid:
        raise CoinbaseAuthorizationError("coinbase_advertised_public_pkce_registration_required")
    return metadata


def _client_info(value: dict) -> OAuthClientInformationFull:
    try:
        client=OAuthClientInformationFull.model_validate(value)
        if not client.client_id or len(client.client_id)>512 or client.client_secret or client.token_endpoint_auth_method!="none" \
            or [str(uri) for uri in client.redirect_uris or []]!=[REDIRECT_URI] or client.issuer!=SERVER \
            or set(client.grant_types)!={"authorization_code","refresh_token"} or client.response_types!=["code"] \
            or set((client.scope or "").split())!=set(SCOPES.split()):
            raise ValueError
        return client
    except (ValidationError,ValueError,TypeError):
        raise CoinbaseAuthorizationError("coinbase_registered_public_client_invalid") from None


def _token(value: dict, *, previous_refresh: str | None = None) -> OAuthToken:
    try:
        token=OAuthToken.model_validate(value)
        if not token.access_token or len(token.access_token)>16384 or re.search(r"\s",token.access_token):
            raise ValueError
        if token.refresh_token is not None and (not token.refresh_token or len(token.refresh_token)>16384 or re.search(r"\s",token.refresh_token)):
            raise ValueError
        if value.get("expires_in") is not None and (type(value["expires_in"]) is not int or value["expires_in"]<=0 or value["expires_in"]>31_536_000):
            raise ValueError
        if token.scope is not None and set(token.scope.split())!=set(SCOPES.split()):
            raise ValueError
        return token.model_copy(update={"scope":SCOPES,"refresh_token":token.refresh_token or previous_refresh})
    except (ValidationError,ValueError,TypeError):
        raise CoinbaseAuthorizationError("coinbase_oauth_token_invalid") from None


def _stored(client: OAuthClientInformationFull, token: OAuthToken, user: str) -> dict:
    now=datetime.now(UTC)
    return {"issuer":SERVER,"server_url":SERVER,"director_user_id":user,"client":client.model_dump(mode="json"),
        "token":token.model_dump(mode="json"),"saved_at":now.isoformat(),
        "expires_at":None if token.expires_in is None else (now+timedelta(seconds=token.expires_in)).isoformat()}


def _callback(value: str) -> tuple[str,str,str]:
    if not isinstance(value,str) or len(value)>16384:
        raise CoinbaseAuthorizationError("coinbase_full_loopback_callback_required")
    url=urlsplit(value)
    if (url.scheme,url.netloc,url.path)!=("http","127.0.0.1:8768","/oauth/coinbase/callback") or url.fragment:
        raise CoinbaseAuthorizationError("coinbase_full_loopback_callback_required")
    try:
        params=parse_qs(url.query,keep_blank_values=True,max_num_fields=10)
    except ValueError:
        raise CoinbaseAuthorizationError("coinbase_callback_invalid") from None
    if "error" in params:
        raise CoinbaseAuthorizationError("coinbase_authorization_not_completed")
    if set(params)-{"code","state","iss"} or any(len(values)!=1 for values in params.values()) \
        or not params.get("code",[""])[0] or not re.fullmatch(r"[A-Za-z0-9_-]{40,128}",params.get("state",[""])[0]) \
        or ("iss" in params and params["iss"]!=[SERVER]):
        raise CoinbaseAuthorizationError("coinbase_callback_invalid")
    state=params["state"][0]
    return state,hashlib.sha256(state.encode()).hexdigest(),params["code"][0]


async def begin(settings: Settings, director_user_id: UUID) -> dict:
    """Explicit invocation registers one public client and prepares user consent."""
    org,run,cipher=_configuration(settings)
    user=str(UUID(str(director_user_id)))
    async with SupabaseClient(settings.supabase_url,settings.backend_key) as db:
        await _require_director(db,org,run,user)
        metadata=OAuthClientMetadata(redirect_uris=[REDIRECT_URI],token_endpoint_auth_method="none",
            grant_types=["authorization_code","refresh_token"],response_types=["code"],scope=SCOPES,client_name="Finney finance")
        async with httpx.AsyncClient(follow_redirects=False,timeout=20) as http:
            await _metadata(http)
            request=metadata.model_dump(mode="json",exclude_none=True)
            registered=await _json_request(http,"registration","POST",SERVER+"/register",json=request)
        if registered.get("issuer",SERVER)!=SERVER:
            raise CoinbaseAuthorizationError("coinbase_registered_public_client_invalid")
        client=_client_info({**request,**registered,"issuer":SERVER})
        pkce=PKCEParameters.generate()
        state=secrets.token_urlsafe(32)
        digest=hashlib.sha256(state.encode()).hexdigest()
        now=datetime.now(UTC)
        await _require_director(db,org,run,user)
        pending={"state":state,"code_verifier":pkce.code_verifier,"client":client.model_dump(mode="json"),"created_at":now.timestamp()}
        await db.insert("oauth_pending",{"state_hash":digest,"organization_id":org,"run_id":run,"provider":PENDING_PROVIDER,
            "user_id":user,"encrypted_verifier":cipher.seal(pending,organization_id=org,connection_id=digest),
            "redirect_uri":REDIRECT_URI,"expires_at":(now+timedelta(seconds=PENDING_SECONDS)).isoformat()})
    url=SERVER+"/authorize?"+urlencode({"response_type":"code","client_id":client.client_id,"redirect_uri":REDIRECT_URI,
        "state":state,"code_challenge":pkce.code_challenge,"code_challenge_method":"S256","scope":SCOPES})
    return {"status":"authorization_required","auth_backend":"mcp_oauth","authorization_url":url,
        "next_step":"Authorize your existing Coinbase Wallet, then complete with the full loopback redirect through hidden terminal input."}


async def finish(settings: Settings, callback_url: str) -> dict:
    """Consume callback once, exchange once and atomically commit the grant."""
    org,run,cipher=_configuration(settings)
    state,digest,code=_callback(callback_url)
    async with SupabaseClient(settings.supabase_url,settings.backend_key) as db:
        rows=await db.update("oauth_pending",{"expires_at":"1970-01-01T00:00:00+00:00"},filters={"state_hash":"eq."+digest,
            "organization_id":"eq."+org,"run_id":"eq."+run,"provider":"eq."+PENDING_PROVIDER,"redirect_uri":"eq."+REDIRECT_URI,
            "expires_at":"gt."+datetime.now(UTC).isoformat()})
        if len(rows)!=1:
            raise CoinbaseAuthorizationError("coinbase_authorization_expired_or_already_used")
        attempt=rows[0]
        if any(attempt.get(key)!=value for key,value in (("organization_id",org),("run_id",run),("state_hash",digest),("provider",PENDING_PROVIDER),("redirect_uri",REDIRECT_URI))):
            raise CoinbaseAuthorizationError("coinbase_authorization_scope_changed")
        user=str(UUID(attempt["user_id"]))
        await _require_director(db,org,run,user)
        pending=cipher.open(attempt["encrypted_verifier"],organization_id=org,connection_id=digest)
        created=pending.get("created_at")
        if type(created) not in (int,float) or not math.isfinite(created) or not 0<=datetime.now(UTC).timestamp()-created<PENDING_SECONDS \
            or not isinstance(pending.get("state"),str) or not hmac.compare_digest(pending["state"],state) \
            or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}",str(pending.get("code_verifier",""))):
            raise CoinbaseAuthorizationError("coinbase_authorization_state_invalid")
        client=_client_info(pending.get("client",{}))
        async with httpx.AsyncClient(follow_redirects=False,timeout=20) as http:
            await _metadata(http)
            token=_token(await _json_request(http,"token_exchange","POST",SERVER+"/token",data={"grant_type":"authorization_code",
                "client_id":client.client_id,"code":code,"redirect_uri":REDIRECT_URI,"code_verifier":pending["code_verifier"]}))
        sealed=cipher.seal(_stored(client,token,user),organization_id=org,connection_id=run+":"+PROVIDER)
        result=await db.rpc("connect_coinbase_wallet",{"p_organization_id":org,"p_run_id":run,"p_director_user_id":user,
            "p_pending_state_hash":digest,"p_encrypted_token":sealed})
        if not isinstance(result,dict) or result.get("status")!="connected":
            raise CoinbaseAuthorizationError("coinbase_authorization_not_committed")
    return {"status":"connected","auth_backend":"mcp_oauth","wallet_identity_verified":False,"refresh_available":bool(token.refresh_token)}


async def load_access_token(settings: Settings) -> str | None:
    """Trusted executor only. Refresh is issuer-bound, single-claim and never retried."""
    org,run,cipher=_configuration(settings)
    filters={"organization_id":"eq."+org,"run_id":"eq."+run,"provider":"eq."+PROVIDER}
    async with SupabaseClient(settings.supabase_url,settings.backend_key) as db:
        connections=await db.select("connections",filters=filters,limit=1)
        secrets_rows=await db.select("connector_secrets",filters=filters,limit=1)
        if not connections and not secrets_rows:
            return None
        if len(connections)!=1 or len(secrets_rows)!=1 or connections[0].get("status")!="connected":
            raise CoinbaseAuthorizationError("coinbase_reconnect_required")
        connection,secret=connections[0],secrets_rows[0]
        if any(row.get("organization_id")!=org or row.get("run_id")!=run or row.get("provider")!=PROVIDER for row in (connection,secret)):
            raise CoinbaseAuthorizationError("coinbase_connection_scope_changed")
        user=str(UUID(connection.get("data",{}).get("connected_by")))
        await _require_director(db,org,run,user)
        saved=cipher.open(secret["encrypted_token"],organization_id=org,connection_id=run+":"+PROVIDER)
        if saved.get("issuer")!=SERVER or saved.get("server_url")!=SERVER or saved.get("director_user_id")!=user:
            raise CoinbaseAuthorizationError("coinbase_connection_scope_changed")
        client=_client_info(saved.get("client",{}))
        token=_token(saved.get("token",{}))
        if saved.get("expires_at") is None:
            return token.access_token
        try:
            expiry=datetime.fromisoformat(saved["expires_at"])
            valid=expiry.tzinfo is not None and expiry>datetime.now(UTC)+timedelta(seconds=30)
        except (ValueError,TypeError):
            raise CoinbaseAuthorizationError("coinbase_stored_expiry_invalid") from None
        if valid:
            return token.access_token
        if not token.refresh_token:
            raise CoinbaseAuthorizationError("coinbase_expired_grant_requires_reconnect")
        async with httpx.AsyncClient(follow_redirects=False,timeout=20) as http:
            await _metadata(http)
            claim=await db.rpc("claim_coinbase_token_refresh",{"p_organization_id":org,"p_run_id":run,"p_director_user_id":user,
                "p_expected_updated_at":secret["updated_at"]})
            if not isinstance(claim,dict) or claim.get("claimed") is not True:
                raise CoinbaseAuthorizationError("coinbase_refresh_already_claimed_or_connection_changed")
            refreshed=_token(await _json_request(http,"refresh","POST",SERVER+"/token",data={"grant_type":"refresh_token",
                "refresh_token":token.refresh_token,"client_id":client.client_id}),previous_refresh=token.refresh_token)
        sealed=cipher.seal(_stored(client,refreshed,user),organization_id=org,connection_id=run+":"+PROVIDER)
        result=await db.rpc("rotate_coinbase_wallet_token",{"p_organization_id":org,"p_run_id":run,"p_director_user_id":user,
            "p_expected_updated_at":secret["updated_at"],"p_refresh_claim_id":str(UUID(claim["claim_id"])),"p_encrypted_token":sealed})
        if not isinstance(result,dict) or result.get("status")!="refreshed":
            raise CoinbaseAuthorizationError("coinbase_refreshed_grant_not_committed")
        return refreshed.access_token
