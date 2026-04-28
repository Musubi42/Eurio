"""Thin, reusable eBay Browse API client.

Handles OAuth client_credentials (application token, no user consent), caches
the token on disk for its full TTL, and exposes the three endpoints we care
about : `item_summary/search`, `item/{itemId}`, `item/get_items_by_item_group`.

No retry logic, no pagination helpers — callers handle that. The module's job
is to make each call a one-liner.

Spec: docs/research/ebay-api-strategy.md
"""

import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx

from api_quota import QuotaTracker

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
ITEM_URL = "https://api.ebay.com/buy/browse/v1/item/{item_id}"
GROUP_URL = "https://api.ebay.com/buy/browse/v1/item/get_items_by_item_group"
SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE = "EBAY_FR"

TOKEN_CACHE_PATH = Path(__file__).parent.parent / ".ebay_token_cache.json"


def get_app_token(client_id: str, client_secret: str, force: bool = False) -> str:
    """Return a valid application token. Caches to disk, refreshes when near expiry."""
    now = time.time()
    if not force and TOKEN_CACHE_PATH.exists():
        try:
            cached = json.loads(TOKEN_CACHE_PATH.read_text())
            if cached.get("expires_at", 0) - 60 > now:
                return cached["access_token"]
        except (json.JSONDecodeError, KeyError):
            pass

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = httpx.post(
        OAUTH_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}",
        },
        data={"grant_type": "client_credentials", "scope": SCOPE},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    access_token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 7200))
    TOKEN_CACHE_PATH.write_text(
        json.dumps(
            {
                "access_token": access_token,
                "expires_at": now + expires_in,
                "fetched_at": now,
            }
        )
    )
    return access_token


EBAY_DAILY_LIMIT = 5000


class EbayClient:
    def __init__(self, token: str, tracker: QuotaTracker | None = None):
        self.token = token
        self.call_count = 0
        self._tracker = tracker if tracker is not None else QuotaTracker(
            "ebay", "daily", EBAY_DAILY_LIMIT
        )
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
            },
            timeout=30,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EbayClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _request(self, url: str, params: dict[str, Any] | None) -> dict:
        resp = self._client.get(url, params=params)
        if resp.status_code == 429:
            self._tracker.mark_exhausted()
            resp.raise_for_status()
        resp.raise_for_status()
        self.call_count += 1
        self._tracker.record()
        return resp.json()

    def search(
        self,
        query: str,
        *,
        category_ids: str | None = None,
        aspect_filter: str | None = None,
        filter_expr: str | None = None,
        limit: int = 50,
        offset: int = 0,
        fieldgroups: str | None = None,
    ) -> dict:
        params: dict[str, Any] = {"q": query, "limit": limit, "offset": offset}
        if category_ids:
            params["category_ids"] = category_ids
        if aspect_filter:
            params["aspect_filter"] = aspect_filter
        if filter_expr:
            params["filter"] = filter_expr
        if fieldgroups:
            params["fieldgroups"] = fieldgroups
        return self._request(SEARCH_URL, params)

    def get_item(self, item_id: str, fieldgroups: str = "PRODUCT") -> dict:
        params = {"fieldgroups": fieldgroups} if fieldgroups else None
        return self._request(ITEM_URL.format(item_id=item_id), params)

    def get_items_by_group(self, group_id: str) -> dict:
        return self._request(GROUP_URL, {"item_group_id": group_id})
