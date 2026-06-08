"""Gold de replay — non-régression du verdict d'auto-validation (C2.5).

Fige un set d'assets à vérité connue + leur verdict ACTUEL ("before"). La
fonction de replay recompute le verdict et diffe before↔after — c'est le **gate
de C3** (changement de règle de consensus) : aucune régression non justifiée ne
passe. Tout est quota-free (données déjà en base).

Sources :
  - ``human_admin`` : assets décidés à la main (``review_queue.decided_by='admin'``
    + ``decided_eurio_id``) → **label fiable** = la décision humaine. C'est l'ancre
    de correction (dino top1 == vérité).
  - ``mix_zone_17`` : cohorte (``experiment_cohorts``) → **diff-only, sans label**.
    Le lien ``run_id → cohort_jobs.target_eurio_id`` ne partitionne PAS proprement
    (cohort_members vide ; un run mélange des cibles ; certaines cibles sont des
    *standards* hors espace d'ancres commemo). Vérifié 2026-06-08 : 0/96 top1==cible.
    On garde ces assets pour élargir la couverture du DIFF before↔after (qui ne
    dépend pas du label), mais on ne leur fait PAS confiance comme vérité terrain.
Restreint aux assets avec une prédiction DINO 2eur_commemo (verdict calculable) ;
``human_admin`` est prioritaire si un asset est dans les deux.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from review.review_lanes import verdict_to_lane
from review.validation.experts import collect_signals
from training.foundation.auto_validate import compute_auto_validate_view

_ML_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD = _ML_ROOT / "state" / "validation_gold" / "verdict_gold.jsonl"
MIX_ZONE_17 = "b0299ca0252b"


@dataclass
class GoldEntry:
    asset_id: str
    source: str
    ground_truth_eurio_id: str | None
    decided_by: str | None
    before_level: str
    before_lane: str
    before_signals: dict  # {expert: label} — snapshot pour audit


def _dino_scope(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT asset_id FROM image_asset_dino_predictions "
            "WHERE anchors_kind='2eur_commemo'"
        )
    }


def _snapshot(conn: sqlite3.Connection, asset_id: str):
    """(level, lane, {expert: label}, signals) — verdict + experts actuels."""
    view = compute_auto_validate_view(conn, asset_id)
    lane = verdict_to_lane(view.level)
    signals = collect_signals(conn, asset_id)
    return view.level, lane, {s.expert: s.label for s in signals}, signals


def build_gold(conn: sqlite3.Connection, *, cohort_id: str = MIX_ZONE_17) -> list[GoldEntry]:
    conn.row_factory = sqlite3.Row
    dino = _dino_scope(conn)

    picked: dict[str, tuple[str, str | None, str | None]] = {}
    for r in conn.execute(
        "SELECT image_asset_id AS aid, decided_eurio_id AS e, decided_by AS b "
        "  FROM review_queue "
        " WHERE decided_by='admin' AND decided_eurio_id IS NOT NULL"
    ):
        if r["aid"] in dino:
            picked[r["aid"]] = ("human_admin", r["e"], r["b"])

    run_targets = {
        r["run_id"]: r["target_eurio_id"]
        for r in conn.execute(
            "SELECT run_id, target_eurio_id FROM cohort_jobs "
            "WHERE cohort_id=? AND run_id IS NOT NULL",
            (cohort_id,),
        )
    }
    if run_targets:
        ph = ",".join("?" * len(run_targets))
        for r in conn.execute(
            f"SELECT id, run_id FROM image_assets WHERE run_id IN ({ph})",
            list(run_targets),
        ):
            if r["id"] in dino and r["id"] not in picked:  # human prioritaire
                # gt=None : le label cohorte (run_id→target) n'est pas fiable
                # (cf. docstring). Diff-only — pas d'ancre de correction.
                picked[r["id"]] = ("mix_zone_17", None, None)

    gold: list[GoldEntry] = []
    for aid, (source, gt, by) in picked.items():
        level, lane, sig_labels, _ = _snapshot(conn, aid)
        gold.append(GoldEntry(aid, source, gt, by, level, lane, sig_labels))
    return gold


def save_gold(gold: list[GoldEntry], path: Path = DEFAULT_GOLD) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for g in gold:
            f.write(json.dumps(asdict(g), ensure_ascii=False) + "\n")


def load_gold(path: Path = DEFAULT_GOLD) -> list[GoldEntry]:
    with path.open() as f:
        return [GoldEntry(**json.loads(line)) for line in f if line.strip()]


def replay_gold(conn: sqlite3.Connection, gold: list[GoldEntry]) -> dict:
    """Recompute le verdict pour chaque entrée et diffe before↔after.

    Retourne le diff (régressions) + une mesure de correction (top1 DINO vs
    vérité terrain) par source — l'ancre que C3 doit améliorer, pas dégrader.
    """
    conn.row_factory = sqlite3.Row
    changes: list[dict] = []
    before_levels, after_levels = Counter(), Counter()
    top1_ok, top1_tot = Counter(), Counter()

    for g in gold:
        level, lane, _labels, signals = _snapshot(conn, g.asset_id)
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
        if g.ground_truth_eurio_id and dino is not None:
            top1_tot[g.source] += 1
            if dino.raw.get("top1") == g.ground_truth_eurio_id:
                top1_ok[g.source] += 1

    return {
        "n_gold": len(gold),
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
