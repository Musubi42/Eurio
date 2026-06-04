"""Construit un échantillon stratifié de raws eBay pour le coin-census-bench.

Sous-chantier cohort-pipeline (cf. docs/cohort-pipeline/coin-census-bench.md).
But : produire un manifeste {source_image_id, raw_path, title, n_crops, …}
sur lequel un LLM-professeur (vision) labellise le nombre de pièces physiques
distinctes — vérité-terrain pour évaluer / entraîner le détecteur de census.

Stratification (couvre les cas durs) :
    single · lot · coincard/capsule (pièges FP) · vrais-lots-titre · au-choix.

Les chemins locaux des raws sont résolus via le cache MinIO
(``~/.cache/eurio/enrichment-raws/<storage_key>``) — préfère les fichiers déjà
en cache, sinon fetch (MinIO requis). Les raws non téléchargés sont sautés.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/build_coin_census_bench.py \
        [--cohort b0299ca0252b] [--out state/coin_census_bench/manifest.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from storage.local_cache import _cache_root, local_path  # noqa: E402

COINCARD = re.compile(r"coin\s*card|coincard|blister|capsul|m[üu]nzkarte|folder|cartera|numisbrief|etui", re.I)
TRUELOT = re.compile(
    r"konvolut|kms|kursm[üu]nzensatz|rotolino|rotolo|lotto|lote|juego|divisionale|"
    r"\d+\s*(valori|valores|valeurs|werte|monete|monedas|m[üu]nzen|monnaies|pi[eè]ces|st[üu]ck|pezzi)|"
    r"\b\d+\s*x\b|/.+/.+/", re.I)
AUCHOIX = re.compile(r"choisi|wählen|w[aä]hlen|elige|elegir|scegli|toutes\s+ann[eé]es|alle\s+jahre|pick\s+your|au\s+choix", re.I)

# Cibles par strate (≈110 items). Ajuster pour étendre le bench.
TARGET = {"single": 45, "lot": 20, "coincard": 20, "true_lot_title": 15, "au_choix": 10}


def _stratum(route: str | None, title: str | None) -> str:
    if route == "review_lot":
        return "lot"
    t = title or ""
    if COINCARD.search(t):
        return "coincard"
    if TRUELOT.search(t):
        return "true_lot_title"
    if AUCHOIX.search(t):
        return "au_choix"
    return "single"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="b0299ca0252b")
    ap.add_argument("--out", default=str(ML_DIR / "state" / "coin_census_bench" / "manifest.json"))
    ap.add_argument("--db", default=str(ML_DIR / "state" / "eurio.db"))
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    eids = [r[0] for r in conn.execute(
        "SELECT value FROM json_each((SELECT eurio_ids_json FROM experiment_cohorts WHERE id=?))",
        (args.cohort,),
    )]
    ph = ",".join("?" * len(eids))
    rows = conn.execute(
        f"""SELECT s.id, s.listing_title AS title, s.target_eurio_id AS target,
                   s.route_decision AS route, s.is_lot_suspected AS lot, s.storage_path AS skey,
                   (SELECT COUNT(*) FROM image_assets a WHERE a.source_image_id=s.id) AS n_crops
            FROM source_images s
            WHERE s.target_eurio_id IN ({ph})
              AND s.download_status='success' AND s.storage_path IS NOT NULL""", eids).fetchall()

    buckets: dict[str, list] = {}
    for r in rows:
        buckets.setdefault(_stratum(r["route"], r["title"]), []).append(r)

    manifest, stats = [], {}
    for strat, want in TARGET.items():
        taken = 0
        for r in sorted(buckets.get(strat, []), key=lambda r: r["id"]):
            if taken >= want:
                break
            cache_p = _cache_root() / "enrichment-raws" / r["skey"]
            path = cache_p if cache_p.exists() else None
            if path is None:
                try:
                    path = local_path("enrichment-raws", r["skey"])
                except Exception:
                    path = None
            if path is None or not path.exists():
                continue
            manifest.append({
                "source_image_id": r["id"], "title": r["title"], "target_eurio_id": r["target"],
                "route_decision": r["route"], "is_lot_suspected": int(r["lot"] or 0),
                "n_crops": r["n_crops"], "stratum": strat, "raw_path": str(path),
            })
            taken += 1
        stats[strat] = {"available": len(buckets.get(strat, [])), "taken": taken}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    for k, v in stats.items():
        print(f"  {k:16s} avail={v['available']:4d}  taken={v['taken']}")
    print(f"TOTAL {len(manifest)} items -> {out}")


if __name__ == "__main__":
    main()
