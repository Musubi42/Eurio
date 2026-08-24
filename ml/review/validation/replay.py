"""Gold de replay — non-régression du verdict d'auto-validation (C2.5).

Fige un set d'assets à vérité connue + leur verdict ACTUEL ("before"). La
fonction de replay recompute le verdict et diffe before↔after — c'est le **gate
de C3** (changement de règle de consensus) : aucune régression non justifiée ne
passe. Tout est quota-free (données déjà en base).

Deux axes orthogonaux par entrée :
  - **label** (vérité terrain) : ``ground_truth_eurio_id`` est posé **ssi** un humain
    a tranché (``review_queue.decided_by='admin'`` + ``decided_eurio_id``). C'est la
    SEULE source fiable — ``resolution_status='manual'`` ne suffit PAS (contaminé par
    l'auto-accept ``decided_by='auto_dino'`` → circulaire). Les assets non décidés-admin
    restent ``ground_truth=None`` (diff-only : couvrent le DIFF before↔after, qui ne
    dépend pas du label, mais ne servent pas d'ancre de correction).
  - **provenance** (``source``) : ``mix_zone_17`` si l'asset vient d'un run de la
    cohorte mix-zone-17 (``cohort_jobs.run_id``), sinon ``human_admin``.

Relabel 2026-06-15 : on n'exige plus une prédiction DINO 2eur_commemo. Le verdict se
calcule même sans (l'expert dino **s'abstient** hors scope) → les **standards
décidés-admin** (jadis droppés par le filtre dino-scope, d'où « standards non
mesurables ») entrent enfin dans le hold-out. ``dino_in_scope`` est porté par entrée
pour que la mesure d'exactitude top1 ne pénalise pas les abstentions légitimes.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from review.review_lanes import verdict_to_lane
from review.validation.experts import collect_signals
from shared.verdict_scope import VERDICT_ANCHORS_KIND, VERDICT_ENCODER_VERSION
from training.foundation.auto_validate import compute_auto_validate_view

_ML_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD = _ML_ROOT / "state" / "validation_gold" / "verdict_gold.jsonl"
MIX_ZONE_17 = "b0299ca0252b"


@dataclass
class GoldEntry:
    asset_id: str
    source: str  # provenance : 'human_admin' | 'mix_zone_17'
    ground_truth_eurio_id: str | None  # posé ssi décidé-admin (label fiable)
    decided_by: str | None
    before_level: str
    before_lane: str
    before_signals: dict  # {expert: label} — snapshot pour audit
    dino_in_scope: bool = False  # a une prédiction DINO 2eur_commemo (défaut: charge anciens golds)


def _dino_scope(
    conn: sqlite3.Connection, *, anchors_kind: str = VERDICT_ANCHORS_KIND,
) -> set[str]:
    """Les assets qui ONT une prédiction dans cette banque.

    Portait `'2eur_commemo'` en dur jusqu'au 2026-08-24 : rejouer le gold sous
    une autre banque mesurait alors l'ANCIEN périmètre et rendait un diff
    rassurant qui ne disait rien. Le paramètre existe pour que le replay puisse
    comparer deux banques dans le même processus.
    """
    return {
        r[0]
        for r in conn.execute(
            "SELECT asset_id FROM image_asset_dino_predictions "
            "WHERE anchors_kind = ?",
            (anchors_kind,),
        )
    }


def _snapshot(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    anchors_kind: str = VERDICT_ANCHORS_KIND,
    encoder_version: str = VERDICT_ENCODER_VERSION,
):
    """(level, lane, {expert: label}, signals) — verdict + experts actuels.

    ⛔ Les DEUX appels doivent recevoir le même couple. `compute_auto_validate_view`
    le prenait déjà ; `collect_signals` non — il retombait sur ses littéraux, et
    le snapshot mélangeait alors deux banques sans rien dire.
    """
    view = compute_auto_validate_view(
        conn, asset_id,
        encoder_version=encoder_version, anchors_kind=anchors_kind,
    )
    lane = verdict_to_lane(view.level)
    signals = collect_signals(
        conn, asset_id,
        encoder_version=encoder_version, anchors_kind=anchors_kind,
    )
    return view.level, lane, {s.expert: s.label for s in signals}, signals


def _mix_zone_assets(conn: sqlite3.Connection, cohort_id: str) -> set[str]:
    """asset_ids issus des runs de la cohorte (``cohort_jobs.run_id``).

    ``cohort_jobs`` = bookkeeping LOCAL (store d'état local) ; ``image_assets``
    reste canonique (``conn``)."""
    from store import local_state_store
    lconn = local_state_store()._connection()  # noqa: SLF001
    runs = [
        r["run_id"]
        for r in lconn.execute(
            "SELECT DISTINCT run_id FROM cohort_jobs WHERE cohort_id=? AND run_id IS NOT NULL",
            (cohort_id,),
        )
    ]
    if not runs:
        return set()
    ph = ",".join("?" * len(runs))
    return {
        r["id"]
        for r in conn.execute(f"SELECT id FROM image_assets WHERE run_id IN ({ph})", runs)
    }


def build_gold(
    conn: sqlite3.Connection,
    *,
    cohort_id: str = MIX_ZONE_17,
    anchors_kind: str = VERDICT_ANCHORS_KIND,
    encoder_version: str = VERDICT_ENCODER_VERSION,
) -> list[GoldEntry]:
    conn.row_factory = sqlite3.Row
    dino = _dino_scope(conn, anchors_kind=anchors_kind)
    mz = _mix_zone_assets(conn, cohort_id)

    # (source, ground_truth, decided_by) par asset. Provenance = mix_zone_17 si
    # l'asset vient d'un run de la cohorte, sinon human_admin.
    def _source(aid: str) -> str:
        return "mix_zone_17" if aid in mz else "human_admin"

    picked: dict[str, tuple[str, str | None, str | None]] = {}

    # 1. LABEL fiable : toute décision admin (commemo ET standard — plus de filtre
    #    dino-scope ; le verdict se calcule même hors ancres, dino s'abstient).
    for r in conn.execute(
        "SELECT image_asset_id AS aid, decided_eurio_id AS e, decided_by AS b "
        "  FROM review_queue "
        " WHERE decided_by='admin' AND decided_eurio_id IS NOT NULL"
    ):
        picked[r["aid"]] = (_source(r["aid"]), r["e"], r["b"])

    # 2. DIFF-ONLY : les assets mix-zone-17 non décidés-admin (label=None). Couvrent
    #    le diff before↔after sur la cohorte vivante ; à relabelliser par review
    #    humaine (cf. worklist) pour devenir vérité terrain.
    for aid in mz:
        if aid not in picked:
            picked[aid] = ("mix_zone_17", None, None)

    gold: list[GoldEntry] = []
    for aid, (source, gt, by) in picked.items():
        level, lane, sig_labels, _ = _snapshot(
            conn, aid, anchors_kind=anchors_kind, encoder_version=encoder_version)
        gold.append(GoldEntry(aid, source, gt, by, level, lane, sig_labels, aid in dino))
    return gold


def relabel_worklist(conn: sqlite3.Connection, *, cohort_id: str = MIX_ZONE_17) -> list[dict]:
    """Assets mix-zone-17 SANS label fiable (non décidés-admin) → à reviewer pour
    grossir le hold-out. Un re-``build_gold`` les capte dès qu'ils sont décidés-admin.

    Trie ``needs_review`` d'abord (vrai travail de relabel), puis les auto/rejected
    (déjà tranchés par une machine — label non fiable mais reviewable)."""
    conn.row_factory = sqlite3.Row
    mz = _mix_zone_assets(conn, cohort_id)
    if not mz:
        return []
    admin = {
        r["image_asset_id"]
        for r in conn.execute(
            "SELECT image_asset_id FROM review_queue "
            "WHERE decided_by='admin' AND decided_eurio_id IS NOT NULL"
        )
    }
    rows = []
    ph = ",".join("?" * len(mz))
    for r in conn.execute(
        f"SELECT id, eurio_id, resolution_status FROM image_assets WHERE id IN ({ph})",
        list(mz),
    ):
        if r["id"] in admin:
            continue  # déjà labellisé fiable
        rows.append(
            {
                "asset_id": r["id"],
                "resolution_status": r["resolution_status"],
                "current_eurio_id": r["eurio_id"],
            }
        )
    order = {"needs_review": 0, "pending_match": 1, "auto_phash": 2, "manual": 3, "rejected": 4}
    rows.sort(key=lambda x: order.get(x["resolution_status"], 9))
    return rows


def save_gold(gold: list[GoldEntry], path: Path = DEFAULT_GOLD) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for g in gold:
            f.write(json.dumps(asdict(g), ensure_ascii=False) + "\n")


def load_gold(path: Path = DEFAULT_GOLD) -> list[GoldEntry]:
    with path.open() as f:
        return [GoldEntry(**json.loads(line)) for line in f if line.strip()]


def replay_gold(
    conn: sqlite3.Connection,
    gold: list[GoldEntry],
    *,
    anchors_kind: str = VERDICT_ANCHORS_KIND,
    encoder_version: str = VERDICT_ENCODER_VERSION,
) -> dict:
    """Recompute le verdict pour chaque entrée et diffe before↔after.

    Retourne le diff (régressions) + une mesure de correction (top1 DINO vs
    vérité terrain) par source — l'ancre que C3 doit améliorer, pas dégrader.
    """
    conn.row_factory = sqlite3.Row
    changes: list[dict] = []
    before_levels, after_levels = Counter(), Counter()
    top1_ok, top1_tot = Counter(), Counter()
    # Le `dino_in_scope` figé dans le gold vaut pour la banque d'ORIGINE. Rejouer
    # sous une autre banque doit remesurer le périmètre, sinon l'exactitude top-1
    # est calculée sur la mauvaise population — sans que rien ne le signale.
    in_scope_now = _dino_scope(conn, anchors_kind=anchors_kind)

    for g in gold:
        level, lane, _labels, signals = _snapshot(
            conn, g.asset_id,
            anchors_kind=anchors_kind, encoder_version=encoder_version)
        before_levels[g.before_level] += 1
        after_levels[level] += 1
        if level != g.before_level or lane != g.before_lane:
            changes.append(
                {
                    "asset_id": g.asset_id,
                    "source": g.source,
                    "before": [g.before_level, g.before_lane],
                    "after": [level, lane],
                }
            )
        dino = next((s for s in signals if s.expert == "dino"), None)
        # Exactitude top1 : seulement sur les labellisés ET in-scope dino — un
        # standard (dino abstient) ne peut pas matcher une ancre commemo, l'inclure
        # déflaterait artificiellement la mesure (le bug « 0/96 » d'origine).
        if g.ground_truth_eurio_id and dino is not None and (
                g.asset_id in in_scope_now):
            top1_tot[g.source] += 1
            if dino.raw.get("top1") == g.ground_truth_eurio_id:
                top1_ok[g.source] += 1

    n_labeled = sum(1 for g in gold if g.ground_truth_eurio_id)
    return {
        "n_gold": len(gold),
        "n_labeled": n_labeled,
        "n_diff_only": len(gold) - n_labeled,
        "anchors_kind": anchors_kind,
        "encoder_version": encoder_version,
        "n_labeled_in_dino_scope": sum(
            1 for g in gold
            if g.ground_truth_eurio_id and g.asset_id in in_scope_now
        ),
        "by_source": dict(Counter(g.source for g in gold)),
        "before_level_dist": dict(before_levels),
        "after_level_dist": dict(after_levels),
        "n_changes": len(changes),
        "changes": changes,
        "dino_top1_eq_ground_truth": {
            src: {
                "ok": top1_ok[src],
                "of": top1_tot[src],
                "pct": round(100 * top1_ok[src] / top1_tot[src], 1)
                if top1_tot[src]
                else None,
            }
            for src in top1_tot
        },
    }
