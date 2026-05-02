"""Copy ``ml/prod/current/`` artefacts → ``app-android/src/main/assets/``.

Phase 4 (lab-prod-refacto). Until now, the prod APK assets under
``app-android/src/main/assets/{models,data}/`` were updated by hand — by
copying from the floating ``ml/output/`` mirror, which reflected
"whatever iteration ran last". After phase 3, ``prod/current/`` is the
canonical state of the deployed model. This script bridges the gap :
exactly one command refreshes the prod APK assets from the promoted
state.

Files written :

    app-android/src/main/assets/models/eurio_embedder_v1.tflite
    app-android/src/main/assets/data/coin_embeddings.json
    app-android/src/main/assets/data/model_meta.json

Usage::

    .venv/bin/python -m scripts.promote_prod_assets [--dry-run]

Refuses if ``ml/prod/current/`` is missing (no promotion has happened
yet). The fix is to run ``python -m scripts.promote_iteration <iid>``
first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_DIR.parent
PROD_CURRENT = ML_DIR / "prod" / "current"
ANDROID_ASSETS = REPO_ROOT / "app-android" / "src" / "main" / "assets"

# (source under prod/current, destination under app-android/src/main/assets)
COPIES: list[tuple[Path, Path]] = [
    (
        PROD_CURRENT / "tflite" / "eurio_embedder_v1.tflite",
        ANDROID_ASSETS / "models" / "eurio_embedder_v1.tflite",
    ),
    (
        PROD_CURRENT / "embeddings" / "coin_embeddings.json",
        ANDROID_ASSETS / "data" / "coin_embeddings.json",
    ),
    (
        PROD_CURRENT / "tflite" / "model_meta.json",
        ANDROID_ASSETS / "data" / "model_meta.json",
    ),
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be copied without touching the filesystem.",
    )
    args = parser.parse_args()

    if not PROD_CURRENT.is_dir():
        print(
            f"error: {PROD_CURRENT.relative_to(REPO_ROOT)} missing.\n"
            "  Run a promotion first :\n"
            "    .venv/bin/python -m scripts.promote_iteration <iteration_id>",
            file=sys.stderr,
        )
        return 2

    promoted_meta = PROD_CURRENT / "promoted_from.json"
    promoted_info = {}
    if promoted_meta.exists():
        try:
            promoted_info = json.loads(promoted_meta.read_text())
        except (json.JSONDecodeError, OSError):
            promoted_info = {}

    print(json.dumps({
        "prod_current": str(PROD_CURRENT.relative_to(REPO_ROOT)),
        "promoted_from": {
            "iteration_id": promoted_info.get("iteration_id"),
            "promoted_at": promoted_info.get("promoted_at"),
            "verdict": promoted_info.get("verdict"),
        },
        "dry_run": args.dry_run,
    }, indent=2))

    missing_sources = [src for (src, _) in COPIES if not src.exists()]
    if missing_sources:
        print(
            "error: missing prod artefacts: "
            + ", ".join(str(p.relative_to(REPO_ROOT)) for p in missing_sources)
            + "\n  prod/current/ is corrupt — re-run promotion or restore from "
              "prod/archive/.",
            file=sys.stderr,
        )
        return 3

    for src, dst in COPIES:
        rel = dst.relative_to(REPO_ROOT)
        if args.dry_run:
            print(f"  would copy {src.relative_to(REPO_ROOT)} → {rel}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  {rel}  sha256={_sha256(dst)[:12]}")

    if args.dry_run:
        return 0
    print(
        "OK · prod APK assets refreshed. "
        "Rebuild the prod APK to ship the new model."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
