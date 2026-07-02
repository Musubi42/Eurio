"""Scan Dino du Jeu d'entraînement d'une cohorte (improvement-loop P1+P2).

Pour chaque crop **éligible au train** des classes de la cohorte, un seul
encodage DINOv2 vitl14 alimente deux verdicts :

- **P1 · intrus (ensemble fermé).** Le crop est classé contre les SEULES
  classes de la cohorte (même logique que ``rank_eurio_ids_for_crop`` de la
  review, à la maille classe = ``COALESCE(design_group_id, eurio_id)``). Si le
  top-1 Dino est une AUTRE classe que celle assignée, avec une marge
  ``sim(top1) − sim(assignée) ≥ intruder_margin``, le crop est marqué
  « probable intrus » — l'UI le remonte en tête, l'humain le réassigne.
- **P2 · face.** Verdict obverse/reverse via la banque revers C7
  (``_decide_face``, τ benché) écrit sur ``image_assets.face`` UNIQUEMENT
  quand la face est NULL ou 'unknown' — jamais par-dessus un label
  obverse/reverse existant (humain, Claude ou run précédent). Vide le bucket
  « à confirmer » du panneau et révèle les reverse cachés (que le gate bake
  P3 exclut désormais).

L'état du scan vit en base (``cohort_training_scans`` + ``…_scan_results``,
cf. store/training_scan.py) : lancé en subprocess détaché par l'endpoint
``POST /lab/cohorts/{id}/training-scan`` (scripts/lab_training_scan.py), même
doctrine que recrop_zero — la progression se lit au poll, survit au
``--reload``, un crash clôt le scan en ``failed``.

Réutilise les singletons process-wide d'``auto_validate`` (encodeur + banques)
— le scan est mono-process, chargement unique ~2 s puis ~10-15 crops/s (MPS).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from store import (
    ScanResultRow,
    training_scan_finish,
    training_scan_progress,
    training_scan_upsert_results,
)

logger = logging.getLogger(__name__)

# Seuil de désaccord « fort » (P1) : marge closed-set sim(top1) − sim(assignée)
# au-delà de laquelle on lève le badge intrus. Précision d'abord (un faux badge
# coûte une vérification humaine). Mesuré sur mix-zone-17 (2026-07-02, 515
# crops éligibles) : 53 désaccords top-1, marges de +0.001 à +0.339 ; 0.05 en
# retient 25 — les plus fortes (≥ +0.10) sont des confusions franches
# inter-classes. Surchargeable par scan (endpoint ?margin= / CLI --margin).
DEFAULT_INTRUDER_MARGIN = 0.05

_RESULTS_BATCH = 32
_PROGRESS_EVERY = 8


@dataclass
class ScanSummary:
    n_total: int
    n_done: int
    n_intruders: int
    n_faces_written: int
    n_skipped: int


def _class_descriptors(store, cohort) -> list:
    """Descriptors (class_id, eurio_ids) des classes de la cohorte — même
    resolver que le bake et training-crops (maille design_group)."""
    from training.eval.class_resolver import build_resolver

    resolver = build_resolver(force_eurio_id=False, db_path=store.db_path)
    descriptors, _unresolved = resolver.classes_for_eurio_ids(cohort.eurio_ids)
    return descriptors


def scan_scope_count(store, cohort) -> int:
    """Nombre de crops dans le scope du scan (n_total de la barre de
    progression) — mêmes filtres que la boucle de ``run_training_set_scan``."""
    descriptors = _class_descriptors(store, cohort)
    members = [eid for d in descriptors for eid in d.eurio_ids]
    if not members:
        return 0
    conn = store._connection()  # noqa: SLF001
    ph = ",".join("?" for _ in members)
    return conn.execute(
        f"""
        SELECT COUNT(*)
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE s.source = 'ebay'
           AND a.eurio_id IN ({ph})
           AND a.training_eligible = 1
           AND a.storage_status = 'present'
        """,
        members,
    ).fetchone()[0]


def run_training_set_scan(
    store,
    cohort_id: str,
    scan_id: str,
    *,
    intruder_margin: float = DEFAULT_INTRUDER_MARGIN,
) -> ScanSummary:
    """Boucle du scan — le scan ``scan_id`` est déjà ouvert (status='running').

    Clôt le scan (done/failed) elle-même ; toute exception est persistée en
    ``failed`` par l'appelant CLI (scripts/lab_training_scan.py). Retourne le
    résumé pour les logs.
    """
    # Briques Dino partagées avec la review/le backfill — mêmes banques, mêmes
    # singletons, même verdict de face (τ benché C7).
    from shared.storage.local_cache import local_path
    from sources._base.steps.auto_validate import (
        _decide_face,
        _get_bank,
        _get_encoder_singleton,
        _get_reverse_bank,
    )
    from training.foundation import SUGGESTIONS_ANCHORS_KIND, encode_image

    conn = store._connection()  # noqa: SLF001
    cohort = store.get_cohort(cohort_id)
    if cohort is None:
        raise RuntimeError(f"Cohort introuvable : {cohort_id}")

    bank = _get_bank(SUGGESTIONS_ANCHORS_KIND)
    if bank is None:
        raise RuntimeError(
            f"Banque d'ancres {SUGGESTIONS_ANCHORS_KIND} absente — "
            "`go-task ml:dino-anchors:build` d'abord"
        )
    rev_bank = _get_reverse_bank()  # None → P2 sautée (dégrade proprement)
    encoder, device, transform = _get_encoder_singleton(bank.encoder_version)

    # Index closed-set : classe → indices de ses ancres dans la banque.
    descriptors = _class_descriptors(store, cohort)
    anchor_index = {eid: i for i, eid in enumerate(bank.eurio_ids)}
    class_anchor_rows: dict[str, list[tuple[int, str]]] = {}
    class_of_member: dict[str, str] = {}
    for d in descriptors:
        rows = []
        for eid in d.eurio_ids:
            class_of_member[eid] = d.class_id
            i = anchor_index.get(eid)
            if i is not None:
                rows.append((i, eid))
        class_anchor_rows[d.class_id] = rows
    classes_without_anchor = sorted(
        cid for cid, rows in class_anchor_rows.items() if not rows
    )
    if classes_without_anchor:
        logger.warning(
            "training-scan %s: %d classe(s) sans ancre dans %s (%s) — leurs "
            "crops ne sont pas jugeables en intrus",
            scan_id, len(classes_without_anchor), SUGGESTIONS_ANCHORS_KIND,
            ", ".join(classes_without_anchor),
        )

    members = list(class_of_member)
    crops: list = []
    if members:
        ph = ",".join("?" for _ in members)
        crops = conn.execute(
            f"""
            SELECT a.id, a.eurio_id, a.face, a.storage_path
              FROM image_assets a
              JOIN source_images s ON s.id = a.source_image_id
             WHERE s.source = 'ebay'
               AND a.eurio_id IN ({ph})
               AND a.training_eligible = 1
               AND a.storage_status = 'present'
             ORDER BY a.eurio_id, a.id
            """,
            members,
        ).fetchall()

    n_done = 0
    n_intruders = 0
    n_faces = 0
    n_skipped = 0
    batch: list[ScanResultRow] = []
    for crop in crops:
        aid = crop["id"]
        assigned_class = class_of_member[crop["eurio_id"]]
        try:
            crop_p = local_path("enrichment-crops", crop["storage_path"])
            if not crop_p.is_file():
                raise FileNotFoundError(crop_p)
            vec = encode_image(
                crop_p, encoder=encoder, device=device, transform=transform,
            )
        except Exception as exc:  # noqa: BLE001 — le scan doit balayer tout le scope
            logger.warning("training-scan: crop %s illisible: %s", aid, exc)
            n_skipped += 1
            n_done += 1
            continue

        sims = bank.matrix @ vec  # banque + vec L2-normalisés

        # ── P2 · face — même verdict que le backfill C7, mais autorisé à
        # résoudre 'unknown' (posé quand personne n'a détecté la face), jamais
        # à écraser un obverse/reverse existant.
        face_verdict: str | None = None
        face_written = False
        if rev_bank is not None:
            obverse_sim = float(np.max(sims))
            rev_sim = float(np.max(rev_bank.matrix @ vec))
            face_verdict = _decide_face(rev_sim, obverse_sim)
            if crop["face"] is None or crop["face"] == "unknown":
                cur = conn.execute(
                    "UPDATE image_assets SET face=? WHERE id=? "
                    "AND (face IS NULL OR face='unknown')",
                    (face_verdict, aid),
                )
                if cur.rowcount:
                    face_written = True
                    n_faces += 1

        # ── P1 · intrus — classement closed-set entre les classes de la
        # cohorte. La face effective (label existant sinon verdict) doit être
        # avers : un revers ressemble à un revers, pas à sa classe — le juger
        # « intrus » serait un faux signal (il est déjà ambre + hors bake P3).
        effective_face = crop["face"] or face_verdict
        assigned_rows = class_anchor_rows.get(assigned_class, [])
        assigned_sim = (
            float(max(sims[i] for i, _ in assigned_rows))
            if assigned_rows else None
        )
        top1_class = None
        top1_eurio_id = None
        top1_sim = None
        for cid, rows in class_anchor_rows.items():
            for i, eid in rows:
                s = float(sims[i])
                if top1_sim is None or s > top1_sim:
                    top1_class, top1_eurio_id, top1_sim = cid, eid, s
        margin = (
            top1_sim - assigned_sim
            if (top1_sim is not None and assigned_sim is not None)
            else None
        )
        is_intruder = bool(
            margin is not None
            and top1_class is not None
            and top1_class != assigned_class
            and margin >= intruder_margin
            and effective_face != "reverse"
        )
        if assigned_sim is None:
            n_skipped += 1  # classe sans ancre — pas jugeable
        if is_intruder:
            n_intruders += 1

        batch.append(ScanResultRow(
            asset_id=aid,
            assigned_class=assigned_class,
            assigned_sim=assigned_sim,
            top1_class=top1_class,
            top1_eurio_id=top1_eurio_id,
            top1_sim=top1_sim,
            margin=margin,
            is_intruder=is_intruder,
            face_verdict=face_verdict,
            face_written=face_written,
        ))
        n_done += 1
        if len(batch) >= _RESULTS_BATCH:
            training_scan_upsert_results(conn, scan_id, batch)
            batch.clear()
        if n_done % _PROGRESS_EVERY == 0:
            training_scan_progress(conn, scan_id, n_done=n_done)

    training_scan_upsert_results(conn, scan_id, batch)
    training_scan_finish(
        conn, scan_id, status="done",
        n_done=n_done, n_intruders=n_intruders,
        n_faces_written=n_faces, n_skipped=n_skipped,
    )
    logger.info(
        "training-scan %s: %d crops, %d intrus, %d faces écrites, %d skips",
        scan_id, n_done, n_intruders, n_faces, n_skipped,
    )
    return ScanSummary(
        n_total=len(crops), n_done=n_done, n_intruders=n_intruders,
        n_faces_written=n_faces, n_skipped=n_skipped,
    )
