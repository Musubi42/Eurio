"""teardown_census_run.py — supprime proprement les crops d'un run census-recover.

Pour re-rouler `recrop_cohort_census` avec une probe/τ différents, il faut d'abord
retirer les crops du run précédent — sinon les raws ne sont plus « 0 crop présent »
et seraient skippés (scope additif).

Supprime, pour un `run_id` donné : l'objet MinIO + le cache de chaque crop, puis la
ligne `image_assets` (CASCADE → review_queue + image_asset_dino_predictions des
crops). Remet les `source_images` concernés en `crop_status='zero_crops'` (cohérent :
0 crop présent). Ces crops sont des récup bot jamais entrées en training
(`training_eligible=0`) → suppression sans perte de travail humain.

Dry-run par défaut, `--commit` pour exécuter.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/teardown_census_run.py --run census-recover-b0299ca0252b --commit
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ML_DIR / "state" / "eurio.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    from storage import _client
    from storage.local_cache import _cache_root

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, storage_path, source_image_id FROM image_assets WHERE run_id = ?",
        (args.run,),
    ).fetchall()
    sids = {r["source_image_id"] for r in rows}
    te = conn.execute(
        "SELECT COUNT(*) FROM image_assets WHERE run_id = ? AND training_eligible = 1",
        (args.run,),
    ).fetchone()[0]
    print(f"Run {args.run} : {len(rows)} crops, {len(sids)} source_images, "
          f"{te} training_eligible=1")
    if te:
        print("⚠️  des crops sont training_eligible=1 — ABANDON (perte de review humaine).")
        return 1
    if not args.commit:
        print("[DRY-RUN] rien supprimé. Relancer avec --commit.")
        return 0

    client = _client()
    cache = _cache_root() / "enrichment-crops"
    n_obj = 0
    for r in rows:
        if r["storage_path"]:
            try:
                client.delete_object(Bucket="enrichment-crops", Key=r["storage_path"])
                n_obj += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  warn MinIO delete {r['storage_path']}: {exc}")
            (cache / r["storage_path"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM image_assets WHERE run_id = ?", (args.run,))
    for sid in sids:
        conn.execute(
            "UPDATE source_images SET crop_status='zero_crops', n_crops_detected=0 WHERE id=?",
            (sid,))
    conn.commit()
    print(f"[COMMITTÉ] {len(rows)} lignes image_assets supprimées (CASCADE review_queue/"
          f"dino_predictions), {n_obj} objets MinIO purgés, {len(sids)} source_images "
          f"remis en zero_crops.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
