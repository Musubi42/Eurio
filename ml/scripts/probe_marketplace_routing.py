"""Probe — benchmark du recall eBay par (pays d'origine × marketplace).

Objectif : remplacer le routage `_ROUTES` hand-assigné de
`ml/sources/ebay/marketplaces.py` par du recall **mesuré**. Pour chaque
pays d'origine d'un coin (préfixe de l'eurio_id), on benchmarke les 9
marketplaces eBay et on recommande le `primary` au meilleur recall.

Cf. discussion 2026-05-20 (post-V1) : V1 a tranché PT→GB-only sur cette
même logique de mesure ; on la généralise à toutes les origines.

Méthode :
- Pour chaque origine O : K coins commémo 2€ échantillon.
- Pour chaque marketplace M (9) : query construite dans la langue
  native de M, on lit le `total` eBay (estimation du nb de listings).
- Recall(O, M) = médiane des `total` sur les K coins.
- Primary recommandé = marketplace non-GB au recall médian le plus haut,
  s'il bat GB d'au moins ×MARGIN ; sinon GB-only.

Le `total` eBay est bruité entre sessions mais stable intra-session
(vérifié V1 : PT = 1.68× identique sur 5 runs consécutifs).

Coût quota : ~26 origines × 9 marketplaces × K coins.

Usage:
    python -m scripts.probe_marketplace_routing
    python -m scripts.probe_marketplace_routing --origins ad,pt,fr
    python -m scripts.probe_marketplace_routing --coins-per-origin 5

Output : ml/state/probe_marketplace_routing_<timestamp>.json

Script jetable — supprimé après mise à jour de `_ROUTES`.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.market.ebay_client import SEARCH_URL, get_app_token  # noqa: E402
from sources.ebay.filters import accept_listing, listing_row  # noqa: E402
from sources.ebay.queries import (  # noqa: E402
    CATEGORY_EURO_COINS,
    build_query,
    load_coin,
    title_matches_theme,
)
from store import Store  # noqa: E402

# Marketplace → langue de query native (cf. vision.md §P3).
MARKETPLACES: dict[str, str] = {
    "EBAY_AT": "de", "EBAY_BE": "fr", "EBAY_DE": "de",
    "EBAY_ES": "es", "EBAY_FR": "fr", "EBAY_GB": "en",
    "EBAY_IE": "en", "EBAY_IT": "it", "EBAY_NL": "nl",
}
ACCEPT_LANG: dict[str, str] = {
    "EBAY_AT": "de-AT", "EBAY_BE": "fr-BE", "EBAY_DE": "de-DE",
    "EBAY_ES": "es-ES", "EBAY_FR": "fr-FR", "EBAY_GB": "en-GB",
    "EBAY_IE": "en-IE", "EBAY_IT": "it-IT", "EBAY_NL": "nl-NL",
}
GLOBAL_MKT = "EBAY_GB"
# Le primary doit battre GB d'au moins ×MARGIN pour être retenu.
MARGIN = 1.3
THROTTLE = 0.3
SEARCH_LIMIT = 200  # 1re page eBay (max API) — base du comptage survivors


def search_survivors(
    token: str, marketplace: str, coin: Any, conn: sqlite3.Connection,
) -> tuple[int | None, int | None, str | None]:
    """Renvoie (survivors, total, error).

    `survivors` = listings de la 1re page (≤200) qui passent
    ``accept_listing`` (prix / devise EUR / noise / millésime) **ET**
    ``title_matches_theme`` (le titre seller désigne bien CETTE pièce).
    C'est le vrai recall exploitable de la pièce visée.

    Le theme-match est désormais non-biaisé : depuis I3, les 112 coins
    du benchmark ont leurs titres localisés DE/IT/ES/NL en plus de
    FR/EN → ``title_matches_theme`` couvre les 6 langues de marketplace
    sans retomber sur le fallback legacy. Il est appliqué **toujours**
    (pas seulement sur les (pays, année) ambigus) pour mesurer le recall
    propre de la pièce ; sur les coins non-ambigus le matcher est
    permissif et n'écarte rien.
    """
    q = build_query(coin, query_lang=MARKETPLACES[marketplace]).q
    try:
        resp = httpx.get(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace,
                "Accept-Language": ACCEPT_LANG.get(marketplace, "en-US"),
            },
            params={"q": q, "limit": SEARCH_LIMIT, "category_ids": CATEGORY_EURO_COINS},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        return None, None, str(exc)[:160]
    if resp.status_code != 200:
        return None, None, f"HTTP {resp.status_code}"
    body = resp.json()
    total = body.get("total") if isinstance(body.get("total"), int) else 0
    survivors = 0
    for it in body.get("itemSummaries") or []:
        row = listing_row(it)
        ok, _ = accept_listing(
            row, coin.face_value,
            expected_year=coin.year, is_commemorative=bool(coin.is_commemorative),
        )
        if not ok:
            continue
        if not title_matches_theme(
            row.get("title") or "", coin.eurio_id,
            marketplace=marketplace, conn=conn,
        ):
            continue
        survivors += 1
    return survivors, total, None


def _db_country(origin: str) -> str:
    """Normalise une origine vers `coins.country` (ISO2 majuscule, 'eu' joint)."""
    return "eu" if origin.lower() == "eu" else origin.upper()


def sample_coins(conn: sqlite3.Connection, origin: str, k: int) -> list[Any]:
    """K coins commémo 2€ d'une origine — circulés de préférence (recall fiable)."""
    rows = conn.execute(
        """
        SELECT eurio_id FROM coins
         WHERE country = ? AND face_value = 2.0 AND is_commemorative = 1
         ORDER BY CASE WHEN year BETWEEN 2008 AND 2023 THEN 0 ELSE 1 END,
                  year DESC
         LIMIT ?
        """,
        (_db_country(origin), k),
    ).fetchall()
    coins = []
    for r in rows:
        try:
            coins.append(load_coin(conn, r["eurio_id"]))
        except Exception as exc:  # noqa: BLE001
            print(f"  !! load_coin {r['eurio_id']}: {exc}")
    return coins


