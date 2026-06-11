"""FastAPI router for `/review-queue`.

Surfaces the queue managed by `ml/sources/_base/steps/enqueue.py`. The
admin front (`admin/packages/web/src/features/review/`) consumes this
router single-item-style: list 20 → pick one → decide / skip / reject
→ go back to list. No multi-select per D-16.

Decisions write back to `image_assets` (resolution_status, eurio_id,
face, variant_kind) AND to `review_queue` (decided_*, status='done').
The two writes happen in a single transaction so the queue and the
asset never disagree.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    """Timestamp UTC ISO-8601 avec suffixe Z explicite.

    Format unique pour les ``decided_at``, ``resolved_at``, ``acked_at``
    écrits côté Python — garantit un tri lexicographique cohérent et
    élimine l'ambiguïté de timezone (chunk F, GAP 9 de l'audit).

    Exemple : ``2026-05-25T14:30:00Z``.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )

import cv2
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from review.validation.consensus import consensus_verdict
from review.validation.experts import collect_signals
from review.validation.persist import load_consensus_verdict
from training.foundation.auto_validate import (
    compute_auto_validate_verdict,
    compute_auto_validate_verdict_from_row,
    compute_auto_validate_view,
)
from training.foundation.anchors import (
    CONSENSUS_ANCHORS_KIND,
    SUGGESTIONS_ANCHORS_KIND,
    encoder_version_for_kind,
)
from training.foundation.claude_review import DEFAULT_MODEL_ALIAS, MODELS, judge
from training.foundation.thresholds import (
    DINO_ABSTENTION_THRESHOLDS,
    DINO_VERDICT_THRESHOLDS,
    DinoAbstentionThresholds,
    DinoVerdictThresholds,
)

# Chunk B 2026-05-25 : engine version stables, écrits dans
# ``review_queue.decision_engine_version`` pour permettre de retrouver
# quelle version d'algorithme a tranché une décision passée. Bumper si on
# change la logique du verdict ou les seuils — c'est la trace canonique
# de la calibration en vigueur au moment de l'écriture.
_HUMAN_ENGINE_VERSION = "human@v1"
_AUTO_DINO_ENGINE_VERSION = (
    f"auto_dino@s{DINO_VERDICT_THRESHOLDS['top1_country_sim_min']}"
    f"-d{DINO_VERDICT_THRESHOLDS['country_spread_min']}"
)
from vision.normalize_snap import normalize_listing_with_detections
from store import Store, emit_state_event

from serving.crop_edit import (
    CropEditContextData,
    ManualCropData,
    apply_manual_crop,
    load_crop_edit_context,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/review-queue", tags=["review-queue"])

_VALID_FACES = ("obverse", "reverse", "unknown")
_SKIP_PRIORITY_BUMP = 50

# Marqueur (review_queue.decision_notes) d'un item qu'un humain a ré-ouvert
# depuis la grille de récupération (cf. /restore). Ces items sont « épinglés
# manuel » : ils doivent être tranchés à la main (re-crop), donc on les EXCLUT
# de l'auto-triage (auto-accept Dino + batch Claude) et des buckets de verdict
# du cockpit — sinon ils retomberaient dans CCProxy/Auto et n'apparaîtraient
# pas dans le compteur « Queue manuelle ». Ils restent visibles en tête de la
# queue manuelle (list_queue n'applique aucun filtre de verdict).
_RESTORED_NOTE = "restored"
# Clause SQL réutilisable : « pas un item restauré » (alias review_queue = rq).
_NOT_RESTORED_SQL = (
    f"(rq.decision_notes IS NULL OR rq.decision_notes != '{_RESTORED_NOTE}')"
)
_VALID_KINDS = ("single", "lot", "all")
_VALID_LANES = ("manual", "auto_accept", "ccproxy")
_VALID_REJECT_REASONS = (
    "not_a_coin", "out_of_scope", "duplicate_in_listing", "unreadable", "other",
)

# listing_key extraction — eBay : `ebay_<itemId>` via raw_payload_json.
# Pour les autres sources (catawiki, etc.), fallback à `source_ref` en
# attendant que l'adapter dédié arrive avec son propre pattern.
_LISTING_KEY_SQL = """
CASE
  WHEN si.source = 'ebay'
   AND json_extract(si.raw_payload_json, '$.ebay_item_id') IS NOT NULL
    THEN 'ebay_' || json_extract(si.raw_payload_json, '$.ebay_item_id')
  ELSE si.source_ref
END
"""


def _store() -> Store:
    from serving.server import _store as shared_store
    return shared_store


# ── List ──────────────────────────────────────────────────────────────────


class ReviewBbox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class ReviewCandidate(BaseModel):
    eurio_id: str
    score: float
    label: str
    country: str
    denomination: str
    year: int | None = None
    canonical_thumb_url: str = ""


class ReviewItem(BaseModel):
    id: str
    crop_url: str
    bbox: ReviewBbox | None
    source: str
    source_ref: str
    listing_title: str | None
    listing_url: str | None
    listing_price: float | None
    # Chunk C4 — contexte listing pour la carte d'audit « Listing & marché ».
    # Issu de listing_text_signals (C2) + source_images (C1). None sur les
    # rows antérieures aux chunks C1/C2.
    listing_kind: str | None = None
    listing_kind_confidence: float | None = None
    condition: str | None = None
    condition_confidence: float | None = None
    listing_origin_date: str | None = None
    sold_qty: int | None = None
    candidates: list[ReviewCandidate]
    face_detected: str | None
    priority: int
    is_multi_coin_lot: bool
    quality_score: float
    enqueued_at: str
    # eurio_id attribué au listing par le theme-match
    # (source_images.target_eurio_id). Sert au front à afficher la « pièce
    # proposée » en haut de la colonne de droite, pré-sélectionnée par
    # défaut — ~80 % des reviews valident la proposition. None quand le
    # matcher n'a pas tranché (verdict ambigu) ou pour les sources legacy
    # (mock, scans manuels).
    target_eurio_id: str | None = None
    # ReviewCandidate enrichi (image, label, pays/année) de la pièce
    # proposée — prêt à consommer côté front comme suggestion par défaut.
    # None quand target_eurio_id est None ou que la coin n'est pas dans le catalog.
    target_candidate: ReviewCandidate | None = None
    # Chunk 5b — pièces du groupe de découverte (dénom, pays, année) :
    # toutes les 2 € commémoratives du même pays/année. Peuplé seulement
    # quand le theme-match n'a pas tranché (target_candidate is None,
    # verdict ambigu) — le reviewer choisit la sœur d'un clic sans passer
    # par la recherche libre. Vide sinon.
    group_candidates: list[ReviewCandidate] = []
    # Chantier « review N-contre-designs » : pour un crop issu d'un scrape
    # STANDARD (recherche large pays, ``listing_year IS NULL``), les *design
    # groups* avers du pays (ex. ES → Juan Carlos I 1er type / 2e type /
    # Felipe VI). Affichés EN PRIORITÉ (haut de colonne) : un standard sans
    # année propre ne peut pas être splitté automatiquement par range — le
    # reviewer tranche entre 3 designs d'un clic, au lieu de subir un drop
    # « ambigu ». ``eurio_id`` du candidat = membre représentant du groupe (le
    # plus ancien millésime) ; trancher écrit ce membre → classe d'entraînement
    # = ``COALESCE(design_group_id, eurio_id)`` = le groupe. Vide pour les crops
    # commémo (année présente). La sélection libre (touche F) reste le fallback
    # pour les vraies commémos noyées dans le pool standard.
    standard_candidates: list[ReviewCandidate] = []
    # Chunk Cr — top-1 DINOv2 inliné (dinov2-vits14, 2eur_commemo).
    # Préférence : top1_country (restreint au pays du listing) > top1 global.
    # None si pas de prédiction Dino pour cet asset ou eurio_id inexistant
    # dans coins (mort après rename). Affiché comme bouton « Accept Dino »
    # 1-clic dans SingleReviewView — face hardcodée à 'obverse' (ancres
    # Dino = obverses canoniques Numista, correct pour 2€ commémo).
    dino_top1: ReviewCandidate | None = None


def _build_target_candidate(
    row: sqlite3.Row,
    target_eurio_id: str | None,
) -> ReviewCandidate | None:
    """Construit le ReviewCandidate enrichi de la pièce proposée (attribuée
    au listing par le theme-match) à partir d'une row SQL où on a JOIN
    coins. Attendu en colonnes :
    t_eurio_id, t_country, t_country_name, t_year, t_theme,
    t_face_value, t_numista_id. None si target_eurio_id absent ou la
    coin n'est pas dans le catalog. Partagé entre /review-queue (queue
    single) et /review-queue/lots/{key} (détail lot)."""
    if not target_eurio_id or "t_eurio_id" not in row.keys() or not row["t_eurio_id"]:
        return None
    label_bits = [
        row["t_country_name"],
        str(row["t_year"]) if row["t_year"] else None,
        row["t_theme"],
    ]
    denom = (
        f"{float(row['t_face_value']):.2f} EUR"
        if row["t_face_value"] is not None
        else ""
    )
    thumb = (
        f"/images/{int(row['t_numista_id'])}/source"
        if row["t_numista_id"]
        else ""
    )
    return ReviewCandidate(
        eurio_id=row["t_eurio_id"],
        score=1.0,  # prior — pas un score Dino, juste un marqueur "défaut"
        label=" · ".join([b for b in label_bits if b]) or row["t_eurio_id"],
        country=row["t_country"] or "",
        denomination=denom,
        year=row["t_year"],
        canonical_thumb_url=thumb,
    )


def _build_dino_top1_candidate(
    conn: sqlite3.Connection,
    eurio_id: str | None,
    sim: float | None,
) -> ReviewCandidate | None:
    """Construit le ReviewCandidate pour la suggestion DINOv2 top-1.

    Fait un SELECT coins pour enrichir label/country/year. Retourne None si
    eurio_id est absent, sim None, ou la coin n'est pas dans le catalog
    (ex: eurio_id mort post-rename)."""
    if not eurio_id or sim is None:
        return None
    row = conn.execute(
        """
        SELECT eurio_id, country, country_name, year, theme,
               face_value, numista_id
          FROM coins
         WHERE eurio_id = ?
        """,
        (eurio_id,),
    ).fetchone()
    if row is None:
        return None
    label_bits = [
        row["country_name"],
        str(row["year"]) if row["year"] else None,
        row["theme"],
    ]
    denom = (
        f"{float(row['face_value']):.2f} EUR"
        if row["face_value"] is not None
        else ""
    )
    thumb = (
        f"/images/{int(row['numista_id'])}/source"
        if row["numista_id"]
        else ""
    )
    return ReviewCandidate(
        eurio_id=row["eurio_id"],
        score=float(sim),
        label=" · ".join([b for b in label_bits if b]) or row["eurio_id"],
        country=row["country"] or "",
        denomination=denom,
        year=row["year"],
        canonical_thumb_url=thumb,
    )


def _fetch_group_candidates(
    conn: sqlite3.Connection,
    pairs: set[tuple[str, int]],
) -> dict[tuple[str, int], list[ReviewCandidate]]:
    """Pour chaque groupe `(pays, année)`, les pièces 2 € commémoratives —
    candidats sélectionnables quand le theme-match n'a pas tranché (chunk
    5b). `pairs` est petit (≤ nb de groupes du run), une requête par paire
    reste cheap. Clé du dict : `(country, year)`."""
    out: dict[tuple[str, int], list[ReviewCandidate]] = {}
    for country, year in pairs:
        rows = conn.execute(
            """
            SELECT eurio_id, country, country_name, year, theme,
                   face_value, numista_id
              FROM coins
             WHERE country = ? AND year = ?
               AND face_value = 2.0 AND is_commemorative = 1
             ORDER BY theme
            """,
            (country, year),
        ).fetchall()
        cands: list[ReviewCandidate] = []
        for r in rows:
            label_bits = [
                r["country_name"],
                str(r["year"]) if r["year"] else None,
                r["theme"],
            ]
            cands.append(ReviewCandidate(
                eurio_id=r["eurio_id"],
                score=0.0,  # pas un score — juste un membre du groupe
                label=" · ".join([b for b in label_bits if b]) or r["eurio_id"],
                country=r["country"] or "",
                denomination=(
                    f"{float(r['face_value']):.2f} EUR"
                    if r["face_value"] is not None else ""
                ),
                year=r["year"],
                canonical_thumb_url=(
                    f"/images/{int(r['numista_id'])}/source"
                    if r["numista_id"] else ""
                ),
            ))
        out[(country, year)] = cands
    return out


def _fetch_standard_candidates(
    conn: sqlite3.Connection,
    countries: set[str],
    denom: float = 2.0,
) -> dict[str, list[ReviewCandidate]]:
    """Pour chaque pays, les *design groups* avers standard (denom 2 €) —
    candidats prioritaires d'un crop de scrape standard (chantier « review
    N-contre-designs »).

    Une ligne par ``COALESCE(design_group_id, eurio_id)`` : les Types partageant
    un avers (ex. ``be-1999`` + ``be-2007``) fusionnent en UN candidat. Le
    membre représentant = le plus ancien millésime (prior) — c'est son
    ``eurio_id`` qui est écrit à la décision (la classe d'entraînement reste le
    groupe via ``COALESCE`` en aval). Le libellé vient de
    ``design_groups.designation`` quand le groupe en a une, sinon construit
    depuis pays/thème. Vignette = avers canonique du représentant.
    ``pairs``/``countries`` est petit (≤ nb de pays du run)."""
    from serving._coin_helpers import canonical_obverse_url

    out: dict[str, list[ReviewCandidate]] = {}
    for country in countries:
        rows = conn.execute(
            """
            SELECT c.eurio_id, c.country, c.country_name, c.year, c.theme,
                   c.face_value, c.numista_id,
                   COALESCE(c.design_group_id, c.eurio_id) AS class_id,
                   dg.designation AS dg_designation
              FROM coins c
              LEFT JOIN design_groups dg ON dg.id = c.design_group_id
             WHERE c.face_value = ? AND c.country = ?
               AND c.is_commemorative = 0 AND c.canonical_eurio_id IS NULL
             ORDER BY c.year, c.eurio_id
            """,
            (denom, country),
        ).fetchall()
        # Collapse par classe (design group) ; 1er vu (plus ancien millésime,
        # grâce à l'ORDER BY) = représentant.
        groups: dict[str, sqlite3.Row] = {}
        for r in rows:
            groups.setdefault(r["class_id"], r)
        cands: list[ReviewCandidate] = []
        for r in groups.values():
            label = r["dg_designation"] or " · ".join(
                b for b in [
                    r["country_name"],
                    str(r["year"]) if r["year"] else None,
                    r["theme"],
                ] if b
            ) or r["eurio_id"]
            cands.append(ReviewCandidate(
                eurio_id=r["eurio_id"],
                score=0.0,  # pas un score — design group sélectionnable
                label=label,
                country=r["country"] or "",
                denomination=(
                    f"{float(r['face_value']):.2f} EUR"
                    if r["face_value"] is not None else ""
                ),
                year=r["year"],
                canonical_thumb_url=canonical_obverse_url(conn, r["eurio_id"]) or (
                    f"/images/{int(r['numista_id'])}/source"
                    if r["numista_id"] else ""
                ),
            ))
        cands.sort(key=lambda c: (c.year or 0))
        out[country] = cands
    return out


def _row_to_item(
    row: sqlite3.Row,
    group_map: dict[tuple[str, int], list[ReviewCandidate]] | None = None,
    conn: sqlite3.Connection | None = None,
    std_map: dict[str, list[ReviewCandidate]] | None = None,
) -> ReviewItem:
    bbox: ReviewBbox | None = None
    if row["bbox_json"]:
        try:
            d = json.loads(row["bbox_json"])
            bbox = ReviewBbox(x=d.get("x", 0), y=d.get("y", 0),
                              w=d.get("w", 0), h=d.get("h", 0))
        except (json.JSONDecodeError, TypeError):
            bbox = None

    candidates: list[ReviewCandidate] = []
    if row["candidate_eurio_ids_json"]:
        try:
            raw = json.loads(row["candidate_eurio_ids_json"])
            for c in raw if isinstance(raw, list) else []:
                if not isinstance(c, dict) or "eurio_id" not in c:
                    continue
                # Vignette : la valeur stockée dans candidate_eurio_ids_json est
                # souvent NULL (jamais peuplée au scrape) → image cassée. On la
                # recalcule live via canonical_obverse_url (même source que les
                # « pièces standards »), avec fallback sur la valeur stockée.
                thumb = c.get("canonical_thumb_url") or ""
                if not thumb and conn is not None:
                    from serving._coin_helpers import canonical_obverse_url
                    thumb = canonical_obverse_url(conn, c["eurio_id"]) or ""
                candidates.append(ReviewCandidate(
                    eurio_id=c["eurio_id"],
                    score=float(c.get("score", 0)),
                    label=c.get("label", c["eurio_id"]),
                    country=c.get("country", ""),
                    denomination=c.get("denomination", ""),
                    year=c.get("year"),
                    canonical_thumb_url=thumb,
                ))
        except json.JSONDecodeError:
            pass

    target_eurio_id: str | None = (
        row["target_eurio_id"] if "target_eurio_id" in row.keys() else None
    )
    target_candidate = _build_target_candidate(row, target_eurio_id)

    cols = row.keys()

    def _opt(name: str):
        return row[name] if name in cols else None

    # Pièces du groupe : seulement quand le theme-match n'a pas tranché
    # (pas de proposition) et que pays/année du listing sont connus.
    group_candidates: list[ReviewCandidate] = []
    if target_candidate is None and group_map is not None:
        gc_country = _opt("listing_country")
        gc_year = _opt("listing_year")
        if gc_country and gc_year is not None:
            group_candidates = group_map.get((gc_country, gc_year), [])

    # Design groups standard du pays : crop issu d'un scrape standard
    # (``listing_year IS NULL`` + pays connu). Affichés en priorité quel que
    # soit le verdict d'attribution (même un rescued-commemo voit les 3 designs
    # au-dessus de sa proposition commémo).
    standard_candidates: list[ReviewCandidate] = []
    if std_map is not None:
        sc_country = _opt("listing_country")
        if sc_country and _opt("listing_year") is None:
            standard_candidates = std_map.get(sc_country, [])

    # Chunk Cr — top-1 Dino inliné. Préférence country > global.
    # Les colonnes dino_* sont présentes si le SELECT du caller fait
    # le LEFT JOIN image_asset_dino_predictions. Sinon _opt() retourne None
    # et _build_dino_top1_candidate retourne None gracieusement.
    dino_top1: ReviewCandidate | None = None
    if conn is not None:
        dino_eurio_id = _opt("dino_top1_country_eurio_id") or _opt("dino_top1_eurio_id")
        dino_sim = _opt("dino_top1_country_sim") if _opt("dino_top1_country_eurio_id") \
            else _opt("dino_top1_sim")
        dino_top1 = _build_dino_top1_candidate(conn, dino_eurio_id, dino_sim)

    return ReviewItem(
        id=row["id"],
        crop_url=f"/sources/{row['source']}/assets/{row['image_asset_id']}/file",
        bbox=bbox,
        source=row["source"],
        source_ref=row["source_ref"],
        listing_title=row["listing_title"],
        listing_url=row["source_url"],
        listing_price=row["listing_price"],
        listing_kind=_opt("listing_kind"),
        listing_kind_confidence=_opt("listing_kind_confidence"),
        condition=_opt("condition_normalized"),
        condition_confidence=_opt("condition_confidence"),
        listing_origin_date=_opt("listing_origin_date"),
        sold_qty=_opt("sold_qty"),
        candidates=candidates,
        face_detected=row["face"],
        priority=row["priority"],
        is_multi_coin_lot=False,  # detection landing later
        quality_score=row["quality_score"] or 0.0,
        enqueued_at=row["enqueued_at"],
        target_eurio_id=target_eurio_id,
        target_candidate=target_candidate,
        group_candidates=group_candidates,
        standard_candidates=standard_candidates,
        dino_top1=dino_top1,
    )


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (fetchReviewQueue)
@router.get("", response_model=list[ReviewItem])
def list_queue(
    status: str = Query(default="open"),
    limit: int = Query(default=20, ge=1, le=200),
    order: str = Query(default="priority"),
    kind: str = Query(default="single"),
    lane: str | None = Query(default=None),
    cohort_id: str | None = Query(default=None),
    eurio_id: str | None = Query(default=None),
    review_ids: str | None = Query(default=None),
) -> list[ReviewItem]:
    if order not in ("priority", "enqueued_at"):
        raise HTTPException(status_code=422, detail="order must be 'priority' or 'enqueued_at'")
    if kind not in _VALID_KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind must be one of {_VALID_KINDS}",
        )
    if lane is not None and lane not in _VALID_LANES:
        raise HTTPException(
            status_code=422, detail=f"lane must be one of {_VALID_LANES}",
        )
    order_clause = "rq.priority ASC, rq.enqueued_at ASC" \
        if order == "priority" else "rq.enqueued_at ASC"

    store = _store()
    conn = store._connection()  # noqa: SLF001
    where = "rq.status = ?"
    args: list[Any] = [status]
    if kind != "all":
        where += " AND rq.kind = ?"
        args.append(kind)
    # Lane persistée (WS1) : chaque écran de review filtre sur sa lane → le
    # compteur de la lane décroît à chaque décision. lane NULL (legacy) = manual.
    if lane is not None:
        if lane == "manual":
            where += " AND (rq.lane = 'manual' OR rq.lane IS NULL)"
        else:
            where += " AND rq.lane = ?"
            args.append(lane)
    # Scope par IDS EXPLICITES (prioritaire absolu) : la galerie enrichment
    # reflagge une sélection puis navigue ici sur ces rows EXACTES — robuste aux
    # crops rescués (target_eurio_id ≠ pièce assignée). CSV d'ids review_queue.
    if review_ids:
        ids = [x for x in review_ids.split(",") if x]
        if not ids:
            return []
        where += f" AND rq.id IN ({','.join('?' * len(ids))})"
        args.extend(ids)
    # Scope PAR PIÈCE : la review déclenchée depuis une row coin du cockpit ne
    # doit servir QUE les crops de cette pièce, sinon trancher ne fait pas bouger
    # SA ligne (bug constaté : « Reviewer N » servait toute la cohorte).
    #
    # EXCEPTION standards (chantier « review N-contre-designs ») : un scrape
    # standard est une recherche LARGE pays ; ses crops sans année propre
    # atterrissent en ``target_eurio_id NULL`` (ambigu) et seraient invisibles
    # sous un scope ``target = eurio_id``. Pour un eurio_id standard on sert donc
    # tout le POOL standard du pays (``listing_country = pays AND listing_year
    # IS NULL``), y compris les crops NULL — c'est exactement « toutes les 2 €
    # standard du pays », que le reviewer trie contre les 3 designs.
    elif eurio_id:
        std_coin = conn.execute(
            "SELECT country, face_value FROM coins "
            "WHERE eurio_id = ? AND is_commemorative = 0",
            (eurio_id,),
        ).fetchone()
        if std_coin and std_coin["country"]:
            # Pool standard CANONIQUE = (pays, single, lane manual, open). On
            # force ``kind=single`` + ``lane=manual`` ici quels que soient les
            # query params : les coffrets/lots (kind=lot) ont leur review lot
            # dédiée (un coffret n'est pas une standard unique), et les commémos
            # rescue vivent en lanes ccproxy/auto_accept. Sans ce resserrement,
            # ouvrir la review d'un standard déversait tout le pool pays toutes
            # lanes (≈ centaines d'items mélangés). Ce scope == celui que le
            # cockpit compte (lab_routes funnel-status) → les 2 surfaces
            # affichent le MÊME nombre.
            where += (
                " AND s.source = 'ebay' AND s.listing_country = ? "
                "AND s.listing_year IS NULL "
                "AND rq.kind = 'single' "
                "AND (rq.lane = 'manual' OR rq.lane IS NULL)"
            )
            args.append(std_coin["country"])
        else:
            where += " AND s.target_eurio_id = ?"
            args.append(eurio_id)
    # Cohort scope : only items whose theme-matched coin is in the cohort.
    elif cohort_id:
        cohort = store.get_cohort(cohort_id)
        if cohort is None:
            raise HTTPException(status_code=404, detail="Cohort introuvable")
        if not cohort.eurio_ids:
            return []
        where += (
            " AND s.target_eurio_id IN "
            f"({','.join('?' * len(cohort.eurio_ids))})"
        )
        args.extend(cohort.eurio_ids)
    args.append(limit)

    rows = conn.execute(
        f"""
        SELECT rq.id, rq.image_asset_id, rq.priority, rq.enqueued_at,
               rq.candidate_eurio_ids_json AS rq_candidates,
               a.bbox_json, a.candidate_eurio_ids_json, a.face, a.quality_score,
               s.source, s.source_ref, s.listing_title, s.source_url,
               s.listing_price, s.target_eurio_id,
               s.listing_country, s.listing_year,
               s.listing_origin_date, s.sold_qty,
               lts.listing_kind, lts.listing_kind_confidence,
               lts.condition_normalized, lts.condition_confidence,
               t.eurio_id     AS t_eurio_id,
               t.country      AS t_country,
               t.country_name AS t_country_name,
               t.year         AS t_year,
               t.theme        AS t_theme,
               t.face_value   AS t_face_value,
               t.numista_id   AS t_numista_id,
               p.top1_country_eurio_id AS dino_top1_country_eurio_id,
               p.top1_country_sim      AS dino_top1_country_sim,
               p.top1_eurio_id         AS dino_top1_eurio_id,
               p.top1_sim              AS dino_top1_sim
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN listing_text_signals lts ON lts.source_image_id = s.id
          LEFT JOIN coins t   ON t.eurio_id = s.target_eurio_id
          LEFT JOIN image_asset_dino_predictions p
                 ON p.asset_id = a.id
                AND p.encoder_version = 'dinov2-vits14'
                AND p.anchors_kind = '2eur_commemo'
         WHERE {where}
         ORDER BY {order_clause}
         LIMIT ?
        """,
        args,
    ).fetchall()

    # Chunk 5b — batch-fetch des pièces du groupe pour les seuls items
    # sans proposition (target_eurio_id NULL → verdict ambigu). Une
    # requête par (pays, année) distinct ; l'ensemble est petit.
    pairs: set[tuple[str, int]] = set()
    # Pays des crops de scrape standard (listing_year NULL) → design groups.
    std_countries: set[str] = set()
    for r in rows:
        c, y = r["listing_country"], r["listing_year"]
        if c and y is None:
            std_countries.add(c)
        if r["target_eurio_id"]:
            continue
        if c and y is not None:
            pairs.add((c, y))
    group_map = _fetch_group_candidates(conn, pairs)
    std_map = _fetch_standard_candidates(conn, std_countries)

    return [_row_to_item(r, group_map, conn=conn, std_map=std_map) for r in rows]


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (fetchReviewStats)
def _cohort_filter(cohort_id: str | None, alias: str = "s") -> tuple[str, list[Any], bool]:
    """Clause SQL pour restreindre une queue aux coins d'une cohort.

    Retourne ``(clause, args, is_empty)`` où ``clause`` est ``" AND
    {alias}.target_eurio_id IN (?,…)"`` (vide si ``cohort_id`` None). Même
    filtre que ``GET /review-queue?cohort_id=`` (chunk 04), réutilisé par les
    voies auto-accept / claude (§C4b). Cohort inconnue → 404 ; cohort sans
    coin → ``is_empty=True`` (l'appelant court-circuite vers un résultat vide).
    """
    if not cohort_id:
        return "", [], False
    cohort = _store().get_cohort(cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="Cohort introuvable")
    if not cohort.eurio_ids:
        return "", [], True
    clause = (
        f" AND {alias}.target_eurio_id IN "
        f"({','.join('?' * len(cohort.eurio_ids))})"
    )
    return clause, list(cohort.eurio_ids), False


