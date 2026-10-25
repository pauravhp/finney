"""Bind the worker's provider credentials to one explicitly configured private run."""

from __future__ import annotations

from app.config import Settings
from app.finance.tools import FinanceToolClient
from app.payments.types import PaymentError, address


async def assert_payment_run_authorized(tools: FinanceToolClient, settings: Settings) -> dict:
    """Call before any provider access, including sender discovery or x402 setup.

    Scope IDs come only from the trusted worker configuration. A browser payload
    or model tool argument must never select the credentials' event/run binding.
    """
    if tools.prepare_only:
        raise PaymentError("evaluation_cannot_access_payment_provider")
    if not settings.organization_id or not settings.run_id or not settings.coinbase_sender_address:
        raise PaymentError("payment_provider_requires_explicit_private_event_binding")
    if (tools.scope.organization_id, tools.scope.run_id) != (settings.organization_id, settings.run_id):
        raise PaymentError("payment_provider_not_authorized_for_event_run")
    sender = address(settings.coinbase_sender_address)
    result = await tools.call("assert_payment_run_authorized", {
        "configured_organization_id": str(settings.organization_id),
        "configured_run_id": str(settings.run_id), "sender": sender,
    })
    if not isinstance(result, dict) or result.get("authorized") is not True or result.get("is_demo") is not False \
        or result.get("organization_id") != str(settings.organization_id) or result.get("run_id") != str(settings.run_id) \
        or result.get("sender") != sender:
        raise PaymentError("payment_provider_authorization_not_verified")
    return result
