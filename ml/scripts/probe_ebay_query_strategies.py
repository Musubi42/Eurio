"""A/B probe : compare eBay search strategies for a sample of eurio_ids.

Pas de prod-effect — on hit l'API en lecture seule, on imprime un tableau.
Sert à arbitrer "country FR vs EN", "drop year aspect", "marketplace EBAY_FR
vs EBAY_GB vs EBAY_DE", "theme tokens dans q ou pas".

Usage :
    EBAY_CLIENT_ID=… EBAY_CLIENT_SECRET=… python -m scripts.probe_ebay_query_strategies
    # ou via direnv si .envrc charge déjà les secrets

Output :
    ml/state/probe_ebay_query_strategies_<timestamp>.json   (full dump)
    stdout                                                   (tableau lisible)

Coût quota : ~30 calls (5 eurio_ids × 6 variantes). Daily limit = 5000.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# Allow `python -m scripts.probe_ebay_query_strategies` from ml/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources.market.ebay_client import SEARCH_URL, get_app_token  # noqa: E402
from sources.ebay.queries import (  # noqa: E402
    CATEGORY_EURO_COINS,
    ISO2_TO_NAME_FR,
    _theme_keywords,
    load_coin,
)
from store import Store  # noqa: E402


# Country canonical EN names (used in eBay listings cross-marketplace).
ISO2_TO_NAME_EN: dict[str, str] = {
    "AD": "Andorra",
    "AT": "Austria",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "CY": "Cyprus",
    "DE": "Germany",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GR": "Greece",
    "HR": "Croatia",
    "IE": "Ireland",
    "IT": "Italy",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MC": "Monaco",
    "MT": "Malta",
    "NL": "Netherlands",
    "PT": "Portugal",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "SM": "San Marino",
    "VA": "Vatican",
}


# Sample d'eurio_ids variés : un connu vide, un connu abondant, et 3 mid.
DEFAULT_SAMPLE = [
    "ad-2025-2eur-bearded-vulture",
    "be-2006-2eur-renovation-of-the-atomium-in-brussels",
    "fr-2012-2eur-100th-birthday-of-abbe-pierre",
    "de-2024-2eur-175th-anniversary-of-the-paulskirche-constitution",
    "sk-2024-2eur-100-years-of-kosice-peace-marathon",
]


@dataclass
class VariantSpec:
    label: str
    description: str
    marketplace: str
    use_country_en: bool
    include_year_in_q: bool
    include_year_aspect: bool
    include_theme_tokens: bool


VARIANTS: list[VariantSpec] = [
    VariantSpec("V1_baseline",
                "FR name + year-in-q + Année:{year} aspect + EBAY_FR",
                "EBAY_FR", False, True, True, False),
    VariantSpec("V2_name_en",
                "EN name + year-in-q + Année:{year} aspect + EBAY_FR",
                "EBAY_FR", True, True, True, False),
    VariantSpec("V3_no_aspect",
                "EN name + no year + no aspect + EBAY_FR",
                "EBAY_FR", True, False, False, False),
    VariantSpec("V4_theme",
                "EN name + EN theme tokens + EBAY_FR",
                "EBAY_FR", True, False, False, True),
    VariantSpec("V5_gb",
                "EN name + no year + no aspect + EBAY_GB",
                "EBAY_GB", True, False, False, False),
    VariantSpec("V6_de",
                "EN name + no year + no aspect + EBAY_DE",
                "EBAY_DE", True, False, False, False),
]


def _denom_label(face_value: float) -> str:
    return "2 euro" if face_value == 2.0 else f"{face_value} euro"


def _build_q(coin, variant: VariantSpec) -> str:
    name_map = ISO2_TO_NAME_EN if variant.use_country_en else ISO2_TO_NAME_FR
    country = name_map.get(coin.country, coin.country_name or coin.country)
    parts = [_denom_label(coin.face_value), country]
    if variant.include_year_in_q:
        parts.append(str(coin.year))
    if variant.include_theme_tokens:
        tokens = _theme_keywords(coin.eurio_id, max_words=3)
        parts.extend(tokens)
    return " ".join(parts).strip()


def _build_aspect(variant: VariantSpec, year: int) -> str | None:
    if not variant.include_year_aspect:
        return f"categoryId:{CATEGORY_EURO_COINS}"
    return f"categoryId:{CATEGORY_EURO_COINS},Année:{{{year}}}"


def _search_once(
    *,
    token: str,
    marketplace: str,
    q: str,
    aspect_filter: str | None,
    limit: int = 50,
) -> tuple[int, list[str], int | None, str | None]:
    """Returns (n_results, top_titles, http_status, error)."""
    params: dict[str, Any] = {"q": q, "limit": limit, "category_ids": CATEGORY_EURO_COINS}
    if aspect_filter:
        params["aspect_filter"] = aspect_filter
    try:
        resp = httpx.get(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace,
                "Accept-Language": _accept_lang(marketplace),
            },
            params=params,
            timeout=30,
        )
    except httpx.HTTPError as exc:
        return 0, [], None, str(exc)[:200]

    if resp.status_code != 200:
        return 0, [], resp.status_code, resp.text[:200]
    body = resp.json()
    summaries = body.get("itemSummaries") or []
    titles = [s.get("title") or "" for s in summaries[:5]]
    total = body.get("total")
    if isinstance(total, int):
        n = total
    else:
        n = len(summaries)
    return n, titles, 200, None


def _accept_lang(marketplace: str) -> str:
    # Some marketplaces return localized aspect names depending on Accept-Language.
    return {
        "EBAY_FR": "fr-FR",
        "EBAY_GB": "en-GB",
        "EBAY_DE": "de-DE",
        "EBAY_US": "en-US",
    }.get(marketplace, "en-US")


def main() -> int:
    client_id = os.environ.get("EBAY_CLIENT_ID")
    client_secret = os.environ.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERROR: EBAY_CLIENT_ID and EBAY_CLIENT_SECRET must be set", file=sys.stderr)
        return 2

    eurio_ids = sys.argv[1:] or DEFAULT_SAMPLE
    print(f"# Probing {len(eurio_ids)} eurio_ids × {len(VARIANTS)} variants = "
          f"{len(eurio_ids) * len(VARIANTS)} eBay calls\n")

    token = get_app_token(client_id, client_secret)

    store = Store(db_path=Path(__file__).resolve().parents[1] / "state" / "eurio.db")
    conn = store._connection()  # noqa: SLF001

    rows: list[dict[str, Any]] = []
    for eid in eurio_ids:
        try:
            coin = load_coin(conn, eid)
        except Exception as exc:  # noqa: BLE001
            print(f"!! skipping {eid}: {exc}")
            continue
        print(f"\n=== {eid}  ({coin.country} {coin.year})  ambiguity check disabled ===")
        for v in VARIANTS:
            q = _build_q(coin, v)
            aspect = _build_aspect(v, coin.year)
            t0 = time.monotonic()
            n, titles, http_status, err = _search_once(
                token=token, marketplace=v.marketplace, q=q, aspect_filter=aspect,
            )
            dt_ms = int((time.monotonic() - t0) * 1000)
            row = {
                "eurio_id": eid,
                "variant": v.label,
                "description": v.description,
                "marketplace": v.marketplace,
                "q": q,
                "aspect_filter": aspect,
                "http_status": http_status,
                "n_results": n,
                "duration_ms": dt_ms,
                "top_titles": titles,
                "error": err,
            }
            rows.append(row)
            tag = "OK" if http_status == 200 and not err else "ERR"
            print(f"  [{tag}] {v.label:14s} ({v.marketplace:8s}) n={n:>4}  q={q!r}")
            if titles:
                for t in titles[:3]:
                    print(f"        · {t[:100]}")
            if err:
                print(f"        ! {err}")

    # Persist
    out_dir = Path(__file__).resolve().parents[1] / "state"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"probe_ebay_query_strategies_{stamp}.json"
    out_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    print(f"\nDump → {out_path}")

    # Summary table
    print("\n# Summary (n_results)\n")
    header = ["eurio_id"] + [v.label for v in VARIANTS]
    widths = [50] + [12] * len(VARIANTS)
    print("  ".join(h.ljust(w) for h, w in zip(header, widths)))
    print("  ".join("-" * w for w in widths))
    by_eid: dict[str, dict[str, int]] = {}
    for r in rows:
        by_eid.setdefault(r["eurio_id"], {})[r["variant"]] = r["n_results"]
    for eid, per_v in by_eid.items():
        line = [eid[:50]] + [str(per_v.get(v.label, "·")) for v in VARIANTS]
        print("  ".join(c.ljust(w) for c, w in zip(line, widths)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