@router.get("/stats")
def queue_stats() -> dict[str, Any]:
    """Counts for the queue header strip. Cheap (single query)."""
    conn = _store()._connection()  # noqa: SLF001
    today = datetime.utcnow().strftime("%Y-%m-%d")
    week_start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    n_pending = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'open'"
    ).fetchone()["c"]
    n_done_today = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'done' AND decided_at >= ?",
        (today,),
    ).fetchone()["c"]
    n_done_week = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'done' AND decided_at >= ?",
        (week_start,),
    ).fetchone()["c"]
    # Median seconds: rough proxy — diff between decided_at and enqueued_at
    # over the last 100 done items. Cheap, no real percentile needed yet.
    deltas: list[float] = []
    for r in conn.execute(
        """
        SELECT enqueued_at, decided_at FROM review_queue
         WHERE status = 'done' AND decided_at IS NOT NULL
         ORDER BY decided_at DESC LIMIT 100
        """
    ).fetchall():
        try:
            t0 = datetime.fromisoformat(r["enqueued_at"].replace(" ", "T"))
            t1 = datetime.fromisoformat(r["decided_at"].replace(" ", "T"))
            deltas.append((t1 - t0).total_seconds())
        except Exception:  # noqa: BLE001
            continue
    deltas.sort()
    median = deltas[len(deltas) // 2] if deltas else 0.0

    return {
        "n_pending": n_pending,
        "n_done_today": n_done_today,
        "n_done_this_week": n_done_week,
        "median_seconds_per_decision": round(median, 1),
    }


# Consumed by: admin/.../review/composables/useReviewApi.ts (fetchTriageStats)
@router.get("/triage-stats")
def queue_triage_stats(
    kind: str = Query(default="single"),
    cohort_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Compteurs pour le dashboard /review : agrège le verdict
    d'auto-validation sur la queue ``open`` en plus des stats temporelles
    déjà fournies par ``/stats``. Un seul fetch côté front.

    Une passe : ~5 ms pour 800 items (1 SQL scan + boucle pure-Python).
    Pas de cache nécessaire à l'échelle actuelle.

    ``cohort_id`` (optionnel) restreint TOUS les compteurs aux images dont le
    coin theme-matché (``source_images.target_eurio_id``) appartient à la
    cohort — même filtre que ``GET /review-queue?cohort_id=`` (chunk 04). Sert
    aux 3 cartes scopées de la page cohort (§C4a). Cohort inconnue → 404.
    """
    if kind not in _VALID_KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind must be one of {_VALID_KINDS}",
        )

    store = _store()
    conn = store._connection()  # noqa: SLF001
    today = datetime.utcnow().strftime("%Y-%m-%d")
    week_start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    # Les items restaurés (épinglés manuel) sont exclus du scan de verdict :
    # ils ne doivent pas gonfler les buckets auto/partial/divergent. Comme
    # ``n_pending`` les compte toujours (status='open'), ils retombent
    # mécaniquement dans « Queue manuelle » (= n_pending − handled). Cf.
    # _RESTORED_NOTE.
    where = f"rq.status = 'open' AND {_NOT_RESTORED_SQL}"
    args: list[Any] = []
    if kind != "all":
        where += " AND rq.kind = ?"
        args.append(kind)

    # Cohort scope : restreint aux items dont le coin theme-matché est dans la
    # cohort. Le filtre porte sur source_images.target_eurio_id → impose le
    # join (la queue verdict le fait déjà ; les comptes temporels l'ajoutent).
    cohort_clause = ""
    cohort_args: list[Any] = []
    if cohort_id:
        cohort = store.get_cohort(cohort_id)
        if cohort is None:
            raise HTTPException(status_code=404, detail="Cohort introuvable")
        if not cohort.eurio_ids:
            return {
                "n_pending": 0, "n_done_today": 0, "n_done_today_auto_dino": 0,
                "n_done_this_week": 0,
                "by_verdict": {"auto_candidate": 0, "partial": 0,
                               "divergent": 0, "unknown": 0},
                "n_lot_crops": 0, "n_rejected": 0, "n_skipped": 0,
            }
        cohort_clause = (
            " AND si.target_eurio_id IN "
            f"({','.join('?' * len(cohort.eurio_ids))})"
        )
        cohort_args = list(cohort.eurio_ids)

    # Helper : un COUNT scopé. Sans cohort → requête simple sur review_queue ;
    # avec cohort → join image_assets/source_images pour filtrer par coin.
    def _count(status_clause: str, status_args: list[Any], kind_clause: bool) -> int:
        kc = " AND rq.kind = ?" if (kind_clause and kind != "all") else ""
        ka = [kind] if (kind_clause and kind != "all") else []
        if cohort_clause:
            sql = (
                "SELECT COUNT(*) AS c FROM review_queue rq "
                "JOIN image_assets a ON a.id = rq.image_asset_id "
                "JOIN source_images si ON si.id = a.source_image_id "
                f"WHERE {status_clause}{kc}{cohort_clause}"
            )
            return conn.execute(sql, [*status_args, *ka, *cohort_args]).fetchone()["c"]
        sql = f"SELECT COUNT(*) AS c FROM review_queue rq WHERE {status_clause}{kc}"
        return conn.execute(sql, [*status_args, *ka]).fetchone()["c"]

    # Stats temporelles (cohort-scopées si cohort_id).
    n_pending = _count("rq.status = 'open'", [], kind_clause=True)
    n_done_today = _count("rq.status = 'done' AND rq.decided_at >= ?", [today], kind_clause=False)
    n_done_today_auto = _count(
        "rq.decided_by = 'auto_dino' AND rq.decided_at >= ?", [today], kind_clause=False)
    n_done_week = _count("rq.status = 'done' AND rq.decided_at >= ?", [week_start], kind_clause=False)

    # Verdicts — un seul scan SQL puis pure Python.
    rows = conn.execute(
        f"""
        SELECT a.face,
               si.target_eurio_id,
               p.top1_country_eurio_id, p.top1_country_sim, p.country_spread,
               p.top1_eurio_id, p.top1_sim, p.spread,
               lts.vs_target_verdict
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
          LEFT JOIN image_asset_dino_predictions p
                 ON p.asset_id = a.id
                AND p.encoder_version = 'dinov2-vits14'
                AND p.anchors_kind = '2eur_commemo'
          LEFT JOIN listing_text_signals lts
                 ON lts.source_image_id = si.id
         WHERE {where}{cohort_clause}
        """,
        [*args, *cohort_args],
    ).fetchall()

    by_verdict = {"auto_candidate": 0, "partial": 0, "divergent": 0, "unknown": 0}
    for r in rows:
        v = compute_auto_validate_verdict_from_row(r)
        by_verdict[v.level] = by_verdict.get(v.level, 0) + 1

    # Crops en review LOT (kind='lot') — flow distinct du single, surfacé à part
    # dans le cockpit cohort (§C4-lot) sinon ces images semblent « perdues ».
    if cohort_clause:
        n_lot_crops = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE rq.status = 'open' AND rq.kind = 'lot'{cohort_clause}",
            cohort_args,
        ).fetchone()["c"]
    else:
        n_lot_crops = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "WHERE rq.status = 'open' AND rq.kind = 'lot'"
        ).fetchone()["c"]

    # Crops rejetés (récupérables) + items skippés — surfacés dans le cockpit
    # cohort (§C4) : le rejet ouvre la grille de récupération, le skip n'est
    # qu'un report informationnel (l'item reste dans la queue manuelle).
    if cohort_clause:
        n_rejected = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE a.resolution_status = 'rejected'{cohort_clause}",
            cohort_args,
        ).fetchone()["c"]
        n_skipped = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE rq.status = 'open' AND rq.decision_notes = 'skipped'{cohort_clause}",
            cohort_args,
        ).fetchone()["c"]
    else:
        n_rejected = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "WHERE a.resolution_status = 'rejected'"
        ).fetchone()["c"]
        n_skipped = conn.execute(
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "WHERE rq.status = 'open' AND rq.decision_notes = 'skipped'"
        ).fetchone()["c"]

    # Compteurs par LANE PERSISTÉE (WS1) — c'est désormais la source de vérité
    # des 3 cartes du cockpit (plus de recompute via by_verdict). Comptés sur la
    # colonne figée → décroissent à chaque décision dans la lane. lane NULL
    # (legacy avant backfill) compte comme 'manual'. Scopé cohort + kind via _count.
    by_lane = {
        "manual": _count(
            "rq.status = 'open' AND (rq.lane = 'manual' OR rq.lane IS NULL)",
            [], kind_clause=True,
        ),
        "auto_accept": _count(
            "rq.status = 'open' AND rq.lane = ?", ["auto_accept"], kind_clause=True,
        ),
        "ccproxy": _count(
            "rq.status = 'open' AND rq.lane = ?", ["ccproxy"], kind_clause=True,
        ),
    }

    # Lots PAR LANE (kind='lot') — décompose la carte fourre-tout « Lots » (B3 :
    # on ne cache plus les lots manuels). Indépendant du `kind` de la requête.
    def _count_lot(lane_clause: str, lane_args: list[Any]) -> int:
        if cohort_clause:
            sql = (
                "SELECT COUNT(*) AS c FROM review_queue rq "
                "JOIN image_assets a ON a.id = rq.image_asset_id "
                "JOIN source_images si ON si.id = a.source_image_id "
                f"WHERE rq.status='open' AND rq.kind='lot' AND {lane_clause}{cohort_clause}"
            )
            return conn.execute(sql, [*lane_args, *cohort_args]).fetchone()["c"]
        sql = ("SELECT COUNT(*) AS c FROM review_queue rq "
               f"WHERE rq.status='open' AND rq.kind='lot' AND {lane_clause}")
        return conn.execute(sql, lane_args).fetchone()["c"]

    by_lane_lot = {
        "manual": _count_lot("(rq.lane='manual' OR rq.lane IS NULL)", []),
        "auto_accept": _count_lot("rq.lane = ?", ["auto_accept"]),
        "ccproxy": _count_lot("rq.lane = ?", ["ccproxy"]),
    }

    return {
        "n_pending": n_pending,
        "n_done_today": n_done_today,
        "n_done_today_auto_dino": n_done_today_auto,
        "n_done_this_week": n_done_week,
        "by_verdict": by_verdict,
        "by_lane": by_lane,
        "by_lane_lot": by_lane_lot,
        "n_lot_crops": n_lot_crops,
        "n_rejected": n_rejected,
        "n_skipped": n_skipped,
    }


# ── Récupération des crops rejetés (un-reject) ────────────────────────────
#
# Un reject (POST /{id}/reject) ferme la review (status='done') ET marque
# image_assets.resolution_status='rejected' (training_eligible=0). Or un rejet
# est souvent un simple cadrage raté qu'un re-crop manuel aurait sauvé. Ces
# deux endpoints rendent le rejet réversible : lister les rejetés d'une cohort
# (grille de récupération admin) puis les ré-ouvrir en masse — ils repassent
# 'open'/'needs_review' et reviennent en tête de queue manuelle, où l'éditeur
# de re-crop existant prend le relais. Inverse EXACT de reject_review.
#
# Déclarés AVANT /{review_id} (sinon FastAPI capture "rejected" comme un id).

# Priorité donnée aux items restaurés : basse → ils remontent en tête de la
# queue (ORDER BY priority ASC) pour que l'humain les re-traite tout de suite.
_RESTORE_PRIORITY = 5


class RejectedCropItem(BaseModel):
    review_id: str
    image_asset_id: str
    crop_url: str
    listing_title: str | None
    quality_reason: str | None
    decided_at: str | None
    target_eurio_id: str | None
    target_label: str | None


# Consumed by: admin/.../review/composables/useReviewApi.ts (fetchRejectedCrops)
@router.get("/rejected", response_model=list[RejectedCropItem])
def list_rejected(
    cohort_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[RejectedCropItem]:
    """Liste les crops rejetés (``image_assets.resolution_status='rejected'``),
    scopés à la cohort si ``cohort_id``. Alimente la grille de récupération."""
    cohort_clause, cohort_args, cohort_empty = _cohort_filter(cohort_id, alias="s")
    if cohort_empty:
        return []
    conn = _store()._connection()  # noqa: SLF001
    rows = conn.execute(
        f"""
        SELECT rq.id AS review_id, rq.image_asset_id, rq.decided_at,
               a.quality_reason,
               s.source, s.listing_title, s.target_eurio_id,
               t.country_name AS t_country_name, t.year AS t_year,
               t.theme AS t_theme
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN coins t ON t.eurio_id = s.target_eurio_id
         WHERE a.resolution_status = 'rejected'{cohort_clause}
         ORDER BY rq.decided_at DESC
         LIMIT ?
        """,
        [*cohort_args, limit],
    ).fetchall()

    def _label(r: sqlite3.Row) -> str | None:
        bits = [r["t_country_name"], str(r["t_year"]) if r["t_year"] else None,
                r["t_theme"]]
        joined = " · ".join([b for b in bits if b])
        return joined or r["target_eurio_id"]

    return [
        RejectedCropItem(
            review_id=r["review_id"],
            image_asset_id=r["image_asset_id"],
            crop_url=f"/sources/{r['source']}/assets/{r['image_asset_id']}/file",
            listing_title=r["listing_title"],
            quality_reason=r["quality_reason"],
            decided_at=r["decided_at"],
            target_eurio_id=r["target_eurio_id"],
            target_label=_label(r),
        )
        for r in rows
    ]


class RestorePayload(BaseModel):
    review_ids: list[str] = Field(default_factory=list)


class RestoreResult(BaseModel):
    restored: int
    skipped: list[str]  # ids non restaurés (introuvables ou pas rejetés)


# Consumed by: admin/.../review/composables/useReviewApi.ts (restoreRejected)
@router.post("/restore", response_model=RestoreResult)
def restore_rejected(payload: RestorePayload) -> RestoreResult:
    """Ré-ouvre des reviews rejetées (inverse de reject_review). Pour chaque
    id : ``review_queue`` repasse ``status='open'`` avec ses champs décision
    purgés et une priorité basse (re-traitement prioritaire) ; ``image_assets``
    repasse ``resolution_status='needs_review'``, ``training_eligible=1``,
    ``quality_reason=NULL``. Un id introuvable ou dont l'image n'est pas
    ``rejected`` est ignoré (listé dans ``skipped``)."""
    if not payload.review_ids:
        return RestoreResult(restored=0, skipped=[])

    conn = _store()._connection()  # noqa: SLF001
    now_iso = _now_iso()
    restored = 0
    skipped: list[str] = []

    for review_id in payload.review_ids:
        rq = conn.execute(
            "SELECT rq.id, rq.image_asset_id, a.resolution_status "
            "  FROM review_queue rq "
            "  JOIN image_assets a ON a.id = rq.image_asset_id "
            " WHERE rq.id = ?",
            (review_id,),
        ).fetchone()
        if rq is None or rq["resolution_status"] != "rejected":
            skipped.append(review_id)
            continue
        conn.execute("BEGIN")
        try:
            conn.execute(
                """
                UPDATE image_assets
                   SET resolution_status = 'needs_review',
                       training_eligible = 1,
                       quality_reason = NULL,
                       resolved_at = NULL
                 WHERE id = ?
                """,
                (rq["image_asset_id"],),
            )
            conn.execute(
                """
                UPDATE review_queue
                   SET status = 'open',
                       priority = ?,
                       decided_at = NULL,
                       decided_by = NULL,
                       decided_eurio_id = NULL,
                       decided_face = NULL,
                       decided_variant_kind = NULL,
                       decision_notes = ?,
                       decision_engine_version = NULL,
                       decision_metadata_json = '{}'
                 WHERE id = ?
                """,
                (_RESTORE_PRIORITY, _RESTORED_NOTE, review_id),
            )
            emit_state_event(
                conn, asset_id=rq["image_asset_id"], to_state="queued",
                actor="human", reason="restored",
            )
            conn.execute("COMMIT")
            restored += 1
        except Exception:
            conn.execute("ROLLBACK")
            raise

    logger.info("[review] restored %d rejected (skipped=%d)", restored, len(skipped))
    return RestoreResult(restored=restored, skipped=skipped)


# ── Lot review (V1.5) ─────────────────────────────────────────────────────
#
# Cf. docs/sources-refacto/lot-review-kickoff.md.
#
# Une listing eBay = N source_images (1 par photo) = N×M image_assets
# (M crops par photo). Le reviewer doit voir toute la listing en une fois,
# pas crop-par-crop. Trois endpoints :
#
#   GET  /review-queue/lots                       — liste paginated, groupée par listing_key
#   GET  /review-queue/lots/{listing_key}         — détail (toutes images + crops)
#   POST /review-queue/lots/{listing_key}/decide  — bulk decide (assignments)
#
# IMPORTANT : ces routes doivent être déclarées AVANT /{review_id} sinon
# FastAPI capture "lots" comme un review_id.


class LotListItem(BaseModel):
    listing_key: str
    source: str
    target_eurio_id: str | None
    listing_title: str | None
    listing_price: float | None
    listing_currency: str
    is_lot_suspected: bool
    n_images: int
    n_crops_in_review: int
    oldest_enqueued_at: str
    thumb_url: str | None  # raw image URL, pour la card grille


class LotListResponse(BaseModel):
    items: list[LotListItem]
    total: int


# Consumed by: admin/packages/web/src/features/review/composables/useLotReview.ts (fetchLots)
@router.get("/lots", response_model=LotListResponse)
def list_lots(
    limit: int = Query(default=24, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    cohort_id: str | None = Query(default=None),
) -> LotListResponse:
    """Liste les listings ayant ≥ 1 row review_queue.kind='lot' status='open'.

    Groupé par listing_key (cf. _LISTING_KEY_SQL — eBay : ebay_<itemId>).
    Tri : oldest_enqueued_at ASC (le reviewer commence par les plus vieux).
    ``cohort_id`` (optionnel) restreint aux listings d'un coin de la cohort
    (§C4-lot) — même filtre ``si.target_eurio_id`` que le reste du cockpit.
    """
    conn = _store()._connection()  # noqa: SLF001
    cohort_clause, cohort_args, cohort_empty = _cohort_filter(cohort_id, alias="si")
    if cohort_empty:
        return LotListResponse(items=[], total=0)

    total = conn.execute(
        f"""
        SELECT COUNT(DISTINCT {_LISTING_KEY_SQL}) AS n
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
         WHERE rq.kind = 'lot' AND rq.status = 'open'{cohort_clause}
        """,
        cohort_args,
    ).fetchone()["n"]

    rows = conn.execute(
        f"""
        WITH grouped AS (
          SELECT {_LISTING_KEY_SQL} AS listing_key,
                 si.source             AS source,
                 si.target_eurio_id    AS target_eurio_id,
                 MAX(si.listing_title) AS listing_title,
                 MAX(si.listing_price) AS listing_price,
                 MAX(si.listing_currency) AS listing_currency,
                 MAX(si.is_lot_suspected) AS is_lot_suspected,
                 COUNT(DISTINCT si.id)    AS n_images,
                 COUNT(DISTINCT a.id)     AS n_crops_in_review,
                 MIN(rq.enqueued_at)      AS oldest_enqueued_at,
                 (SELECT si2.id FROM source_images si2
                   WHERE si2.source = si.source
                     AND {_LISTING_KEY_SQL.replace('si.', 'si2.')} = {_LISTING_KEY_SQL}
                   ORDER BY si2.fetched_at ASC LIMIT 1) AS thumb_si_id
            FROM review_queue rq
            JOIN image_assets a ON a.id = rq.image_asset_id
            JOIN source_images si ON si.id = a.source_image_id
           WHERE rq.kind = 'lot' AND rq.status = 'open'{cohort_clause}
           GROUP BY listing_key
        )
        SELECT * FROM grouped
         ORDER BY oldest_enqueued_at ASC
         LIMIT ? OFFSET ?
        """,
        (*cohort_args, limit, offset),
    ).fetchall()

    items = [
        LotListItem(
            listing_key=r["listing_key"],
            source=r["source"],
            target_eurio_id=r["target_eurio_id"],
            listing_title=r["listing_title"],
            listing_price=r["listing_price"],
            listing_currency=r["listing_currency"] or "EUR",
            is_lot_suspected=bool(r["is_lot_suspected"]),
            n_images=r["n_images"],
            n_crops_in_review=r["n_crops_in_review"],
            oldest_enqueued_at=r["oldest_enqueued_at"],
            thumb_url=(
                f"/sources/{r['source']}/raws/{r['thumb_si_id']}/file"
                if r["thumb_si_id"] else None
            ),
        )
        for r in rows
    ]
    return LotListResponse(items=items, total=int(total or 0))


class LotCrop(BaseModel):
    asset_id: str
    review_id: str
    crop_url: str
    crop_index: int
    phash: int | None
    current_eurio_id: str | None
    candidate_eurio_ids: list[ReviewCandidate]
    bbox: ReviewBbox | None


class LotDetection(BaseModel):
    """One circle from `detect_circles_multi`, computed on-the-fly.

    Coordinates en native pixel space du raw (`raw_width × raw_height`).
    `accepted=True` → ce cercle a produit un image_asset (lien via
    `crop_index`). `accepted=False` → cercle écarté par les critères
    stricts, exposé pour la vue debug uniquement (Stage 2). Pas de
    persistance DB — recompute déterministe à chaque requête.
    """
    cx: int
    cy: int
    r: int
    accepted: bool
    reject_reason: str | None
    method: str
    crop_index: int | None  # None si rejected


class LotImage(BaseModel):
    source_image_id: str
    image_index: int | None
    raw_url: str
    raw_width: int | None
    raw_height: int | None
    detections: list[LotDetection]
    crops: list[LotCrop]


class LotDetail(BaseModel):
    listing_key: str
    source: str
    target_eurio_id: str | None
    # ReviewCandidate enrichi de la pièce proposée (idem
    # ReviewItem.target_candidate). Permet au front lot de la
    # pré-sélectionner comme défaut, exactement comme la page single. None
    # si target_eurio_id est None ou la coin n'est pas dans le catalog.
    target_candidate: ReviewCandidate | None = None
    listing_title: str | None
    listing_price: float | None
    listing_currency: str
    is_lot_suspected: bool
    is_multi_crop_single: bool  # niveau 2 D-26 : titre single mais image multi-crop
    images: list[LotImage]
    prev_listing_key: str | None
    next_listing_key: str | None


def _parse_candidates(json_str: str | None) -> list[ReviewCandidate]:
    if not json_str:
        return []
    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    out: list[ReviewCandidate] = []
    for c in raw:
        if not isinstance(c, dict) or "eurio_id" not in c:
            continue
        out.append(ReviewCandidate(
            eurio_id=c["eurio_id"],
            score=float(c.get("score", 0)),
            label=c.get("label", c["eurio_id"]),
            country=c.get("country", ""),
            denomination=c.get("denomination", ""),
            year=c.get("year"),
            canonical_thumb_url=c.get("canonical_thumb_url", ""),
        ))
    return out


def _parse_bbox(json_str: str | None) -> ReviewBbox | None:
    if not json_str:
        return None
    try:
        d = json.loads(json_str)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    return ReviewBbox(
        x=d.get("x", 0), y=d.get("y", 0), w=d.get("w", 0), h=d.get("h", 0),
    )


def _compute_detections(raw_storage_key: str | None,
                        crop_indices_in_db: list[int],
                        census: bool | None = None) -> list[LotDetection]:
    """Re-run le pipeline de détection complet (`normalize_listing_with_detections`
    : crop + gate anti-fragment) sur le raw — re-détection à la demande
    (Chunk C). N'est PLUS sur le chemin de chargement (get_lot lit le JSON
    persisté) ; appelé seulement quand l'humain relance la détection sur une
    image. Coûteux (YOLO+Hough), d'où le déclenchement manuel.

    Les détections acceptées sont mappées aux `image_assets` existants par
    ordre (pipeline déterministe : ordre accepté == ordre crop_index).

    `census` : aligne le mode sur le scrape (eBay = census=True). None = flag
    d'env. `raw_storage_key` = clé S3 `enrichment-raws` (read-through cache).
    """
    if not raw_storage_key:
        return []
    from shared.storage.local_cache import local_path as _local_path
    try:
        p = _local_path("enrichment-raws", raw_storage_key)
    except FileNotFoundError:
        return []
    bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return []
    # Passe par le pipeline COMPLET (crop + gate anti-fragment), pas par
    # detect_circles_multi brut : la re-détection LIVE doit produire EXACTEMENT
    # le même constat que le scrape. Sinon les capsules/fragments gatés au
    # scrape ressortent "acceptés" ici → overlay faux + mapping accepté→
    # crop_index décalé. On jette les crops (1er élément), on garde le constat.
    _, detections = normalize_listing_with_detections(bgr, census=census)
    out: list[LotDetection] = []
    accepted_idx = 0
    for det in detections:
        crop_index: int | None = None
        if det.accepted:
            if accepted_idx < len(crop_indices_in_db):
                crop_index = crop_indices_in_db[accepted_idx]
            accepted_idx += 1
        out.append(LotDetection(
            cx=det.cx, cy=det.cy, r=det.r,
            accepted=det.accepted,
            reject_reason=det.reject_reason,
            method=det.method,
            crop_index=crop_index,
        ))
    return out


def _lot_detections_from_json(
    detections_json: str | None,
    crop_indices_in_db: list[int],
) -> list[LotDetection]:
    """Lit les détections persistées (`source_images.detections_json`) et
    mappe les cercles ACCEPTÉS aux `crop_index` existants par ordre — même
    logique que `_compute_detections`, mais zéro recompute.

    Persistées au scrape par `detect_crop._detection_to_dict`. Renvoie []
    si la colonne est nulle (listing pré-backfill → la plate sera vide tant
    qu'on n'a pas relancé la détection à la main, cf. Chunk C).
    """
    if not detections_json:
        return []
    try:
        raw = json.loads(detections_json)
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[LotDetection] = []
    accepted_idx = 0
    for det in raw:
        crop_index: int | None = None
        if det.get("accepted"):
            if accepted_idx < len(crop_indices_in_db):
                crop_index = crop_indices_in_db[accepted_idx]
            accepted_idx += 1
        out.append(LotDetection(
            cx=det.get("cx", 0), cy=det.get("cy", 0), r=det.get("r", 0),
            accepted=bool(det.get("accepted")),
            reject_reason=det.get("reject_reason"),
            method=det.get("method", ""),
            crop_index=crop_index,
        ))
    return out


def _siblings(conn: sqlite3.Connection, listing_key: str
              ) -> tuple[str | None, str | None]:
    """Find the previous and next listing_key in the open lots queue (by
    oldest enqueued_at — same order as `GET /review-queue/lots`). Returns
    `(prev, next)`, either side ``None`` at the boundaries."""
    rows = conn.execute(
        f"""
        SELECT {_LISTING_KEY_SQL} AS listing_key,
               MIN(rq.enqueued_at) AS oldest_enqueued_at
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
         WHERE rq.kind = 'lot' AND rq.status = 'open'
         GROUP BY listing_key
         ORDER BY oldest_enqueued_at ASC, listing_key ASC
        """,
    ).fetchall()
    keys = [r["listing_key"] for r in rows]
    if listing_key not in keys:
        return None, None
    i = keys.index(listing_key)
    prev_key = keys[i - 1] if i > 0 else None
    next_key = keys[i + 1] if i + 1 < len(keys) else None
    return prev_key, next_key


# Consumed by: admin/packages/web/src/features/review/composables/useLotReview.ts (fetchLotDetail)
@router.get("/lots/{listing_key}", response_model=LotDetail)
def get_lot(listing_key: str) -> LotDetail:
    conn = _store()._connection()  # noqa: SLF001
    # Header (depuis n'importe quelle source_image du listing).
    # JOIN coins pour enrichir target_candidate (idem _row_to_item).
    header = conn.execute(
        f"""
        SELECT si.source, si.target_eurio_id, si.listing_title,
               si.listing_price, si.listing_currency, si.is_lot_suspected,
               t.eurio_id     AS t_eurio_id,
               t.country      AS t_country,
               t.country_name AS t_country_name,
               t.year         AS t_year,
               t.theme        AS t_theme,
               t.face_value   AS t_face_value,
               t.numista_id   AS t_numista_id
          FROM source_images si
          LEFT JOIN coins t ON t.eurio_id = si.target_eurio_id
         WHERE {_LISTING_KEY_SQL} = ?
         LIMIT 1
        """,
        (listing_key,),
    ).fetchone()
    if header is None:
        raise HTTPException(status_code=404, detail=f"Lot '{listing_key}' not found.")

    # Toutes les source_images du listing (une seule requête JOIN).
    rows = conn.execute(
        f"""
        SELECT si.id AS source_image_id,
               si.raw_payload_json,
               si.storage_path AS raw_storage_path,
               si.detections_json AS detections_json,
               si.width AS raw_width, si.height AS raw_height,
               a.id AS asset_id,
               a.crop_index, a.bbox_json, a.phash, a.eurio_id AS current_eurio_id,
               a.candidate_eurio_ids_json,
               rq.id AS review_id, rq.status AS rq_status, rq.kind AS rq_kind,
               si.source AS source
          FROM source_images si
          LEFT JOIN image_assets a ON a.source_image_id = si.id
          LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
         WHERE {_LISTING_KEY_SQL} = ?
         ORDER BY si.id, a.crop_index
        """,
        (listing_key,),
    ).fetchall()

    # detections_json persisté au scrape, gardé de côté par source_image.
    detections_json_by_si: dict[str, str | None] = {}
    by_si: dict[str, LotImage] = {}
    for r in rows:
        si_id = r["source_image_id"]
        if si_id not in by_si:
            image_index: int | None = None
            if r["raw_payload_json"]:
                try:
                    payload = json.loads(r["raw_payload_json"])
                    image_index = payload.get("image_index")
                except json.JSONDecodeError:
                    pass
            detections_json_by_si[si_id] = r["detections_json"]
            by_si[si_id] = LotImage(
                source_image_id=si_id,
                image_index=image_index,
                raw_url=f"/sources/{r['source']}/raws/{si_id}/file",
                raw_width=r["raw_width"],
                raw_height=r["raw_height"],
                detections=[],
                crops=[],
            )
        # Skip rows where the LEFT JOIN didn't produce a crop (image with 0 detect).
        if r["asset_id"] is None:
            continue
        # Only surface crops that are actually in the lot review queue
        # (or any crop on a multi-crop image — useful for context).
        # V1.5 : on liste tous les crops du listing, le front filtrera
        # les actions sur ceux dont rq.kind='lot' AND rq.status='open'.
        by_si[si_id].crops.append(LotCrop(
            asset_id=r["asset_id"],
            review_id=r["review_id"] or "",
            crop_url=f"/sources/{r['source']}/assets/{r['asset_id']}/file",
            crop_index=r["crop_index"] or 0,
            phash=r["phash"],
            current_eurio_id=r["current_eurio_id"],
            candidate_eurio_ids=_parse_candidates(r["candidate_eurio_ids_json"]),
            bbox=_parse_bbox(r["bbox_json"]),
        ))

    # Lecture des détections persistées au scrape (Stage 2 debug). Plus de
    # recompute live ici — c'était la cause des ~67s. Le rafraîchissement à
    # la main se fait via l'endpoint /images/{sid}/detect (Chunk C). Crops
    # triés par crop_index déjà (ORDER BY si.id, a.crop_index).
    for si_id, im in by_si.items():
        crop_indices = [c.crop_index for c in im.crops]
        im.detections = _lot_detections_from_json(
            detections_json_by_si.get(si_id), crop_indices,
        )

    # Tri images par image_index (None à la fin).
    images = sorted(
        by_si.values(),
        key=lambda im: (im.image_index is None, im.image_index or 0),
    )

    # is_multi_crop_single : titre n'est PAS lot mais ≥1 image multi-crop.
    is_multi_crop_single = (
        not bool(header["is_lot_suspected"])
        and any(len(im.crops) > 1 for im in images)
    )

    prev_key, next_key = _siblings(conn, listing_key)

    return LotDetail(
        listing_key=listing_key,
        source=header["source"],
        target_eurio_id=header["target_eurio_id"],
        target_candidate=_build_target_candidate(header, header["target_eurio_id"]),
        listing_title=header["listing_title"],
        listing_price=header["listing_price"],
        listing_currency=header["listing_currency"] or "EUR",
        is_lot_suspected=bool(header["is_lot_suspected"]),
        is_multi_crop_single=is_multi_crop_single,
        images=images,
        prev_listing_key=prev_key,
        next_listing_key=next_key,
    )


class LotImageDetectResponse(BaseModel):
    source_image_id: str
    detections: list[LotDetection]


# Consumed by: admin/packages/web/src/features/review/composables/useLotReview.ts (detectLotImage)
@router.post("/lots/{listing_key}/images/{source_image_id}/detect",
             response_model=LotImageDetectResponse)
def detect_lot_image(listing_key: str, source_image_id: str) -> LotImageDetectResponse:
    """Re-détection LIVE d'UNE image du listing (Chunk C) — rattrapage manuel
    quand le scrape a raté des pièces.

    Relance le pipeline complet (gate anti-fragment inclus, mode aligné scrape :
    eBay = census), met à
    jour `source_images.detections_json`, et renvoie les cercles (acceptés +
    rejetés) pour overlay immédiat. Coûteux (YOLO+Hough) → déclenché à la main,
    une image à la fois (jamais sur le chemin de chargement, cf. Chunk A).
    """
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        f"""
        SELECT si.id, si.source, si.storage_path
          FROM source_images si
         WHERE {_LISTING_KEY_SQL} = ? AND si.id = ?
         LIMIT 1
        """,
        (listing_key, source_image_id),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Image '{source_image_id}' not found in lot '{listing_key}'.",
        )

    # crop_index existants → mapping accepté→crop_index (ordre déterministe).
    crop_indices = [
        r["crop_index"] for r in conn.execute(
            "SELECT crop_index FROM image_assets WHERE source_image_id = ? "
            "ORDER BY crop_index",
            (source_image_id,),
        ).fetchall()
    ]
    detections = _compute_detections(
        row["storage_path"], crop_indices, census=(row["source"] == "ebay"),
    )

    # Persiste le constat rafraîchi (sans crop_index — dérivé à la lecture par
    # _lot_detections_from_json). Même schéma que detect_crop._detection_to_dict.
    conn.execute(
        "UPDATE source_images SET detections_json = ? WHERE id = ?",
        (json.dumps([{
            "cx": d.cx, "cy": d.cy, "r": d.r, "method": d.method,
            "accepted": d.accepted, "reject_reason": d.reject_reason,
        } for d in detections]), source_image_id),
    )
    conn.commit()
    return LotImageDetectResponse(source_image_id=source_image_id, detections=detections)


class LotAddCropPayload(BaseModel):
    cx: float
    cy: float
    r: float


# Consumed by: admin/packages/web/src/features/review/composables/useLotReview.ts (addLotCrop)
@router.post("/lots/{listing_key}/images/{source_image_id}/crops",
             response_model=LotCrop)
def add_lot_crop(listing_key: str, source_image_id: str,
                 payload: LotAddCropPayload) -> LotCrop:
    """Add-crop manuel (Chunk D) : crée un nouveau crop sur l'image depuis un
    cercle (cx,cy,r) en px natifs du raw — rattrapage des pièces ratées par la
    détection (depuis un cercle détecté cliqué OU un tracé manuel). Le crop
    rejoint la review (kind lot) avec ses candidats ; les crops frères ne sont
    pas touchés. Renvoie le LotCrop pour insertion live côté front.
    """
    conn = _store()._connection()  # noqa: SLF001
    src = conn.execute(
        f"""
        SELECT si.source FROM source_images si
         WHERE {_LISTING_KEY_SQL} = ? AND si.id = ?
         LIMIT 1
        """,
        (listing_key, source_image_id),
    ).fetchone()
    if src is None:
        raise HTTPException(
            status_code=404,
            detail=f"Image '{source_image_id}' not found in lot '{listing_key}'.",
        )

    from serving.crop_edit import create_manual_crop
    new = create_manual_crop(
        _store(), source_image_id, payload.cx, payload.cy, payload.r)
    return LotCrop(
        asset_id=new.asset_id,
        review_id=new.review_id,
        crop_url=f"/sources/{src['source']}/assets/{new.asset_id}/file",
        crop_index=new.crop_index,
        phash=new.phash,
        current_eurio_id=None,
        candidate_eurio_ids=_parse_candidates(json.dumps(new.candidate_eurio_ids)),
        bbox=_parse_bbox(json.dumps(new.bbox)),
    )


class LotSyncCropsResponse(BaseModel):
    source_image_id: str
    crops: list[LotCrop]
    repointed: int
    created: int
    deleted: int


# Consumed by: admin/packages/web/src/features/review/composables/useLotReview.ts (syncLotCrops)
@router.post("/lots/{listing_key}/images/{source_image_id}/sync-crops",
             response_model=LotSyncCropsResponse)
def sync_lot_crops(listing_key: str, source_image_id: str) -> LotSyncCropsResponse:
    """Resync crops ↔ détection — action EXPLICITE, distincte de Re-détecter.

    Reconstruit les crops d'UNE image pour coller aux cercles ACCEPTÉS du
    constat persisté (`detections_json` = l'overlay que l'humain voit et valide) :
      - re-pointe les crops existants sur les cercles (`apply_manual_crop` :
        écrase le fichier en place + recompute Dino → corrige aussi les
        suggestions périmées) ;
      - crée les crops manquants (`create_manual_crop`) ;
      - supprime le surplus (`delete_crop`, cascade).

    Garde : REFUSE (409) si un crop de l'image est déjà décidé (review ≠ 'open')
    — on ne réécrit pas une décision humaine. Ne relance PAS la détection :
    relance Re-détecter d'abord si l'overlay est périmé. Le mapping cercle↔crop
    est par ordre (accepté[i] → crop_index[i]) — cohérent avec l'overlay.
    """
    conn = _store()._connection()  # noqa: SLF001
    img = conn.execute(
        f"""
        SELECT si.id, si.source, si.detections_json
          FROM source_images si
         WHERE {_LISTING_KEY_SQL} = ? AND si.id = ?
         LIMIT 1
        """,
        (listing_key, source_image_id),
    ).fetchone()
    if img is None:
        raise HTTPException(
            status_code=404,
            detail=f"Image '{source_image_id}' not found in lot '{listing_key}'.",
        )

    crops = conn.execute(
        """
        SELECT a.id AS asset_id, a.crop_index, rq.status AS rq_status
          FROM image_assets a
          LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
         WHERE a.source_image_id = ?
         ORDER BY a.crop_index
        """,
        (source_image_id,),
    ).fetchall()
    decided = [c["asset_id"] for c in crops if c["rq_status"] and c["rq_status"] != "open"]
    if decided:
        raise HTTPException(
            status_code=409,
            detail=(f"{len(decided)} crop(s) déjà décidé(s) sur cette image — "
                    "resync refusée (annule la/les décision(s) d'abord)."),
        )

    accepted = [d for d in json.loads(img["detections_json"] or "[]") if d.get("accepted")]
    if not accepted:
        raise HTTPException(
            status_code=422,
            detail="Aucun cercle accepté dans le constat — relance Re-détecter d'abord.",
        )

    from serving.crop_edit import apply_manual_crop, create_manual_crop, delete_crop
    existing = list(crops)
    n_repoint = min(len(existing), len(accepted))
    for i in range(n_repoint):
        d = accepted[i]
        apply_manual_crop(_store(), existing[i]["asset_id"],
                          float(d["cx"]), float(d["cy"]), float(d["r"]))
    for i in range(n_repoint, len(accepted)):
        d = accepted[i]
        create_manual_crop(_store(), source_image_id,
                           float(d["cx"]), float(d["cy"]), float(d["r"]))
    for i in range(len(accepted), len(existing)):
        delete_crop(_store(), existing[i]["asset_id"])

    # Recharge les crops de l'image post-sync (même format que get_lot).
    rows = conn.execute(
        """
        SELECT a.id AS asset_id, a.crop_index, a.bbox_json, a.phash,
               a.eurio_id AS current_eurio_id, a.candidate_eurio_ids_json,
               rq.id AS review_id
          FROM image_assets a
          LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
         WHERE a.source_image_id = ?
         ORDER BY a.crop_index
        """,
        (source_image_id,),
    ).fetchall()
    out_crops = [
        LotCrop(
            asset_id=r["asset_id"],
            review_id=r["review_id"] or "",
            crop_url=f"/sources/{img['source']}/assets/{r['asset_id']}/file",
            crop_index=r["crop_index"] or 0,
            phash=r["phash"],
            current_eurio_id=r["current_eurio_id"],
            candidate_eurio_ids=_parse_candidates(r["candidate_eurio_ids_json"]),
            bbox=_parse_bbox(r["bbox_json"]),
        )
        for r in rows
    ]
    return LotSyncCropsResponse(
        source_image_id=source_image_id,
        crops=out_crops,
        repointed=n_repoint,
        created=max(0, len(accepted) - len(existing)),
        deleted=max(0, len(existing) - len(accepted)),
    )


class LotAssignment(BaseModel):
    asset_id: str
    eurio_id: str | None = None
    face: str | None = None
    variant_kind: str | None = None
    reject_reason: str | None = None
    skip: bool = False


class LotDecidePayload(BaseModel):
    assignments: list[LotAssignment]


class LotDecideResponse(BaseModel):
    done: int
    rejected: int
    skipped: int
    errors: list[str]


# Consumed by: admin/packages/web/src/features/review/composables/useLotReview.ts (decideLot)
@router.post("/lots/{listing_key}/decide", response_model=LotDecideResponse)
def decide_lot(listing_key: str, payload: LotDecidePayload) -> LotDecideResponse:
    """Bulk decision sur un listing entier.

    Pour chaque assignment :
      - eurio_id → image_assets.resolution_status='manual', eurio_id=X ;
        review_queue.status='done', decided_eurio_id=X
      - reject_reason → image_assets.resolution_status='rejected' ;
        review_queue.status='done', decision_notes=reason
      - skip=True → review_queue.status='skipped' (sans toucher l'asset)

    Idempotence : si une review row n'est plus 'open' (déjà décidée),
    on l'ajoute aux errors mais on poursuit.
    Validation : chaque asset_id doit appartenir au listing — sinon erreur.
    """
    if not payload.assignments:
        return LotDecideResponse(done=0, rejected=0, skipped=0, errors=[])

    conn = _store()._connection()  # noqa: SLF001
    # Récupère tous les assets du listing avec leur review_id.
    listing_assets = {
        r["asset_id"]: r
        for r in conn.execute(
            f"""
            SELECT a.id AS asset_id,
                   rq.id AS review_id,
                   rq.status AS rq_status
              FROM source_images si
              JOIN image_assets a ON a.source_image_id = si.id
              LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
             WHERE {_LISTING_KEY_SQL} = ?
            """,
            (listing_key,),
        ).fetchall()
    }
    if not listing_assets:
        raise HTTPException(status_code=404, detail=f"Lot '{listing_key}' not found.")

    now_iso = _now_iso()
    n_done = 0
    n_rejected = 0
    n_skipped = 0
    errors: list[str] = []

    conn.execute("BEGIN")
    try:
        for asg in payload.assignments:
            asset_row = listing_assets.get(asg.asset_id)
            if asset_row is None:
                errors.append(f"asset {asg.asset_id} does not belong to lot {listing_key}")
                continue
            review_id = asset_row["review_id"]
            rq_status = asset_row["rq_status"]
            if review_id is None:
                errors.append(f"asset {asg.asset_id} has no review_queue row")
                continue
            if rq_status != "open":
                errors.append(f"asset {asg.asset_id} already {rq_status}")
                continue

            # Decide path
            if asg.eurio_id:
                face = asg.face or "unknown"
                if face not in _VALID_FACES:
                    errors.append(f"asset {asg.asset_id} invalid face '{face}'")
                    continue
                conn.execute(
                    """
                    UPDATE image_assets
                       SET eurio_id = ?, face = ?,
                           variant_kind = COALESCE(?, variant_kind),
                           resolution_status = 'manual',
                           resolution_confidence = 1.0,
                           training_eligible = 1,
                           resolved_at = ?
                     WHERE id = ?
                    """,
                    (asg.eurio_id, face, asg.variant_kind, now_iso, asg.asset_id),
                )
                cur = conn.execute(
                    """
                    UPDATE review_queue
                       SET status = 'done',
                           decided_eurio_id = ?, decided_face = ?,
                           decided_variant_kind = ?, decided_at = ?,
                           decided_by = 'admin',
                           decision_engine_version = ?,
                           decision_metadata_json = ?
                     WHERE id = ? AND status = 'open'
                    """,
                    (asg.eurio_id, face, asg.variant_kind, now_iso,
                     _HUMAN_ENGINE_VERSION,
                     json.dumps({"context": "lot_bulk", "face_chosen": face}),
                     review_id),
                )
                if cur.rowcount != 1:
                    errors.append(
                        f"asset {asg.asset_id} decided concurrently — skipped"
                    )
                    continue
                emit_state_event(
                    conn, asset_id=asg.asset_id, to_state="resolved",
                    actor="human", reason="human_decided_lot", eurio_id=asg.eurio_id,
                )
                n_done += 1

            # Reject path
            elif asg.reject_reason:
                if asg.reject_reason not in _VALID_REJECT_REASONS:
                    errors.append(
                        f"asset {asg.asset_id} invalid reject_reason "
                        f"'{asg.reject_reason}' — accepted: {_VALID_REJECT_REASONS}"
                    )
                    continue
                conn.execute(
                    """
                    UPDATE image_assets
                       SET resolution_status = 'rejected',
                           training_eligible = 0,
                           quality_reason = 'rejected_in_review',
                           resolved_at = ?
                     WHERE id = ?
                    """,
                    (now_iso, asg.asset_id),
                )
                cur = conn.execute(
                    """
                    UPDATE review_queue
                       SET status = 'done',
                           decision_notes = ?, decided_at = ?, decided_by = 'admin',
                           decision_engine_version = ?,
                           decision_metadata_json = ?
                     WHERE id = ? AND status = 'open'
                    """,
                    (asg.reject_reason, now_iso, _HUMAN_ENGINE_VERSION,
                     json.dumps({"reason": asg.reject_reason, "context": "lot_bulk"}),
                     review_id),
                )
                if cur.rowcount != 1:
                    errors.append(
                        f"asset {asg.asset_id} decided concurrently — skipped"
                    )
                    continue
                emit_state_event(
                    conn, asset_id=asg.asset_id, to_state="rejected",
                    actor="human", reason=f"trash_{asg.reject_reason}",
                )
                n_rejected += 1

            # Skip path
            elif asg.skip:
                cur = conn.execute(
                    "UPDATE review_queue SET status = 'skipped' "
                    " WHERE id = ? AND status = 'open'",
                    (review_id,),
                )
                if cur.rowcount != 1:
                    errors.append(
                        f"asset {asg.asset_id} decided concurrently — skipped"
                    )
                    continue
                emit_state_event(
                    conn, asset_id=asg.asset_id, to_state="skipped",
                    actor="human", reason="deferred_lot",
                )
                n_skipped += 1

            else:
                errors.append(
                    f"asset {asg.asset_id} has no action "
                    "(provide eurio_id, reject_reason, or skip=true)"
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info(
        "[lot] decide listing=%s done=%d rejected=%d skipped=%d errors=%d",
        listing_key, n_done, n_rejected, n_skipped, len(errors),
    )
    return LotDecideResponse(
        done=n_done, rejected=n_rejected, skipped=n_skipped, errors=errors,
    )


# ── Single review fetch / mutations (existing) ────────────────────────────


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (fetchReviewItem)
@router.get("/{review_id}", response_model=ReviewItem)
def get_review(review_id: str) -> ReviewItem:
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT rq.id, rq.image_asset_id, rq.priority, rq.enqueued_at,
               rq.candidate_eurio_ids_json AS rq_candidates,
               a.bbox_json, a.candidate_eurio_ids_json, a.face, a.quality_score,
               s.source, s.source_ref, s.listing_title, s.source_url,
               s.listing_price, s.target_eurio_id,
               s.listing_country, s.listing_year,
               s.listing_origin_date, s.sold_qty,
               lts.listing_kind, lts.listing_kind_confidence,
               lts.condition_normalized, lts.condition_confidence,
               t.eurio_id     AS t_eurio_id,
               t.country      AS t_country,
               t.country_name AS t_country_name,
               t.year         AS t_year,
               t.theme        AS t_theme,
               t.face_value   AS t_face_value,
               t.numista_id   AS t_numista_id,
               p.top1_country_eurio_id AS dino_top1_country_eurio_id,
               p.top1_country_sim      AS dino_top1_country_sim,
               p.top1_eurio_id         AS dino_top1_eurio_id,
               p.top1_sim              AS dino_top1_sim
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN listing_text_signals lts ON lts.source_image_id = s.id
          LEFT JOIN coins t   ON t.eurio_id = s.target_eurio_id
          LEFT JOIN image_asset_dino_predictions p
                 ON p.asset_id = a.id
                AND p.encoder_version = 'dinov2-vits14'
                AND p.anchors_kind = '2eur_commemo'
         WHERE rq.id = ?
        """,
        (review_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return _row_to_item(row, conn=conn)


# ── Mutations ─────────────────────────────────────────────────────────────


class DecidePayload(BaseModel):
    eurio_id: str = Field(min_length=1)
    face: str
    variant_kind: str | None = None
    notes: str | None = None


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (decideReview)
@router.post("/{review_id}/decide", status_code=200)
def decide_review(review_id: str, payload: DecidePayload) -> dict[str, str]:
    if payload.face not in _VALID_FACES:
        raise HTTPException(
            status_code=422, detail=f"face must be one of {_VALID_FACES}",
        )

    conn = _store()._connection()  # noqa: SLF001
    rq = conn.execute(
        "SELECT id, image_asset_id, status FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review already {rq['status']} — cannot decide twice.",
        )

    now_iso = _now_iso()
    asset_id = rq["image_asset_id"]

    # Two-step transaction: image_assets + review_queue.
    # Atomicité « premier-écrit-gagne » : l'UPDATE final de review_queue
    # inclut `AND status='open'`. Si rowcount=0, une autre voie (auto_dino,
    # claude_ack ou un autre onglet humain) a déjà tranché — on ROLLBACK
    # et on renvoie 409 plutôt que d'écraser. Cf. docs/operations/.
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            UPDATE image_assets
               SET eurio_id = ?,
                   face = ?,
                   variant_kind = COALESCE(?, variant_kind),
                   resolution_status = 'manual',
                   resolution_confidence = 1.0,
                   training_eligible = 1,
                   resolved_at = ?
             WHERE id = ?
            """,
            (payload.eurio_id, payload.face, payload.variant_kind, now_iso, asset_id),
        )
        metadata = json.dumps({
            k: v for k, v in {"notes": payload.notes}.items() if v is not None
        })
        cur = conn.execute(
            """
            UPDATE review_queue
               SET status = 'done',
                   decided_eurio_id = ?,
                   decided_face = ?,
                   decided_variant_kind = ?,
                   decision_notes = ?,
                   decided_at = ?,
                   decided_by = 'admin',
                   decision_engine_version = ?,
                   decision_metadata_json = ?
             WHERE id = ? AND status = 'open'
            """,
            (payload.eurio_id, payload.face, payload.variant_kind,
             payload.notes, now_iso,
             _HUMAN_ENGINE_VERSION, metadata, review_id),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=409,
                detail="Review already decided concurrently by another voie.",
            )
        emit_state_event(
            conn, asset_id=asset_id, to_state="resolved", actor="human",
            reason="human_decided", eurio_id=payload.eurio_id,
        )
        conn.execute("COMMIT")
    except HTTPException:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info("[review] decided id=%s eurio_id=%s face=%s",
                review_id, payload.eurio_id, payload.face)
    return {"status": "done", "id": review_id}


# ── Correction listing_kind / condition (chunk C4) ────────────────────────

_VALID_LISTING_KINDS = ("single", "lot", "coffret", "graded_slab")
_VALID_CONDITIONS = ("UNC", "TTB", "TB")


class CorrectListingPayload(BaseModel):
    listing_kind: str | None = None
    condition: str | None = None


# Consumed by: admin/.../review/composables/useReviewApi.ts (correctListing)
@router.post("/{review_id}/correct-listing", status_code=200)
def correct_listing(review_id: str, payload: CorrectListingPayload) -> dict[str, Any]:
    """Corrige manuellement listing_kind et/ou condition d'un listing.

    La correction se propage à **toutes** les source_images du listing
    (N photos → N rows) et marque ``extractor_version='manual'`` : le
    step C2 ``text_signal`` ne ré-écrasera plus ces signaux. Indépendant
    de la décision d'attribution — la review reste ``open``.
    """
    if payload.listing_kind is None and payload.condition is None:
        raise HTTPException(
            status_code=422, detail="Provide listing_kind and/or condition.",
        )
    if payload.listing_kind is not None and payload.listing_kind not in _VALID_LISTING_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"listing_kind must be one of {_VALID_LISTING_KINDS}",
        )
    if payload.condition is not None and payload.condition not in _VALID_CONDITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"condition must be one of {_VALID_CONDITIONS}",
        )

    conn = _store()._connection()  # noqa: SLF001
    si = conn.execute(
        """
        SELECT s.id AS sid, s.source, s.source_url
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
         WHERE rq.id = ?
        """,
        (review_id,),
    ).fetchone()
    if si is None:
        raise HTTPException(status_code=404, detail="Review item not found.")

    # Toutes les source_images du même listing — identité = source_url
    # (page de l'annonce, partagée par les N photos). Fallback : la row
    # seule si l'URL est absente.
    if si["source_url"]:
        sibling_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM source_images WHERE source = ? AND source_url = ?",
                (si["source"], si["source_url"]),
            ).fetchall()
        ]
    else:
        sibling_ids = [si["sid"]]

    sets = ["extractor_version = 'manual'", "computed_at = datetime('now')"]
    args: list[Any] = []
    if payload.listing_kind is not None:
        sets.append("listing_kind = ?")
        sets.append("listing_kind_confidence = 1.0")
        args.append(payload.listing_kind)
    if payload.condition is not None:
        sets.append("condition_normalized = ?")
        sets.append("condition_confidence = 1.0")
        args.append(payload.condition)

    placeholders = ",".join("?" * len(sibling_ids))
    conn.execute(
        f"UPDATE listing_text_signals SET {', '.join(sets)} "  # noqa: S608
        f"WHERE source_image_id IN ({placeholders})",
        (*args, *sibling_ids),
    )
    conn.commit()
    logger.info(
        "[review] correct-listing id=%s kind=%s condition=%s → %d images",
        review_id, payload.listing_kind, payload.condition, len(sibling_ids),
    )
    return {
        "status": "ok",
        "id": review_id,
        "n_images": len(sibling_ids),
        "listing_kind": payload.listing_kind,
        "condition": payload.condition,
    }


class RequalifyLotResponse(BaseModel):
    status: str
    listing_key: str
    n_requalified: int   # rows review_queue passées en kind='lot'
    n_images: int        # source_images du listing touchées


# Consumed by: admin/.../review/composables/useReviewApi.ts (requalifyReviewAsLot)
@router.post("/{review_id}/requalify-lot", response_model=RequalifyLotResponse)
def requalify_lot(review_id: str) -> RequalifyLotResponse:
    """Requalifie le crop courant — et TOUT son listing — en LOT.

    Le crop était en review SINGLE mais l'annonce est en réalité un lot
    (plusieurs pièces). On bascule toutes les rows ``open`` du listing en
    ``review_queue.kind='lot'`` : elles quittent la queue single et
    apparaissent dans le flow lot (groupé par ``listing_key``). On marque
    aussi ``listing_kind='lot'`` (taxonomie, ``extractor_version='manual'``)
    pour cohérence + empêcher une re-classification auto en single."""
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        f"""
        SELECT {_LISTING_KEY_SQL} AS listing_key
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
         WHERE rq.id = ?
        """,
        (review_id,),
    ).fetchone()
    if row is None or not row["listing_key"]:
        raise HTTPException(status_code=404, detail="Review item not found.")
    listing_key = row["listing_key"]

    # Toutes les source_images du listing (même listing_key) → leurs rows.
    sids = [
        r["sid"] for r in conn.execute(
            f"SELECT si.id AS sid FROM source_images si "  # noqa: S608
            f"WHERE {_LISTING_KEY_SQL} = ?",
            (listing_key,),
        ).fetchall()
    ]
    if not sids:
        raise HTTPException(status_code=404, detail="Listing has no images.")
    ph = ",".join("?" * len(sids))

    with conn:
        cur = conn.execute(
            f"""
            UPDATE review_queue
               SET kind = 'lot'
             WHERE status = 'open' AND kind != 'lot'
               AND image_asset_id IN (
                   SELECT a.id FROM image_assets a
                    WHERE a.source_image_id IN ({ph})
               )
            """,  # noqa: S608
            sids,
        )
        n_requalified = cur.rowcount or 0
        # Taxonomie : marque le listing en 'lot' (manuel → non ré-écrasé par C2).
        conn.execute(
            f"""
            UPDATE listing_text_signals
               SET listing_kind = 'lot', listing_kind_confidence = 1.0,
                   extractor_version = 'manual', computed_at = datetime('now')
             WHERE source_image_id IN ({ph})
            """,  # noqa: S608
            sids,
        )

    logger.info("[review] requalify-lot id=%s listing=%s rows=%d images=%d",
                review_id, listing_key, n_requalified, len(sids))
    return RequalifyLotResponse(
        status="ok", listing_key=listing_key,
        n_requalified=n_requalified, n_images=len(sids),
    )


# Consumed by: admin/.../review/composables/useLotReview.ts (requalifyLotAsSingle)
@router.post("/lots/{listing_key}/requalify-single", response_model=RequalifyLotResponse)
def requalify_single(listing_key: str) -> RequalifyLotResponse:
    """Inverse de requalify-lot : le listing n'est PAS un lot (faux positif de
    la classif v2). Rebascule toutes ses rows ``open`` en ``kind='single'`` +
    ``listing_kind='single'`` → elles repartent dans le flow single."""
    conn = _store()._connection()  # noqa: SLF001
    sids = [
        r["sid"] for r in conn.execute(
            f"SELECT si.id AS sid FROM source_images si "  # noqa: S608
            f"WHERE {_LISTING_KEY_SQL} = ?",
            (listing_key,),
        ).fetchall()
    ]
    if not sids:
        raise HTTPException(status_code=404, detail=f"Lot '{listing_key}' not found.")
    ph = ",".join("?" * len(sids))

    with conn:
        cur = conn.execute(
            f"""
            UPDATE review_queue
               SET kind = 'single'
             WHERE status = 'open' AND kind != 'single'
               AND image_asset_id IN (
                   SELECT a.id FROM image_assets a
                    WHERE a.source_image_id IN ({ph})
               )
            """,  # noqa: S608
            sids,
        )
        n_requalified = cur.rowcount or 0
        conn.execute(
            f"""
            UPDATE listing_text_signals
               SET listing_kind = 'single', listing_kind_confidence = 1.0,
                   extractor_version = 'manual', computed_at = datetime('now')
             WHERE source_image_id IN ({ph})
            """,  # noqa: S608
            sids,
        )

    logger.info("[review] requalify-single listing=%s rows=%d images=%d",
                listing_key, n_requalified, len(sids))
    return RequalifyLotResponse(
        status="ok", listing_key=listing_key,
        n_requalified=n_requalified, n_images=len(sids),
    )


class BatchRequalifyLotResponse(BaseModel):
    dry_run: bool
    n_rows: int                      # rows single→lot (prévues / effectuées)
    n_listings: int                  # listings distincts concernés
    by_listing_kind: dict[str, int]  # {'coffret': N, 'lot': M}


# Filtre commun : rows open kind='single' dont le listing est classé lot/coffret.
_BATCH_LOT_WHERE = """
  rq.status = 'open' AND rq.kind = 'single'
  AND a.id IN (
    SELECT a2.id FROM image_assets a2
      JOIN listing_text_signals lts ON lts.source_image_id = a2.source_image_id
     WHERE lts.listing_kind IN ('lot', 'coffret')
  )
"""


# Endpoint de MAINTENANCE (piloté manuellement en dry-run puis exécution).
# Pas de consommateur front pour l'instant ; un bouton dashboard pourra
# l'appeler si le besoin devient récurrent.
@router.post("/requalify-lot/batch", response_model=BatchRequalifyLotResponse)
def batch_requalify_lot(
    dry_run: bool = Query(default=True),
) -> BatchRequalifyLotResponse:
    """Requalifie en LOT, en masse, tous les crops encore en queue SINGLE dont
    le listing est déjà classé ``lot``/``coffret`` (faux-singles : v2 a vu le
    lot mais le routing n'a pas suivi). ``dry_run=True`` (défaut) ne compte que.

    Ne touche PAS ``listing_text_signals`` (déjà lot/coffret) — uniquement le
    routing ``review_queue.kind``. Idempotent (filtre kind='single')."""
    conn = _store()._connection()  # noqa: SLF001

    # Breakdown par listing_kind (toujours calculé, dry-run inclus).
    by_kind = {
        r["lk"]: r["n"]
        for r in conn.execute(
            """
            SELECT lts.listing_kind AS lk, COUNT(*) AS n
              FROM review_queue rq
              JOIN image_assets a ON a.id = rq.image_asset_id
              JOIN listing_text_signals lts ON lts.source_image_id = a.source_image_id
             WHERE rq.status = 'open' AND rq.kind = 'single'
               AND lts.listing_kind IN ('lot', 'coffret')
             GROUP BY lts.listing_kind
            """,
        ).fetchall()
    }
    n_rows = sum(by_kind.values())
    n_listings = conn.execute(
        f"""
        SELECT COUNT(DISTINCT {_LISTING_KEY_SQL}) AS n
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
          JOIN listing_text_signals lts ON lts.source_image_id = si.id
         WHERE rq.status = 'open' AND rq.kind = 'single'
           AND lts.listing_kind IN ('lot', 'coffret')
        """,
    ).fetchone()["n"]

    if not dry_run and n_rows:
        with conn:
            conn.execute(
                f"UPDATE review_queue SET kind = 'lot' "  # noqa: S608
                f"WHERE rowid IN (SELECT rq.rowid FROM review_queue rq "
                f"JOIN image_assets a ON a.id = rq.image_asset_id "
                f"WHERE {_BATCH_LOT_WHERE})",
            )
        logger.info("[review] batch requalify-lot EXECUTED rows=%d listings=%d",
                    n_rows, n_listings)

    return BatchRequalifyLotResponse(
        dry_run=dry_run, n_rows=n_rows, n_listings=n_listings,
        by_listing_kind=by_kind,
    )


# Trash = sous-cas de reject avec une raison QUALITÉ explicite (chantier
# crop-quality-overhaul, Session B). Le tail des crops imprécis est surtout
# du DÉCHET (non-pièce : coincards, certificats, tubes ; ou photo illisible) :
# l'humain le marque hors-training avec la cause, écrite dans
# image_assets.quality_reason (au lieu du générique 'rejected_in_review').
# `reason=None` → comportement reject historique.
_VALID_TRASH_REASONS = ("not_a_coin", "too_low_quality")


class RejectPayload(BaseModel):
    # Optionnel : body absent → reject générique (rétro-compat). Présent →
    # trash avec cause qualité tracée. Validé contre _VALID_TRASH_REASONS.
    reason: str | None = None


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (rejectReview)
@router.post("/{review_id}/reject", status_code=200)
def reject_review(
    review_id: str, payload: RejectPayload | None = None,
) -> dict[str, str]:
    """Mark the IMAGE as unusable (not the review row's status). The row
    is closed with `decision_notes='rejected'` and the underlying
    `image_assets` row gets `resolution_status='rejected'`.

    Si ``payload.reason`` est fourni (``not_a_coin`` / ``too_low_quality``),
    c'est un *trash qualité* : la cause est écrite dans
    ``image_assets.quality_reason`` et tracée dans la décision. Sans raison,
    on garde le comportement reject historique (``quality_reason =
    'rejected_in_review'``)."""
    reason = payload.reason if payload else None
    if reason is not None and reason not in _VALID_TRASH_REASONS:
        raise HTTPException(
            status_code=422,
            detail=f"reason must be one of {_VALID_TRASH_REASONS}",
        )
    quality_reason = reason or "rejected_in_review"

    conn = _store()._connection()  # noqa: SLF001
    rq = conn.execute(
        "SELECT id, image_asset_id, status FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review already {rq['status']} — cannot reject twice.",
        )

    now_iso = _now_iso()
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            UPDATE image_assets
               SET resolution_status = 'rejected',
                   training_eligible = 0,
                   quality_reason = ?,
                   resolved_at = ?
             WHERE id = ?
            """,
            (quality_reason, now_iso, rq["image_asset_id"]),
        )
        cur = conn.execute(
            """
            UPDATE review_queue
               SET status = 'done',
                   decision_notes = ?,
                   decided_at = ?,
                   decided_by = 'admin',
                   decision_engine_version = ?,
                   decision_metadata_json = ?
             WHERE id = ? AND status = 'open'
            """,
            (reason or "rejected", now_iso, _HUMAN_ENGINE_VERSION,
             json.dumps({"reason": reason or "rejected"}), review_id),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            raise HTTPException(
                status_code=409,
                detail="Review already decided concurrently by another voie.",
            )
        emit_state_event(
            conn, asset_id=rq["image_asset_id"], to_state="rejected",
            actor="human", reason=(f"trash_{reason}" if reason else "rejected"),
        )
        conn.execute("COMMIT")
    except HTTPException:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info("[review] rejected id=%s reason=%s", review_id, quality_reason)
    return {"status": "rejected", "id": review_id, "quality_reason": quality_reason}


# ── Re-crop manuel (chantier crop-quality-overhaul, Session B) ─────────────
#
# Le ~2 % du tail = de VRAIES pièces mal cadrées (rim coupé, décentré) que
# l'humain sauve en re-dessinant le cercle sur le RAW. On reproduit EXACTEMENT
# le format de prod (``_crop_mask_resize_float`` : marge 0.02, masque dur, 224)
# — seule la détection (cx,cy,r) devient manuelle. L'écriture calque
# ``scripts/recrop_ebay_refine.py`` : cache local (overwrite) + MinIO
# write-through + UPDATE image_assets (bbox/method/dims/phash). eurio_id,
# resolution_status et training_eligible PRÉSERVÉS — le re-crop ne décide pas
# l'attribution (la review reste ``open`` ; l'humain valide ensuite la pièce).


class CropEditContext(BaseModel):
    asset_id: str
    source: str
    raw_url: str                 # /sources/{source}/raws/{sid}/file (cache local)
    crop_url: str                # /sources/{source}/assets/{aid}/file (crop actuel)
    raw_width: int | None
    raw_height: int | None
    # Cercle de départ de l'éditeur = crop actuel, en px NATIFS du raw,
    # reconstruit depuis bbox_json (x,y,w,h → centre + rayon). None si la
    # bbox est absente (l'éditeur démarre alors sur un cercle par défaut).
    hint: dict | None
    # Cercle dominant détecté dans le raw (px natifs), proposé comme point de
    # départ quand la source est mono-pièce et le crop stocké mal dimensionné.
    # null sur les lots / quand aucun cercle probant. L'éditeur démarre dessus
    # quand présent, sinon sur `hint`.
    suggested_circle: dict | None = None


# Consumed by: admin/.../review/composables/useReviewApi.ts (fetchCropEditContext)
def _asset_id_for_review(review_id: str) -> str:
    """Résout review_id → asset_id (le re-crop est une opération sur l'asset)."""
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT image_asset_id FROM review_queue WHERE id = ?", (review_id,),
    ).fetchone()
    if row is None or not row["image_asset_id"]:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return row["image_asset_id"]


def _crop_edit_context_response(ctx: CropEditContextData) -> CropEditContext:
    """Habille le contexte (keyé asset) en réponse API + URLs servables."""
    return CropEditContext(
        asset_id=ctx.asset_id,
        source=ctx.source,
        raw_url=f"/sources/{ctx.source}/raws/{ctx.source_image_id}/file",
        crop_url=f"/sources/{ctx.source}/assets/{ctx.asset_id}/file",
        raw_width=ctx.raw_width,
        raw_height=ctx.raw_height,
        hint=ctx.hint,
        suggested_circle=ctx.suggested,
    )


@router.get("/{review_id}/crop-edit-context", response_model=CropEditContext)
def get_crop_edit_context(review_id: str) -> CropEditContext:
    """Contexte pour l'éditeur de cercle : le RAW (sur lequel on dessine) +
    le cercle de départ (crop actuel, px natifs). Délègue au cœur keyé asset."""
    ctx = load_crop_edit_context(_store(), _asset_id_for_review(review_id))
    return _crop_edit_context_response(ctx)


class ManualCropPayload(BaseModel):
    cx: float = Field(ge=0)
    cy: float = Field(ge=0)
    r: float = Field(gt=0)


class ManualCropResponse(BaseModel):
    asset_id: str
    cx: float
    cy: float
    r: float
    bbox: ReviewBbox
    width: int
    height: int
    detection_method: str
    crop_b64: str                # data URI PNG du nouveau crop 224
    minio_ok: bool               # False si le write-through MinIO a échoué
    dino_recomputed: bool = False  # True si Dino a été recalculé sur le crop recadré


# Consumed by: admin/.../review/composables/useReviewApi.ts (manualCrop)
@router.post("/{review_id}/manual-crop", response_model=ManualCropResponse)
def manual_crop(review_id: str, payload: ManualCropPayload) -> ManualCropResponse:
    """Re-croppe l'asset depuis un cercle (cx,cy,r) dessiné à la main sur le
    RAW, écrase le crop (cache + MinIO + DB). Format IDENTIQUE à la prod via
    ``_crop_mask_resize_float`` ; eurio_id préservé ; review inchangée. Délègue
    au cœur keyé asset (partagé avec la voie coin-detail)."""
    data = apply_manual_crop(
        _store(), _asset_id_for_review(review_id), payload.cx, payload.cy, payload.r,
    )
    return _manual_crop_response(data)


def _manual_crop_response(data: ManualCropData) -> ManualCropResponse:
    """Habille le résultat (keyé asset) en réponse API (+ data-URI base64)."""
    crop_b64 = "data:image/png;base64," + base64.b64encode(data.png_bytes).decode("ascii")
    return ManualCropResponse(
        asset_id=data.asset_id,
        cx=data.cx, cy=data.cy, r=data.r,
        bbox=ReviewBbox(x=data.bbox["x"], y=data.bbox["y"],
                        w=data.bbox["w"], h=data.bbox["h"]),
        width=data.width, height=data.height,
        detection_method=data.detection_method,
        crop_b64=crop_b64,
        minio_ok=data.minio_ok,
        dino_recomputed=data.dino_recomputed,
    )


# ── Dino suggestions (auto-validation V1) ─────────────────────────────────


class DinoSuggestion(BaseModel):
    """One top-K candidate enriched with coin metadata for the drawer UI."""

    eurio_id: str
    sim: float
    country: str | None = None
    country_name: str | None = None
    year: int | None = None
    theme: str | None = None
    denomination: float | None = None
    is_commemorative: bool | None = None
    obverse_url: str | None = None  # /images/<numista_id>/source if available


class DinoCriterionOut(BaseModel):
    key: str  # top1_target | top1_country_sim | country_spread
    state: str  # pass | fail | absent


class AutoValidateVerdictOut(BaseModel):
    """Détail Dino par critère (top1/sim/spread) — alimente l'affichage des
    critères (``DinoVerdict.vue``). N'EST PLUS le verdict de routage : c'est
    ``ConsensusVerdictOut`` qui fait foi (cf. câblage live C3)."""

    level: str  # auto_candidate | partial | divergent | unknown
    reason: str
    criteria: list[DinoCriterionOut]


class ConsensusVerdictOut(BaseModel):
    """Verdict de CONSENSUS (C3) — la décision qui fait foi (= la lane routée).
    Le badge front l'affiche tel quel ; fin du drift où le verdict Dino
    4-niveaux pouvait diverger de la lane (ex. crop_cap : Dino auto_candidate
    mais lane ccproxy). Lu depuis ``consensus_verdicts`` (ce qui a décidé la
    lane à l'enqueue), recalculé à la volée en fallback si pas encore persisté."""

    outcome: str  # accept | needs_review | reject
    lane: str  # auto_accept | ccproxy | manual
    reason: str
    rule: str  # branche de décision (audit)
    confidence: float


class DinoSuggestionsResponse(BaseModel):
    asset_id: str
    encoder_version: str
    anchors_kind: str
    anchors_count: int
    computed_at: str | None = None
    duration_ms: int | None = None
    spread: float | None = None
    top1_eurio_id: str | None = None
    top1_sim: float | None = None
    top_k: list[DinoSuggestion]
    # Country-restricted re-rank (chunk 3.5). Empty list when the crop
    # has no target country signal (NULL target_eurio_id on the parent
    # source_image), or when the bank has no anchors for the target
    # country. Front renders this band first when populated.
    target_country: str | None = None
    country_anchors_count: int | None = None
    country_spread: float | None = None
    top1_country_eurio_id: str | None = None
    top1_country_sim: float | None = None
    top_k_country: list[DinoSuggestion] = []
    # eurio_id qui a piloté le scrape (depuis source_images). Sert au
    # front à calculer le critère "top1==target" du verdict d'auto-
    # validation. Peut être None pour les sources legacy (mock, scans
    # sans target).
    target_eurio_id: str | None = None
    # Seuils provisoires de l'auto-validation V1 — display-only, lisibles
    # depuis ml/foundation/thresholds.py. Permet au front d'afficher
    # ✓/✗ par critère sans hardcoder de constante.
    verdict_thresholds: DinoVerdictThresholds = DINO_VERDICT_THRESHOLDS
    # Verdict d'auto-validation calculé côté serveur (source unique — C0 du
    # redesign auto-validation). Le front l'affiche tel quel (level/reason +
    # état par critère), il ne recalcule plus rien. None seulement si l'asset
    # est introuvable (cas qui ne devrait pas arriver vu le 404 amont).
    auto_validate_verdict: AutoValidateVerdictOut | None = None
    # Verdict de CONSENSUS (C3) — décision de routage qui fait foi (= la lane).
    # Source du badge front. None seulement si l'asset n'a aucun signal
    # exploitable (introuvable / non résolu).
    consensus_verdict: ConsensusVerdictOut | None = None
    # Abstention des suggestions (P5 dino-suggestions) — basée sur le spread
    # GLOBAL (la sim ne sépare pas le hors-scope, cf. audit Phase 0) :
    #   confident  : spread ≥ spread_confident_min — liste fiable
    #   low_margin : entre les deux seuils — liste affichée sans confiance
    #   uncertain  : spread < spread_uncertain_max — probablement hors banque
    #                ou design ambigu → l'UI doit le dire plutôt que de
    #                présenter une liste classée trompeuse
    #   unknown    : pas de spread persisté (prédiction legacy)
    abstention_state: str = "unknown"
    abstention_thresholds: DinoAbstentionThresholds = DINO_ABSTENTION_THRESHOLDS
    # Lot multi-pays suspecté (titre « diverse Länder / mixed / divers pays »).
    # Sur ces lots le pays cible du listing ne dit RIEN du pays de CHAQUE
    # crop → le front doit montrer le ranking global en premier et la bande
    # pays seulement en prior indicatif (P2 dino-suggestions).
    multi_country_lot: bool = False


def _enrich_top_k(
    conn: sqlite3.Connection, top_k: list[dict]
) -> list[DinoSuggestion]:
    """Hydrate the bare {eurio_id, sim} top-K with coin metadata + obverse URL."""
    if not top_k:
        return []
    eids = [str(t["eurio_id"]) for t in top_k]
    placeholders = ",".join("?" for _ in eids)
    rows = conn.execute(
        f"""
        SELECT eurio_id, country, country_name, year, theme,
               face_value, is_commemorative, numista_id
          FROM coins WHERE eurio_id IN ({placeholders})
        """,
        eids,
    ).fetchall()
    by_eid = {r["eurio_id"]: r for r in rows}
    enriched: list[DinoSuggestion] = []
    for entry in top_k:
        eid = str(entry["eurio_id"])
        row = by_eid.get(eid)
        if row is None:
            enriched.append(DinoSuggestion(eurio_id=eid, sim=float(entry["sim"])))
            continue
        nid = row["numista_id"]
        enriched.append(
            DinoSuggestion(
                eurio_id=eid,
                sim=float(entry["sim"]),
                country=row["country"],
                country_name=row["country_name"],
                year=row["year"],
                theme=row["theme"],
                denomination=float(row["face_value"]) if row["face_value"] else None,
                is_commemorative=bool(row["is_commemorative"]),
                obverse_url=f"/images/{int(nid)}/source" if nid else None,
            )
        )
    return enriched


# Titres de lots multi-pays — le pays cible du listing n'y contraint pas le
# pays de chaque crop (cas kickoff : « 2 Euro Kursmünze 2011 — Diverse Länder
# nach Wahl », target BE, crops de toute la zone euro). Volontairement court
# et haute-précision : un faux négatif laisse l'UI actuelle, un faux positif
# démote la bande pays qui aide massivement sur les listings mono-pays
# (recall@5 90.7 % vs 71.6 % global, audit Phase 0).
# L'adjectif (divers/verschiedene/mixed…) doit être à ≤ 2 mots d'un mot
# « pays » — « verschiedene Jahre » (multi-années mono-pays) ne matche pas.
_MULTI_COUNTRY_TITLE_RE = re.compile(
    r"(divers\w*|verschieden\w*|gemischt\w*|mixed|various|assortit?\w*"
    r"|misti|vari[oe]?s?|diff[ée]rente?s?)"
    r"\W+(?:\w+\W+){0,2}"
    r"(l[äa]nder\w*|countr\w*|pays|paesi|pa[íi]ses)"
    r"|aus\s+allen\s+l[äa]ndern|alle\s+l[äa]nder|eurol[äa]nder",
    re.IGNORECASE,
)


def _is_multi_country_lot(listing_title: str | None) -> bool:
    return bool(listing_title and _MULTI_COUNTRY_TITLE_RE.search(listing_title))


def _abstention_state(spread: float | None) -> str:
    """État d'abstention des suggestions à partir du spread GLOBAL.
    Seuils calibrés Phase 0 (cf. foundation/thresholds.py)."""
    if spread is None:
        return "unknown"
    if spread >= DINO_ABSTENTION_THRESHOLDS["spread_confident_min"]:
        return "confident"
    if spread < DINO_ABSTENTION_THRESHOLDS["spread_uncertain_max"]:
        return "uncertain"
    return "low_margin"


def _lazy_compute_dino(store, conn, asset_id: str, anchors_kind: str):
    """Calcule + persiste la prédiction Dino d'un crop À LA DEMANDE quand elle
    manque (trou de backfill, ou recompute best-effort raté au scrape/sync).
    Réutilise `predict_and_persist_kinds` (même format que le backfill batch) ;
    les kinds live manquants sont soignés au passage (1 seul encodage).
    Renvoie la row persistée du kind demandé, ou None si hors scope / crop
    illisible / bank absente — le caller garde alors le 404. Idempotent."""
    row = conn.execute(
        """
        SELECT a.storage_path, si.target_eurio_id
          FROM image_assets a JOIN source_images si ON si.id = a.source_image_id
         WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if row is None or not row["storage_path"]:
        return None
    try:
        from shared.storage.local_cache import local_path
        crop_path = local_path("enrichment-crops", row["storage_path"])
    except FileNotFoundError:
        return None
    target_eid = row["target_eurio_id"]
    target_country = (
        target_eid[:2].lower() if target_eid and len(target_eid) >= 2 else None
    )
    try:
        from sources._base.steps.auto_validate import (
            LIVE_ANCHORS_KINDS,
            predict_and_persist_kinds,
        )
        kinds = tuple(dict.fromkeys((*LIVE_ANCHORS_KINDS, anchors_kind)))
        rows = predict_and_persist_kinds(
            store=store, asset_id=asset_id, crop_path=crop_path,
            target_country=target_country, anchors_kinds=kinds,
        )
        pred = rows.get(anchors_kind)
    except Exception as exc:  # noqa: BLE001 — couche d'aide, jamais fatale
        logger.warning("[dino] lazy compute failed asset=%s: %s", asset_id, exc)
        return None
    if pred is not None:
        logger.info("[dino] lazy-computed prediction for asset=%s", asset_id)
    return pred


def _build_dino_response(
    asset_id: str, anchors_kind: str
) -> DinoSuggestionsResponse:
    store = _store()
    conn = store._connection()  # noqa: SLF001
    # L'encodeur dépend du kind : suggestions (2eur_all) = vitl14,
    # consensus (2eur_commemo) = vits14 — cf. ENCODER_VERSION_FOR_KIND.
    pred = store.get_dino_prediction(
        asset_id=asset_id,
        encoder_version=encoder_version_for_kind(anchors_kind),
        anchors_kind=anchors_kind,
    )
    if pred is None:
        # Trou de prédiction (backfill incomplet, ou recompute best-effort raté
        # au sync/scrape) → on calcule à la volée plutôt que de renvoyer 404.
        pred = _lazy_compute_dino(store, conn, asset_id, anchors_kind)
    if pred is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No Dino prediction for asset_id={asset_id} "
                f"(anchors_kind={anchors_kind}). Either out of scope or "
                "the crop could not be encoded — see "
                "go-task ml:dino-predictions:backfill."
            ),
        )
    target_eurio_row = conn.execute(
        """
        SELECT si.target_eurio_id, si.listing_title
          FROM image_assets ia
          JOIN source_images si ON si.id = ia.source_image_id
         WHERE ia.id = ?
        """,
        (asset_id,),
    ).fetchone()
    target_eurio_id = (
        target_eurio_row["target_eurio_id"] if target_eurio_row else None
    )
    multi_country_lot = _is_multi_country_lot(
        target_eurio_row["listing_title"] if target_eurio_row else None
    )
    # Les couches verdict/consensus restent calibrées sur le kind consensus
    # (2eur_commemo, règle C0–C5) quel que soit le kind des SUGGESTIONS servi
    # — le badge ne doit pas bouger parce que la banque affichée est plus large.
    view = compute_auto_validate_view(
        conn, asset_id, anchors_kind=CONSENSUS_ANCHORS_KIND
    )
    auto_validate_verdict = AutoValidateVerdictOut(
        level=view.level,
        reason=view.reason,
        criteria=[
            DinoCriterionOut(key=c.key, state=c.state) for c in view.criteria
        ],
    )
    # Verdict de consensus = ce qui fait foi pour le badge. On lit d'abord la row
    # persistée (ce qui a réellement décidé la lane à l'enqueue) ; à défaut
    # (legacy / pas encore enqueué) on recalcule à la volée depuis les experts.
    cv = load_consensus_verdict(conn, asset_id)
    if cv is None:
        signals = collect_signals(conn, asset_id)
        cv = consensus_verdict(signals) if signals else None
    consensus_out = (
        ConsensusVerdictOut(
            outcome=cv.outcome, lane=cv.lane, reason=cv.reason,
            rule=cv.rule, confidence=cv.confidence,
        )
        if cv is not None
        else None
    )
    return DinoSuggestionsResponse(
        asset_id=pred.asset_id,
        encoder_version=pred.encoder_version,
        anchors_kind=pred.anchors_kind,
        anchors_count=pred.anchors_count,
        computed_at=pred.computed_at,
        duration_ms=pred.duration_ms,
        spread=pred.spread,
        top1_eurio_id=pred.top1_eurio_id,
        top1_sim=pred.top1_sim,
        top_k=_enrich_top_k(conn, pred.top_k),
        target_country=pred.target_country,
        country_anchors_count=pred.country_anchors_count,
        country_spread=pred.country_spread,
        top1_country_eurio_id=pred.top1_country_eurio_id,
        top1_country_sim=pred.top1_country_sim,
        top_k_country=_enrich_top_k(conn, pred.top_k_country or []),
        target_eurio_id=target_eurio_id,
        auto_validate_verdict=auto_validate_verdict,
        consensus_verdict=consensus_out,
        abstention_state=_abstention_state(pred.spread),
        multi_country_lot=multi_country_lot,
    )


# Consumed by: admin/packages/web/src/features/review/composables/useDinoSuggestions.ts (fetchDinoSuggestionsByAssetId)
@router.get(
    "/asset/{asset_id}/dino-suggestions",
    response_model=DinoSuggestionsResponse,
)
def get_dino_suggestions(
    asset_id: str,
    anchors_kind: str = Query(default=SUGGESTIONS_ANCHORS_KIND),
) -> DinoSuggestionsResponse:
    """Return the persisted Dino top-K for one image_asset, enriched.

    404 if no prediction exists (i.e. the asset is out of scope, or
    auto_validate hasn't run yet on this asset). The reviewer drawer
    falls back gracefully — Dino is an optional aid layer, not a
    requirement to review.
    """
    return _build_dino_response(asset_id, anchors_kind)


# Consumed by: admin/packages/web/src/features/review/composables/useDinoSuggestions.ts (fetchDinoSuggestionsByReviewId)
@router.get(
    "/{review_id}/dino-suggestions",
    response_model=DinoSuggestionsResponse,
)
def get_dino_suggestions_for_review(
    review_id: str,
    anchors_kind: str = Query(default=SUGGESTIONS_ANCHORS_KIND),
) -> DinoSuggestionsResponse:
    """Same payload as /asset/{asset_id}/dino-suggestions, but indexed
    by ``review_queue.id`` — handy for the single review drawer which
    only carries the review_id in its state."""
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT image_asset_id FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return _build_dino_response(row["image_asset_id"], anchors_kind)


# ── Listing text signals (chunk 5 auto-validation) ─────────────────────
#
# Expose les signaux extraits par ml/sources/text_signals depuis le
# titre de chaque listing. Pas de comparaison vs target ici (chunk 6) :
# on retourne ce que le titre dit explicitement. 404 propre si pas de
# signal extrait (= source_image hors-scope ou step pas encore exécuté).


class TextSignalsResponse(BaseModel):
    source_image_id: str
    extractor_version: str
    listing_title: str | None = None
    target_eurio_id: str | None = None
    countries: list[str]
    years: list[int]
    denominations: list[float]
    theme_tokens: list[str]
    rejected_markers: list[str]
    is_lot: bool
    coverage: str
    matched: dict[str, list[str]]
    # Chunk 6 — verdict vs target. None quand le target n'est pas connu
    # (pas de target_eurio_id, ou row pré-chunk-6).
    vs_target_verdict: str | None = None
    contradictions: list[str] = []
    convergences: list[str] = []
    computed_at: str | None = None


def _build_text_signals_response(source_image_id: str) -> TextSignalsResponse:
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT lts.*, si.listing_title, si.target_eurio_id
          FROM listing_text_signals lts
          JOIN source_images si ON si.id = lts.source_image_id
         WHERE lts.source_image_id = ?
        """,
        (source_image_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No text signals for this source_image. The text_signal step "
                "may not have run yet — try `go-task ml:text-signals:backfill`."
            ),
        )
    cols = row.keys()
    verdict = row["vs_target_verdict"] if "vs_target_verdict" in cols else None
    contradictions_raw = (
        row["contradictions_json"] if "contradictions_json" in cols else None
    )
    convergences_raw = (
        row["convergences_json"] if "convergences_json" in cols else None
    )
    return TextSignalsResponse(
        source_image_id=row["source_image_id"],
        extractor_version=row["extractor_version"],
        listing_title=row["listing_title"],
        target_eurio_id=row["target_eurio_id"],
        countries=json.loads(row["countries_json"] or "[]"),
        years=json.loads(row["years_json"] or "[]"),
        denominations=json.loads(row["denominations_json"] or "[]"),
        theme_tokens=json.loads(row["theme_tokens_json"] or "[]"),
        rejected_markers=json.loads(row["rejected_markers_json"] or "[]"),
        is_lot=bool(row["is_lot"]),
        coverage=row["coverage"],
        matched=json.loads(row["matched_json"] or "{}"),
        vs_target_verdict=verdict,
        contradictions=json.loads(contradictions_raw or "[]"),
        convergences=json.loads(convergences_raw or "[]"),
        computed_at=row["computed_at"],
    )


# Consumed by: admin/packages/web/src/features/review/composables/useTextSignals.ts (fetchTextSignalsByAssetId)
@router.get(
    "/asset/{asset_id}/text-signals",
    response_model=TextSignalsResponse,
)
def get_text_signals_for_asset(asset_id: str) -> TextSignalsResponse:
    """Return text signals for the source_image parent of an image_asset.

    Le signal vit au niveau du listing (= source_image), pas du crop —
    plusieurs assets d'un même listing partagent le même signal.
    """
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT source_image_id FROM image_assets WHERE id = ?",
        (asset_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return _build_text_signals_response(row["source_image_id"])


# Consumed by: admin/packages/web/src/features/review/composables/useTextSignals.ts (fetchTextSignalsByReviewId)
@router.get(
    "/{review_id}/text-signals",
    response_model=TextSignalsResponse,
)
def get_text_signals_for_review(review_id: str) -> TextSignalsResponse:
    """Same payload as /asset/{asset_id}/text-signals, indexed by
    review_queue.id — handy for the single review drawer."""
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT a.source_image_id
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
         WHERE rq.id = ?
        """,
        (review_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return _build_text_signals_response(row["source_image_id"])


# Consumed by: admin/packages/web/src/features/review/composables/useReviewApi.ts (skipReview)
@router.post("/{review_id}/skip", status_code=200)
def skip_review(review_id: str) -> dict[str, Any]:
    """Defer this item: bump `priority` so it lands further down the
    queue, but keep `status='open'`. No write to `image_assets`.

    Marque aussi ``decision_notes='skipped'`` : un skip est sinon
    indistinguable d'un item jamais touché (même ``status='open'``), ce
    qui empêche tout compteur honnête. Le marqueur est porté par la row
    open ; il disparaît dès que l'item est décidé (status='done') ou
    restauré (cf. ``/restore``). Sert au compteur ``n_skipped`` du cockpit
    cohort (§C4)."""
    conn = _store()._connection()  # noqa: SLF001
    rq = conn.execute(
        "SELECT id, image_asset_id, status, priority FROM review_queue WHERE id = ?",
        (review_id,),
    ).fetchone()
    if rq is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if rq["status"] != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Review is {rq['status']} — only open items can be skipped.",
        )
    # Incrément atomique côté SQL pour éviter le lost-update si deux skips
    # concurrents lisent la même priority et écrivent priority+50 chacun.
    cur = conn.execute(
        "UPDATE review_queue "
        "   SET priority = priority + ?, decision_notes = 'skipped' "
        " WHERE id = ? AND status = 'open'",
        (_SKIP_PRIORITY_BUMP, review_id),
    )
    if cur.rowcount != 1:
        # L'item a changé d'état entre temps (décidé par une autre voie) —
        # le skip n'a plus de sens.
        raise HTTPException(
            status_code=409,
            detail="Review is no longer open — cannot skip.",
        )
    emit_state_event(
        conn, asset_id=rq["image_asset_id"], to_state="skipped",
        actor="human", reason="deferred",
    )
    new_priority = rq["priority"] + _SKIP_PRIORITY_BUMP
    logger.info("[review] skipped id=%s new_priority=%d", review_id, new_priority)
    return {"status": "skipped", "id": review_id, "new_priority": new_priority}


@router.post("/{review_id}/move-lane", status_code=200)
def move_lane(review_id: str) -> dict[str, str]:
    """Déplace un item vers la lane MANUELLE (switch unidirectionnel, WS1).

    Sticky : pose ``lane_source='human'`` → aucun recalcul Dino (enqueue /
    re-route post-Dino) ne pourra le ré-router. C'est le seul sens autorisé
    (manuel→ccproxy n'est pas rentable : le manuel se review un par un). N'agit
    que sur un item ``open``."""
    conn = _store()._connection()  # noqa: SLF001
    cur = conn.execute(
        "UPDATE review_queue SET lane = 'manual', lane_source = 'human' "
        "WHERE id = ? AND status = 'open'",
        (review_id,),
    )
    if cur.rowcount != 1:
        raise HTTPException(
            status_code=404,
            detail="Review item introuvable ou non-ouvert (déjà décidé ?).",
        )
    logger.info("[review] move-lane id=%s → manual (human)", review_id)
    return {"status": "ok", "id": review_id, "lane": "manual"}


# ── Auto-accept déterministe (Dino + texte, pas de Claude) ────────────────


class AutoAcceptPreviewItem(BaseModel):
    """Un item auto-acceptable, avec assez de contexte pour preview UI."""

    review_id: str
    image_asset_id: str
    crop_url: str
    listing_title: str
    listing_url: str | None = None
    source: str
    target_eurio_id: str
    target_label: str
    target_thumb_url: str | None = None
    sim: float | None = None
    spread: float | None = None
    face_detected: str | None = None
    reason: str


class AutoAcceptResult(BaseModel):
    processed: int
    accepted: int
    # Items qui auraient été auto-acceptés mais ont été décidés par une
    # autre voie entre le SELECT et l'UPDATE (race ; on skip silencieusement).
    skipped_concurrent: int = 0
    by_category: dict[str, int]
    dry_run: bool
    # Liste des items `auto_candidate` enrichis pour l'écran de preview.
    # Non vide quand `dry_run=true` (l'admin pré-visualise). Vide sur
    # `dry_run=false` (on retourne les compteurs après écriture).
    preview: list[AutoAcceptPreviewItem] = []


class AutoAcceptRunBody(BaseModel):
    """Body optionnel : si `review_ids` est fourni, on n'auto-accepte que
    ces IDs (et on re-valide le verdict avant écriture, donc un ID qui
    a glissé hors `auto_candidate` est silencieusement skip)."""

    review_ids: list[str] | None = None


# Consumed by: admin/.../review/composables/useReviewApi.ts (runAutoAccept)
@router.post("/auto-accept/run", response_model=AutoAcceptResult)
def run_auto_accept(
    body: AutoAcceptRunBody | None = None,
    limit: int = Query(default=2000, ge=1, le=10000),
    dry_run: bool = Query(default=False),
    kind: str = Query(default="single"),
    cohort_id: str | None = Query(default=None),
) -> AutoAcceptResult:
    """Itère la queue ``open`` et auto-décide les items ``auto_candidate``.

    Mirror exact côté serveur du verdict affiché dans AutoValidateVerdict.
    Un item auto-accepté est traité comme une décision humaine (mêmes
    UPDATE sur ``image_assets`` + ``review_queue``) sauf ``decided_by=
    'auto_dino'`` au lieu de ``'admin'``.

    Modes :
      - ``dry_run=true``  → aucune écriture, on retourne compteurs +
        ``preview[]`` enrichi (crop, canonical, sim, spread, reason)
        pour l'écran de revue manuelle avant validation.
      - ``dry_run=false`` sans ``review_ids`` → auto-accepte tous les
        ``auto_candidate`` rencontrés.
      - ``dry_run=false`` avec ``review_ids`` → auto-accepte uniquement
        les IDs fournis, en re-validant le verdict (les IDs qui ne sont
        plus ``auto_candidate`` sont skip).
    """
    if kind not in _VALID_KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind must be one of {_VALID_KINDS}",
        )

    selected_ids: set[str] | None = (
        set(body.review_ids) if body and body.review_ids is not None else None
    )

    cohort_clause, cohort_args, cohort_empty = _cohort_filter(cohort_id, alias="s")
    if cohort_empty:
        return AutoAcceptResult(
            processed=0, accepted=0, by_category={
                "auto_candidate": 0, "partial": 0, "divergent": 0, "unknown": 0},
            dry_run=dry_run, preview=[])

    conn = _store()._connection()  # noqa: SLF001
    # Exclut les items restaurés (épinglés manuel) de l'auto-triage : un humain
    # les a ré-ouverts pour les trancher à la main. Cf. _RESTORED_NOTE.
    # WS1 : ne traite QUE la lane 'auto_accept' (Dino confiant). Lane de review
    # HUMAINE : la page présélectionne tout, l'admin décoche les mauvais →
    # ceux-là redescendent en 'manual' sticky (voir la boucle plus bas).
    where = f"rq.status = 'open' AND rq.lane = 'auto_accept' AND {_NOT_RESTORED_SQL}"
    args: list[Any] = []
    if kind != "all":
        where += " AND rq.kind = ?"
        args.append(kind)
    where += cohort_clause
    args.extend(cohort_args)
    args.append(limit)

    # Même JOIN que list_queue → on a le contexte preview (target, thumb,
    # listing title) sans seconde requête par item.
    rows = conn.execute(
        f"""
        SELECT rq.id AS review_id, rq.image_asset_id,
               a.face AS asset_face,
               s.source, s.source_url AS listing_url, s.listing_title,
               s.target_eurio_id,
               c.country_name AS t_country_name,
               c.year         AS t_year,
               c.theme        AS t_theme,
               c.numista_id   AS t_numista_id,
               p.top1_country_sim, p.top1_sim,
               p.country_spread, p.spread
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN coins c ON c.eurio_id = s.target_eurio_id
          LEFT JOIN image_asset_dino_predictions p
                 ON p.asset_id = a.id
                AND p.encoder_version = 'dinov2-vits14'
                AND p.anchors_kind = '2eur_commemo'
         WHERE {where}
         ORDER BY rq.priority ASC, rq.enqueued_at ASC
         LIMIT ?
        """,
        args,
    ).fetchall()

    by_category: dict[str, int] = {
        "auto_candidate": 0, "partial": 0, "divergent": 0, "unknown": 0,
    }
    preview: list[AutoAcceptPreviewItem] = []
    accepted = 0
    skipped_concurrent = 0
    now_iso = _now_iso()

    for row in rows:
        verdict = compute_auto_validate_verdict(conn, row["image_asset_id"])
        by_category[verdict.level] = by_category.get(verdict.level, 0) + 1

        if verdict.level != "auto_candidate":
            continue
        if verdict.decided_eurio_id is None:
            continue  # safety — ne devrait jamais arriver pour auto_candidate

        # Build preview row commun (dry_run + écriture). Le coût d'un
        # build supplémentaire en mode run-réel est négligeable et facilite
        # l'observabilité.
        label_bits = [
            row["t_country_name"],
            str(row["t_year"]) if row["t_year"] else None,
            row["t_theme"],
        ]
        target_label = " · ".join(b for b in label_bits if b) \
            or verdict.decided_eurio_id
        thumb = (
            f"/images/{int(row['t_numista_id'])}/source"
            if row["t_numista_id"] else None
        )
        crop_url = f"/sources/{row['source']}/assets/{row['image_asset_id']}/file"
        sim = row["top1_country_sim"] if row["top1_country_sim"] is not None \
            else row["top1_sim"]
        spread = row["country_spread"] if row["country_spread"] is not None \
            else row["spread"]
        item_preview = AutoAcceptPreviewItem(
            review_id=row["review_id"],
            image_asset_id=row["image_asset_id"],
            crop_url=crop_url,
            listing_title=row["listing_title"] or "",
            listing_url=row["listing_url"],
            source=row["source"],
            target_eurio_id=verdict.decided_eurio_id,
            target_label=target_label,
            target_thumb_url=thumb,
            sim=sim,
            spread=spread,
            face_detected=verdict.face_detected,
            reason=verdict.reason,
        )
        if dry_run:
            preview.append(item_preview)
            continue

        # Run réel : item DÉSÉLECTIONNÉ par l'admin → il ne part PAS en train ;
        # on le démote vers la lane 'manual' (sticky) pour qu'il soit re-jugé à
        # la main, plutôt que de le laisser traîner en 'auto_accept' (WS1).
        if selected_ids is not None and row["review_id"] not in selected_ids:
            conn.execute(
                "UPDATE review_queue SET lane='manual', lane_source='human' "
                "WHERE id=? AND status='open'",
                (row["review_id"],),
            )
            continue

        # G7 : ne pas masquer l'incertitude par un default obverse. Si la
        # pipeline ML n'a pas détecté la face, on inscrit 'unknown' (valide
        # dans le CHECK). L'admin pourra corriger via /review/manual si
        # besoin — c'est explicite plutôt que silencieusement faux.
        face = verdict.face_detected or "unknown"
        conn.execute("BEGIN")
        try:
            # Atomicité « premier-écrit-gagne » : on n'écrase pas une
            # décision déjà prise (admin ou claude_ack). Pour image_assets,
            # `resolution_status NOT IN ('manual','rejected')` empêche
            # l'écrasement d'une résolution finale ; pour review_queue,
            # `status='open'` est le verrou principal.
            conn.execute(
                """
                UPDATE image_assets
                   SET eurio_id = ?,
                       face = ?,
                       resolution_status = 'manual',
                       resolution_confidence = 1.0,
                       training_eligible = 1,
                       resolved_at = ?
                 WHERE id = ?
                   AND resolution_status NOT IN ('manual','rejected')
                """,
                (verdict.decided_eurio_id, face, now_iso, row["image_asset_id"]),
            )
            # Snapshot des signaux Dino dans decision_metadata_json :
            # ces valeurs sont fiables même si on re-encode les ancres ou
            # qu'on bouge les seuils plus tard (cf. GAP 4 de l'audit chunk B).
            auto_metadata = json.dumps({
                "sim": verdict.sim,
                "spread": verdict.spread,
                "top1_eurio_id": verdict.top1_eurio_id,
                "text_verdict": verdict.text_verdict,
                "reason": verdict.reason,
            })
            cur = conn.execute(
                """
                UPDATE review_queue
                   SET status = 'done',
                       decided_eurio_id = ?,
                       decided_face = ?,
                       decision_notes = ?,
                       decided_at = ?,
                       decided_by = 'auto_dino',
                       decision_engine_version = ?,
                       decision_metadata_json = ?
                 WHERE id = ? AND status = 'open'
                """,
                (verdict.decided_eurio_id, face, verdict.reason,
                 now_iso, _AUTO_DINO_ENGINE_VERSION, auto_metadata,
                 row["review_id"]),
            )
            if cur.rowcount != 1:
                # Une autre voie a tranché entre notre SELECT et notre
                # UPDATE — on annule notre tentative pour rester cohérent.
                conn.execute("ROLLBACK")
                skipped_concurrent += 1
                continue
            emit_state_event(
                conn, asset_id=row["image_asset_id"], to_state="resolved",
                actor="auto_dino", reason=verdict.reason,
                eurio_id=verdict.decided_eurio_id,
            )
            conn.execute("COMMIT")
            accepted += 1
        except Exception:
            conn.execute("ROLLBACK")
            logger.exception(
                "[auto-accept] failed review_id=%s", row["review_id"],
            )

    logger.info(
        "[auto-accept] processed=%d accepted=%d skipped_concurrent=%d "
        "dry_run=%s by_category=%s",
        len(rows), accepted, skipped_concurrent, dry_run, by_category,
    )
    return AutoAcceptResult(
        processed=len(rows),
        accepted=accepted,
        skipped_concurrent=skipped_concurrent,
        by_category=by_category,
        dry_run=dry_run,
        preview=preview,
    )


# ─────────────────────────────────────────────────────────────────────────
# ── ccproxy (Claude vision) : Claude propose, l'humain dispose ──────────
# ─────────────────────────────────────────────────────────────────────────
#
# Flux :
#   1. POST /claude/batch                → run Sonnet sur N items partial/divergent,
#                                          persiste dans review_claude_verdicts (pending)
#   2. GET  /claude/pending-acks         → liste les "match" pending pour acquittement
#   3. POST /claude/acknowledge          → l'humain acquitte une sélection → décision
#                                          finale écrite dans review_queue.
#
# Cf. memory project_claude_vision_bench (Sonnet 4.6 retenu, prec 92%).

# Chemin disque canonical : ml/datasets/<numista_id>/obverse.jpg
_ML_DIR = Path(__file__).resolve().parent.parent
_DATASETS_DIR = _ML_DIR / "datasets"


def _canonical_path(numista_id: int | None) -> Path | None:
    # Résolveur partagé (cf. foundation.obverse_group_review — réutilisé par la
    # review vision des design_groups par avers). Layout : datasets/<numista>/obverse.*
    from training.foundation.obverse_group_review import canonical_obverse_path
    return canonical_obverse_path(numista_id)


def _crop_path(storage_path: str) -> Path | None:
    """Résout le chemin disque local d'un crop image_assets."""
    try:
        from shared.storage.local_cache import local_path
        return local_path("enrichment-crops", storage_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[claude] crop path resolution failed for %s: %s",
                       storage_path, exc)
        return None


class ClaudeBatchResult(BaseModel):
    processed: int
    judged: int
    skipped_already_judged: int
    skipped_no_canonical: int
    # Race entre SELECT initial du batch et call Claude : l'item a été décidé
    # par une autre voie (admin/auto_dino/claude_ack) avant qu'on lance le LLM.
    # On skip silencieusement — évite de payer Claude pour un orphan.
    skipped_not_open: int = 0
    by_verdict: dict[str, int]
    errors: int
    model: str


class ClaudeBatchBody(BaseModel):
    # Scope : sous-ensemble des verdicts éligibles. Defaults aux deux cas
    # où Claude apporte le plus de valeur (cf. bench chunk 2).
    scope: list[str] = Field(default_factory=lambda: ["partial", "divergent"])
    # Alias modèle (haiku|sonnet|opus) — par défaut sonnet (cf. bench).
    model: str = DEFAULT_MODEL_ALIAS
    # ``force=True`` re-judge même les items qui ont déjà un verdict Claude.
    force: bool = False


# Consumed by: admin/.../review/composables/useReviewApi.ts (runClaudeBatch)
@router.post("/claude/batch", response_model=ClaudeBatchResult)
def run_claude_batch(
    body: ClaudeBatchBody | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    kind: str = Query(default="single"),
    cohort_id: str | None = Query(default=None),
    base_url: str = Query(default="http://127.0.0.1:3002"),
) -> ClaudeBatchResult:
    """Pull N items ``open`` dans le scope, appelle Claude vision sur chacun,
    persiste les verdicts dans ``review_claude_verdicts`` (status='pending').

    Idempotent par défaut : un item ayant déjà un verdict Claude est skip.
    ``force=true`` pour re-judger (utile après changement de prompt/modèle).
    """
    if kind not in _VALID_KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind must be one of {_VALID_KINDS}",
        )
    b = body or ClaudeBatchBody()
    scope = set(b.scope) & {"partial", "divergent", "auto_candidate", "unknown"}
    if not scope:
        raise HTTPException(
            status_code=422,
            detail="scope must include at least one of partial|divergent|auto_candidate|unknown",
        )
    model_alias = b.model
    if model_alias not in MODELS:
        raise HTTPException(
            status_code=422,
            detail=f"model must be one of {list(MODELS.keys())}",
        )

    cohort_clause, cohort_args, cohort_empty = _cohort_filter(cohort_id, alias="s")
    if cohort_empty:
        return ClaudeBatchResult(
            processed=0, judged=0, skipped_already_judged=0,
            skipped_no_canonical=0, skipped_not_open=0,
            by_verdict={"match": 0, "no_match": 0, "uncertain": 0, "error": 0},
            errors=0, model=MODELS[model_alias])

    conn = _store()._connection()  # noqa: SLF001
    # Exclut les items restaurés (épinglés manuel) de l'auto-triage : un humain
    # les a ré-ouverts pour les trancher à la main. Cf. _RESTORED_NOTE.
    # WS1 : ccproxy ne traite QUE la lane 'ccproxy' (Dino hésite/contredit →
    # arbitrage Claude vision). Les unknown (manual) et auto_candidate ne passent
    # jamais ici.
    where = f"rq.status = 'open' AND rq.lane = 'ccproxy' AND {_NOT_RESTORED_SQL}"
    args: list[Any] = []
    if kind != "all":
        where += " AND rq.kind = ?"
        args.append(kind)
    where += cohort_clause
    args.extend(cohort_args)
    args.append(limit)

    rows = conn.execute(
        f"""
        SELECT rq.id AS review_id, rq.image_asset_id,
               a.storage_path,
               s.source, s.listing_title, s.target_eurio_id,
               c.country_name AS t_country_name,
               c.year         AS t_year,
               c.theme        AS t_theme,
               c.numista_id   AS t_numista_id
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN coins c ON c.eurio_id = s.target_eurio_id
         WHERE {where}
         ORDER BY rq.priority ASC, rq.enqueued_at ASC
         LIMIT ?
        """,
        args,
    ).fetchall()

    by_verdict: dict[str, int] = {
        "match": 0, "no_match": 0, "uncertain": 0, "error": 0,
    }
    judged = 0
    skipped_already = 0
    skipped_no_canon = 0
    skipped_not_open = 0
    errors = 0

    for row in rows:
        verdict_dt = compute_auto_validate_verdict(conn, row["image_asset_id"])
        if verdict_dt.level not in scope:
            continue

        # Idempotence
        if not b.force:
            existing = conn.execute(
                "SELECT 1 FROM review_claude_verdicts WHERE review_id = ?",
                (row["review_id"],),
            ).fetchone()
            if existing is not None:
                skipped_already += 1
                continue

        # Pre-check : l'item est-il toujours open ? Le SELECT initial du
        # batch peut être à jour de plusieurs secondes, et entre temps une
        # autre voie peut avoir décidé l'item. Évite de payer Claude pour
        # un verdict orphan. Cf. chunk C.
        still_open = conn.execute(
            "SELECT 1 FROM review_queue WHERE id = ? AND status = 'open'",
            (row["review_id"],),
        ).fetchone()
        if still_open is None:
            skipped_not_open += 1
            continue

        canonical = _canonical_path(row["t_numista_id"])
        if canonical is None:
            skipped_no_canon += 1
            continue
        crop = _crop_path(row["storage_path"]) if row["storage_path"] else None
        if crop is None or not crop.exists():
            skipped_no_canon += 1
            continue

        label_bits = [
            row["t_country_name"],
            str(row["t_year"]) if row["t_year"] else None,
            row["t_theme"],
        ]
        target_label = " · ".join(b for b in label_bits if b) or row["target_eurio_id"]

        j = judge(
            crop_path=crop,
            canonical_path=canonical,
            target_label=target_label,
            listing_title=row["listing_title"] or "",
            model_alias=model_alias,
            base_url=base_url,
        )

        # Upsert
        verdict_str = j.verdict or "error"
        by_verdict[verdict_str] = by_verdict.get(verdict_str, 0) + 1
        if not j.parsed_ok:
            errors += 1
        conn.execute(
            """
            INSERT INTO review_claude_verdicts
              (review_id, model, verdict, face, confidence, raw_content,
               tokens_in, tokens_out, cache_read, cost_usd, duration_ms,
               status, error, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, datetime('now'))
            ON CONFLICT(review_id) DO UPDATE SET
              model       = excluded.model,
              verdict     = excluded.verdict,
              face        = excluded.face,
              confidence  = excluded.confidence,
              raw_content = excluded.raw_content,
              tokens_in   = excluded.tokens_in,
              tokens_out  = excluded.tokens_out,
              cache_read  = excluded.cache_read,
              cost_usd    = excluded.cost_usd,
              duration_ms = excluded.duration_ms,
              status      = 'pending',
              error       = excluded.error,
              computed_at = datetime('now'),
              acked_at    = NULL
            """,
            (row["review_id"], j.model, verdict_str, j.face, j.confidence,
             j.raw_content, j.tokens_in, j.tokens_out, j.cache_read_tokens,
             j.cost_usd, j.duration_ms, j.error),
        )
        judged += 1

    logger.info(
        "[claude] batch model=%s scope=%s judged=%d skipped_already=%d "
        "skipped_no_canon=%d skipped_not_open=%d errors=%d by_verdict=%s",
        model_alias, sorted(scope), judged, skipped_already,
        skipped_no_canon, skipped_not_open, errors, by_verdict,
    )

    return ClaudeBatchResult(
        processed=len(rows),
        judged=judged,
        skipped_already_judged=skipped_already,
        skipped_no_canonical=skipped_no_canon,
        skipped_not_open=skipped_not_open,
        by_verdict=by_verdict,
        errors=errors,
        model=MODELS[model_alias],
    )


class ClaudePendingItem(BaseModel):
    review_id: str
    image_asset_id: str
    crop_url: str
    listing_title: str
    listing_url: str | None = None
    source: str
    target_eurio_id: str
    target_label: str
    target_thumb_url: str | None = None
    # Verdict Claude
    verdict: str
    confidence: float | None = None
    face_detected: str | None = None
    model: str
    raw_content: str
    computed_at: str


class ClaudePendingResult(BaseModel):
    total_pending: int                          # tous status=pending, tous verdicts
    by_verdict: dict[str, int]                  # match/no_match/uncertain/error
    items: list[ClaudePendingItem]              # filtré au verdict demandé


# Consumed by: admin/.../review/composables/useReviewApi.ts (fetchClaudePendingAcks)
@router.get("/claude/pending-acks", response_model=ClaudePendingResult)
def list_claude_pending(
    verdict: str = Query(default="match"),
    limit: int = Query(default=200, ge=1, le=1000),
    cohort_id: str | None = Query(default=None),
) -> ClaudePendingResult:
    """Liste les items où Claude a tranché ``verdict`` et qui attendent
    l'acquittement humain. Par défaut filtre sur ``match`` (le seul cas
    qu'on veut auto-acquitter ; les autres restent en queue manuelle).

    ``cohort_id`` (optionnel) restreint la liste ET les compteurs by_verdict
    aux coins de la cohort (§C4b)."""
    if verdict not in ("match", "no_match", "uncertain", "error"):
        raise HTTPException(
            status_code=422,
            detail="verdict must be match|no_match|uncertain|error",
        )

    cohort_clause, cohort_args, cohort_empty = _cohort_filter(cohort_id, alias="s")
    if cohort_empty:
        return ClaudePendingResult(total_pending=0, by_verdict={}, items=[])

    conn = _store()._connection()  # noqa: SLF001

    # by_verdict : compteurs scopés cohort si demandé (join requis pour le
    # filtre par coin ; sinon scan plat de la table verdicts).
    if cohort_clause:
        by_verdict_rows = conn.execute(
            f"""
            SELECT v.verdict AS verdict, COUNT(*) AS c
              FROM review_claude_verdicts v
              JOIN review_queue rq ON rq.id = v.review_id
              JOIN image_assets a  ON a.id  = rq.image_asset_id
              JOIN source_images s ON s.id  = a.source_image_id
             WHERE v.status = 'pending' AND rq.status = 'open'{cohort_clause}
             GROUP BY v.verdict
            """,
            cohort_args,
        ).fetchall()
    else:
        by_verdict_rows = conn.execute(
            """
            SELECT verdict, COUNT(*) AS c FROM review_claude_verdicts
             WHERE status = 'pending'
             GROUP BY verdict
            """
        ).fetchall()
    by_verdict = {r["verdict"]: r["c"] for r in by_verdict_rows}
    total = sum(by_verdict.values())

    rows = conn.execute(
        f"""
        SELECT v.review_id, v.model, v.verdict, v.confidence, v.face,
               v.raw_content, v.computed_at,
               rq.image_asset_id,
               a.face AS asset_face,
               s.source, s.source_url AS listing_url, s.listing_title,
               s.target_eurio_id,
               c.country_name AS t_country_name,
               c.year         AS t_year,
               c.theme        AS t_theme,
               c.numista_id   AS t_numista_id
          FROM review_claude_verdicts v
          JOIN review_queue rq ON rq.id = v.review_id
          JOIN image_assets a  ON a.id  = rq.image_asset_id
          JOIN source_images s ON s.id  = a.source_image_id
          LEFT JOIN coins c    ON c.eurio_id = s.target_eurio_id
         WHERE v.status = 'pending' AND v.verdict = ? AND rq.status = 'open'{cohort_clause}
         ORDER BY v.computed_at DESC
         LIMIT ?
        """,
        (verdict, *cohort_args, limit),
    ).fetchall()

    items: list[ClaudePendingItem] = []
    for r in rows:
        label_bits = [
            r["t_country_name"],
            str(r["t_year"]) if r["t_year"] else None,
            r["t_theme"],
        ]
        label = " · ".join(b for b in label_bits if b) or r["target_eurio_id"]
        thumb = (
            f"/images/{int(r['t_numista_id'])}/source"
            if r["t_numista_id"] else None
        )
        items.append(ClaudePendingItem(
            review_id=r["review_id"],
            image_asset_id=r["image_asset_id"],
            crop_url=f"/sources/{r['source']}/assets/{r['image_asset_id']}/file",
            listing_title=r["listing_title"] or "",
            listing_url=r["listing_url"],
            source=r["source"],
            target_eurio_id=r["target_eurio_id"],
            target_label=label,
            target_thumb_url=thumb,
            verdict=r["verdict"],
            confidence=r["confidence"],
            face_detected=r["face"] or r["asset_face"],
            model=r["model"],
            raw_content=r["raw_content"],
            computed_at=r["computed_at"],
        ))

    return ClaudePendingResult(
        total_pending=total,
        by_verdict=by_verdict,
        items=items,
    )


class ClaudeAckBody(BaseModel):
    review_ids: list[str]
    # 'ack'    → humain valide la suggestion Claude → écrit la décision
    # 'reject' → humain rejette → l'item reste open en queue manuelle,
    #            le verdict Claude passe juste à 'rejected' (audit)
    action: str = "ack"


class ClaudeAckResult(BaseModel):
    requested: int
    committed: int
    rejected: int
    skipped: int    # IDs invalides / déjà acquittés / verdict ≠ match
    skipped_concurrent: int = 0   # tranchés par une autre voie pendant l'ack


# Consumed by: admin/.../review/composables/useReviewApi.ts (ackClaudeVerdicts)
@router.post("/claude/acknowledge", response_model=ClaudeAckResult)
def acknowledge_claude(body: ClaudeAckBody) -> ClaudeAckResult:
    """L'humain acquitte (ou rejette) une sélection de verdicts Claude.

    ``ack`` : écrit la décision finale dans ``review_queue`` (
    ``decided_by='claude_ack_human'``) ET ``image_assets``, et marque le
    verdict Claude ``status='acked'``.

    ``reject`` : ne touche pas à ``review_queue`` (l'item reste open et
    sortira en queue manuelle classique), marque juste le verdict Claude
    ``status='rejected'``.
    """
    if body.action not in ("ack", "reject"):
        raise HTTPException(status_code=422, detail="action must be 'ack' or 'reject'")
    if not body.review_ids:
        return ClaudeAckResult(requested=0, committed=0, rejected=0, skipped=0)

    conn = _store()._connection()  # noqa: SLF001
    now_iso = _now_iso()
    committed = 0
    rejected = 0
    skipped = 0
    skipped_concurrent = 0

    for review_id in body.review_ids:
        # Charge le verdict + état rq pour valider qu'on peut acquitter.
        # Note : ce SELECT est hors transaction et donc snapshot stale —
        # la vraie garde est dans le `AND status='open'` du UPDATE final
        # (pattern « premier-écrit-gagne »).
        row = conn.execute(
            """
            SELECT v.verdict, v.face, v.status AS v_status,
                   v.model, v.confidence, v.raw_content,
                   v.tokens_in, v.tokens_out, v.cost_usd, v.duration_ms,
                   rq.status AS rq_status, rq.image_asset_id,
                   s.target_eurio_id
              FROM review_claude_verdicts v
              JOIN review_queue rq ON rq.id = v.review_id
              JOIN image_assets a  ON a.id  = rq.image_asset_id
              JOIN source_images s ON s.id  = a.source_image_id
             WHERE v.review_id = ?
            """,
            (review_id,),
        ).fetchone()

        if row is None:
            skipped += 1
            continue
        if row["v_status"] != "pending":
            skipped += 1
            continue

        if body.action == "reject":
            # Reject = action consultative côté humain : on archive le
            # verdict Claude. La review_queue n'est pas touchée. Garde
            # `AND status='pending'` pour éviter le double-write si la
            # même row a déjà été rejetée concurremment.
            cur = conn.execute(
                "UPDATE review_claude_verdicts "
                "SET status='rejected', acked_at=? "
                "WHERE review_id=? AND status='pending'",
                (now_iso, review_id),
            )
            if cur.rowcount == 1:
                rejected += 1
            else:
                skipped += 1
            continue

        # action = 'ack' — nécessite verdict=match + queue open + target connu
        if row["verdict"] != "match":
            skipped += 1
            continue
        if row["rq_status"] != "open":
            skipped += 1
            continue
        target = row["target_eurio_id"]
        if not target:
            skipped += 1
            continue

        # G7 : pareil qu'auto_dino — on n'écrase pas par un default 'obverse'.
        # Claude renvoie 'unknown' explicitement quand la face est ambiguë.
        face = row["face"] or "unknown"

        conn.execute("BEGIN")
        try:
            conn.execute(
                """
                UPDATE image_assets
                   SET eurio_id = ?, face = ?,
                       resolution_status = 'manual',
                       resolution_confidence = 1.0,
                       training_eligible = 1,
                       resolved_at = ?
                 WHERE id = ?
                   AND resolution_status NOT IN ('manual','rejected')
                """,
                (target, face, now_iso, row["image_asset_id"]),
            )
            # Snapshot complet du verdict Claude au moment de l'ack —
            # raw_content + tokens + coût figés sur la row review_queue
            # pour que la trace survive à un re-batch force=true côté
            # review_claude_verdicts (cf. GAP 5).
            claude_metadata = json.dumps({
                "model": row["model"],
                "confidence": row["confidence"],
                "face": row["face"],
                "raw_content": row["raw_content"],
                "tokens_in": row["tokens_in"],
                "tokens_out": row["tokens_out"],
                "cost_usd": row["cost_usd"],
                "duration_ms": row["duration_ms"],
            })
            cur = conn.execute(
                """
                UPDATE review_queue
                   SET status = 'done',
                       decided_eurio_id = ?, decided_face = ?,
                       decision_notes = ?,
                       decided_at = ?, decided_by = 'claude_ack_human',
                       decision_engine_version = ?,
                       decision_metadata_json = ?
                 WHERE id = ? AND status = 'open'
                """,
                (target, face, "Claude vision suggestion acquittée par humain",
                 now_iso, row["model"], claude_metadata, review_id),
            )
            if cur.rowcount != 1:
                # Race : une autre voie a tranché entre le SELECT et l'UPDATE.
                # On annule tout (ROLLBACK) — le verdict Claude reste 'pending'
                # et sera nettoyé en chunk C (stale verdicts).
                conn.execute("ROLLBACK")
                skipped_concurrent += 1
                continue
            emit_state_event(
                conn, asset_id=row["image_asset_id"], to_state="resolved",
                actor="ccproxy", reason="claude_ack", eurio_id=target,
            )
            # Le commit de l'ack n'est valide que si le UPDATE rq a écrit ;
            # sinon on aurait passé le verdict à 'acked' sans avoir tranché.
            conn.execute(
                "UPDATE review_claude_verdicts "
                "SET status='acked', acked_at=? "
                "WHERE review_id=? AND status='pending'",
                (now_iso, review_id),
            )
            conn.execute("COMMIT")
            committed += 1
        except Exception:
            conn.execute("ROLLBACK")
            logger.exception("[claude] ack failed for review_id=%s", review_id)
            skipped += 1

    logger.info(
        "[claude] ack action=%s requested=%d committed=%d rejected=%d "
        "skipped=%d skipped_concurrent=%d",
        body.action, len(body.review_ids),
        committed, rejected, skipped, skipped_concurrent,
    )
    return ClaudeAckResult(
        requested=len(body.review_ids),
        committed=committed,
        rejected=rejected,
        skipped=skipped,
        skipped_concurrent=skipped_concurrent,
    )


class ClaudeCleanupResult(BaseModel):
    deleted: int
    inspected: int


# Consumed by: admin/.../review/composables/useReviewApi.ts (cleanupClaudeOrphans)
@router.post("/claude/cleanup-orphans", response_model=ClaudeCleanupResult)
def cleanup_claude_orphans(dry_run: bool = Query(default=False)) -> ClaudeCleanupResult:
    """Supprime les verdicts Claude ``status='pending'`` dont la
    review_queue parente n'est plus ``status='open'``. Ce sont des
    verdicts orphans nés des races chunk-A entre voies (auto_dino,
    admin) et le batch Claude. Le SELECT côté /pending-acks les filtre
    déjà, mais ils s'accumulent en table — cette route les expurge.

    ``dry_run=true`` retourne juste le compteur. Pas d'écriture.
    """
    conn = _store()._connection()  # noqa: SLF001
    rows = conn.execute(
        """
        SELECT v.review_id FROM review_claude_verdicts v
          JOIN review_queue rq ON rq.id = v.review_id
         WHERE v.status = 'pending' AND rq.status != 'open'
        """
    ).fetchall()
    orphan_ids = [r["review_id"] for r in rows]

    if dry_run or not orphan_ids:
        return ClaudeCleanupResult(deleted=0, inspected=len(orphan_ids))

    placeholders = ",".join("?" for _ in orphan_ids)
    cur = conn.execute(
        f"DELETE FROM review_claude_verdicts WHERE review_id IN ({placeholders})",
        orphan_ids,
    )
    conn.commit()
    logger.info("[claude] cleanup-orphans deleted=%d", cur.rowcount)
    return ClaudeCleanupResult(deleted=cur.rowcount, inspected=len(orphan_ids))
