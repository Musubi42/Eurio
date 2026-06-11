"""Anchor banks: pre-computed obverse embeddings for the catalog.

An ``AnchorBank`` is a fixed set of (eurio_id, vec) pairs derived from
canonical Numista obverse images, packaged as a single .npz file under
``ml/state/foundation_anchors_<kind>.npz``. The auto-validation
pipeline encodes each scraped crop and matches it against the loaded
bank to produce top-K suggestions.

Scopes (anchors_kind):
  - ``2eur_commemo`` — V1 scope: all 2€ commemoratives in the local
    coins table that have a numista_id and a ``ml/datasets/<nid>/obverse.jpg``.
  - ``2eur_standard`` — one anchor per *design group* of 2€ courantes
    (avers national partagé) ; l'eurio_id de l'ancre = le représentant
    (plus ancien millésime, même convention que la review), l'image =
    le premier membre du groupe avec un obverse.jpg sur disque.
  - ``2eur_all`` — concat des deux banques ci-dessus (mêmes embeddings,
    pas de ré-encodage). C'est la banque des SUGGESTIONS review ; le
    consensus/lanes reste calibré sur ``2eur_commemo``.
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
    SUGGESTIONS_ENCODER_VERSION,
    build_transform,
    encode_paths,
    load_encoder,
)

logger = logging.getLogger(__name__)

# anchors.py vit dans ml/training/foundation/ → remonter 3 niveaux pour ml/.
# (Bug historique : .parent.parent pointait sur ml/training/ → STATE_DIR =
# ml/training/state inexistant → la banque d'ancres ne se chargeait plus à la
# demande, et tout recompute Dino — sync, scrape — skippait en silence.)
ML_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ML_DIR / "state"
DATASETS_DIR = ML_DIR / "datasets"

# Kind par défaut pour les SUGGESTIONS review (banque large commémo +
# courantes). Le consensus / les lanes restent sur ``2eur_commemo`` — la
# règle C0–C5 a été calibrée sur ce scope, ne pas la déplacer sans re-replay.
SUGGESTIONS_ANCHORS_KIND = "2eur_all"
CONSENSUS_ANCHORS_KIND = "2eur_commemo"

# Encodeur par kind : les suggestions tournent sur vitl14 (+22 pts recall@1,
# bench Phase 2.4 dino-suggestions) ; le consensus reste sur vits14 (seuils
# C0–C5 calibrés sur ses sims — re-replay gold requis avant toute bascule).
ENCODER_VERSION_FOR_KIND = {
    CONSENSUS_ANCHORS_KIND: DEFAULT_ENCODER_VERSION,
    SUGGESTIONS_ANCHORS_KIND: SUGGESTIONS_ENCODER_VERSION,
    "2eur_standard": DEFAULT_ENCODER_VERSION,
}


def encoder_version_for_kind(kind: str) -> str:
    return ENCODER_VERSION_FOR_KIND.get(kind, DEFAULT_ENCODER_VERSION)


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


def _select_2eur_standard_groups(
    conn: sqlite3.Connection,
) -> list[list[dict[str, Any]]]:
    """Les 2€ courantes groupées par design group (avers partagé).

    Une liste de membres par groupe, triés (year, eurio_id) — le premier
    est le représentant (même convention que ``_fetch_standard_candidates``
    côté review : c'est son eurio_id qui est écrit à la décision).
    """
    rows = conn.execute(
        """
        SELECT c.eurio_id, c.numista_id, c.country, c.year,
               COALESCE(c.design_group_id, c.eurio_id) AS class_id
          FROM coins c
         WHERE c.face_value = 2.0
           AND c.is_commemorative = 0
           AND c.canonical_eurio_id IS NULL
         ORDER BY c.year ASC, c.eurio_id ASC
        """
    ).fetchall()
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r["class_id"], []).append(dict(r))
    # Ordre stable par eurio_id du représentant.
    return sorted(groups.values(), key=lambda members: members[0]["eurio_id"])


def _commemo_paths_with_eid(
    conn: sqlite3.Connection, datasets_dir: Path
) -> list[tuple[str, Path]]:
    """(eurio_id, obverse_path) pour toutes les 2€ commémo avec image."""
    coins = _select_2eur_commemo(conn)
    logger.info("Selected %d 2€ commemorative coins from DB", len(coins))
    out: list[tuple[str, Path]] = []
    skipped = 0
    for c in coins:
        path = _resolve_obverse_path(int(c["numista_id"]), datasets_dir)
        if path is None:
            skipped += 1
            continue
        out.append((c["eurio_id"], path))
    if skipped:
        logger.info(
            "Skipped %d coins (no obverse.jpg under %s/<numista>/)",
            skipped, datasets_dir,
        )
    return out


def _standard_paths_with_eid(
    conn: sqlite3.Connection, datasets_dir: Path
) -> list[tuple[str, Path]]:
    """(eurio_id du représentant, obverse_path) par design group standard.

    L'image peut venir de n'importe quel membre du groupe (même avers par
    définition) — premier membre avec un ``obverse.jpg`` sur disque.
    """
    groups = _select_2eur_standard_groups(conn)
    logger.info("Selected %d standard 2€ design groups from DB", len(groups))
    out: list[tuple[str, Path]] = []
    skipped = 0
    for members in groups:
        rep_eid = members[0]["eurio_id"]
        image_path: Path | None = None
        for m in members:
            if m["numista_id"] is None:
                continue
            image_path = _resolve_obverse_path(int(m["numista_id"]), datasets_dir)
            if image_path is not None:
                break
        if image_path is None:
            skipped += 1
            logger.warning(
                "No obverse.jpg for any member of standard group rep=%s "
                "(%d members) — group has no anchor",
                rep_eid, len(members),
            )
            continue
        out.append((rep_eid, image_path))
    if skipped:
        logger.info(
            "Skipped %d standard groups (no obverse.jpg for any member under %s)",
            skipped, datasets_dir,
        )
    return out


def _encode_and_save(
    *,
    kind: str,
    paths_with_eid: list[tuple[str, Path]],
    encoder_version: str,
) -> AnchorBank:
    """Encode une liste (eurio_id, image_path) et persiste la banque."""
    logger.info(
        "Encoding %d obverse images via DINOv2 %s (%s)…",
        len(paths_with_eid), encoder_version, kind,
    )
    encoder, device = load_encoder(encoder_version=encoder_version)
    transform = build_transform()
    paths = [p for _, p in paths_with_eid]
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

    paths_with_eid = _commemo_paths_with_eid(conn, datasets_dir)
    if not paths_with_eid:
        raise RuntimeError(
            f"No 2€ commemorative obverse found under {datasets_dir} — "
            "did you bootstrap the dataset?"
        )

    return _encode_and_save(
        kind=kind, paths_with_eid=paths_with_eid, encoder_version=encoder_version
    )


def build_anchors_2eur_standard(
    *,
    conn: sqlite3.Connection,
    datasets_dir: Path = DATASETS_DIR,
    encoder_version: str = DEFAULT_ENCODER_VERSION,
    force_recompute: bool = False,
) -> AnchorBank:
    """Une ancre par design group de 2€ courante (avers national partagé).

    L'eurio_id de l'ancre = le représentant du groupe (plus ancien
    millésime). L'image peut venir de n'importe quel membre du groupe
    (même avers par définition du groupe) — on prend le premier qui a un
    ``obverse.jpg`` sur disque, ce qui rattrape les représentants sans
    dataset (ex. lt/lv/mt 1st type).
    """
    kind = "2eur_standard"

    if not force_recompute:
        cached = load_anchors(kind)
        if cached is not None and cached.encoder_version == encoder_version:
            logger.info(
                "Anchors cache hit (%s, %d entries, encoder=%s) — skipping rebuild",
                kind, cached.count, cached.encoder_version,
            )
            return cached

    paths_with_eid = _standard_paths_with_eid(conn, datasets_dir)
    if not paths_with_eid:
        raise RuntimeError(
            f"No standard 2€ obverse found under {datasets_dir} — "
            "did you bootstrap the dataset?"
        )

    return _encode_and_save(
        kind=kind, paths_with_eid=paths_with_eid, encoder_version=encoder_version
    )


def build_anchors_2eur_all(
    *,
    conn: sqlite3.Connection,
    datasets_dir: Path = DATASETS_DIR,
    encoder_version: str = SUGGESTIONS_ENCODER_VERSION,
    force_recompute: bool = False,
) -> AnchorBank:
    """Banque unifiée = commémo + standards (banque des SUGGESTIONS review).

    Encode from scratch — son encodeur (vitl14) diffère des sous-banques
    consensus (vits14), un concat serait incohérent. ~550 images, coût
    négligeable vs un backfill.
    """
    kind = "2eur_all"

    if not force_recompute:
        cached = load_anchors(kind)
        if cached is not None and cached.encoder_version == encoder_version:
            logger.info(
                "Anchors cache hit (%s, %d entries, encoder=%s) — skipping rebuild",
                kind, cached.count, cached.encoder_version,
            )
            return cached

    commemo = _commemo_paths_with_eid(conn, datasets_dir)
    standard = _standard_paths_with_eid(conn, datasets_dir)

    overlap = {e for e, _ in commemo} & {e for e, _ in standard}
    if overlap:
        raise RuntimeError(
            f"{len(overlap)} eurio_ids present in both selections "
            f"(ex. {sorted(overlap)[:3]}) — selections must be disjoint"
        )

    paths_with_eid = commemo + standard
    if not paths_with_eid:
        raise RuntimeError(
            f"No 2€ obverse found under {datasets_dir} — "
            "did you bootstrap the dataset?"
        )

    return _encode_and_save(
        kind=kind, paths_with_eid=paths_with_eid, encoder_version=encoder_version
    )
