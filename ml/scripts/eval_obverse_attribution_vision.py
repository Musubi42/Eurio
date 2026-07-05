"""Éval vision du filtrage eBay → design_group avers (exploratoire).

Pour chaque groupe avers d'un pays, échantillonne les crops eBay qui lui sont
ATTRIBUÉS (via ``source_images.target_eurio_id`` → groupe) et demande à Claude de
classer chaque crop (cf. ``foundation.standard_gate_review`` pour le contrat) :
``correct`` / ``wrong_era`` / ``wrong_coin`` / ``junk`` / ``reverse_cant_tell``.

Mesure si « cette histoire de design_group » filtre correctement. LECTURE SEULE
(n'écrit rien — voir ``scripts.gate_standard_vision`` pour l'action de rejet).
ccproxy = service global partagé (port 3042, ``task -g global:ccproxy:start``).

Usage :
    python -m scripts.eval_obverse_attribution_vision --country BE --per-group 8
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from shared import ccproxy_client  # noqa: E402
from training.foundation.claude_review import DEFAULT_MODEL_ALIAS, MODELS  # noqa: E402
from training.foundation.obverse_group_review import canonical_obverse_path  # noqa: E402
from training.foundation.standard_gate_review import classify_crop  # noqa: E402
from shared.storage.local_cache import local_path  # noqa: E402
from store import resolve_db_path  # noqa: E402

DEFAULT_DB = resolve_db_path(ML_DIR / "state" / "eurio.db")


def _open_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _groups(conn: sqlite3.Connection, country: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT COALESCE(c.design_group_id, c.eurio_id) AS grp,
               dg.designation AS designation,
               MIN(c.year) AS y0, MAX(c.year) AS y1,
               GROUP_CONCAT(c.numista_id) AS ref_numistas
          FROM coins c
          LEFT JOIN design_groups dg ON dg.id = c.design_group_id
         WHERE c.country = ? AND c.is_commemorative = 0 AND c.canonical_eurio_id IS NULL
         GROUP BY grp
         ORDER BY y0
        """,
        (country.upper(),),
    ).fetchall()


def _canon_paths(ref_numistas: str | None) -> list[Path]:
    paths: list[Path] = []
    for nid in (ref_numistas or "").split(","):
        nid = nid.strip()
        if not nid:
            continue
        p = canonical_obverse_path(int(nid))
        if p is not None:
            paths.append(p)
    return paths


def _crops_for_group(conn: sqlite3.Connection, country: str, grp: str, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT ia.storage_path, si.listing_title
          FROM image_assets ia
          JOIN source_images si ON si.id = ia.source_image_id
          JOIN coins c ON c.eurio_id = si.target_eurio_id
         WHERE si.source = 'ebay' AND c.country = ?
           AND c.is_commemorative = 0
           AND COALESCE(c.design_group_id, c.eurio_id) = ?
           AND ia.storage_path IS NOT NULL
         ORDER BY ia.fetched_at DESC
         LIMIT ?
        """,
        (country.upper(), grp, limit),
    ).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", required=True)
    parser.add_argument("--per-group", type=int, default=8)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--model", default=DEFAULT_MODEL_ALIAS, choices=list(MODELS))
    parser.add_argument("--base-url", default=ccproxy_client.DEFAULT_BASE_URL)
    args = parser.parse_args()

    try:
        ccproxy_client.health(args.base_url)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ ccproxy injoignable ({exc}).")
        return 2

    conn = _open_ro(Path(args.db))
    groups = _groups(conn, args.country)
    total_cost = 0.0

    for g in groups:
        canon = _canon_paths(g["ref_numistas"])
        crops = _crops_for_group(conn, args.country, g["grp"], args.per_group)
        rng = f"{g['y0']}" if g["y0"] == g["y1"] else f"{g['y0']}-{g['y1']}"
        print(f"\n■ {g['grp']} — {g['designation'] or '(sans designation)'} [{rng}] — {len(crops)} crop(s)")
        if not canon:
            print("  ✗ avers canonique introuvable — groupe sauté")
            continue
        tally: Counter[str] = Counter()
        for cr in crops:
            try:
                crop_path = local_path("enrichment-crops", cr["storage_path"])
            except Exception as exc:  # noqa: BLE001
                tally["unresolved"] += 1
                print(f"    · crop non résolu: {exc}")
                continue
            v = classify_crop(
                canonical_paths=canon, crop_path=crop_path,
                group_label=g["designation"] or g["grp"], year_range=rng,
                listing_title=cr["listing_title"] or "",
                model_alias=args.model, base_url=args.base_url,
            )
            total_cost += v.cost_usd
            label = v.error or v.label
            tally[label] += 1
            confs = f"{v.confidence:.2f}" if v.confidence is not None else "?"
            print(f"    {label:18} conf={confs}  «{(cr['listing_title'] or '')[:60]}»")
        good = tally["correct"] + tally["reverse_cant_tell"]
        bad = tally["wrong_era"] + tally["wrong_coin"] + tally["junk"]
        n = sum(tally.values())
        print(f"  → {dict(tally)}  (correct+revers={good}/{n}, mal-filtré={bad})")

    print(f"\nCoût total ≈ ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
