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
from sources._base.storage import storage_root  # noqa: E402
from state import Store  # noqa: E402

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
    """Supprime les .png crops sur disque qui ne référencent plus d'image_asset.

    Le SQL cleanup a vidé image_assets non-manual mais a laissé les fichiers
    .png orphelins sur disque. On les enlève ici. ``image_assets.storage_path``
    est la source de vérité — tout fichier .png absent de cette colonne est
    orphelin.
    """
    crops_dir = storage_root() / _SOURCE_ID / "crops"
    if not crops_dir.is_dir():
        return 0
    referenced = {
        Path(row["storage_path"]).resolve()
        for row in conn.execute(
            """
            SELECT ia.storage_path FROM image_assets ia
              JOIN source_images si ON si.id = ia.source_image_id
             WHERE si.source = ? AND ia.storage_path IS NOT NULL
            """,
            (_SOURCE_ID,),
        ).fetchall()
    }
    removed = 0
    for f in crops_dir.rglob("*.png"):
        if f.resolve() not in referenced:
            f.unlink()
            removed += 1
    return removed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="preview only, no changes")
    ap.add_argument("--limit", type=int, default=None, help="process at most N source_images")
    ap.add_argument("--no-fs-cleanup", action="store_true",
                    help="skip orphan crop file deletion")
    args = ap.parse_args()

    db_path = _ML_DIR / "state" / "training.db"
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
        if args.dry:
            crops_dir = storage_root() / _SOURCE_ID / "crops"
            n_files = sum(1 for _ in crops_dir.rglob("*.png")) if crops_dir.is_dir() else 0
            print(f"[ebay-recrop] would scan {n_files} crop .png files for orphan cleanup")
        else:
            removed = _cleanup_orphan_crop_files(conn)
            print(f"[ebay-recrop] removed {removed} orphan crop .png files")

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
