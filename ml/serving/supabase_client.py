"""Supabase REST client — thin wrapper around httpx for PostgREST."""

from __future__ import annotations

import httpx

# Canonical secret accessor (single source: secrets/dev.env via .envrc).
# Re-exported so existing callers `from serving.supabase_client import load_env`
# keep working without churn.
from shared.env import load_env

__all__ = ["SupabaseClient", "load_env"]


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

    def patch(
        self,
        table: str,
        *,
        filters: dict,
        payload: dict,
    ) -> list[dict]:
        """PATCH rows matching `filters` with `payload`.

        `filters` are PostgREST query params, e.g. {"eurio_id": "eq.fr-2017-..."}.
        Returns the patched rows (Prefer: return=representation).
        """
        resp = self._client.patch(
            f"{self.rest_base}/{table}",
            params=filters,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def delete(
        self,
        table: str,
        *,
        filters: dict,
    ) -> None:
        """DELETE rows matching `filters`."""
        resp = self._client.delete(
            f"{self.rest_base}/{table}",
            params=filters,
        )
        resp.raise_for_status()

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
