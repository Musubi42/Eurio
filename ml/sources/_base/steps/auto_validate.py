"""Step 5.5 — Auto-validate via DINOv2.

Encodes each crop produced by step 4 (`detect_crop`) and computes its
top-K cosine similarity against a pre-built obverse anchor bank
(``ml/state/foundation_anchors_<kind>.npz``). Persists one row per
``(asset_id, encoder_version, anchors_kind)`` into
``image_asset_dino_predictions``.

This is **not** a decision step in V1: the asset's
``resolution_status`` stays untouched, the review_queue entry stays
``open``. The top-K is exposed as suggestions in the admin review
drawer (chunk 3) so Raphaël sees what Dino proposes alongside each
crop. Auto-accept will plug in here as a later chunk once we observe
real distributions in `/review` (cf. vision §P5).

Idempotence: skip an asset if a row already exists for the same
``(encoder_version, anchors_kind)``. Pass ``force=True`` to recompute.

Scopes (un crop est encodé UNE fois, matché contre N banques) :
  - ``2eur_commemo`` — target = 2€ commémo. C'est la prédiction que lit
    la couche consensus/lanes (calibrée C0–C5) — ne pas déplacer.
  - ``2eur_all`` — target = 2€ (commémo OU courante). Banque large
    (commémo + design groups standards) servie comme SUGGESTIONS dans
    la review : un lot « diverse Länder » ciblé commémo contient des
    courantes, la banque large les couvre.
  - ``2eur_standard`` — target = 2€ courante (backfill ciblé uniquement).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from training.foundation import (
    CONSENSUS_ANCHORS_KIND,
    DEFAULT_ENCODER_VERSION,
    REVERSE_ANCHORS_KIND,
    SUGGESTIONS_ANCHORS_KIND,
    SUGGESTIONS_ENCODER_VERSION,
    AnchorBank,
    build_transform,
    encode_image,
    encoder_version_for_kind,
    load_anchors,
    load_encoder,
    spread,
    top_k_match,
    top_k_match_country,
)
from review.review_lanes import compute_lane
from sources._base.run_logger import RunHandle
from sources._base.steps.enqueue import _kind_for_source_image
from store import DinoPredictionRow
from vision.denom_probe import decide_denom, denom_score

logger = logging.getLogger(__name__)

_TOP_K_STORE = 5  # how many candidates to persist per asset

# Détection de face (C7) : un crop est le REVERS commun 2€ si sa similarité au
# revers dépasse sa similarité à l'avers d'au moins τ. Seuil recalibré pour la
# banque ENRICHIE (2 canoniques + 32 ancres wild, cf. `_REVERSE_WILD_FILE`
# dans anchors.py) — bench `bench_face_recall.py` (2026-06-13) : τ=+0,065 →
# FP 0/566 avers confirmés, rappel revers durs (denom-rescue) 0 % → 73,3 %,
# revers faciles 100 %. Pire avers à +0,059, prochain revers dur à +0,070 →
# τ équidistant. Conservateur (précision > rappel) car un faux « reverse »
# jetterait un avers identifiable.
FACE_REVERSE_TAU = 0.065

# Kinds calculés au fil de l'eau (scrape/sync) : la prédiction consensus
# (2eur_commemo) + la prédiction suggestions (2eur_all). Un seul encodage
# par crop, N matchings — le matching est négligeable (dot-product numpy).
LIVE_ANCHORS_KINDS: tuple[str, ...] = (
    CONSENSUS_ANCHORS_KIND,
    SUGGESTIONS_ANCHORS_KIND,
)


def _kind_in_scope(kind: str, face_value, is_commemorative) -> bool:
    """Le target du listing rend-il ce kind pertinent pour le crop ?"""
    if face_value is None:
        # Pas de target attribué : le crop appartient au POOL AMBIGU. Les
        # banques scopées (commémo / courantes) ne peuvent rien en dire, mais
        # `2eur_all` couvre tout le 2 € — et c'est justement sur ce pool que
        # le modèle est le plus utile. Cf. `_select_assets_for_backfill`.
        return kind == "2eur_all"
    if float(face_value) != 2.0:
        return False
    if kind == "2eur_commemo":
        return bool(is_commemorative)
    if kind == "2eur_standard":
        return not is_commemorative
    if kind == "2eur_all":
        return True
    return False

# Module-level singletons — torch.hub model load is ~2s, transform is
# stateless. Reuse across calls within the same Python process.
# Les kinds live tournent sur des encodeurs différents (consensus=vits14,
# suggestions=vitl14) → un singleton PAR encoder_version.
_encoder_cache: dict[str, tuple[Any, Any, Any]] = {}
# Clé = le COUPLE (anchors_kind, encoder_version) : deux encodeurs peuvent
# être benchés sur le même kind dans un même process, ils ne doivent pas se
# rendre le même objet.
_bank_cache: dict[tuple[str, str], AnchorBank] = {}


@dataclass
class AutoValidateResult:
    n_predicted: int
    n_skipped_existing: int
    n_skipped_no_anchor: int
    n_skipped_out_of_scope: int
    n_errors: int


def _get_encoder_singleton(encoder_version: str = DEFAULT_ENCODER_VERSION):
    """Lazy-load a DINOv2 encoder + transform; cached per (process, version)."""
    if encoder_version not in _encoder_cache:
        encoder, device = load_encoder(encoder_version=encoder_version)
        _encoder_cache[encoder_version] = (encoder, device, build_transform())
        logger.info("auto_validate: DINOv2 %s ready on %s", encoder_version, device)
    return _encoder_cache[encoder_version]


def _get_bank(
    anchors_kind: str, encoder_version: str | None = None
) -> AnchorBank | None:
    """Banque d'ancres pour un couple (kind, encodeur).

    ``encoder_version=None`` → la **banque SERVIE**
    (``state/foundation_anchors_{kind}.npz``), celle que lisent aussi les ~9
    scripts historiques. On vérifie qu'elle porte bien l'encodeur de
    production du kind (``encoder_version_for_kind``) ; sinon elle est traitée
    comme absente **et journalisée en ERROR**.

    ⚠️ Ne PAS remplacer cette lecture par ``load_anchors(kind, encodeur_de_prod)``
    (c'est ce que faisait la version P6-1, et c'est D3+D10) : l'artefact scopé
    du couple ``(kind, dinov2-vitl14)`` est aussi le **bras baseline du banc**.
    La review se serait mise à servir la banque du dernier run de banc, et le
    garde « banque périmée » serait devenu muet — ``load_anchors`` avalait le
    mismatch avant d'arriver ici.

    Un encodeur explicite charge l'artefact de banc de ce couple, sans que la
    banque servie soit traitée comme « stale »."""
    expected = encoder_version or encoder_version_for_kind(anchors_kind)
    key = (anchors_kind, expected)
    if key in _bank_cache:
        return _bank_cache[key]
    bank = (
        load_anchors(anchors_kind)                     # banque SERVIE
        if encoder_version is None
        else load_anchors(anchors_kind, encoder_version)  # artefact de banc
    )
    if bank is None:
        return None
    if bank.encoder_version != expected:
        # Banque périmée : c'est exactement le geste « bascule d'encodeur » qui
        # a motivé ce garde. Il doit rester BRUYANT — la review deviendrait
        # sinon aveugle (zéro suggestion) sans un mot dans les logs.
        logger.error(
            "auto_validate: anchor bank %s has encoder=%s, expected %s — "
            "treating as missing (rebuild: go-task ml:dino-anchors:build "
            "-- --kind %s --force)",
            anchors_kind, bank.encoder_version, expected, anchors_kind,
        )
        return None
    _bank_cache[key] = bank
    logger.info(
        "auto_validate: anchor bank %s loaded (%d anchors, dim=%d, encoder=%s)",
        anchors_kind, bank.count, bank.dim, bank.encoder_version,
    )
    return bank


def _get_reverse_bank() -> AnchorBank | None:
    """Banque du revers commun 2€ (vitl14). None si absente → face non calculée
    (dégrade proprement, comme une banque d'ancres manquante)."""
    return _get_bank(REVERSE_ANCHORS_KIND)


def _decide_face(reverse_sim: float, obverse_sim: float) -> str:
    """Verdict de face depuis la marge reverse-ness − obverse-ness (cf. C7)."""
    return "reverse" if (reverse_sim - obverse_sim) >= FACE_REVERSE_TAU else "obverse"


def _is_lot_source(
    conn: sqlite3.Connection,
    *,
    source_image_id: str,
    is_lot_suspected,
    cache: dict[str, bool],
) -> bool:
    """La photo source est-elle un LOT (multi-pièces) ? Mémoïsé par run.

    Réutilise la résolution D-26 de l'enqueue (`_kind_for_source_image` :
    titre lot / listing_kind='lot' / >1 crops). Le gate dénomination ne
    s'applique QU'AUX crops de lots (HANDOFF-C7 §1) : la pollution non-2€
    vient des photos de collections entières ; un single ciblé 2€ a déjà
    passé le theme-matcher amont."""
    if source_image_id not in cache:
        cache[source_image_id] = _kind_for_source_image(
            conn,
            source_image_id=source_image_id,
            is_lot_suspected=bool(is_lot_suspected),
        ) == "lot"
    return cache[source_image_id]


def _select_assets_for_run(
    conn: sqlite3.Connection,
    source_image_ids: dict[str, str],
) -> list[sqlite3.Row]:
    """Return assets that should be Dino-validated for this orchestrator run.

    Filters:
      - has a storage_path on disk
      - the parent source_image has a target_eurio_id pointing at a 2€ commemo
        (matches the V1 scope ``2eur_commemo``)
    """
    if not source_image_ids:
        return []
    placeholders = ",".join("?" for _ in source_image_ids)
    rows = conn.execute(
        f"""
        SELECT a.id AS asset_id, a.storage_path, a.source_image_id,
               s.target_eurio_id, s.is_lot_suspected,
               c.face_value, c.is_commemorative
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
     LEFT JOIN coins c ON c.eurio_id = s.target_eurio_id
         WHERE a.source_image_id IN ({placeholders})
           AND a.storage_path IS NOT NULL
        """,
        tuple(source_image_ids.values()),
    ).fetchall()
    return list(rows)


def _select_assets_for_backfill(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    anchors_kind: str = "2eur_commemo",
) -> list[sqlite3.Row]:
    """Return all `image_assets` candidates for a standalone backfill run."""
    sql = """
        SELECT a.id AS asset_id, a.storage_path, a.source_image_id,
               s.target_eurio_id, s.is_lot_suspected,
               c.face_value, c.is_commemorative
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
     LEFT JOIN coins c ON c.eurio_id = s.target_eurio_id
         WHERE a.storage_path IS NOT NULL
    """
    if anchors_kind == "2eur_commemo":
        sql += " AND c.face_value = 2.0 AND c.is_commemorative = 1"
    elif anchors_kind == "2eur_standard":
        sql += " AND c.face_value = 2.0 AND c.is_commemorative = 0"
    else:
        # 2eur_all : tout target 2€ — ET le POOL AMBIGU (listing sans target).
        #
        # `LEFT JOIN coins` suivi de `WHERE c.face_value = 2.0` se comportait en
        # INNER JOIN : un listing sans `target_eurio_id` a `face_value` NULL et
        # sortait du périmètre. Mesuré le 2026-08-19 : 2 193 crops ouverts sur
        # 6 897 — c'est-à-dire précisément ceux dont personne ne sait à quelle
        # pièce ils appartiennent, donc ceux qui auraient le plus besoin du
        # modèle. Ils viennent d'une recherche 2 € de toute façon.
        sql += " AND (c.face_value = 2.0 OR s.target_eurio_id IS NULL)"
    sql += " ORDER BY a.fetched_at ASC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return list(conn.execute(sql).fetchall())


def _predict_one(
    *,
    asset_id: str,
    crop_path: Path,
    bank: AnchorBank,
    encoder,
    device,
    transform,
    anchors_kind: str,
    target_country: str | None = None,
    vec=None,
) -> DinoPredictionRow | None:
    """Match un crop contre une banque. Passer ``vec`` (embedding déjà
    calculé) pour matcher le même crop contre plusieurs banques sans
    ré-encoder — l'encodage domine le coût, le matching est négligeable."""
    t0 = time.perf_counter()
    if vec is None:
        if not crop_path.is_file():
            logger.warning(
                "auto_validate: missing crop file for asset=%s path=%s",
                asset_id, crop_path,
            )
            return None
        vec = encode_image(
            crop_path, encoder=encoder, device=device, transform=transform
        )
    matches = top_k_match(vec, bank, top_k=_TOP_K_STORE)

    # Country-restricted re-rank — same embedding, masked bank. Cheap.
    country_matches: list = []
    country_anchors_count = 0
    if target_country:
        country_matches = top_k_match_country(
            vec, bank, target_country=target_country, top_k=_TOP_K_STORE,
        )
        # Compte des CLASSES distinctes (bank multi-exemplaires : plusieurs
        # lignes/eurio_id), pas des lignes de la banque.
        country_anchors_count = len({
            eid for eid in bank.eurio_ids
            if eid[:2].lower() == target_country.lower()
        })

    duration_ms = int((time.perf_counter() - t0) * 1000)
    if not matches:
        return None
    top1 = matches[0]
    top2 = matches[1] if len(matches) > 1 else None

    c_top1 = country_matches[0] if country_matches else None
    c_top2 = country_matches[1] if len(country_matches) > 1 else None

    return DinoPredictionRow(
        asset_id=asset_id,
        encoder_version=bank.encoder_version,
        anchors_kind=anchors_kind,
        anchors_count=len(set(bank.eurio_ids)),  # classes distinctes, pas lignes
        top_k=[m.to_dict() for m in matches],
        top1_eurio_id=top1.eurio_id,
        top1_sim=float(top1.sim),
        top2_eurio_id=top2.eurio_id if top2 else None,
        top2_sim=float(top2.sim) if top2 else None,
        spread=spread(matches),
        target_country=target_country,
        country_anchors_count=country_anchors_count if target_country else None,
        top_k_country=[m.to_dict() for m in country_matches] if country_matches else None,
        top1_country_eurio_id=c_top1.eurio_id if c_top1 else None,
        top1_country_sim=float(c_top1.sim) if c_top1 else None,
        top2_country_eurio_id=c_top2.eurio_id if c_top2 else None,
        top2_country_sim=float(c_top2.sim) if c_top2 else None,
        country_spread=spread(country_matches) if country_matches else None,
        duration_ms=duration_ms,
    )


def _existing_keys(
    conn: sqlite3.Connection,
    asset_ids: list[str],
    encoder_version: str,
    anchors_kind: str,
) -> set[str]:
    if not asset_ids:
        return set()
    placeholders = ",".join("?" for _ in asset_ids)
    rows = conn.execute(
        f"""
        SELECT asset_id FROM image_asset_dino_predictions
         WHERE asset_id IN ({placeholders})
           AND encoder_version = ? AND anchors_kind = ?
        """,
        (*asset_ids, encoder_version, anchors_kind),
    ).fetchall()
    return {r["asset_id"] for r in rows}


def _load_banks(kinds: tuple[str, ...], context: str) -> dict[str, AnchorBank]:
    """Charge les banques demandées ; celles qui manquent sont loggées et
    sautées (le pipeline amont ne casse jamais sur la couche suggestion)."""
    banks: dict[str, AnchorBank] = {}
    for kind in kinds:
        bank = _get_bank(kind)
        if bank is None:
            logger.warning(
                "[%s] auto_validate: anchor bank %s missing — skipping this "
                "kind (run `go-task ml:dino-anchors:build` to bootstrap)",
                context, kind,
            )
            continue
        banks[kind] = bank
    return banks


# Called by: ml/sources/_base/orchestrator.py (step 7/8 — after resolve, before enqueue; suggestion layer, no decision in V1)
def run_auto_validate_dino(
    *,
    conn: sqlite3.Connection,
    run: RunHandle | None,
    source_id: str,
    source_image_ids: dict[str, str],
    anchors_kinds: tuple[str, ...] = LIVE_ANCHORS_KINDS,
    force: bool = False,
) -> AutoValidateResult:
    """Step 5.5 entry point — called by the orchestrator after `resolve`.

    Falls back to a no-op (logged) if the bank files are missing — the
    upstream pipeline should not break because the auto-validation
    layer hasn't been bootstrapped yet.
    """
    banks = _load_banks(anchors_kinds, source_id)
    if not banks:
        return AutoValidateResult(0, 0, 0, 0, 0)

    candidates = _select_assets_for_run(conn, source_image_ids)
    return _run_inner(
        conn=conn,
        candidates=candidates,
        banks=banks,
        force=force,
    )


# Called by: ml/scripts/backfill_dino_predictions.py (standalone re-run over all in-scope assets, no run row)
def run_auto_validate_dino_backfill(
    *,
    store,
    anchors_kind: str = "2eur_commemo",
    force: bool = False,
    limit: int | None = None,
    run_id: str | None = None,
) -> AutoValidateResult:
    """Standalone backfill — used by ml/scripts/backfill_dino_predictions.py.

    Selects all `image_assets` matching the V1 scope and runs the same
    inner loop. Bypasses the orchestrator's run handle.
    """
    bank = _get_bank(anchors_kind)
    if bank is None:
        logger.error(
            "auto_validate backfill: anchor bank %s missing — run "
            "`go-task ml:dino-anchors:build` first",
            anchors_kind,
        )
        return AutoValidateResult(0, 0, 0, 0, 0)

    conn = store._connection()  # noqa: SLF001
    candidates = _select_assets_for_backfill(
        conn, limit=limit, anchors_kind=anchors_kind
    )
    logger.info(
        "auto_validate backfill: %d candidate assets in scope %s",
        len(candidates), anchors_kind,
    )
    return _run_inner(
        conn=conn,
        candidates=candidates,
        banks={anchors_kind: bank},
        force=force,
        store=store,
        run_id=run_id,
    )


# Called by: ml/api/review_queue_routes.py (manual_crop) — recompute on demand
# after a human re-crop, so the Dino suggestions panel reflects the corrected
# crop without waiting for a batch backfill.
def predict_and_persist_one(
    *,
    store,
    asset_id: str,
    crop_path: Path,
    target_country: str | None = None,
    anchors_kind: str = "2eur_commemo",
) -> DinoPredictionRow | None:
    """Encode one crop, match against ONE anchor bank, upsert the prediction.

    Reuses the process-wide encoder + bank singletons (same path as the
    batch backfill → identical format). Returns the persisted row, or None
    if the bank is missing or the crop can't be encoded. Scope is NOT
    enforced here: a human re-crop is an explicit action and the caller
    owns the decision to run Dino.
    """
    rows = predict_and_persist_kinds(
        store=store,
        asset_id=asset_id,
        crop_path=crop_path,
        target_country=target_country,
        anchors_kinds=(anchors_kind,),
    )
    return rows.get(anchors_kind)


# Called by: ml/serving/crop_edit.py (re-crop / add-crop manuel) et
# ml/review/review_queue_routes.py (_lazy_compute_dino) — recompute à la
# demande des kinds live, en partageant l'embedding (1 encode → N banques).
def predict_and_persist_kinds(
    *,
    store,
    asset_id: str,
    crop_path: Path,
    target_country: str | None = None,
    anchors_kinds: tuple[str, ...] = LIVE_ANCHORS_KINDS,
) -> dict[str, DinoPredictionRow]:
    """Encode un crop (une fois PAR encodeur) et upsert une prédiction par kind.

    Les kinds partageant un encodeur partagent l'embedding ; consensus
    (vits14) et suggestions (vitl14) impliquent deux encodages. Les kinds
    dont la banque manque sont sautés (loggés). Renvoie les rows persistées
    par kind — dict vide si rien n'a pu être calculé.
    """
    banks = _load_banks(anchors_kinds, f"asset={asset_id}")
    if not banks:
        return {}
    if not crop_path.is_file():
        logger.warning(
            "predict_and_persist_kinds: missing crop file asset=%s path=%s",
            asset_id, crop_path,
        )
        return {}
    out: dict[str, DinoPredictionRow] = {}
    for version in sorted({b.encoder_version for b in banks.values()}):
        encoder, device, transform = _get_encoder_singleton(version)
        vec = encode_image(
            crop_path, encoder=encoder, device=device, transform=transform
        )
        for kind, bank in banks.items():
            if bank.encoder_version != version:
                continue
            prediction = _predict_one(
                asset_id=asset_id,
                crop_path=crop_path,
                bank=bank,
                encoder=encoder,
                device=device,
                transform=transform,
                anchors_kind=kind,
                target_country=target_country,
                vec=vec,
            )
            if prediction is not None:
                out[kind] = prediction
        # Face (C7) : sur le vec vitl14, renseigne reverse_sim/face_margin de la
        # row 2eur_all (audit). L'écriture de image_assets.face reste au run
        # principal / backfill (ici on n'a pas le garde-fou face IS NULL ciblé).
        if version == SUGGESTIONS_ENCODER_VERSION and SUGGESTIONS_ANCHORS_KIND in out:
            rev_bank = _get_reverse_bank()
            ap = out[SUGGESTIONS_ANCHORS_KIND]
            if rev_bank is not None and ap.top1_sim is not None:
                rev_sim = float(np.max(rev_bank.matrix @ vec))
                ap.reverse_sim = rev_sim
                ap.face_margin = rev_sim - ap.top1_sim
            # Gate dénom (C7 pilier 2) : score 2€-ness audit sur la row 2eur_all,
            # crops de LOTS uniquement (même périmètre que _run_inner). Le verdict
            # image_assets.denom n'est PAS réécrit ici : un re-crop manuel est une
            # action humaine, le rejet/restore reste la décision de l'opérateur.
            conn = store._connection()  # noqa: SLF001
            meta = conn.execute(
                "SELECT a.source_image_id, s.is_lot_suspected"
                "  FROM image_assets a"
                "  JOIN source_images s ON s.id = a.source_image_id"
                " WHERE a.id = ?",
                (asset_id,),
            ).fetchone()
            if meta is not None and _is_lot_source(
                conn,
                source_image_id=meta["source_image_id"],
                is_lot_suspected=meta["is_lot_suspected"],
                cache={},
            ):
                bgr = cv2.imread(str(crop_path))
                if bgr is not None:
                    ds = denom_score(vec, bgr)
                    if ds is not None:
                        ap.denom_2eur_score = ds
    if out:
        store.upsert_dino_predictions(list(out.values()))
        # Remontée canonique au VPS (Direction A, C4d). L'écriture locale
        # ci-dessus reste (cache réplique + lecture immédiate par la review UI,
        # cf. review/review_queue_routes._build_dino_response — même pattern que
        # le forward face dans training/training_set_scan.py). Best-effort : un
        # échec réseau ne casse pas le recompute déjà committé localement (le
        # prochain recompute/backfill re-tentera).
        from client.http import sync_enabled  # noqa: PLC0415

        if sync_enabled():
            try:
                from client.ingest import push_dino_predictions  # noqa: PLC0415

                push_dino_predictions([r.to_dict() for r in out.values()])
            except Exception as exc:  # noqa: BLE001 — forward best-effort
                logger.warning(
                    "predict_and_persist_kinds: forward /ingest/dino échoué "
                    "asset=%s (%d prediction(s)): %s",
                    asset_id, len(out), exc,
                )
    return out


# Called by: ml/review/review_queue_routes.py (endpoint rank-candidates) —
# départage Dino en ENSEMBLE FERMÉ entre des candidats CONNUS (pièces du
# groupe / designs standard du pays). Différent du top-K open-vocab : là on ne
# cherche pas la pièce dans toute la banque (qui enterre la bonne réponse sous
# des pays voisins à forte sim — ex. Donatello #6 derrière des Monaco), on
# compare le crop UNIQUEMENT aux candidats fournis et on classe. Pas
# d'abstention : l'appelant a déjà restreint l'espace à 2-N pièces plausibles.
def rank_eurio_ids_for_crop(
    crop_path: Path,
    eurio_ids: list[str],
    *,
    anchors_kind: str = SUGGESTIONS_ANCHORS_KIND,
) -> dict[str, Any]:
    """Classe ``eurio_ids`` par similarité Dino décroissante au crop.

    Retourne ``{"anchors_kind", "encoder_version", "ranked": [{"eurio_id",
    "sim"}], "missing": [...]}`` où ``ranked`` est trié sim décroissante et
    ``missing`` liste les eurio_ids absents de la banque (pas d'ancre → non
    classables). ``ranked`` vide si la banque manque ou le crop est illisible
    (l'appelant dégrade proprement — c'est une aide, pas un bloqueur)."""
    empty = {
        "anchors_kind": anchors_kind, "encoder_version": None,
        "ranked": [], "missing": list(eurio_ids),
    }
    if not eurio_ids:
        return {**empty, "missing": []}
    bank = _get_bank(anchors_kind)
    if bank is None or not crop_path.is_file():
        return empty
    encoder, device, transform = _get_encoder_singleton(bank.encoder_version)
    vec = encode_image(crop_path, encoder=encoder, device=device, transform=transform)
    sims = bank.matrix @ vec  # (N,) — banque L2-normalisée, vec L2-normalisé
    # Max-pool par eurio_id : depuis B, une classe a plusieurs lignes (canonique
    # + exemplaires FPS) → la sim de la classe = la meilleure de ses lignes.
    best: dict[str, float] = {}
    for i, eid in enumerate(bank.eurio_ids):
        s = float(sims[i])
        if eid not in best or s > best[eid]:
            best[eid] = s
    ranked: list[dict[str, Any]] = []
    missing: list[str] = []
    for eid in eurio_ids:
        if eid in best:
            ranked.append({"eurio_id": eid, "sim": best[eid]})
        else:
            missing.append(eid)
    ranked.sort(key=lambda r: r["sim"], reverse=True)
    return {
        "anchors_kind": anchors_kind,
        "encoder_version": bank.encoder_version,
        "ranked": ranked,
        "missing": missing,
    }


def _run_inner(
    *,
    conn: sqlite3.Connection,
    candidates: list,
    banks: dict[str, AnchorBank],
    force: bool,
    store=None,
    run_id: str | None = None,
) -> AutoValidateResult:
    """Boucle interne : encode chaque crop une fois, matche contre chaque
    banque dont le kind est en scope pour le target du listing.

    Compteurs : ``n_predicted`` = rows écrites (assets × kinds),
    ``n_skipped_existing`` / ``n_skipped_out_of_scope`` = assets.
    """
    n_predicted = 0
    n_existing = 0
    n_no_anchor = 0
    n_oos = 0
    n_errors = 0
    predicted_ids: list[str] = []  # assets re-prédits → re-route lane post-Dino

    # (asset, kinds applicables au target) — un asset peut nourrir N kinds.
    in_scope: list[tuple[Any, list[str]]] = []
    for r in candidates:
        kinds = [
            k for k in banks
            if _kind_in_scope(k, r["face_value"], r["is_commemorative"])
        ]
        if not kinds:
            n_oos += 1
            continue
        in_scope.append((r, kinds))

    if not in_scope:
        return AutoValidateResult(0, 0, 0, n_oos, 0)

    asset_ids = [r["asset_id"] for r, _ in in_scope]
    skip_by_kind: dict[str, set[str]] = {
        kind: (
            _existing_keys(conn, asset_ids, bank.encoder_version, kind)
            if not force
            else set()
        )
        for kind, bank in banks.items()
    }

    # Banque revers (C7 face) — chargée une fois, partagée. None → face skip.
    rev_bank = _get_reverse_bank()
    face_writes: list[tuple[str, str]] = []  # (face, asset_id), WHERE face IS NULL
    denom_writes: list[tuple[str, str]] = []  # (denom, asset_id), WHERE denom IS NULL
    lot_cache: dict[str, bool] = {}  # source_image_id → lot ? (gate denom)

    rows_to_write: list[DinoPredictionRow] = []
    for r, kinds in in_scope:
        aid = r["asset_id"]
        kinds_todo = [k for k in kinds if aid not in skip_by_kind[k]]
        if not kinds_todo:
            n_existing += 1
            continue
        # Target country from the parent eBay query (source_images.target_eurio_id).
        # First 2 chars of the eurio_id = ISO2. NULL if no target — fall back to
        # global top-K only.
        target_eid = r["target_eurio_id"]
        target_country = (
            target_eid[:2].lower() if target_eid and len(target_eid) >= 2 else None
        )
        # storage_path is the S3 key in enrichment-crops. local_path()
        # does read-through cache (no-op if cached by same-run detect_crop).
        from shared.storage.local_cache import local_path as _local_path
        try:
            crop_p = _local_path("enrichment-crops", r["storage_path"])
        except FileNotFoundError as exc:
            logger.error("auto_validate: missing crop in MinIO asset=%s key=%s: %s",
                         aid, r["storage_path"], exc)
            n_errors += 1
            continue
        try:
            if not crop_p.is_file():
                logger.warning(
                    "auto_validate: missing crop file for asset=%s path=%s",
                    aid, crop_p,
                )
                n_errors += 1
                continue
            # Un embedding par encodeur (consensus=vits14, suggestions=vitl14),
            # partagé entre les kinds qui tournent sur le même encodeur.
            predictions = []
            vecs_by_version: dict[str, Any] = {}
            for version in sorted(
                {banks[k].encoder_version for k in kinds_todo}
            ):
                encoder, device, transform = _get_encoder_singleton(version)
                vec = encode_image(
                    crop_p, encoder=encoder, device=device, transform=transform
                )
                vecs_by_version[version] = vec
                predictions.extend(
                    p for kind in kinds_todo
                    if banks[kind].encoder_version == version
                    and (p := _predict_one(
                        asset_id=aid,
                        crop_path=crop_p,
                        bank=banks[kind],
                        encoder=encoder,
                        device=device,
                        transform=transform,
                        anchors_kind=kind,
                        target_country=target_country,
                        vec=vec,
                    )) is not None
                )
        except Exception as exc:  # broad on purpose — pipeline must keep moving
            logger.exception("auto_validate: failed on asset=%s: %s", aid, exc)
            n_errors += 1
            continue
        if not predictions:
            n_errors += 1
            continue

        # ── Face + dénomination (C7) — gratuits : réutilisent le vec vitl14 ──
        # Calculés seulement quand on (re)prédit 2eur_all (même encodeur vitl14).
        if SUGGESTIONS_ENCODER_VERSION in vecs_by_version:
            all_pred = next(
                (p for p in predictions if p.anchors_kind == SUGGESTIONS_ANCHORS_KIND),
                None,
            )
            if all_pred is not None and all_pred.top1_sim is not None:
                vvec = vecs_by_version[SUGGESTIONS_ENCODER_VERSION]
                # Face : reverse_sim/face_margin stockés sur la row 2eur_all
                # (audit), image_assets.face écrit plus bas si NULL. Skip si la
                # banque revers manque (dégrade proprement).
                if rev_bank is not None:
                    rev_sim = float(np.max(rev_bank.matrix @ vvec))
                    all_pred.reverse_sim = rev_sim
                    all_pred.face_margin = rev_sim - all_pred.top1_sim
                    face_writes.append(
                        (_decide_face(rev_sim, all_pred.top1_sim), aid)
                    )
                # ── Gate dénomination (C7 pilier 2) — crops de LOTS uniquement.
                # Probe DINO+bimétal : score 2€-ness sur la row 2eur_all (ranker)
                # + verdict image_assets.denom écrit plus bas si NULL. No-op si
                # l'artefact denom_probe.npz est absent (denom_score → None).
                if _is_lot_source(
                    conn,
                    source_image_id=r["source_image_id"],
                    is_lot_suspected=r["is_lot_suspected"],
                    cache=lot_cache,
                ):
                    bgr = cv2.imread(str(crop_p))
                    if bgr is not None:
                        ds = denom_score(vvec, bgr)
                        if ds is not None:
                            all_pred.denom_2eur_score = ds
                            denom_writes.append((decide_denom(ds), aid))

        # Model B (C6b) : tag les prédictions avec le run_id du backfill (sur des
        # assets préexistants) pour qu'export_run les collecte par run_id. NULL au
        # run scrape normal (collectées par asset_id via le run parent de l'asset).
        if run_id is not None:
            for p in predictions:
                p.run_id = run_id
        rows_to_write.extend(predictions)
        predicted_ids.append(aid)
        n_predicted += len(predictions)
        if len(rows_to_write) >= 32:
            _flush(conn, store, rows_to_write)
            rows_to_write.clear()

    if rows_to_write:
        _flush(conn, store, rows_to_write)
        rows_to_write.clear()

    # ── Écriture de la face (C7) ─────────────────────────────────────────
    # UNIQUEMENT si face IS NULL : ne clobbe pas les labels humains/Claude
    # (review_queue.decided_face → image_assets.face) ni un run précédent →
    # idempotent. Le routing (rejet face_reverse) se fait à l'enqueue / backfill.
    if face_writes:
        conn.executemany(
            "UPDATE image_assets SET face=? WHERE id=? AND face IS NULL",
            face_writes,
        )
        n_rev = sum(1 for f, _ in face_writes if f == "reverse")
        logger.info(
            "auto_validate: face écrit sur %d crops (%d reverse, %d obverse) "
            "[face IS NULL only]", len(face_writes), n_rev, len(face_writes) - n_rev,
        )

    # ── Écriture de la dénomination (C7 pilier 2) — miroir de la face ─────
    # UNIQUEMENT si denom IS NULL (anti-clobber). Le rejet 'not_2eur' se fait
    # à l'enqueue / backfill, comme face_reverse.
    if denom_writes:
        conn.executemany(
            "UPDATE image_assets SET denom=? WHERE id=? AND denom IS NULL",
            denom_writes,
        )
        n_junk = sum(1 for d, _ in denom_writes if d == "not_2eur")
        logger.info(
            "auto_validate: denom écrit sur %d crops (%d not_2eur, %d 2eur) "
            "[denom IS NULL only]", len(denom_writes), n_junk,
            len(denom_writes) - n_junk,
        )

    # Re-route post-Dino : pour les items DÉJÀ en queue (cas backfill — en run
    # normal l'enqueue vient APRÈS et pose la lane lui-même), recalcule la lane
    # des items open NON épinglés humain à partir de la prédiction qu'on vient
    # d'écrire. Source de vérité = foundation/review_lanes. Les items
    # lane_source='human' (déplacés à la main) ne sont JAMAIS re-routés.
    n_relane = 0
    for aid in predicted_ids:
        rq = conn.execute(
            "SELECT id, lane FROM review_queue "
            "WHERE image_asset_id=? AND status='open' AND lane_source='auto'",
            (aid,),
        ).fetchone()
        if rq is None:
            continue
        _v, lane = compute_lane(conn, aid)
        if lane != rq["lane"]:
            conn.execute(
                "UPDATE review_queue SET lane=? WHERE id=? AND lane_source='auto'",
                (lane, rq["id"]),
            )
            n_relane += 1
    if n_relane:
        logger.info("auto_validate: re-routed %d review lanes (post-Dino)", n_relane)

    logger.info(
        "auto_validate: predicted=%d existing=%d no_anchor=%d "
        "out_of_scope=%d errors=%d",
        n_predicted, n_existing, n_no_anchor, n_oos, n_errors,
    )
    return AutoValidateResult(
        n_predicted=n_predicted,
        n_skipped_existing=n_existing,
        n_skipped_no_anchor=n_no_anchor,
        n_skipped_out_of_scope=n_oos,
        n_errors=n_errors,
    )


def _flush(conn: sqlite3.Connection, store, rows: list[DinoPredictionRow]) -> None:
    """Persist a batch of predictions. Uses Store helper when available
    (orchestrator path), falls back to a direct SQL upsert (run from a
    raw connection — tests / standalone backfill before Store is
    plumbed)."""
    if not rows:
        return
    if store is not None:
        store.upsert_dino_predictions(rows)
        return
    # Direct path — reproduces the SQL of Store.upsert_dino_predictions
    import json as _json
    conn.executemany(
        """
        INSERT INTO image_asset_dino_predictions (
          asset_id, encoder_version, anchors_kind, anchors_count,
          top_k_json, top1_eurio_id, top1_sim, top2_eurio_id,
          top2_sim, spread,
          target_country, country_anchors_count, top_k_country_json,
          top1_country_eurio_id, top1_country_sim,
          top2_country_eurio_id, top2_country_sim, country_spread,
          reverse_sim, face_margin, denom_2eur_score,
          computed_at, duration_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?,
                  datetime('now'), ?)
        ON CONFLICT(asset_id, encoder_version, anchors_kind) DO UPDATE SET
          anchors_count          = excluded.anchors_count,
          top_k_json             = excluded.top_k_json,
          top1_eurio_id          = excluded.top1_eurio_id,
          top1_sim               = excluded.top1_sim,
          top2_eurio_id          = excluded.top2_eurio_id,
          top2_sim               = excluded.top2_sim,
          spread                 = excluded.spread,
          target_country         = excluded.target_country,
          country_anchors_count  = excluded.country_anchors_count,
          top_k_country_json     = excluded.top_k_country_json,
          top1_country_eurio_id  = excluded.top1_country_eurio_id,
          top1_country_sim       = excluded.top1_country_sim,
          top2_country_eurio_id  = excluded.top2_country_eurio_id,
          top2_country_sim       = excluded.top2_country_sim,
          country_spread         = excluded.country_spread,
          reverse_sim            = excluded.reverse_sim,
          face_margin            = excluded.face_margin,
          denom_2eur_score       = excluded.denom_2eur_score,
          duration_ms            = excluded.duration_ms,
          computed_at            = datetime('now')
        """,
        [
            (
                r.asset_id, r.encoder_version, r.anchors_kind, r.anchors_count,
                _json.dumps(r.top_k),
                r.top1_eurio_id, r.top1_sim, r.top2_eurio_id, r.top2_sim,
                r.spread,
                r.target_country, r.country_anchors_count,
                _json.dumps(r.top_k_country) if r.top_k_country is not None else None,
                r.top1_country_eurio_id, r.top1_country_sim,
                r.top2_country_eurio_id, r.top2_country_sim, r.country_spread,
                r.reverse_sim, r.face_margin, r.denom_2eur_score,
                r.duration_ms,
            )
            for r in rows
        ],
    )
