"""Scan Dino du Jeu d'entraînement d'une cohorte (improvement-loop P1+P2).

Pour chaque crop **affiché au triage** (validés, needs_review, exclus,
rejetés — mêmes statuts que le panneau), un seul encodage DINOv2 vitl14
alimente deux verdicts :

- **P1 · intrus (ensemble fermé + consensus intra-classe).** Le crop est
  classé contre les SEULES classes de la cohorte, à la maille classe
  (``COALESCE(design_group_id, eurio_id)``). La similarité d'une classe est
  ``max(ancre canonique, consensus)`` où le **consensus** est le centroïde
  des crops éligibles avers de la classe (leave-one-out pour le crop jugé,
  ≥ ``MIN_CONSENSUS_CROPS`` contributeurs). Raison d'être du consensus :
  l'ancre canonique est UNE photo studio — sur un design sombre/bas-relief
  (ex. Kniefall de-2020) les photos eBay réelles ne la matchent qu'à ~0.4-0.6
  et des designs voisins passaient devant → faux positifs. Un crop cohérent
  avec ses camarades de classe n'est jamais flagué ; un intrus minoritaire
  reste loin du centroïde et l'est toujours. Si le top-1 Dino est une AUTRE
  classe avec marge ≥ ``intruder_margin`` → « probable intrus » ; l'UI le
  remonte en tête, l'humain tranche (réassignation / rescue d'un rejeté).
- **P2 · face.** Verdict obverse/reverse via la banque revers C7
  (``_decide_face``, τ benché) écrit sur ``image_assets.face`` UNIQUEMENT
  quand la face est NULL ou 'unknown' — jamais par-dessus un label
  obverse/reverse existant (humain, Claude ou run précédent).

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

# Contributeurs minimum au centroïde de consensus (après leave-one-out).
# En-dessous, la classe n'a pas assez de crops validés pour définir son
# « allure réelle » → on retombe sur l'ancre canonique seule. Garde-fou :
# avec 2-3 crops, deux intrus jumeaux se « valideraient » mutuellement.
MIN_CONSENSUS_CROPS = 3

# ── Détection d'outlier intra-classe (2ᵉ signal d'intrus) ────────────────────
# Le signal « marge » ne voit que les intrus qu'une AUTRE classe de la cohorte
# réclame. Un intrus dont la vraie classe est HORS cohorte (mesuré : Brandenburg
# étiqueté de-2020-gpr — Brandenburg n'est pas dans mix-zone-17) n'est réclamé
# par personne → marge ~0. Mais il reste un OUTLIER parmi ses camarades :
# sur mix-zone-17, sims LOO au centroïde = Kniefall corrects 0.77-0.90 vs
# Brandenburg intrus 0.61-0.66. Verdict : sim < médiane − K·MAD (stats robustes
# des membres éligibles) ET sim < CAP (évite de flaguer l'excentrique d'une
# classe ultra-cohésive). Appliqué aux seuls membres éligibles (protéger le
# train) sur ≥ MIN_OUTLIER_MEMBERS membres, avec un centroïde RAFFINÉ (une
# passe de purge des outliers) pour dé-contaminer la moyenne.
OUTLIER_MAD_K = 3.5
OUTLIER_MIN_MAD = 0.02
OUTLIER_SIM_CAP = 0.75
MIN_OUTLIER_MEMBERS = 5

# Statuts affichés au triage = périmètre du scan (aligné sur le panneau
# training-crops — serving/lab_routes importe cette constante). On scanne
# aussi les rejetés/needs_review : badge cohérent partout + rescue (un rejeté
# qui est en fait une autre pièce de la cohorte devient réassignable).
TRIAGE_STATUSES = ("auto_name", "auto_phash", "manual", "needs_review", "rejected")

_RESULTS_BATCH = 128
_PROGRESS_EVERY = 8


@dataclass
class ScanSummary:
    n_total: int
    n_done: int
    n_intruders: int
    n_faces_written: int
    n_skipped: int


@dataclass
class CropForVerdict:
    """Entrée du verdict closed-set (pure, testable sans torch) : un crop
    encodé + son contexte. ``effective_face`` = label existant sinon verdict
    P2 du scan."""

    asset_id: str
    assigned_class: str
    eligible: bool
    effective_face: str | None
    face_verdict: str | None = None
    face_written: bool = False


def compute_closed_set_verdicts(
    crops: list[CropForVerdict],
    vecs: np.ndarray,
    *,
    class_anchor_rows: dict[str, list[tuple[int, str]]],
    bank_matrix: np.ndarray,
    intruder_margin: float,
    min_consensus: int = MIN_CONSENSUS_CROPS,
) -> list[ScanResultRow]:
    """Cœur P1, pur numpy (testable offline) — verdict intrus par crop.

    ``vecs`` : (N, D) L2-normalisés, alignés sur ``crops``. La sim d'une
    classe = max(meilleure ancre canonique, consensus centroïde RAFFINÉ des
    crops éligibles avers de la classe, leave-one-out pour le crop jugé).
    Deux raisons de badge : ``margin`` (une autre classe de la cohorte le
    réclame) et ``outlier`` (il ne ressemble pas à ses camarades — attrape
    les intrus dont la vraie classe est hors cohorte).
    """
    if not crops:
        return []
    anchor_sims = vecs @ bank_matrix.T  # (N, A)

    # Membres de consensus : crops éligibles avers, par classe.
    idx_by_class: dict[str, list[int]] = {}
    for i, c in enumerate(crops):
        if c.eligible and c.effective_face != "reverse":
            idx_by_class.setdefault(c.assigned_class, []).append(i)

    def _loo_sims(members: list[int]) -> dict[int, float]:
        """Sim de chaque membre au centroïde de SES camarades (LOO)."""
        total = vecs[members].sum(axis=0)
        out: dict[int, float] = {}
        n = len(members)
        if n - 1 < 1:
            return out
        for i in members:
            rest = total - vecs[i]
            norm = float(np.linalg.norm(rest))
            if norm > 0.0:
                out[i] = float((rest / norm) @ vecs[i])
        return out

    # ── Purge des outliers (une passe) + stats robustes par classe ──
    # Le centroïde brut est contaminé par les intrus qu'il contient (mesuré :
    # 3 Brandenburg dans les 20 de de-2020 → leur sim mutuelle les sauvait).
    # On détecte les outliers sur les sims LOO (médiane − K·MAD, sous CAP),
    # puis le centroïde RAFFINÉ (sans eux) sert au consensus final.
    outlier_ids: set[str] = set()
    refined_by_class: dict[str, list[int]] = {}
    for cid, members in idx_by_class.items():
        refined = members
        if len(members) >= MIN_OUTLIER_MEMBERS:
            sims = _loo_sims(members)
            vals = np.array(list(sims.values()))
            med = float(np.median(vals))
            mad = max(float(np.median(np.abs(vals - med))), OUTLIER_MIN_MAD)
            threshold = min(med - OUTLIER_MAD_K * mad, OUTLIER_SIM_CAP)
            flagged = [i for i in members if sims.get(i, 1.0) < threshold]
            if flagged and len(members) - len(flagged) >= min_consensus:
                outlier_ids.update(crops[i].asset_id for i in flagged)
                refined = [i for i in members if i not in flagged]
        refined_by_class[cid] = refined
    refined_sum = {
        cid: vecs[idx].sum(axis=0) for cid, idx in refined_by_class.items()
    }

    def _consensus_sim(i: int, cid: str) -> float | None:
        members = refined_by_class.get(cid)
        if not members:
            return None
        total = refined_sum[cid]
        n = len(members)
        if i in members:  # leave-one-out : le crop ne se valide pas lui-même
            total = total - vecs[i]
            n -= 1
        if n < min_consensus:
            return None
        norm = float(np.linalg.norm(total))
        if norm == 0.0:
            return None
        return float((total / norm) @ vecs[i])

    out: list[ScanResultRow] = []
    for i, c in enumerate(crops):
        assigned_anchor: float | None = None
        assigned_consensus: float | None = None
        assigned_sim: float | None = None
        top1_class = None
        top1_eurio_id = None
        top1_sim: float | None = None
        for cid, rows in class_anchor_rows.items():
            a_sim: float | None = None
            a_eid: str | None = None
            for j, eid in rows:
                s = float(anchor_sims[i, j])
                if a_sim is None or s > a_sim:
                    a_sim, a_eid = s, eid
            c_sim = _consensus_sim(i, cid)
            cls_sim = max(
                (s for s in (a_sim, c_sim) if s is not None), default=None,
            )
            if cid == c.assigned_class:
                assigned_anchor, assigned_consensus = a_sim, c_sim
                assigned_sim = cls_sim
            if cls_sim is not None and (top1_sim is None or cls_sim > top1_sim):
                # Cible de réassignation = le membre à la meilleure ancre
                # (fallback : classe sans ancre gagnante par consensus → None).
                top1_class, top1_eurio_id, top1_sim = cid, a_eid, cls_sim
        margin = (
            top1_sim - assigned_sim
            if (top1_sim is not None and assigned_sim is not None)
            else None
        )
        judgeable = c.effective_face != "reverse"
        by_margin = bool(
            judgeable
            and margin is not None
            and top1_class is not None
            and top1_class != c.assigned_class
            and margin >= intruder_margin
        )
        by_outlier = judgeable and c.asset_id in outlier_ids
        reason = (
            "margin+outlier" if (by_margin and by_outlier)
            else "margin" if by_margin
            else "outlier" if by_outlier
            else None
        )
        out.append(ScanResultRow(
            asset_id=c.asset_id,
            assigned_class=c.assigned_class,
            assigned_sim=assigned_sim,
            anchor_sim=assigned_anchor,
            consensus_sim=assigned_consensus,
            top1_class=top1_class,
            top1_eurio_id=top1_eurio_id,
            top1_sim=top1_sim,
            margin=margin,
            is_intruder=by_margin or by_outlier,
            intruder_reason=reason,
            face_verdict=c.face_verdict,
            face_written=c.face_written,
        ))
    return out


def _class_descriptors(store, cohort) -> list:
    """Descriptors (class_id, eurio_ids) des classes de la cohorte — même
    resolver que le bake et training-crops (maille design_group)."""
    from training.eval.class_resolver import build_resolver

    resolver = build_resolver(force_eurio_id=False, db_path=store.db_path)
    descriptors, _unresolved = resolver.classes_for_eurio_ids(cohort.eurio_ids)
    return descriptors


def _scope_sql_and_params(members: list[str]) -> tuple[str, list]:
    member_ph = ",".join("?" for _ in members)
    status_ph = ",".join("?" for _ in TRIAGE_STATUSES)
    sql = f"""
        SELECT a.id, a.eurio_id, a.face, a.training_eligible, a.storage_path
          FROM image_assets a
          JOIN source_images s ON s.id = a.source_image_id
         WHERE s.source = 'ebay'
           AND a.eurio_id IN ({member_ph})
           AND a.resolution_status IN ({status_ph})
           AND a.storage_status = 'present'
         ORDER BY a.eurio_id, a.id
    """
    return sql, [*members, *TRIAGE_STATUSES]


def scan_scope_count(store, cohort) -> int:
    """Nombre de crops dans le scope du scan (n_total de la barre de
    progression) — mêmes filtres que ``run_training_set_scan`` (= le panneau)."""
    descriptors = _class_descriptors(store, cohort)
    members = [eid for d in descriptors for eid in d.eurio_ids]
    if not members:
        return 0
    conn = store._connection()  # noqa: SLF001
    sql, params = _scope_sql_and_params(members)
    return conn.execute(
        f"SELECT COUNT(*) FROM ({sql})", params,  # noqa: S608 — placeholders
    ).fetchone()[0]


def run_training_set_scan(
    store,
    cohort_id: str,
    scan_id: str,
    *,
    intruder_margin: float = DEFAULT_INTRUDER_MARGIN,
) -> ScanSummary:
    """Boucle du scan — le scan ``scan_id`` est déjà ouvert (status='running').

    Deux passes : (1) encoder tous les crops du scope + résoudre la face
    (P2, écrite au fil de l'eau) ; (2) verdict intrus closed-set + consensus
    (pur numpy, ``compute_closed_set_verdicts``). Clôt le scan (done) ;
    l'appelant CLI persiste ``failed`` sur exception.
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
            "training-scan %s: %d classe(s) sans ancre dans %s (%s) — "
            "leur sim d'ancre est absente (le consensus peut compenser)",
            scan_id, len(classes_without_anchor), SUGGESTIONS_ANCHORS_KIND,
            ", ".join(classes_without_anchor),
        )

    members = list(class_of_member)
    rows: list = []
    if members:
        sql, params = _scope_sql_and_params(members)
        rows = conn.execute(sql, params).fetchall()

    # ── Passe 1 : encodage + face (P2) ────────────────────────────────────
    n_done = 0
    n_faces = 0
    n_skipped = 0
    crops: list[CropForVerdict] = []
    vec_list: list[np.ndarray] = []
    for r in rows:
        aid = r["id"]
        try:
            crop_p = local_path("enrichment-crops", r["storage_path"])
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

        face_verdict: str | None = None
        face_written = False
        if rev_bank is not None:
            obverse_sim = float(np.max(bank.matrix @ vec))
            rev_sim = float(np.max(rev_bank.matrix @ vec))
            face_verdict = _decide_face(rev_sim, obverse_sim)
            if r["face"] is None or r["face"] == "unknown":
                cur = conn.execute(
                    "UPDATE image_assets SET face=? WHERE id=? "
                    "AND (face IS NULL OR face='unknown')",
                    (face_verdict, aid),
                )
                if cur.rowcount:
                    face_written = True
                    n_faces += 1

        crops.append(CropForVerdict(
            asset_id=aid,
            assigned_class=class_of_member[r["eurio_id"]],
            eligible=bool(r["training_eligible"]),
            effective_face=r["face"] or face_verdict,
            face_verdict=face_verdict,
            face_written=face_written,
        ))
        vec_list.append(vec)
        n_done += 1
        if n_done % _PROGRESS_EVERY == 0:
            training_scan_progress(conn, scan_id, n_done=n_done)

    # ── Passe 2 : verdict intrus (closed-set + consensus, pur numpy) ─────
    results = compute_closed_set_verdicts(
        crops,
        np.stack(vec_list) if vec_list else np.zeros((0, bank.matrix.shape[1])),
        class_anchor_rows=class_anchor_rows,
        bank_matrix=bank.matrix,
        intruder_margin=intruder_margin,
    )
    # Compteur du scan = intrus AU TRAIN (ce qui pollue le modèle). Les flags
    # sur les needs_review/rejetés restent en base (rescue via les filtres).
    n_intruders = sum(
        1 for c, x in zip(crops, results) if x.is_intruder and c.eligible
    )
    for start in range(0, len(results), _RESULTS_BATCH):
        training_scan_upsert_results(
            conn, scan_id, results[start:start + _RESULTS_BATCH],
        )

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
        n_total=len(rows), n_done=n_done, n_intruders=n_intruders,
        n_faces_written=n_faces, n_skipped=n_skipped,
    )
