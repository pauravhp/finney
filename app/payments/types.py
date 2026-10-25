from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.finance.types import minor_units

CHAIN_ID = 84532
NETWORK = "eip155:84532"
USDC_ADDRESS = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
USDC_DECIMALS = 6
BASE_UNITS_PER_CENT = 10_000
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class PaymentError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def address(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", value) or int(value, 16) == 0:
        raise PaymentError("invalid_evm_address")
    return value.lower()


def transaction_hash(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", value):
        raise PaymentError("invalid_transaction_hash")
    return value.lower()


@dataclass(frozen=True)
class TransferIntent:
    destination: str
    sender: str
    amount_minor: int
    amount_base_units: int
    network_alias: str

    @classmethod
    def from_action(cls, action: dict[str, Any], *, expected_sender: str, max_base_units: int = 100_000_000) -> TransferIntent:
        if action.get("type") != "payment" or action.get("currency") != "USD" or action.get("asset") != "USDC":
            raise PaymentError("only_usd_usdc_testnet_payments_supported")
        if action.get("network") not in {NETWORK, "base-sepolia"}:
            raise PaymentError("mainnet_or_unknown_network_denied")
        if action.get("asset_decimals") != USDC_DECIMALS or str(action.get("token_address", "")).lower() != USDC_ADDRESS.lower():
            raise PaymentError("exact_usdc_contract_and_decimals_required_in_approved_action")
        amount = minor_units(action.get("amount_minor"), nonnegative=True)
        base = minor_units(action.get("amount_base_units"), nonnegative=True)
        if amount <= 0 or base != amount * BASE_UNITS_PER_CENT or base > max_base_units:
            raise PaymentError("amount_conversion_or_testnet_limit_mismatch")
        sender = address(expected_sender)
        if address(action.get("sender")) != sender:
            raise PaymentError("approved_sender_mismatch")
        address(action.get("destination"))
        return cls(action["destination"], sender, amount, base, action["network"])

    def usdc_decimal(self) -> str:
        whole, fraction = divmod(self.amount_base_units, 10**USDC_DECIMALS)
        return f"{whole}.{fraction:06d}"


def build_testnet_payment_action(*, obligation_id: str, obligation_version: int,
                                amount_minor: int | str, destination: str, sender: str,
                                max_base_units: int = 100_000_000) -> dict[str, Any]:
    """Trusted proposal preparation derives conversion/contract before approvals."""
    if isinstance(obligation_version, bool) or not isinstance(obligation_version, int) or obligation_version < 1:
        raise PaymentError("positive_obligation_version_required")
    amount = minor_units(amount_minor, nonnegative=True)
    result = {"type": "payment", "currency": "USD", "amount_minor": str(amount),
        "asset": "USDC", "amount_base_units": str(amount*BASE_UNITS_PER_CENT),
        "asset_decimals": USDC_DECIMALS, "token_address": USDC_ADDRESS, "network": NETWORK,
        "sender": address(sender), "destination": address(destination),
        "obligation_id": str(UUID(obligation_id)), "obligation_version": obligation_version}
    TransferIntent.from_action(result, expected_sender=sender, max_base_units=max_base_units)
    return result
