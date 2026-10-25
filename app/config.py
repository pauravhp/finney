"""Typed configuration. Secrets never appear in diagnostic representations."""

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True, env_ignore_empty=True
    )

    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: SecretStr = SecretStr("")
    supabase_service_role_key: SecretStr = SecretStr("")
    supabase_db_url: SecretStr = SecretStr("")
    organization_id: UUID | None = Field(None, validation_alias="FINANCE_ORGANIZATION_ID")
    run_id: UUID | None = Field(None, validation_alias="FINANCE_RUN_ID")
    finance_model: str = "claude-sonnet-4-6"
    finance_model_base_url: str = "https://api.anthropic.com/v1"
    finance_model_api_mode: str = "anthropic_messages"
    finance_model_api_key: SecretStr = SecretStr("")
    ai_gateway_api_key: SecretStr = SecretStr("")
    finance_hermes_source: str = ""
    finance_hermes_python: str = ""
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = "http://127.0.0.1:8767/oauth/gmail/callback"
    finance_token_encryption_key: SecretStr = SecretStr("")
    finance_gmail_query: str = "label:director-finance"
    finance_gmail_backend: Literal["hermes", "api"] = "hermes"
    coinbase_mcp_url: str = ""
    coinbase_redirect_uri: str = "http://127.0.0.1:8768/oauth/coinbase/callback"
    coinbase_mcp_token: SecretStr = SecretStr("")
    coinbase_sender_address: str = ""
    base_sepolia_rpc_url: str = "https://sepolia.base.org"
    coinbase_max_test_usdc_base_units: int = Field(100_000_000, ge=1)
    x402_pay_to_address: str = ""
    x402_price_base_units: int = Field(10_000, ge=1)
    x402_facilitator_url: str = "https://x402.org/facilitator"
    finance_payment_network: str = "eip155:84532"
    finance_testnet_only: bool = True
    finance_worker_id: str = "finance-worker"
    finance_poll_seconds: float = Field(3.0, ge=0.25, le=60)
    finance_auto_intake_enabled: bool = True
    finance_auto_intake_batch_size: int = Field(20, ge=1, le=100)
    finance_state_dir: Path = Path(".state")
    finance_event_timezone: str = "America/Vancouver"

    @property
    def backend_key(self) -> str:
        return (
            self.supabase_secret_key.get_secret_value()
            or self.supabase_service_role_key.get_secret_value()
        )

    def configured(self) -> dict[str, bool]:
        return {
            "supabase": bool(self.supabase_url and self.backend_key),
            "database_migrations": bool(self.supabase_db_url.get_secret_value()),
            "model": bool(self.finance_model_api_key.get_secret_value()),
            "jev": bool(self.ai_gateway_api_key.get_secret_value()),
            "gmail_oauth": bool(
                self.google_client_id and self.google_client_secret.get_secret_value()
            ),
            "token_encryption": bool(self.finance_token_encryption_key.get_secret_value()),
            "coinbase": bool(self.coinbase_mcp_url),
            "scope": bool(self.organization_id and self.run_id),
        }
