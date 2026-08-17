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

from shared.verdict_scope import (
    VERDICT_ANCHORS_KIND as _VERDICT_ANCHORS_KIND,
)
from shared.verdict_scope import (
    VERDICT_ENCODER_VERSION as _VERDICT_ENCODER_VERSION,
)
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

# Banque revers commun 2€ (C7 pilier face) : exactement 2 designs (carte v1
# ≤2006, v2 ≥2007), packagés dans l'APK. Sert à détecter qu'un crop montre le
# côté commun (non identifiable) plutôt que l'avers national. Encodée en vitl14
# pour partager l'embedding avec ``2eur_all`` (même ``vec`` au runtime → la
# marge reverse-ness vs obverse-ness est calculable sans ré-encoder).
REVERSE_ANCHORS_KIND = "reverse_2eur"
_REVERSE_ANCHOR_SOURCES = [
    ("reverse_2eur_v1", ML_DIR.parent / "app-android" / "src" / "main"
     / "assets" / "shared_reverse" / "reverse_2eur_v1.webp"),
    ("reverse_2eur_v2", ML_DIR.parent / "app-android" / "src" / "main"
     / "assets" / "shared_reverse" / "reverse_2eur_v2.webp"),
]
# Ancres revers WILD (C7 pilier 1, rappel) : revers eBay vérifiés visuellement,
# curés depuis les `face='reverse'` à margin élevé, dédup par annonce et HORS
# `face_gold.jsonl` (pas de fuite éval). Fichier optionnel : absent, la banque
# retombe sur les 2 canoniques seules. Bench : `scripts/bench_face_recall.py`.
_REVERSE_WILD_FILE = STATE_DIR / "face_bench" / "reverse_wild_anchors.jsonl"

# Encodeur par kind : les suggestions tournent sur vitl14 (+22 pts recall@1,
# bench Phase 2.4 dino-suggestions) ; le consensus reste sur vits14 (seuils
# C0–C5 calibrés sur ses sims — re-replay gold requis avant toute bascule).
ENCODER_VERSION_FOR_KIND = {
    CONSENSUS_ANCHORS_KIND: DEFAULT_ENCODER_VERSION,
    SUGGESTIONS_ANCHORS_KIND: SUGGESTIONS_ENCODER_VERSION,
    "2eur_standard": DEFAULT_ENCODER_VERSION,
    REVERSE_ANCHORS_KIND: SUGGESTIONS_ENCODER_VERSION,
}


def encoder_version_for_kind(kind: str) -> str:
    return ENCODER_VERSION_FOR_KIND.get(kind, DEFAULT_ENCODER_VERSION)


# ─── Scope du VERDICT de review — ré-export du point de bascule unique ──────
#
# La valeur vit dans `shared/verdict_scope.py` (stdlib pure) parce que l'image
# lean du VPS (`serving/review_queue/`) doit la lire sans numpy ni torch. On la
# ré-exporte ici pour que `training.foundation` garde une surface unique.
# Cohérence (kind, encoder) entre les deux modules : vérifiée par
# `tests/test_verdict_anchors_scope.py`.
VERDICT_ANCHORS_KIND = _VERDICT_ANCHORS_KIND
VERDICT_ENCODER_VERSION = _VERDICT_ENCODER_VERSION


@dataclass
class AnchorBank:
    eurio_ids: list[str]
    matrix: np.ndarray  # (N, D) float32, L2-normalized
    encoder_version: str
    anchors_kind: str
    built_at: str
    source_paths: list[str] = field(default_factory=list)
    # improvement-loop B : provenance de chaque ligne. Une classe peut avoir
    # PLUSIEURS lignes (canonique + exemplaires réels FPS) → même eurio_id
    # répété, asset_id distinct. ``None`` = ligne canonique (avers Numista).
    # Vide (banques mono-ancre commemo/standard) ⇒ toutes canoniques.
    asset_ids: list[str | None] = field(default_factory=list)

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
    # asset_ids parallèle aux eurio_ids ("" = ligne canonique). Aligné sur count
    # (les vieilles banques mono-ancre passent []) pour un chargement homogène.
    asset_ids = bank.asset_ids or [None] * bank.count
    np.savez(
        path,
        matrix=bank.matrix,
        eurio_ids=np.array(bank.eurio_ids, dtype=np.str_),
        source_paths=np.array(bank.source_paths, dtype=np.str_),
        asset_ids=np.array([a or "" for a in asset_ids], dtype=np.str_),
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
        asset_ids=[(str(x) or None) for x in npz["asset_ids"].tolist()]
        if "asset_ids" in npz.files
        else [],
    )


