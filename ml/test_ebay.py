"""Smoke test for eBay Browse API — OAuth client_credentials + a single search."""

import base64
import json
import os
import sys
from pathlib import Path

import httpx

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


def load_env() -> dict[str, str]:
    env = {}
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    for key in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def get_app_token(client_id: str, client_secret: str) -> str:
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
    if resp.status_code != 200:
        print(f"OAuth failed: HTTP {resp.status_code}")
        print(resp.text)
        sys.exit(1)
    payload = resp.json()
    print(f"OAuth OK — token type {payload['token_type']}, expires in {payload['expires_in']}s")
    return payload["access_token"]


def search(token: str, query: str, limit: int = 5) -> dict:
    resp = httpx.get(
        BROWSE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR",
        },
        params={"q": query, "limit": limit},
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"Search failed: HTTP {resp.status_code}")
        print(resp.text)
        sys.exit(1)
    return resp.json()


def print_results(data: dict) -> None:
    total = data.get("total", 0)
    items = data.get("itemSummaries", []) or []
    print(f"\nTotal matches: {total}  —  showing {len(items)}\n")
    for i, item in enumerate(items, 1):
        title = item.get("title", "?")
        price = item.get("price", {})
        price_str = f"{price.get('value', '?')} {price.get('currency', '')}".strip()
        condition = item.get("condition", "?")
        seller = item.get("seller", {}).get("username", "?")
        location = item.get("itemLocation", {}).get("country", "?")
        image = item.get("image", {}).get("imageUrl", "")
        print(f"[{i}] {title}")
        print(f"    price={price_str}  condition={condition}  seller={seller}  country={location}")
        if image:
            print(f"    image={image}")
        print()


def main() -> None:
    env = load_env()
    client_id = env.get("EBAY_CLIENT_ID")
    client_secret = env.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERROR: EBAY_CLIENT_ID / EBAY_CLIENT_SECRET missing from .env")
        sys.exit(1)

    query = sys.argv[1] if len(sys.argv) > 1 else "2 euro commemorative allemagne 2006"
    print(f"Query: {query!r}")

    token = get_app_token(client_id, client_secret)
    data = search(token, query, limit=5)
    print_results(data)

    dump_path = Path(__file__).parent / "output" / "ebay_last_response.json"
    dump_path.parent.mkdir(exist_ok=True)
    dump_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Raw response saved to {dump_path}")


if __name__ == "__main__":
    main()
