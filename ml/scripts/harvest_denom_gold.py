"""Récolte C7 pilier 2 — enrichit le gold denom depuis les sources de labels.

La boucle rétroactive vit ici : chaque tour verse de nouveaux labels dans
``denom_gold.jsonl`` puis ré-entraîne la probe (`train_denom_probe.py`).
Sources supportées :

- ``--labels FICHIER.jsonl`` : passe visuelle (Claude ou humaine) — lignes
  ``{"asset_id", "label": pos|neg|unk, "kind"?, "conf": hi|lo, "face"?, "note"?}``.
  Le ``sp`` (storage_path) est résolu depuis la DB. ``--source``/``--labeled-by``
  taguent la provenance.
- ``--review-admin`` : positifs vérité terrain = reviews ``done`` tranchées par
  un humain (``decided_by='admin'``) avec une identité décidée → ``pos/hi``.
  (Les rejets admin sans identité ne sont PAS récoltés : motif ambigu —
  junk OU vrai 2€ de mauvaise qualité.)

Merge non-destructif par ``asset_id`` (pattern `_seed_denom_gold`) : le gold
existant est préservé ; en cas de doublon entre sources du run, la vérité
humaine (`--review-admin`) prime sur une passe visuelle. Idempotent.

Après récolte : supprimer ``gold_vitl14.npz`` n'est PAS nécessaire —
`train_denom_probe._load_embeddings` détecte le désalignement et ré-encode.

Usage :
  python -m scripts.harvest_denom_gold --labels /tmp/labels.jsonl \
      --source reject-audit-172 --labeled-by claude-visual-2026-06-13 \
      --review-admin
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ML_DIR / "state" / "eurio.db"
GOLD = ML_DIR / "state" / "denom_bench" / "denom_gold.jsonl"

REVIEW_ADMIN_SQL = """
SELECT ia.id AS asset_id, ia.storage_path AS sp
FROM image_assets ia
JOIN review_queue rq ON rq.image_asset_id = ia.id
WHERE rq.status = 'done' AND rq.decided_by = 'admin'
  AND rq.decided_eurio_id IS NOT NULL AND ia.storage_path IS NOT NULL
"""


def _load_visual_labels(path: Path, source: str, labeled_by: str,
                        conn: sqlite3.Connection) -> dict[str, dict]:
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    sp_by_id = {
        r[0]: r[1] for r in conn.execute(
            "SELECT id, storage_path FROM image_assets WHERE storage_path IS NOT NULL")
    }
    out = {}
    for r in rows:
        aid = r["asset_id"]
        if aid not in sp_by_id:
            print(f"  skip {aid} : storage_path introuvable en DB")
            continue
        entry = {"asset_id": aid, "sp": sp_by_id[aid], "label": r["label"],
                 "kind": r.get("kind"), "conf": r.get("conf", "lo"),
                 "source": source, "labeled_by": labeled_by}
        if r.get("face"):
            entry["face"] = r["face"]
        if r.get("note"):
            entry["note"] = r["note"]
        out[aid] = entry
    return out


def _load_review_admin(conn: sqlite3.Connection) -> dict[str, dict]:
    return {
        r["asset_id"]: {"asset_id": r["asset_id"], "sp": r["sp"], "label": "pos",
                        "kind": None, "conf": "hi", "source": "review-admin",
                        "labeled_by": "human-review"}
        for r in (dict(zip(("asset_id", "sp"), row))
                  for row in conn.execute(REVIEW_ADMIN_SQL))
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, action="append", default=[],
                    help="JSONL d'une passe visuelle (répétable)")
    ap.add_argument("--source", default="visual-pass")
    ap.add_argument("--labeled-by", default="claude-visual")
    ap.add_argument("--review-admin", action="store_true",
                    help="récolter les positifs review humaine (decided_by=admin)")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    fresh: dict[str, dict] = {}
    for p in args.labels:
        got = _load_visual_labels(p, args.source, args.labeled_by, conn)
        print(f"{p} : {len(got)} labels")
        fresh.update(got)
    if args.review_admin:
        admin = _load_review_admin(conn)
        print(f"review-admin : {len(admin)} positifs humains")
        fresh.update(admin)  # l'humain prime sur la passe visuelle

    existing = []
    if GOLD.exists():
        existing = [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]
    seen = {o["asset_id"] for o in existing}
    added = [v for k, v in fresh.items() if k not in seen]
    dupes = len(fresh) - len(added)
    merged = existing + added

    print(f"gold : {len(existing)} existants · +{len(added)} nouveaux "
          f"({dupes} doublons préservés côté gold)")
    print("label :", dict(Counter(o["label"] for o in merged)))
    print("neg kind :", dict(Counter(o.get("kind") for o in merged
                                     if o["label"] == "neg")))
    if args.dry:
        print("DRY — rien écrit.")
        return 0
    GOLD.write_text("\n".join(json.dumps(o) for o in merged) + "\n")
    print(f"→ {GOLD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
