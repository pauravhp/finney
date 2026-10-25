from uuid import uuid4

import httpx
import pytest

from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope
from app.storage.supabase import SupabaseClient, SupabaseError


@pytest.mark.asyncio
async def test_new_secret_key_is_not_bearer_jwt_and_user_jwt_is_explicit():
    requests = []
    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})
    async with SupabaseClient("https://test.supabase.co", "sb_secret_TEST", transport=httpx.MockTransport(handler)) as client:
        await client.rpc("get_finance_snapshot", {})
    assert requests[0].headers["apikey"] == "sb_secret_TEST"
    assert "authorization" not in requests[0].headers
    async with SupabaseClient("https://test.supabase.co", "sb_publishable_TEST", access_token="user.jwt", transport=httpx.MockTransport(handler)) as client:
        await client.rpc("get_finance_snapshot", {})
    assert requests[1].headers["authorization"] == "Bearer user.jwt"


@pytest.mark.asyncio
async def test_provider_error_does_not_disclose_secrets_or_retry_mutation():
    attempts = 0
    async def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"code": "P0001", "message": "SECRET-PROVIDER-BODY"})
    async with SupabaseClient("https://test.supabase.co", "sb_secret_TEST", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SupabaseError) as error:
            await client.rpc("finance_kernel_call", {})
    assert attempts == 1
    assert "SECRET" not in str(error.value)


@pytest.mark.asyncio
async def test_artifact_scope_and_collision_requires_actual_content_match():
    async def handler(request):
        if request.method == "POST":
            return httpx.Response(409, json={"code": "Duplicate"})
        return httpx.Response(200, content=b"wrong bytes")
    scope = Scope(uuid4(), uuid4())
    async with SupabaseClient("https://test.supabase.co", "sb_secret_TEST", transport=httpx.MockTransport(handler)) as client:
        tools = FinanceToolClient(scope, client)
        with pytest.raises(FinanceError, match="outside"):
            await tools.call("read_artifact", {"artifact_path": f"{scope.organization_id}/{uuid4()}/artifacts/test"})
        with pytest.raises(FinanceError, match="collision"):
            await tools.call("put_artifact", {"name": "skill.md", "content": "correct bytes", "idempotency_key": "test"})
