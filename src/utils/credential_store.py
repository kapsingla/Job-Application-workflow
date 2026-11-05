from __future__ import annotations

import json
from pathlib import Path
from typing import Dict
from urllib.parse import urlparse
from src.config import CREDENTIALS_VAULT_PATH, APPLICANT_EMAIL, WORKDAY_DEFAULT_PASSWORD


class WorkdayCredentialStore:
    """
    Stores per-company Workday / career portal credentials.
    Reads default credentials (`APPLICANT_EMAIL` and `WORKDAY_DEFAULT_PASSWORD`) from `.env`.
    Always attempts to Sign In first using these credentials; only creates a new account
    with these credentials if the account does not exist yet.
    """

    def __init__(self, vault_path: Path = CREDENTIALS_VAULT_PATH):
        self.vault_path = vault_path
        if not self.vault_path.exists():
            self._save({})

    def _load(self) -> Dict[str, Dict[str, str]]:
        try:
            return json.loads(self.vault_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: Dict[str, Dict[str, str]]) -> None:
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def get_tenant_key(job_url: str) -> str:
        parsed = urlparse(job_url)
        return parsed.netloc.lower() or "default_tenant"

    def get_credentials(self, job_url: str) -> Dict[str, str]:
        vault = self._load()
        tenant = self.get_tenant_key(job_url)
        if tenant in vault:
            return {
                **vault[tenant],
                "account_exists": "true",
                "tenant": tenant,
            }
        return {
            "email": APPLICANT_EMAIL,
            "password": WORKDAY_DEFAULT_PASSWORD,
            "account_exists": "try_login_first",
            "tenant": tenant,
        }

    def mark_account_created(self, job_url: str, email: str, password: str) -> None:
        vault = self._load()
        tenant = self.get_tenant_key(job_url)
        vault[tenant] = {
            "email": email,
            "password": password,
        }
        self._save(vault)