# ---------------------------------------------------------------------------
# Sélection d'exemplaires par diversité (improvement-loop B)
# ---------------------------------------------------------------------------

# Plancher de validité : un exemplaire FPS doit rester au moins aussi proche
# du centroïde de sa classe que ce cosinus. Empêche FPS d'aller chercher le
# déchet extrême (crop mal cadré/mal étiqueté = « très nouveau » mais nuisible).
# Diversité À L'INTÉRIEUR d'une boule de validité.
DEFAULT_EXEMPLAR_FLOOR_SIM = 0.45
# Nb max d'exemplaires réels FPS par classe (hors canonique + pins). Le coût de
# calcul est négligeable (un produit matriciel) ; K est borné par la PRÉCISION
# (un exemplaire douteux = faux attracteur), pas par la vitesse.
DEFAULT_EXEMPLARS_PER_CLASS = 10


def farthest_point_select(
    vecs: np.ndarray,
    *,
    candidate_idx: list[int],
    k: int,
    seed_vecs: np.ndarray | None = None,
    floor_sim: float = DEFAULT_EXEMPLAR_FLOOR_SIM,
    centroid: np.ndarray | None = None,
) -> list[tuple[int, float]]:
    """Farthest-Point Sampling dans l'espace d'embedding (pur numpy, testable).

    Choisit jusqu'à ``k`` indices parmi ``candidate_idx`` en maximisant la
    diversité d'apparence : à chaque tour on prend le candidat dont la
    similarité MAX à l'ensemble déjà retenu est la plus basse (le plus
    « nouveau à l'œil de DINO »). ``seed_vecs`` = vecteurs déjà dans l'ensemble
    (canonique + pins) ; s'il est vide, on amorce par le médoïde (candidat le
    plus proche du centroïde = le plus représentatif).

    Plancher de validité : seuls les candidats à cosinus ≥ ``floor_sim`` du
    centroïde de classe sont éligibles — un scan parfait quasi-dupliqué du
    canonique ne sera de toute façon jamais choisi (trop proche du set), et le
    déchet trop lointain est écarté par le plancher.

    ``vecs`` : (N, D) L2-normalisés. Retourne ``[(idx, sim_au_set)]`` du plus
    divers au moins divers (``sim_au_set`` basse = très diversifiant)."""
    if k <= 0 or not candidate_idx:
        return []
    if centroid is None:
        c = vecs[candidate_idx].mean(axis=0)
        norm = float(np.linalg.norm(c))
        centroid = c / norm if norm > 0 else c
    # Plancher de validité.
    pool = [j for j in candidate_idx if float(vecs[j] @ centroid) >= floor_sim]
    if not pool:
        return []

    selected: list[np.ndarray] = []
    if seed_vecs is not None and len(seed_vecs):
        selected = [row for row in np.asarray(seed_vecs)]
    picked: list[tuple[int, float]] = []
    if not selected:
        # Amorce = médoïde (le plus proche du centroïde).
        medoid = max(pool, key=lambda j: float(vecs[j] @ centroid))
        picked.append((medoid, 1.0))
        selected.append(vecs[medoid])
        pool = [j for j in pool if j != medoid]

    while len(picked) < k and pool:
        set_mat = np.stack(selected)              # (S, D)
        sims = vecs[pool] @ set_mat.T             # (P, S)
        max_sim = sims.max(axis=1)                # (P,)
        bi = int(np.argmin(max_sim))              # le plus lointain du set
        j = pool[bi]
        picked.append((j, float(max_sim[bi])))
        selected.append(vecs[j])
        pool.pop(bi)
    return picked


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


