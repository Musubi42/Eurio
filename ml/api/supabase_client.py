"""Supabase REST client — thin wrapper around httpx for PostgREST.

Reuses the same env-loading pattern as the existing ML scripts.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

_ENV_KEYS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "NUMISTA_API_KEY",
]


def load_env() -> dict[str, str]:
    """Load environment variables from .env file, overridden by OS env."""
    env: dict[str, str] = {}
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    for key in _ENV_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


class SupabaseClient:
    """Lightweight PostgREST client using httpx."""

    def __init__(self, url: str, service_key: str) -> None:
        self.url = url.rstrip("/")
        self.rest_base = f"{self.url}/rest/v1"
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self._client = httpx.Client(headers=self._headers, timeout=60)

    def query(
        self,
        table: str,
        *,
        select: str = "*",
        params: dict | None = None,
    ) -> list[dict]:
        """GET query with optional filter params."""
        p = {"select": select, **(params or {})}
        resp = self._client.get(f"{self.rest_base}/{table}", params=p)
        resp.raise_for_status()
        return resp.json()

    def upsert(
        self,
        table: str,
        rows: list[dict],
        *,
        on_conflict: str | None = None,
    ) -> list[dict]:
        """Upsert rows in batches of 500."""
        endpoint = f"{self.rest_base}/{table}"
        if on_conflict:
            endpoint += f"?on_conflict={on_conflict}"

        all_results: list[dict] = []
        for i in range(0, len(rows), 500):
            batch = rows[i : i + 500]
            resp = self._client.post(
                endpoint,
                json=batch,
                headers={
                    **self._headers,
                    "Prefer": "return=representation,resolution=merge-duplicates",
                },
            )
            resp.raise_for_status()
            all_results.extend(resp.json())
        return all_results

    def count(self, table: str, *, params: dict | None = None) -> int:
        """Count rows with optional filters."""
        p = {"select": "*", **(params or {})}
        resp = self._client.get(
            f"{self.rest_base}/{table}",
            params=p,
            headers={**self._headers, "Prefer": "count=exact", "Range": "0-0"},
        )
        resp.raise_for_status()
        content_range = resp.headers.get("Content-Range", "")
        # Format: "0-0/123" or "*/0"
        if "/" in content_range:
            return int(content_range.split("/")[1])
        return 0

    def close(self) -> None:
        self._client.close()
