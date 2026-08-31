"""Encrypted local Azure DevOps connection profile management."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import keyring
from cryptography.fernet import Fernet


SERVICE_NAME = "ado-agile-metrics"
KEY_ACCOUNT = "connection-encryption-key"


@dataclass(frozen=True)
class ConnectionProfile:
    """Connection metadata excluding the decrypted PAT."""

    name: str
    organization_url: str
    default_project: str = ""
    default_team: str = ""


class ConnectionStore:
    """Store encrypted PATs locally; encryption keys remain in the OS credential manager."""

    def __init__(self, location: Path) -> None:
        location.parent.mkdir(parents=True, exist_ok=True)
        self.location = location

    def _cipher(self) -> Fernet:
        encoded_key = keyring.get_password(SERVICE_NAME, KEY_ACCOUNT)
        if encoded_key is None:
            encoded_key = Fernet.generate_key().decode()
            keyring.set_password(SERVICE_NAME, KEY_ACCOUNT, encoded_key)
        return Fernet(encoded_key.encode())

    def _read(self) -> dict[str, dict[str, str]]:
        return json.loads(self.location.read_text()) if self.location.exists() else {}

    def save(self, profile: ConnectionProfile, pat: str) -> None:
        """Persist metadata and an encrypted PAT; plaintext is never written to disk."""
        payload = self._read()
        payload[profile.name] = {**asdict(profile), "encrypted_pat": self._cipher().encrypt(pat.encode()).decode()}
        self.location.write_text(json.dumps(payload, indent=2))

    def profiles(self) -> list[ConnectionProfile]:
        """List stored profiles without decrypting their tokens."""
        return [ConnectionProfile(**{key: value for key, value in record.items() if key != "encrypted_pat"}) for record in self._read().values()]

    def load_pat(self, name: str) -> str:
        """Decrypt a PAT only at the moment an authenticated client is created."""
        record = self._read()[name]
        return self._cipher().decrypt(record["encrypted_pat"].encode()).decode()

    def remove(self, name: str) -> None:
        """Remove a stored connection profile and encrypted credential."""
        payload = self._read()
        payload.pop(name, None)
        self.location.write_text(json.dumps(payload, indent=2))