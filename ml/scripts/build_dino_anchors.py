"""Bootstrap DINOv2 anchor banks from canonical Numista obverses.

Picks coins from the local SQLite catalog (`coins` table) according to
the requested scope, encodes their `<datasets>/<numista_id>/obverse.jpg`
through DINOv2 ViT-S/14, and writes the bank to
`ml/state/foundation_anchors_<kind>.npz`.

Usage:
    .venv/bin/python -m scripts.build_dino_anchors                # 2eur_commemo, cache hit OK
    .venv/bin/python -m scripts.build_dino_anchors --force        # force recompute
    .venv/bin/python -m scripts.build_dino_anchors --kind 2eur_commemo
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from training.foundation.anchors import (  # noqa: E402
    DATASETS_DIR,
    build_anchors_2eur_all,
    build_anchors_2eur_commemo,
    build_anchors_2eur_standard,
    load_anchors,
)
from store import Store  # noqa: E402

DB_PATH = ML_DIR / "state" / "eurio.db"

_BUILDERS = {
    "2eur_commemo": build_anchors_2eur_commemo,
    "2eur_standard": build_anchors_2eur_standard,
    "2eur_all": build_anchors_2eur_all,
}


def _build_dispatcher(kind: str, store: Store, force: bool):
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise ValueError(f"Unknown anchors kind: {kind!r}")
    with store._writing() as conn:  # noqa: SLF001 — we only read here
        return builder(
            conn=conn,
            datasets_dir=DATASETS_DIR,
            force_recompute=force,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        default="2eur_commemo",
        choices=sorted(_BUILDERS),
        help="Anchor scope (default: 2eur_commemo).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even if the .npz cache exists.",
    )
    parser.add_argument(
        "--db",
        default=str(DB_PATH),
        help="Path to the training SQLite DB (default: ml/state/eurio.db).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    # Always echo INFO from the foundation module to give visibility on
    # this CLI.
    logging.getLogger("training.foundation").setLevel(logging.INFO)

    store = Store(Path(args.db))
    t0 = time.perf_counter()
    bank = _build_dispatcher(args.kind, store, args.force)
    dt = time.perf_counter() - t0

    print(f"\nKind:        {bank.anchors_kind}")
    print(f"Encoder:     {bank.encoder_version}")
    print(f"Built at:    {bank.built_at}")
    print(f"Anchors:     {bank.count}")
    print(f"Dim:         {bank.dim}")
    print(f"Path:        {ML_DIR / 'state' / f'foundation_anchors_{bank.anchors_kind}.npz'}")
    print(f"Total time:  {dt:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