def benchmark_origin(
    token: str, origin: str, coins: list[Any], conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Recall médian (survivors) par marketplace + primary recommandé."""
    per_mkt: dict[str, list[int]] = {m: [] for m in MARKETPLACES}
    for coin in coins:
        for mkt in MARKETPLACES:
            survivors, _total, err = search_survivors(token, mkt, coin, conn)
            if err:
                print(f"  !! {origin} {coin.eurio_id} {mkt}: {err}")
            elif survivors is not None:
                per_mkt[mkt].append(survivors)
            time.sleep(THROTTLE)

    medians = {
        m: (statistics.median(v) if v else 0.0) for m, v in per_mkt.items()
    }
    gb = medians.get(GLOBAL_MKT, 0.0)
    non_gb = {m: v for m, v in medians.items() if m != GLOBAL_MKT}
    best_mkt = max(non_gb, key=lambda m: non_gb[m]) if non_gb else None
    best_val = non_gb.get(best_mkt, 0.0) if best_mkt else 0.0

    if best_mkt and gb > 0 and best_val >= MARGIN * gb:
        recommended = best_mkt
    elif best_mkt and gb == 0 and best_val > 0:
        recommended = best_mkt
    else:
        recommended = None  # GB-only

    return {
        "origin": origin,
        "n_coins": len(coins),
        "coins": [c.eurio_id for c in coins],
        "recall_median": {m: round(v, 1) for m, v in medians.items()},
        "best_non_gb": best_mkt,
        "best_non_gb_recall": round(best_val, 1),
        "gb_recall": round(gb, 1),
        "recommended_primary": recommended,
        "recommended_query_lang": MARKETPLACES.get(recommended) if recommended else "en",
    }


def load_coins_file(
    conn: sqlite3.Connection, path: Path,
) -> dict[str, list[Any]]:
    """Charge les eurio_ids du fichier, groupés par origine (préfixe).

    On benchmarke **exactement** les coins traduits (DE/IT/ES/NL via I3)
    — re-piocher en SQL risquerait des pièces sans titre i18n, qui
    feraient retomber ``title_matches_theme`` sur le fallback legacy et
    re-biaiseraient le benchmark.
    """
    by_origin: dict[str, list[Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        eurio_id = line.strip()
        if not eurio_id or eurio_id.startswith("#"):
            continue
        origin = eurio_id.split("-", 1)[0]
        try:
            coin = load_coin(conn, eurio_id)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! load_coin {eurio_id}: {exc}")
            continue
        by_origin.setdefault(origin, []).append(coin)
    return by_origin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origins", help="CSV d'origines (défaut: toutes)")
    parser.add_argument(
        "--coins-file",
        default=str(ROOT / "state" / "benchmark_coins.txt"),
        help="Fichier d'eurio_ids à benchmarker (1 par ligne). "
             "Défaut: les 112 coins traduits. Vide = sampling SQL legacy.",
    )
    parser.add_argument("--coins-per-origin", type=int, default=3,
                        help="Utilisé seulement si --coins-file est vide.")
    args = parser.parse_args()

    client_id = os.environ.get("EBAY_CLIENT_ID")
    client_secret = os.environ.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERROR: EBAY_CLIENT_ID / EBAY_CLIENT_SECRET manquants", file=sys.stderr)
        return 2

    token = get_app_token(client_id, client_secret)
    store = Store(db_path=ROOT / "state" / "eurio.db")
    conn = store._connection()  # noqa: SLF001
    conn.row_factory = sqlite3.Row

    coins_by_origin: dict[str, list[Any]] = {}
    if args.coins_file:
        coins_by_origin = load_coins_file(conn, Path(args.coins_file))

    if args.origins:
        origins = [o.strip() for o in args.origins.split(",") if o.strip()]
    elif coins_by_origin:
        origins = sorted(coins_by_origin)
    else:
        origins = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT country FROM coins "
                "WHERE face_value=2.0 AND is_commemorative=1 ORDER BY country"
            ).fetchall()
        ]

    n_coins = sum(len(v) for v in coins_by_origin.values()) or (
        len(origins) * args.coins_per_origin)
    print(f"# Benchmark routing : {len(origins)} origines × {len(MARKETPLACES)} mkts "
          f"— {n_coins} coins")
    results: list[dict[str, Any]] = []
    for origin in origins:
        if coins_by_origin:
            coins = coins_by_origin.get(origin, [])
        else:
            coins = sample_coins(conn, origin, args.coins_per_origin)
        if not coins:
            print(f"  {origin:4} — aucun coin, skip")
            continue
        res = benchmark_origin(token, origin, coins, conn)
        results.append(res)
        rec = res["recommended_primary"] or "GB-only"
        print(f"  {origin:4} n={res['n_coins']}  best={res['best_non_gb']}"
              f"({res['best_non_gb_recall']:.0f}) vs GB({res['gb_recall']:.0f})"
              f"  → {rec}")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coins_per_origin": args.coins_per_origin,
        "margin": MARGIN,
        "metric": "survivors (accept_listing + title_matches_theme) sur 200, médiane sur K coins",
        "coins_file": args.coins_file or None,
        "results": results,
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "state" / f"probe_marketplace_routing_{ts}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out}")
    _print_recommendation_table(results)
    return 0


def _print_recommendation_table(results: list[dict[str, Any]]) -> None:
    print(f"\n{'='*78}")
    print("RECOMMANDATIONS — primary par origine (vs _ROUTES actuel à comparer)")
    print(f"{'='*78}")
    print(f"{'orig':5} {'primary reco':14} {'recall':>8} {'gb':>8}  {'ratio':>6}")
    for r in sorted(results, key=lambda x: x["origin"]):
        prim = r["recommended_primary"] or "— (GB-only)"
        ratio = (r["best_non_gb_recall"] / r["gb_recall"]) if r["gb_recall"] else None
        ratio_s = f"{ratio:.2f}" if ratio is not None else "—"
        print(f"{r['origin']:5} {prim:14} {r['best_non_gb_recall']:8.0f} "
              f"{r['gb_recall']:8.0f}  {ratio_s:>6}")


if __name__ == "__main__":
    raise SystemExit(main())