# Nb max de vrais crops candidats à ENCODER par classe (le pool où FPS pioche).
# Borne le coût d'encodage du build ; FPS garde les plus divers parmi eux. Pas
# de tri par qualité (biaiserait vers les scans parfaits) — ordre stable par id.
MAX_CANDIDATES_PER_CLASS = 40
_VALIDATED_STATUSES = ("manual", "auto_name", "auto_phash")


def _class_specs_2eur_all(
    conn: sqlite3.Connection, datasets_dir: Path,
) -> list[dict[str, Any]]:
    """Classes de la banque de suggestions : canonique + membres.

    ``[{class_id, canonical_path, members}]`` — ``class_id`` = eurio_id du
    représentant (commémo : lui-même ; standard : rep du design group), qui est
    aussi la clé sous laquelle TOUTES les lignes de la classe (canonique +
    exemplaires) sont indexées dans la banque (cohérent avec les consumers).
    ``members`` = eurio_ids dont les crops peuvent servir d'exemplaires (avers
    partagé pour un groupe standard)."""
    specs: list[dict[str, Any]] = []
    for eid, path in _commemo_paths_with_eid(conn, datasets_dir):
        specs.append({"class_id": eid, "canonical_path": path, "members": [eid]})
    for members in _select_2eur_standard_groups(conn):
        rep = members[0]["eurio_id"]
        path: Path | None = None
        for m in members:
            if m["numista_id"] is not None:
                path = _resolve_obverse_path(int(m["numista_id"]), datasets_dir)
                if path is not None:
                    break
        if path is None:
            continue
        specs.append({
            "class_id": rep, "canonical_path": path,
            "members": [m["eurio_id"] for m in members],
        })
    return specs


def _candidate_crops_for_class(
    conn: sqlite3.Connection, members: list[str],
) -> list[dict[str, Any]]:
    """Crops éligibles comme exemplaires : avers validés, 2€, au train, présents.
    ``[{asset_id, eurio_id, storage_path}]`` (borné, ordre stable par id)."""
    if not members:
        return []
    member_ph = ",".join("?" for _ in members)
    status_ph = ",".join("?" for _ in _VALIDATED_STATUSES)
    rows = conn.execute(
        f"""
        SELECT id, eurio_id, storage_path
          FROM image_assets
         WHERE eurio_id IN ({member_ph})
           AND face = 'obverse'
           AND (denom IS NULL OR denom != 'not_2eur')
           AND resolution_status IN ({status_ph})
           AND training_eligible = 1
           AND storage_status = 'present'
         ORDER BY id
         LIMIT ?
        """,
        (*members, *_VALIDATED_STATUSES, MAX_CANDIDATES_PER_CLASS),
    ).fetchall()
    return [dict(r) for r in rows]


