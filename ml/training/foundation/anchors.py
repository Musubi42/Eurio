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
import os
import re
import shutil
import socket
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

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

# Kind par défaut pour les SUGGESTIONS review (banque large commémo + courantes).
SUGGESTIONS_ANCHORS_KIND = "2eur_all"

# Le consensus et les lanes lisent la banque du VERDICT — et ce n'est PAS une
# valeur de plus : c'est un alias du point de bascule unique. Elle portait son
# propre littéral `"2eur_commemo"` jusqu'au 2026-08-24, hors de portée du test
# qui verrouille le scope, alors que `review_queue_routes` et
# `sources/_base/steps/auto_validate` s'en servent en production. Deux
# constantes pour une seule décision, c'est une divergence programmée.
CONSENSUS_ANCHORS_KIND = _VERDICT_ANCHORS_KIND

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
# ⛔ Cette table dit un FAIT sur chaque banque (avec quel encodeur elle a été
# construite), pas un CHOIX de périmètre. Ses clés sont donc des littéraux, et
# `2eur_commemo` y reste même quand le verdict ne la lit plus : les 7 780
# prédictions déjà en base sous cette paire restent lisibles. La remplacer par
# `CONSENSUS_ANCHORS_KIND` ferait disparaître une entrée de la table le jour où
# le verdict bascule — et `encoder_version_for_kind('2eur_commemo')` rendrait
# alors vits14 par le défaut, par accident plutôt que par décision.
ENCODER_VERSION_FOR_KIND = {
    "2eur_commemo": DEFAULT_ENCODER_VERSION,
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
    # Renseignés par `build_anchors_2eur_all` seulement : de quoi POUSSER la
    # traçabilité au canonique (Direction A — la base locale est une réplique).
    build: Any | None = None
    ref_rows: list = field(default_factory=list)
    # Identifiant du CONTENU écrit sur disque (posé par `_write_bank_npz`).
    # Deux fichiers issus du même `save_anchors` le partagent : c'est ce qui
    # rend lisible « ces deux .npz sont la même banque » vs « ils ont divergé ».
    # ``None`` pour une banque en mémoire ou un .npz d'avant ce champ.
    bank_id: str | None = None

    @property
    def count(self) -> int:
        return len(self.eurio_ids)

    @property
    def dim(self) -> int:
        return int(self.matrix.shape[1]) if self.matrix.size else 0


# ─── Deux rôles, deux fichiers : la banque SERVIE et les banques de BANC ────
#
# Historique : `anchor_path(kind)` ne portait que le kind. Bencher un second
# encodeur sur `2eur_all` ÉCRASAIT donc la banque que la review sert en
# production — panne muette.
#
# Le scoping par encodeur (P6-1) a réglé le cas « autre encodeur », mais pas
# celui du BRAS BASELINE : `dinov2-vitl14` est à la fois l'encodeur servi et
# le bras de référence du banc. Deux banques légitimes portent donc le même
# couple (kind, encodeur), et un nom de fichier ne peut pas les distinguer.
#
# STRATÉGIE RETENUE (D10/D11) — séparer par le RÔLE, pas par le contenu :
#
#   * `state/foundation_anchors_{kind}.npz` = **LA BANQUE SERVIE**. C'est ce
#     que lisent la review (`_get_bank(kind)`) et les ~9 scripts qui appellent
#     `load_anchors(kind)`. Un seul slot par kind, et il n'est écrit QUE sur
#     intention explicite (`save_anchors(..., write_legacy=True)`, que seul
#     `scripts/build_dino_anchors.py` passe).
#   * `state/foundation_anchors_{kind}__{encoder_slug}.npz` = **artefact de
#     banc**, un par (kind, encodeur). Toujours écrit par `save_anchors`, lu
#     seulement par qui demande un encodeur explicite
#     (`load_anchors(kind, encoder)`).
#
# Pourquoi pas les deux autres options examinées :
#
#   - « le legacy devient un alias/lien du scopé » : le lien ferait suivre la
#     banque servie à chaque rebuild du bras baseline — exactement le défaut
#     D10, rendu structurel au lieu d'accidentel.
#   - « écrire les deux atomiquement + vérifier la cohérence à la lecture » :
#     ne dit toujours pas LEQUEL des deux contenus est le bon quand baseline
#     et production divergent légitimement ; on détecterait un désaccord sans
#     pouvoir le trancher.
#
# Avec la séparation par rôle, une divergence ne peut plus être silencieuse
# parce qu'il n'y a plus deux fichiers pour la même chose : il y a un fichier
# servi, et des artefacts de banc. Ce qui reste bruyant :
#
#   - écraser la banque servie par un contenu différent → WARNING avec les
#     comptes avant/après (`save_anchors`) ;
#   - bâtir la banque de l'encodeur de production SANS la servir → WARNING
#     « la banque servie n'est pas mise à jour » ;
#   - servir une banque dont le meta annonce un autre encodeur que celui de
#     production → ERROR + banque traitée comme absente (`_get_bank`, D3) ;
#   - demander un encodeur alors que seule la banque servie existe et qu'elle
#     en annonce un autre → ERROR (`load_anchors`, D3).
#
# Les écritures sont ATOMIQUES (`.tmp` + `os.replace`) : un `save_anchors`
# interrompu laisse la banque servie intacte, jamais un .npz tronqué.
#
# Les 4 .npz déjà sur disque (`foundation_anchors_2eur_all.npz`,
# `_2eur_commemo.npz`, `_2eur_standard.npz`, `_reverse_2eur.npz`) sont les
# banques servies et restent lus tels quels — aucun d'eux n'est touché par ce
# chantier. `adopt_legacy_bank()` en fait une COPIE sous le nom scopé sans
# rien recalculer ni rien supprimer.

_SLUG_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def encoder_slug(encoder_version: str) -> str:
    """Nom de fichier sûr pour un identifiant d'encodeur.

    Minuscules, tout caractère hors ``[a-z0-9._-]`` (``:`` inclus) remplacé
    par ``-`` :

    - ``'dinov2-vitl14'`` → ``'dinov2-vitl14'``
    - ``'timm:vit_small_patch16_dinov3.lvd1689m'``
      → ``'timm-vit_small_patch16_dinov3.lvd1689m'``

    Injectif sur les specs qu'on manipule (verrouillé par
    ``tests/test_anchor_encoder_scope.py``)."""
    slug = _SLUG_UNSAFE.sub("-", encoder_version.strip().lower())
    return slug.strip("-") or "unknown"


def legacy_anchor_path(kind: str) -> Path:
    """Le chemin de la banque **SERVIE** : ``state/foundation_anchors_{kind}.npz``.

    Nom historique conservé (les ~9 scripts qui font ``load_anchors(kind)``
    n'ont pas bougé d'un caractère). ``served_anchor_path`` en est l'alias
    lisible : c'est ce fichier, et lui seul, que la review consomme."""
    return STATE_DIR / f"foundation_anchors_{kind}.npz"


#: Alias explicite — même fichier, nom qui dit le rôle plutôt que l'histoire.
served_anchor_path = legacy_anchor_path


def anchor_path(kind: str, encoder_version: str | None = None) -> Path:
    """Chemin du .npz d'une banque.

    ``encoder_version=None`` → la banque SERVIE (chemin historique ; la
    signature à un argument garde exactement son comportement).
    Sinon → l'artefact de banc ``state/foundation_anchors_{kind}__{slug}.npz``."""
    if encoder_version is None:
        return legacy_anchor_path(kind)
    return STATE_DIR / f"foundation_anchors_{kind}__{encoder_slug(encoder_version)}.npz"


def _write_bank_npz(bank: AnchorBank, path: Path, *, bank_id: str | None = None) -> str:
    """Écrit la banque en .npz de façon ATOMIQUE et renvoie son ``bank_id``.

    L'écriture passe par un temporaire dans le même dossier puis
    ``os.replace`` : une interruption (Ctrl-C, disque plein, OOM) laisse le
    fichier précédent intact au lieu d'un .npz tronqué que ``np.load``
    rejetterait au prochain démarrage de la review. Le temporaire est nettoyé
    même en cas d'échec — et l'exception REMONTE, elle n'est pas avalée.

    ``bank_id`` identifie le contenu écrit : deux fichiers issus du même
    ``save_anchors`` le partagent, ce qui rend une divergence lisible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    bank_id = bank_id or uuid4().hex
    meta = json.dumps(
        {
            "encoder_version": bank.encoder_version,
            "anchors_kind": bank.anchors_kind,
            "built_at": bank.built_at,
            "count": bank.count,
            "dim": bank.dim,
            "bank_id": bank_id,
        }
    )
    # asset_ids parallèle aux eurio_ids ("" = ligne canonique). Aligné sur count
    # (les vieilles banques mono-ancre passent []) pour un chargement homogène.
    asset_ids = bank.asset_ids or [None] * bank.count
    tmp = path.parent / f".{path.name}.{uuid4().hex[:8]}.tmp.npz"
    try:
        np.savez(
            tmp,
            matrix=bank.matrix,
            eurio_ids=np.array(bank.eurio_ids, dtype=np.str_),
            source_paths=np.array(bank.source_paths, dtype=np.str_),
            asset_ids=np.array([a or "" for a in asset_ids], dtype=np.str_),
            meta=np.array([meta], dtype=np.str_),
        )
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return bank_id


def _peek_meta(path: Path) -> dict:
    """Meta d'un .npz sans charger la matrice. ``{}`` si illisible (journalisé)."""
    try:
        with np.load(path, allow_pickle=False) as npz:
            raw = npz["meta"][0] if npz["meta"].size else "{}"
            return json.loads(str(raw))
    except Exception as exc:  # noqa: BLE001 — on journalise, on ne masque pas
        logger.error("Banque illisible %s : %s", path, exc)
        return {}


def save_anchors(bank: AnchorBank, *, write_legacy: bool = False) -> Path:
    """Écrit l'artefact de banc (kind + encodeur) et renvoie son chemin.

    La banque **SERVIE** (``legacy_anchor_path``) n'est écrite QUE si
    ``write_legacy=True``. C'est une INTENTION, jamais une déduction : avant
    ce correctif (D10) le défaut était déduit de « la banque porte l'encodeur
    de production », or ``dinov2-vitl14`` est à la fois l'encodeur servi et le
    bras baseline du banc — un rebuild de baseline écrasait donc la banque que
    la review sert, sans un mot. Seul ``scripts/build_dino_anchors.py`` passe
    ``write_legacy=True`` (drapeau ``--no-serve`` pour y renoncer).

    Rien n'est silencieux ici :

    - remplacer une banque servie par un contenu différent → WARNING avec les
      comptes avant/après ;
    - bâtir la banque de l'encodeur de production sans la servir → WARNING
      disant que la banque servie n'est PAS mise à jour ;
    - servir une banque qui n'est pas celle de l'encodeur de production →
      WARNING (échappatoire volontaire, pas un accident).
    """
    scoped = anchor_path(bank.anchors_kind, bank.encoder_version)
    served = legacy_anchor_path(bank.anchors_kind)
    prod = encoder_version_for_kind(bank.anchors_kind)

    bank_id = _write_bank_npz(bank, scoped)

    if write_legacy and served != scoped:
        before = _peek_meta(served) if served.exists() else None
        if before and before.get("bank_id") != bank_id:
            logger.warning(
                "save_anchors: la banque SERVIE %s est remplacée — %s ancres "
                "(encoder=%s, built_at=%s) → %d ancres (encoder=%s, built_at=%s)",
                served.name, before.get("count", "?"),
                before.get("encoder_version", "?"), before.get("built_at", "?"),
                bank.count, bank.encoder_version, bank.built_at,
            )
        if bank.encoder_version != prod:
            logger.warning(
                "save_anchors: la banque servie %s va porter encoder=%s alors "
                "que l'encodeur de production de ce kind est %s — "
                "les lecteurs historiques compareront des cosinus inter-espaces",
                served.name, bank.encoder_version, prod,
            )
        _write_bank_npz(bank, served, bank_id=bank_id)
    elif bank.encoder_version == prod and served != scoped:
        logger.warning(
            "save_anchors: %s bâtie avec l'encodeur de PRODUCTION (%s) mais "
            "write_legacy=False — la banque servie %s n'est PAS mise à jour "
            "(c'est le comportement attendu d'un bras baseline de banc)",
            scoped.name, bank.encoder_version, served.name,
        )

    logger.info(
        "Saved %d anchors (%s, encoder=%s, dim=%d, bank_id=%s) → %s%s",
        bank.count, bank.anchors_kind, bank.encoder_version, bank.dim,
        bank_id[:12], scoped, " (+ banque servie)" if write_legacy else "",
    )
    return scoped


def _read_bank_npz(path: Path, kind: str) -> AnchorBank:
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
        bank_id=meta.get("bank_id"),
    )


