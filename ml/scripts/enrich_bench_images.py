"""Enrichit le gold du bench avec l'URL d'image de chaque annonce eBay.

Le gold (`theme_match_gold.jsonl`) reste gelé — les images sont des
métadonnées d'affichage stockées à part dans un sidecar
`gold_images.jsonl` (`{listing_id, image_url, source}`), joint par le
studio bench (`api/bench_routes.py`).

Deux sources d'URL :

- **listings gardés** — déjà téléchargés pendant le run : l'URL CDN eBay
  d'origine est dans `source_images.raw_payload_json.image_url`. Gratuit.
- **listings rejetés** — jamais téléchargés (rejet pré-download) :
  re-fetch one-time via Browse API `getItem` sur l'item_id. Les annonces
  terminées (404) restent sans image.

Idempotent : ré-exécuter ne re-fetch que les listings encore sans URL.

Usage::

    python -m scripts.enrich_bench_images [--dry]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from scripts.bench_theme_match import GOLD_PATH, _norm_listing_id  # noqa: E402
from state import Store  # noqa: E402

DB_PATH = ML_DIR / "state" / "eurio.db"
IMAGES_PATH = ML_DIR / "state" / "discovery_bench" / "gold_images.jsonl"


def _kept_image_urls(conn) -> dict[str, str]:
    """{listing_id → image_url} pour les listings déjà en `source_images`.

    L'image primaire = `image_index` 0 ; on prend la première rencontrée.
    """
    out: dict[str, str] = {}
    for r in conn.execute(
        "SELECT source_ref, raw_payload_json FROM source_images "
        "WHERE source='ebay' AND raw_payload_json IS NOT NULL"
    ).fetchall():
        lid = _norm_listing_id(r["source_ref"])
        if lid in out:
            continue
        try:
            payload = json.loads(r["raw_payload_json"]) or {}
        except (json.JSONDecodeError, TypeError):
            continue
        url = payload.get("image_url")
        if url and payload.get("image_index", 0) == 0:
            out[lid] = url
    return out


def _load_sidecar() -> dict[str, dict]:
    if not IMAGES_PATH.exists():
        return {}
    return {
        json.loads(ln)["listing_id"]: json.loads(ln)
        for ln in IMAGES_PATH.read_text().splitlines() if ln.strip()
    }


def _write_sidecar(records: dict[str, dict]) -> None:
    with IMAGES_PATH.open("w") as f:
        for lid in sorted(records):
            f.write(json.dumps(records[lid], ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true",
                        help="affiche le plan sans fetch ni écriture")
    args = parser.parse_args()

    if not GOLD_PATH.exists():
        print(f"gold absent : {GOLD_PATH}", file=sys.stderr)
        return 1

    conn = Store(DB_PATH)._connection()  # noqa: SLF001
    gold = [json.loads(ln) for ln in GOLD_PATH.read_text().splitlines() if ln.strip()]
    kept = _kept_image_urls(conn)
    sidecar = _load_sidecar()

    # Plan : ce qui est déjà résolu, ce qui se résout gratis, ce qui doit
    # être re-fetché via l'API eBay.
    to_fetch: list[dict] = []
    n_local = n_done = 0
    for g in gold:
        lid = g["listing_id"]
        if sidecar.get(lid, {}).get("image_url"):
            n_done += 1
            continue
        if lid in kept:
            sidecar[lid] = {"listing_id": lid, "image_url": kept[lid],
                            "source": "source_images"}
            n_local += 1
        else:
            to_fetch.append(g)

    print(f"gold {len(gold)} · déjà résolus {n_done} · "
          f"depuis source_images {n_local} · à re-fetch eBay {len(to_fetch)}")

    if args.dry:
        print("DRY — rien écrit.")
        return 0

    if n_local:
        _write_sidecar(sidecar)

    if to_fetch:
        client_id = os.environ.get("EBAY_CLIENT_ID")
        client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not client_id or not client_secret:
            print("EBAY_CLIENT_ID / EBAY_CLIENT_SECRET absents — re-fetch "
                  "sauté (source_images écrit). Relance dans un shell "
                  "direnv pour les rejetés.", file=sys.stderr)
            return 1
        from market.ebay_client import EbayClient, get_app_token

        token = get_app_token(client_id, client_secret)
        clients: dict[str, EbayClient] = {}
        n_fetched = n_missing = 0
        for i, g in enumerate(to_fetch, 1):
            lid, mkt = g["listing_id"], g.get("marketplace") or "EBAY_DE"
            try:
                client = clients.get(mkt) or clients.setdefault(
                    mkt, EbayClient(token, marketplace=mkt))
                item = client.get_item(lid, fieldgroups="")
                url = (item.get("image") or {}).get("imageUrl")
            except Exception as exc:  # noqa: BLE001 — annonce terminée / 404
                url = None
                print(f"  [{i}/{len(to_fetch)}] {lid} — {type(exc).__name__}")
            sidecar[lid] = {
                "listing_id": lid,
                "image_url": url,
                "source": "ebay_getitem" if url else "missing",
            }
            if url:
                n_fetched += 1
            else:
                n_missing += 1
            if i % 20 == 0:
                _write_sidecar(sidecar)  # checkpoint
            time.sleep(0.15)
        _write_sidecar(sidecar)
        print(f"re-fetch eBay : {n_fetched} images, {n_missing} sans image "
              f"(annonces terminées)")

    resolved = sum(1 for r in sidecar.values() if r.get("image_url"))
    print(f"sidecar → {IMAGES_PATH}  ({resolved}/{len(gold)} avec image)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
