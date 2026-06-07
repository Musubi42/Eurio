"""One-shot script — re-run detect_crop on existing eBay source_images.

Usage::

    cd ml
    python -m scripts.recrop_ebay_orphans            # exec
    python -m scripts.recrop_ebay_orphans --dry      # preview only
    python -m scripts.recrop_ebay_orphans --limit 5  # process N source_images

Pré-requis : avoir d'abord exécuté ``docs/sources-refacto/cleanup-ebay-crops.sql``
qui supprime les image_assets non-manual et reset ``pipeline_state='downloaded'``.
Ce script reprend ces source_images et les fait passer par le nouveau
pipeline multi-Hough (chunk 1).

Pas de re-download : le script utilise les raws déjà sur disque
(``ml/state/sources/ebay/raw/<sharded>/<source_ref>.jpg``).

Aussi : nettoie les crop files orphelins sur disque qui ne correspondent
plus à un image_asset existant (``ml/state/sources/ebay/crops/...``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Path setup pour pouvoir lancer en `python -m scripts.recrop_ebay_orphans`
_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from sources._base.run_logger import start_run  # noqa: E402
from sources._base.steps.detect_crop import run_detect_crop  # noqa: E402
from store import Store  # noqa: E402

_SOURCE_ID = "ebay"


def _list_orphans(conn) -> dict[str, str]:
    """Charge les source_images eBay au state 'downloaded' (= candidats recrop).

    Renvoie ``{source_ref: source_image_id}`` (forme attendue par
    ``run_detect_crop``).
    """
    rows = conn.execute(
        """
        SELECT si.id AS id, si.source_ref AS source_ref
          FROM source_images si
          JOIN discovery_log dl
            ON dl.source = si.source AND dl.source_ref = si.source_ref
         WHERE si.source = ? AND dl.pipeline_state = 'downloaded'
         ORDER BY si.fetched_at ASC
        """,
        (_SOURCE_ID,),
    ).fetchall()
    return {row["source_ref"]: row["id"] for row in rows}


def _cleanup_orphan_crop_files(conn) -> int:
    """DEPRECATED post-SS-1 (write-through MinIO).

    L'ancien comportement scannait `ml/state/sources/ebay/crops/*.png` pour
    supprimer les fichiers orphelins (non référencés en DB). Avec le
    write-through, plus de FS local — les crops vivent dans le bucket
    `enrichment-crops`. Le cleanup orphan MinIO se fait via
    `scripts/cascade_sync.py audit`, pas ici.
    """
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="preview only, no changes")
    ap.add_argument("--limit", type=int, default=None, help="process at most N source_images")
    ap.add_argument("--no-fs-cleanup", action="store_true",
                    help="skip orphan crop file deletion")
    args = ap.parse_args()

    db_path = _ML_DIR / "state" / "eurio.db"
    if not db_path.is_file():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 1

    store = Store(db_path)
    conn = store._connection()

    orphans = _list_orphans(conn)
    if args.limit is not None:
        orphans = dict(list(orphans.items())[: args.limit])

    print(f"[ebay-recrop] {len(orphans)} source_images at state='downloaded' to recrop")

    if not args.no_fs_cleanup:
        print("[ebay-recrop] FS cleanup skipped (post SS-1 write-through MinIO — "
              "use cascade_sync audit for orphan cleanup)")

    if args.dry:
        print("[ebay-recrop] DRY RUN — no detect_crop calls.")
        for sref in list(orphans)[:10]:
            print(f"  would recrop: {sref}")
        if len(orphans) > 10:
            print(f"  … and {len(orphans) - 10} more")
        return 0

    if not orphans:
        print("[ebay-recrop] nothing to do.")
        return 0

    with start_run(conn, source=_SOURCE_ID, kind="reset",
                   filters={"reason": "multi-hough recrop", "n_targets": len(orphans)}) as run:
        run.set_step("detect")
        result = run_detect_crop(
            conn=conn,
            run=run,
            source_id=_SOURCE_ID,
            source_image_ids=orphans,
        )
        run.end("success")

    print(
        f"[ebay-recrop] done · "
        f"crops_added={result.n_crops_added} skipped={result.n_skipped} "
        f"errors={result.n_errors} auto_phash={result.n_auto_phash}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