def load_anchors(kind: str, encoder_version: str | None = None) -> AnchorBank | None:
    """Charge une banque, ``None`` si absente.

    ``encoder_version=None`` : la banque SERVIE, et rien d'autre — comportement
    historique inchangé.
    ``encoder_version`` fourni : l'artefact de banc de ce couple ; s'il manque
    on retombe sur la banque servie UNIQUEMENT si son ``meta.encoder_version``
    correspond. Sinon on rend ``None`` **en le journalisant en ERROR** : rendre
    une banque d'un autre encodeur produirait des similarités inter-espaces
    silencieusement fausses, et rendre ``None`` sans un mot rendrait la review
    aveugle le jour d'une bascule d'encodeur (D3)."""
    if encoder_version is None:
        path = legacy_anchor_path(kind)
        return _read_bank_npz(path, kind) if path.exists() else None

    scoped = anchor_path(kind, encoder_version)
    if scoped.exists():
        return _read_bank_npz(scoped, kind)
    served = legacy_anchor_path(kind)
    if not served.exists():
        return None
    bank = _read_bank_npz(served, kind)
    if bank.encoder_version == encoder_version:
        return bank
    logger.error(
        "load_anchors(%s, %s) : aucun artefact %s sur disque, et la banque "
        "servie %s annonce encoder=%s — banque traitée comme ABSENTE. "
        "Rebuild : go-task ml:dino-anchors:build -- --kind %s --force",
        kind, encoder_version, scoped.name, served.name,
        bank.encoder_version, kind,
    )
    return None


