"""Authenticated encryption for connector tokens stored in private database rows."""

import json

from cryptography.fernet import Fernet, InvalidToken


class TokenCipher:
    def __init__(self, key: str):
        if not key:
            raise ValueError("FINANCE_TOKEN_ENCRYPTION_KEY must be configured")
        self._cipher = Fernet(key.encode())

    def seal(self, value: dict, *, organization_id: str, connection_id: str) -> str:
        bound = {"organization_id": organization_id, "connection_id": connection_id, "value": value}
        return self._cipher.encrypt(json.dumps(bound, sort_keys=True).encode()).decode()

    def open(self, ciphertext: str, *, organization_id: str, connection_id: str) -> dict:
        try:
            bound = json.loads(self._cipher.decrypt(ciphertext.encode()))
        except (InvalidToken, ValueError, TypeError) as exc:
            raise ValueError("Connector token could not be decrypted") from exc
        if (
            bound.get("organization_id") != organization_id
            or bound.get("connection_id") != connection_id
        ):
            raise ValueError("Connector token scope mismatch")
        return bound["value"]