def build_anchors_2eur_all(
    *,
    conn: sqlite3.Connection,
    datasets_dir: Path = DATASETS_DIR,
    encoder_version: str = SUGGESTIONS_ENCODER_VERSION,
    force_recompute: bool = False,
    exemplars_per_class: int = DEFAULT_EXEMPLARS_PER_CLASS,
    floor_sim: float = DEFAULT_EXEMPLAR_FLOOR_SIM,
    write_references: bool = True,
) -> AnchorBank:
    """Banque de SUGGESTIONS = commémo + standards, MULTI-EXEMPLAIRES (B).

    Par classe : le canonique Numista + jusqu'à ``exemplars_per_class`` vrais
    crops validés choisis pour la DIVERSITÉ d'apparence (farthest-point sampling,
    plancher de validité) — un crop réel sombre/tilté/usé fait mieux matcher les
    photos eBay qu'un énième scan parfait. Les overrides humains (pin/exclude) de
    ``dino_class_references`` sont honorés. La sélection est tracée dans cette
    table (``write_references``). Toutes les lignes d'une classe partagent
    l'eurio_id du représentant (clé de classe des consumers)."""
    from shared.storage.local_cache import local_path
    from store.dino_references import (
        DinoRefRow,
        get_reference_overrides,
        replace_auto_references,
    )

    kind = "2eur_all"
    if not force_recompute:
        cached = load_anchors(kind)
        if cached is not None and cached.encoder_version == encoder_version:
            logger.info(
                "Anchors cache hit (%s, %d entries, encoder=%s) — skipping rebuild",
                kind, cached.count, cached.encoder_version,
            )
            return cached

    specs = _class_specs_2eur_all(conn, datasets_dir)
    if not specs:
        raise RuntimeError(
            f"No 2€ obverse found under {datasets_dir} — did you bootstrap the dataset?"
        )
    overrides = get_reference_overrides(conn, kind)

    # ── Rassemble tout ce qu'il faut encoder : canoniques + crops candidats ──
    # meta indexé par chemin (chemins uniques) : encode_paths peut sauter un
    # fichier illisible, on ré-aligne via kept_paths.
    meta_by_path: dict[str, dict[str, Any]] = {}
    all_paths: list[Path] = []
    for spec in specs:
        cpath = spec["canonical_path"]
        meta_by_path[str(cpath)] = {
            "class_id": spec["class_id"], "eurio_id": spec["class_id"],
            "asset_id": None, "canonical": True,
        }
        all_paths.append(cpath)
        for cand in _candidate_crops_for_class(conn, spec["members"]):
            try:
                cp = local_path("enrichment-crops", cand["storage_path"])
            except Exception:  # noqa: BLE001 — chemin illisible → on saute
                continue
            meta_by_path[str(cp)] = {
                "class_id": spec["class_id"], "eurio_id": cand["eurio_id"],
                "asset_id": cand["id"], "canonical": False,
            }
            all_paths.append(cp)

    logger.info(
        "2eur_all multi-exemplaires : %d classes, %d images à encoder (vitl14)…",
        len(specs), len(all_paths),
    )
    encoder, device = load_encoder(encoder_version=encoder_version)
    transform = build_transform()
    kept_paths, matrix = encode_paths(
        all_paths, encoder=encoder, device=device, transform=transform,
    )
    # Vecteurs alignés sur kept_paths → regroupés par classe.
    vec_by_path = {str(p): matrix[i] for i, p in enumerate(kept_paths)}
    by_class: dict[str, dict[str, Any]] = {}
    for spec in specs:
        by_class[spec["class_id"]] = {"canonical": None, "cands": []}
    for path_s, vec in vec_by_path.items():
        m = meta_by_path.get(path_s)
        if m is None:
            continue
        slot = by_class[m["class_id"]]
        if m["canonical"]:
            slot["canonical"] = {"vec": vec, "path": path_s}
        else:
            slot["cands"].append({
                "vec": vec, "path": path_s,
                "eurio_id": m["eurio_id"], "asset_id": m["asset_id"],
            })

    # ── Sélection par classe : canonique + pins + FPS(candidats − exclus) ──
    bank_eids: list[str] = []
    bank_assets: list[str | None] = []
    bank_paths: list[str] = []
    bank_vecs: list[np.ndarray] = []
    ref_rows: list = []
    for class_id, slot in by_class.items():
        ov = overrides.get(class_id, [])
        pinned = {r["asset_id"] for r in ov if r["method"] == "manual_pin"}
        excluded = {r["asset_id"] for r in ov if r["method"] == "manual_exclude"}

        rank = 0
        seed_vecs: list[np.ndarray] = []
        if slot["canonical"] is not None:
            v = slot["canonical"]["vec"]
            bank_eids.append(class_id); bank_assets.append(None)
            bank_paths.append(slot["canonical"]["path"]); bank_vecs.append(v)
            seed_vecs.append(v)
            ref_rows.append(DinoRefRow(class_id, class_id, None, "canonical", rank, None))
            rank += 1

        cands = [c for c in slot["cands"] if c["asset_id"] not in excluded]
        cand_vecs = np.stack([c["vec"] for c in cands]) if cands else np.zeros((0, 0))

        # Pins d'abord (toujours dans la banque), puis FPS pour le reste.
        forced = [i for i, c in enumerate(cands) if c["asset_id"] in pinned]
        for i in forced:
            c = cands[i]
            bank_eids.append(class_id); bank_assets.append(c["asset_id"])
            bank_paths.append(c["path"]); bank_vecs.append(c["vec"])
            seed_vecs.append(c["vec"])
            ref_rows.append(DinoRefRow(
                class_id, c["eurio_id"], c["asset_id"], "manual_pin", rank, None))
            rank += 1

        budget = max(0, exemplars_per_class - len(forced))
        pool = [i for i in range(len(cands)) if i not in set(forced)]
        picks = farthest_point_select(
            cand_vecs, candidate_idx=pool, k=budget,
            seed_vecs=np.stack(seed_vecs) if seed_vecs else None,
            floor_sim=floor_sim,
        ) if pool and budget else []
        for idx, sim_to_set in picks:
            c = cands[idx]
            bank_eids.append(class_id); bank_assets.append(c["asset_id"])
            bank_paths.append(c["path"]); bank_vecs.append(c["vec"])
            ref_rows.append(DinoRefRow(
                class_id, c["eurio_id"], c["asset_id"], "fps", rank, sim_to_set))
            rank += 1

    if not bank_vecs:
        raise RuntimeError("2eur_all : aucune ligne encodée (dataset absent ?)")
    bank = AnchorBank(
        eurio_ids=bank_eids,
        matrix=np.stack(bank_vecs).astype(np.float32),
        encoder_version=encoder_version,
        anchors_kind=kind,
        built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_paths=bank_paths,
        asset_ids=bank_assets,
    )
    save_anchors(bank)
    n_exemplars = sum(1 for a in bank_assets if a is not None)
    logger.info(
        "2eur_all : %d lignes (%d canoniques + %d exemplaires réels) sur %d classes",
        bank.count, bank.count - n_exemplars, n_exemplars, len(by_class),
    )
    if write_references:
        # La transaction est gérée par l'appelant (Store._writing) — pas de
        # commit ici (il casserait le BEGIN IMMEDIATE/COMMIT du contexte).
        replace_auto_references(conn, kind, ref_rows)
    return bank


