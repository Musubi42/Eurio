"""Anchor banks: pre-computed obverse embeddings for the catalog.

An ``AnchorBank`` is a fixed set of (eurio_id, vec) pairs derived from
canonical Numista obverse images, packaged as a single .npz file under
``ml/state/foundation_anchors_<kind>.npz``. The auto-validation
pipeline encodes each scraped crop and matches it against the loaded
bank to produce top-K suggestions.

Scopes (anchors_kind):
  - ``2eur_commemo`` — V1 scope: all 2€ commemoratives in the local
    coins table that have a numista_id and a ``ml/datasets/<nid>/obverse.jpg``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from training.foundation.encoder import (
    DEFAULT_ENCODER_VERSION,
    build_transform,
    encode_paths,
    load_encoder,
)

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = ML_DIR / "state"
DATASETS_DIR = ML_DIR / "datasets"


@dataclass
class AnchorBank:
    eurio_ids: list[str]
    matrix: np.ndarray  # (N, D) float32, L2-normalized
    encoder_version: str
    anchors_kind: str
    built_at: str
    source_paths: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.eurio_ids)

    @property
    def dim(self) -> int:
        return int(self.matrix.shape[1]) if self.matrix.size else 0


def anchor_path(kind: str) -> Path:
    return STATE_DIR / f"foundation_anchors_{kind}.npz"


def save_anchors(bank: AnchorBank) -> Path:
    path = anchor_path(bank.anchors_kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = json.dumps(
        {
            "encoder_version": bank.encoder_version,
            "anchors_kind": bank.anchors_kind,
            "built_at": bank.built_at,
            "count": bank.count,
            "dim": bank.dim,
        }
    )
    np.savez(
        path,
        matrix=bank.matrix,
        eurio_ids=np.array(bank.eurio_ids, dtype=np.str_),
        source_paths=np.array(bank.source_paths, dtype=np.str_),
        meta=np.array([meta], dtype=np.str_),
    )
    logger.info(
        "Saved %d anchors (%s, dim=%d) → %s",
        bank.count, bank.anchors_kind, bank.dim, path,
    )
    return path


def load_anchors(kind: str) -> AnchorBank | None:
    path = anchor_path(kind)
    if not path.exists():
        return None
    npz = np.load(path, allow_pickle=False)
    meta_raw = npz["meta"][0] if npz["meta"].size else "{}"
    meta = json.loads(str(meta_raw))
    return AnchorBank(
        eurio_ids=[str(x) for x in npz["eurio_ids"].tolist()],
        matrix=np.asarray(npz["matrix"], dtype=np.float32),
        encoder_version=meta.get("encoder_version", DEFAULT_ENCODER_VERSION),
        anchors_kind=meta.get("anchors_kind", kind),
        built_at=meta.get("built_at", ""),
        source_paths=[str(x) for x in npz["source_paths"].tolist()]
        if "source_paths" in npz.files
        else [],
    )


# ---------------------------------------------------------------------------
# Bank builders (one per anchors_kind)
# ---------------------------------------------------------------------------


def _select_2eur_commemo(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Pick all 2€ commemoratives with a numista_id, sorted stable by eurio_id."""
    rows = conn.execute(
        """
        SELECT eurio_id, numista_id, country, year, theme
          FROM coins
         WHERE face_value = 2.0
           AND is_commemorative = 1
           AND numista_id IS NOT NULL
         ORDER BY eurio_id ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _resolve_obverse_path(numista_id: int, datasets_dir: Path) -> Path | None:
    candidate = datasets_dir / str(numista_id) / "obverse.jpg"
    return candidate if candidate.exists() else None


def build_anchors_2eur_commemo(
    *,
    conn: sqlite3.Connection,
    datasets_dir: Path = DATASETS_DIR,
    encoder_version: str = DEFAULT_ENCODER_VERSION,
    force_recompute: bool = False,
) -> AnchorBank:
    """Encode all 2€ commemorative obverses available on disk into a fresh bank.

    If a cache exists at ``anchor_path('2eur_commemo')`` and
    ``force_recompute=False``, returns it as-is. Otherwise encodes from
    scratch and writes the new ``.npz``.
    """
    kind = "2eur_commemo"

    if not force_recompute:
        cached = load_anchors(kind)
        if cached is not None and cached.encoder_version == encoder_version:
            logger.info(
                "Anchors cache hit (%s, %d entries, encoder=%s) — skipping rebuild",
                kind, cached.count, cached.encoder_version,
            )
            return cached

    coins = _select_2eur_commemo(conn)
    logger.info("Selected %d 2€ commemorative coins from DB", len(coins))

    paths_with_eid: list[tuple[str, Path]] = []
    skipped_no_obverse = 0
    for c in coins:
        nid = c["numista_id"]
        path = _resolve_obverse_path(int(nid), datasets_dir)
        if path is None:
            skipped_no_obverse += 1
            continue
        paths_with_eid.append((c["eurio_id"], path))

    if skipped_no_obverse:
        logger.info(
            "Skipped %d coins (no obverse.jpg under %s/<numista>/)",
            skipped_no_obverse, datasets_dir,
        )

    if not paths_with_eid:
        raise RuntimeError(
            f"No 2€ commemorative obverse found under {datasets_dir} — "
            "did you bootstrap the dataset?"
        )

    logger.info("Encoding %d obverse images via DINOv2…", len(paths_with_eid))
    encoder, device = load_encoder()
    transform = build_transform()
    paths = [p for _, p in paths_with_eid]
    eids_in_order = [e for e, _ in paths_with_eid]
    kept_paths, matrix = encode_paths(
        paths, encoder=encoder, device=device, transform=transform
    )

    # Re-align eurio_ids to the kept_paths order (in case some failed to load).
    kept_set = {str(p): True for p in kept_paths}
    aligned_eids: list[str] = []
    aligned_paths: list[str] = []
    for eid, path in paths_with_eid:
        if str(path) in kept_set:
            aligned_eids.append(eid)
            aligned_paths.append(str(path))

    bank = AnchorBank(
        eurio_ids=aligned_eids,
        matrix=matrix,
        encoder_version=encoder_version,
        anchors_kind=kind,
        built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_paths=aligned_paths,
    )
    save_anchors(bank)
    return bank