def adopt_legacy_bank(kind: str, *, dry_run: bool = False) -> Path | None:
    """Copie un .npz legacy vers son nom scopé, d'après son propre meta.

    Migration de NOMMAGE : rien n'est recalculé, le legacy n'est jamais
    supprimé (les appelants historiques continuent de le lire). Idempotente :
    si le scopé existe déjà, on le renvoie sans réécrire. ``None`` si aucun
    legacy sur disque. Personne ne l'appelle automatiquement — c'est un geste
    d'opérateur, câblé par l'intégration."""
    legacy = legacy_anchor_path(kind)
    if not legacy.exists():
        return None
    bank = _read_bank_npz(legacy, kind)
    scoped = anchor_path(kind, bank.encoder_version)
    if scoped == legacy or scoped.exists():
        return scoped
    if dry_run:
        return scoped
    scoped.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, scoped)
    logger.info("adopt_legacy_bank: %s → %s (encoder=%s)",
                legacy.name, scoped.name, bank.encoder_version)
    return scoped


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
    medoid_first: bool = False,
) -> list[tuple[int, float]]:
    """Farthest-Point Sampling dans l'espace d'embedding (pur numpy, testable).

    Choisit jusqu'à ``k`` indices parmi ``candidate_idx`` en maximisant la
    diversité d'apparence : à chaque tour on prend le candidat dont la
    similarité MAX à l'ensemble déjà retenu est la plus basse (le plus
    « nouveau à l'œil de DINO »). ``seed_vecs`` = vecteurs déjà dans l'ensemble
    (canonique + pins) ; s'il est vide, on amorce par le médoïde (candidat le
    plus proche du centroïde = le plus représentatif).

    ``medoid_first`` — l'AMORCE AU MÉDOÏDE (O6) : le premier choix est le
    médoïde du pool éligible MÊME quand ``seed_vecs`` est fourni ; les choix
    suivants restent du FPS ordinaire contre ``seed_vecs`` + choix. Sans elle,
    un seed (le canonique Numista) fait du premier choix le crop le plus
    LOINTAIN du canonique — le plus atypique de sa classe, un faux attracteur.
    Mesuré le 2026-08-20 à nombre d'ancres identique (795 lignes, un
    exemplaire par classe) : garder le rang le moins diversifiant rend 77,8 %
    contre 73,8 % au rang 1 (``scripts.bench_refs_curve --rank-order last``).
    Le ``sim_au_set`` du médoïde est sa similarité MAX au seed (1,0 sans
    seed) : les rangs restent lisibles comme avant.

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
    if medoid_first or not selected:
        # Amorce = médoïde (le plus proche du centroïde). Sans seed, c'est la
        # seule amorce possible ; avec seed, c'est l'amorce O6 — le FPS nu
        # partirait du point le plus lointain du canonique.
        medoid = max(pool, key=lambda j: float(vecs[j] @ centroid))
        sim_au_set = (
            float(max(float(vecs[medoid] @ row) for row in selected))
            if selected else 1.0
        )
        picked.append((medoid, sim_au_set))
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
    out: list[tuple[str, Path | None]] = []
    skipped = 0
    for c in coins:
        path = _resolve_obverse_path(int(c["numista_id"]), datasets_dir)
        if path is None:
            skipped += 1
            # On garde quand même la pièce : `2eur_all` sait bâtir une classe
            # sur ses seuls crops validés (cf. `_class_specs_2eur_all`). Les
            # banques mono-image, elles, filtrent ce None plus bas.
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
    write_legacy: bool = False,
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
    save_anchors(bank, write_legacy=write_legacy)
    return bank


def build_anchors_2eur_commemo(
    *,
    conn: sqlite3.Connection,
    datasets_dir: Path = DATASETS_DIR,
    encoder_version: str = DEFAULT_ENCODER_VERSION,
    force_recompute: bool = False,
    write_legacy: bool = False,
) -> AnchorBank:
    """Encode all 2€ commemorative obverses available on disk into a fresh bank.

    If a cache exists at ``anchor_path('2eur_commemo')`` and
    ``force_recompute=False``, returns it as-is. Otherwise encodes from
    scratch and writes the new ``.npz``.
    """
    kind = "2eur_commemo"

    if not force_recompute:
        # Cache scopé : bencher un autre encodeur ne doit pas « hit » sur la
        # banque de production (et inversement).
        cached = load_anchors(kind, encoder_version)
        if cached is not None and cached.encoder_version == encoder_version:
            logger.info(
                "Anchors cache hit (%s, %d entries, encoder=%s) — skipping rebuild",
                kind, cached.count, cached.encoder_version,
            )
            return cached

    # Banque MONO-image : sans canonique, il n'y a rien à encoder. On filtre
    # donc les None que `_commemo_paths_with_eid` laisse passer désormais pour
    # `2eur_all` (qui, lui, sait bâtir une classe sur ses crops validés).
    paths_with_eid = [
        (eid, path)
        for eid, path in _commemo_paths_with_eid(conn, datasets_dir)
        if path is not None
    ]
    if not paths_with_eid:
        raise RuntimeError(
            f"No 2€ commemorative obverse found under {datasets_dir} — "
            "did you bootstrap the dataset?"
        )

    return _encode_and_save(
        kind=kind, paths_with_eid=paths_with_eid, encoder_version=encoder_version,
        write_legacy=write_legacy,
    )


def build_anchors_2eur_standard(
    *,
    conn: sqlite3.Connection,
    datasets_dir: Path = DATASETS_DIR,
    encoder_version: str = DEFAULT_ENCODER_VERSION,
    force_recompute: bool = False,
    write_legacy: bool = False,
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
        # Cache scopé : bencher un autre encodeur ne doit pas « hit » sur la
        # banque de production (et inversement).
        cached = load_anchors(kind, encoder_version)
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
        kind=kind, paths_with_eid=paths_with_eid, encoder_version=encoder_version,
        write_legacy=write_legacy,
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
        # `canonical_path=None` est désormais ACCEPTÉ (cf. build_anchors_2eur_all).
        #
        # Avant, une classe sans avers Numista sur le disque était éliminée
        # ENTIÈREMENT — même avec quarante crops validés. Mesuré le 2026-08-19 :
        # 130 pièces sur 658 dans ce cas, dont des pays presque complets
        # (LU 33/41, MT 27/34, LT 18/21). Le canonique est une GRAINE, pas un
        # prérequis : une classe qui a des exemplaires validés sait se décrire
        # sans lui.
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
    min_exemplars: int | None = None,
    medoid_first: bool = True,
    write_references: bool = True,
    write_legacy: bool = False,
) -> AnchorBank:
    """Banque de SUGGESTIONS = commémo + standards, MULTI-EXEMPLAIRES (B).

    ``medoid_first`` — l'AMORCE du FPS (O6, défaut True) : le premier
    exemplaire de chaque classe est le médoïde de ses crops, pas le plus
    lointain du canonique. Tracé dans la note du build (``amorce=medoide`` /
    ``amorce=fps``) pour que deux banques se comparent sur ce qu'elles sont.

    Par classe : le canonique Numista + jusqu'à ``exemplars_per_class`` vrais
    crops validés choisis pour la DIVERSITÉ d'apparence (farthest-point sampling,
    plancher de validité) — un crop réel sombre/tilté/usé fait mieux matcher les
    photos eBay qu'un énième scan parfait. Les overrides humains (pin/exclude) de
    ``dino_class_references`` sont honorés. La sélection est tracée dans cette
    table (``write_references``). Toutes les lignes d'une classe partagent
    l'eurio_id du représentant (clé de classe des consumers).

    ``min_exemplars`` — le PLANCHER : sous ce nombre d'exemplaires FPS, une
    classe garde son canonique SEUL. La valeur vient de la base
    (``dino_thresholds``, scopée par le couple banque × encodeur, décision D5) ;
    passer l'argument la force, ce qui ne sert qu'aux tests et aux essais.

    ⚠️ **Le défaut est revenu à 1, donc le plancher est INACTIF** (2026-08-20).
    Il a valu 2 pendant une journée, sur la foi du creux agrégé de la courbe
    (N=0 53,1 %, N=1 50,1 %). Mesuré depuis, à la maille qui manquait : donner
    à 57 classes exactement un exemplaire AMÉLIORE leurs propres crops (vitl14
    67,6 → 69,1 %, p = 0,048 ; vits14 41,6 → 45,5 %, p = 4,5e-10, 1073 crops),
    et le creux agrégé tient à l'ORDRE du FPS — à nombre d'ancres égal, garder
    le rang le moins diversifiant au lieu du plus diversifiant donne 77,8 % au
    lieu de 73,8 % (vitl14). Le raisonnement complet, les réserves et la
    commande qui rejoue tout ça : ``shared/dino_threshold_defaults.py``, couple
    ``("2eur_all", "dinov2-vitl14")``. Le mécanisme reste ici pour qu'un
    plancher se repose en une ligne le jour où une mesure le demandera."""
    from shared.storage.local_cache import local_path
    from store import dino_thresholds as dino_seuils
    from store.dino_references import (
        DinoBuild,
        DinoRefRow,
        delta_de_forme,
        forme_servie,
        get_reference_overrides,
        histogramme_exemplaires,
        record_build,
        replace_auto_references,
    )

    kind = "2eur_all"
    if not force_recompute:
        # Cache scopé : bencher un autre encodeur ne doit pas « hit » sur la
        # banque de production (et inversement).
        cached = load_anchors(kind, encoder_version)
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

    # ── Le plancher d'exemplaires, résolu AVANT les ~4 min d'encodage ────────
    # D5 : le seuil vit en base, scopé par (banque, encodeur). Ligne absente,
    # table absente (réplique en retard, canonique pas redéployé) → le défaut
    # du code, et on DIT lequel : un plancher qui retomberait en silence sur
    # une autre valeur que celle réglée déplacerait la composition de la banque
    # sans laisser de trace.
    if min_exemplars is None:
        seuils = dino_seuils.resolve(
            conn, anchors_kind=kind, encoder_version=encoder_version
        )
        brut = float(seuils["min_exemplars"])
        if brut != int(brut):
            # S1 : la porte d'écriture refuse désormais une valeur
            # fractionnaire, mais une ligne posée avant ce garde (ou par un
            # SQL à la main) reste lisible. La tronquer en silence poserait le
            # régime N=1 sous couvert d'un réglage.
            logger.warning(
                "min_exemplars vaut %s en base — ce seuil est un COMPTE, il "
                "est tronqué : plancher effectif : %d. Repose une valeur "
                "entière (store.dino_thresholds.set_threshold la refuse "
                "désormais fractionnaire).",
                brut, int(brut),
            )
        min_exemplars = int(brut)
        source_plancher = seuils.source["min_exemplars"]
    else:
        source_plancher = "argument"
    plancher = int(min_exemplars)
    if plancher > exemplars_per_class:
        # Un plancher au-dessus du plafond viderait la banque de TOUS ses
        # exemplaires — l'inverse de ce qu'il vise. On clampe, bruyamment.
        logger.warning(
            "min_exemplars=%d > exemplars_per_class=%d : plancher ramené à %d "
            "(sinon aucune classe ne pourrait l'atteindre et la banque perdrait "
            "tous ses exemplaires).",
            plancher, exemplars_per_class, exemplars_per_class,
        )
        plancher = exemplars_per_class
    logger.info(
        "plancher d'exemplaires : min_exemplars=%d (source=%s, couple=%s/%s) — "
        "%s. Une classe sous le plancher garde son canonique SEUL.",
        plancher, source_plancher, kind, encoder_version,
        "INACTIF (1 : aucune classe n'est ramenée au canonique seul)"
        if plancher <= 1 else "ACTIF",
    )
    amorce = "medoide" if medoid_first else "fps"
    logger.info(
        "amorce du FPS : amorce=%s — %s",
        amorce,
        "le premier exemplaire de chaque classe est le MÉDOÏDE de ses crops (O6)"
        if medoid_first else
        "le premier exemplaire est le crop le plus LOINTAIN du canonique "
        "(FPS nu, mesuré -4 pts à banque de taille égale)",
    )

    # ── Rassemble tout ce qu'il faut encoder : canoniques + crops candidats ──
    # meta indexé par chemin (chemins uniques) : encode_paths peut sauter un
    # fichier illisible, on ré-aligne via kept_paths.
    meta_by_path: dict[str, dict[str, Any]] = {}
    all_paths: list[Path] = []
    n_no_canonical = 0
    for spec in specs:
        cpath = spec["canonical_path"]
        if cpath is None:
            # Classe portée par ses seuls exemplaires. Aucune ligne canonique
            # n'est écrite : la sélection FPS amorcera sur le médoïde des
            # crops validés (cf. `farthest_point_select`, seed=None).
            n_no_canonical += 1
        else:
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
        "2eur_all multi-exemplaires : %d classes (%d sans canonique, portées "
        "par leurs crops validés), %d images à encoder (vitl14)…",
        len(specs), n_no_canonical, len(all_paths),
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
    sous_plancher: list[tuple[str, int]] = []   # classes ramenées au canonique seul
    sans_canonique_gardees: list[str] = []      # gardées sous le plancher, faute de canonique
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
            floor_sim=floor_sim, medoid_first=medoid_first,
        ) if pool and budget else []
        # ── Plancher : sous le seuil, la classe reste sur son canonique ────
        # Les pins ne sont JAMAIS retirés (décision d'humain sur un crop) ; le
        # plancher ne coupe que la part automatique.
        #
        # Le cas limite tranché : une classe SANS canonique garde ses
        # exemplaires même sous le plancher. La rejeter la ferait disparaître
        # de la banque — recall 0 garanti, pire que dégradé. Combien de classes
        # sont dans ce cas : ZÉRO au dernier build (`n_no_canonical` = 0 pour
        # 23c637d93b43, et `SELECT COUNT(*) FROM (SELECT class_id FROM
        # dino_class_references WHERE anchors_kind='2eur_all' GROUP BY 1 HAVING
        # SUM(method='canonical')=0)` → 0 sur eurio.replica.db, 2026-08-20). La
        # règle est écrite pour le cas qui ne se présente pas — pour qu'il ne
        # se tranche pas tout seul le jour où il se présentera.
        if (
            slot["canonical"] is not None
            and picks
            and len(forced) + len(picks) < plancher
        ):
            sous_plancher.append((class_id, len(forced) + len(picks)))
            picks = []
        elif (
            slot["canonical"] is None
            and picks
            and len(forced) + len(picks) < plancher
        ):
            sans_canonique_gardees.append(class_id)

        for idx, sim_to_set in picks:
            c = cands[idx]
            bank_eids.append(class_id); bank_assets.append(c["asset_id"])
            bank_paths.append(c["path"]); bank_vecs.append(c["vec"])
            ref_rows.append(DinoRefRow(
                class_id, c["eurio_id"], c["asset_id"], "fps", rank, sim_to_set))
            rank += 1

    if sous_plancher:
        logger.info(
            "plancher : %d classes ramenées au canonique seul (moins de %d "
            "exemplaires) — ex. %s",
            len(sous_plancher), plancher,
            ", ".join(f"{c}({n})" for c, n in sous_plancher[:5]),
        )
    if sans_canonique_gardees:
        logger.warning(
            "plancher : %d classes SANS canonique gardées malgré moins de %d "
            "exemplaires (les rejeter les ferait disparaître de la banque) : %s",
            len(sans_canonique_gardees), plancher,
            ", ".join(sans_canonique_gardees[:5]),
        )

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
    save_anchors(bank, write_legacy=write_legacy)
    n_exemplars = sum(1 for a in bank_assets if a is not None)
    logger.info(
        "2eur_all : %d lignes (%d canoniques + %d exemplaires réels) sur %d classes",
        bank.count, bank.count - n_exemplars, n_exemplars, len(by_class),
    )
    # Le build, vu comme un fait daté : un identifiant partagé par toutes les
    # lignes, l'encodeur, et le compte des classes portées sans canonique — ce
    # dernier est la mesure de santé du référentiel image.
    build = DinoBuild(
        build_id=uuid4().hex,
        anchors_kind=kind,
        encoder_version=encoder_version,
        built_at=bank.built_at,
        n_classes=len(by_class),
        n_rows=bank.count,
        n_canonical=bank.count - n_exemplars,
        n_exemplars=n_exemplars,
        n_no_canonical=n_no_canonical,
        exemplars_per_class=exemplars_per_class,
        floor_sim=floor_sim,
        host=socket.gethostname(),
        # La composition d'une banque ne se relit pas depuis le .npz : sans
        # cette note, « pourquoi cette classe n'a-t-elle plus d'exemplaire ? »
        # n'a pas de réponse six semaines plus tard.
        note=(
            f"min_exemplars={plancher} (source={source_plancher}); "
            f"amorce={amorce}; "
            f"{len(sous_plancher)} classes ramenées au canonique seul; "
            f"{len(sans_canonique_gardees)} sans canonique gardées sous le plancher"
        ),
    )
    # ── La FORME de la banque, comparée à celle qu'on remplace ───────────────
    # Le compte d'exemplaires ne dit pas la forme, et c'est par là qu'une
    # banque a déjà changé en silence (cf. `delta_de_forme`). La lecture se
    # fait AVANT `replace_auto_references` : après, il n'y a plus rien à
    # comparer.
    delta = delta_de_forme(
        forme_servie(conn, kind, encoder_version),
        histogramme_exemplaires(ref_rows),
    )
    if delta:
        logger.warning("2eur_all : %s", delta)
        build.note = f"{build.note}; {delta}"
    else:
        logger.info("2eur_all : forme inchangée par rapport à la banque servie")
    if write_references:
        # La transaction est gérée par l'appelant (Store._writing) — pas de
        # commit ici (il casserait le BEGIN IMMEDIATE/COMMIT du contexte).
        record_build(conn, build)
        replace_auto_references(
            conn, kind, ref_rows,
            encoder_version=encoder_version, build_id=build.build_id,
        )
    # Le build est retourné pour que l'appelant puisse le POUSSER au canonique
    # (Direction A : sur Mac/PC la base locale est une réplique, l'écrire ne
    # servirait à rien — cf. scripts/build_dino_anchors.py).
    bank.build = build
    bank.ref_rows = ref_rows
    return bank


def build_anchors_reverse_2eur(
    *,
    conn: sqlite3.Connection | None = None,
    datasets_dir: Path = DATASETS_DIR,
    encoder_version: str = SUGGESTIONS_ENCODER_VERSION,
    force_recompute: bool = False,
    write_legacy: bool = False,
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
        # Cache scopé : bencher un autre encodeur ne doit pas « hit » sur la
        # banque de production (et inversement).
        cached = load_anchors(kind, encoder_version)
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
        kind=kind, paths_with_eid=paths_with_eid, encoder_version=encoder_version,
        write_legacy=write_legacy,
    )