def build_anchors_reverse_2eur(
    *,
    conn: sqlite3.Connection | None = None,
    datasets_dir: Path = DATASETS_DIR,
    encoder_version: str = SUGGESTIONS_ENCODER_VERSION,
    force_recompute: bool = False,
) -> AnchorBank:
    """Banque du revers commun 2€ : 2 designs canoniques (APK) + revers wild.

    ``conn``/``datasets_dir`` ignorés (signature homogène avec les autres
    builders pour le dispatcher CLI). Sources : les 2 webp figés
    ``app-android/.../shared_reverse/reverse_2eur_v{1,2}.webp``, plus les
    ancres wild de ``_REVERSE_WILD_FILE`` si présent (C7 pilier 1 rappel —
    revers usés/inclinés/mal éclairés que les 2 designs propres ratent).
    Encodée vitl14 pour partager l'embedding avec ``2eur_all`` (cf. C7 face).
    """
    kind = REVERSE_ANCHORS_KIND

    if not force_recompute:
        cached = load_anchors(kind)
        if cached is not None and cached.encoder_version == encoder_version:
            logger.info(
                "Anchors cache hit (%s, %d entries, encoder=%s) — skipping rebuild",
                kind, cached.count, cached.encoder_version,
            )
            return cached

    paths_with_eid = [(eid, p) for eid, p in _REVERSE_ANCHOR_SOURCES if p.is_file()]
    if len(paths_with_eid) < 2:
        raise RuntimeError(
            "Reverse anchors missing — expected 2 webp under "
            f"{_REVERSE_ANCHOR_SOURCES[0][1].parent} "
            "(run export.build_shared_reverse_assets)"
        )

    if _REVERSE_WILD_FILE.is_file():
        from shared.storage.local_cache import local_path
        n_wild = 0
        for line in _REVERSE_WILD_FILE.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            p = Path(local_path("enrichment-crops", row["storage_path"]))
            if p.is_file():
                paths_with_eid.append((f"wild-{row['asset_id'][:12]}", p))
                n_wild += 1
        logger.info("Reverse bank: +%d ancres wild (%s)", n_wild,
                    _REVERSE_WILD_FILE.name)

    return _encode_and_save(
        kind=kind, paths_with_eid=paths_with_eid, encoder_version=encoder_version
    )
