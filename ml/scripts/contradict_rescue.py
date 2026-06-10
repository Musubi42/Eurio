"""Mesure du rescue des ex-contradicts TUÉS par le gate (gate C3, §6/§8 du doc).

Les listings ``text=contradict`` sont tués à l'étape 2.5
(``sources/_base/steps/text_signal.py::_apply_text_contradict_rejections`` →
``discarded_listings(reason='text_contradict_*')``, download sauté). Le gold de
replay (``verdict_gold.py``) est **post-gate** → ces tués n'y figurent pas. Ce
script ferme le trou : il rejoue à travers ``collect_signals → consensus_verdict``
(C3) les ex-contradicts qui ont **déjà un crop** (les autres exigeraient un
detect+crop), **SANS rien écrire**, et rapporte combien seraient sauvés en
``needs_review`` vs confirmés en ``reject`` (dual_contradict, in-scope only).

Lecture seule. Réutilise les mêmes briques que ``verdict_gold.py``
(``review.validation.{experts,consensus}``). À relancer après un detect+crop des
~338 restants pour étendre la couverture (le funnel ci-dessous chiffre le gap).

    python scripts/contradict_rescue.py            # rapport complet
    python scripts/contradict_rescue.py --limit 0  # sans le dump spot-check
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

from review.validation.consensus import consensus_verdict
from review.validation.experts import collect_signals

_DB = Path(__file__).resolve().parents[1] / "state" / "eurio.db"

# Crops issus d'un listing tué pour text_contradict_* : on remonte
# discarded_listings → source_images (clé source+source_ref) → image_assets.
# La reason porte l'axe (year/country) ; le titre vient du source_image.
_SQL_CROPS = """
SELECT ia.id              AS asset_id,
       d.reason           AS reason,
       d.target_eurio_id  AS target,
       si.listing_title   AS title,
       ia.resolution_status AS res_status
  FROM discarded_listings d
  JOIN source_images si
    ON si.source = d.source AND si.source_ref = d.source_ref
  JOIN image_assets ia
    ON ia.source_image_id = si.id
 WHERE d.reason LIKE 'text_contradict_%'
 ORDER BY d.reason, ia.id
"""


def _funnel(conn: sqlite3.Connection) -> dict:
    """Le tonneau 424 → source_image → crop → dino, pour chiffrer le gap."""
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    base = "FROM discarded_listings d WHERE d.reason LIKE 'text_contradict_%'"
    join_si = (
        "FROM discarded_listings d "
        "JOIN source_images si ON si.source=d.source AND si.source_ref=d.source_ref "
        "WHERE d.reason LIKE 'text_contradict_%'"
    )
    join_ia = (
        "FROM discarded_listings d "
        "JOIN source_images si ON si.source=d.source AND si.source_ref=d.source_ref "
        "JOIN image_assets ia ON ia.source_image_id=si.id "
        "WHERE d.reason LIKE 'text_contradict_%'"
    )
    join_dino = join_ia + (
        " AND EXISTS (SELECT 1 FROM image_asset_dino_predictions p "
        "WHERE p.asset_id=ia.id AND p.anchors_kind='2eur_commemo')"
    )
    return {
        "discards_total": q(f"SELECT COUNT(*) {base}"),
        "by_axis": dict(
            conn.execute(
                f"SELECT d.reason, COUNT(*) {base} GROUP BY d.reason"
            ).fetchall()
        ),
        "with_source_image": q(f"SELECT COUNT(DISTINCT d.id) {join_si}"),
        "with_crop_listings": q(f"SELECT COUNT(DISTINCT d.id) {join_ia}"),
        "with_crop_assets": q(f"SELECT COUNT(DISTINCT ia.id) {join_ia}"),
        "with_dino_assets": q(f"SELECT COUNT(DISTINCT ia.id) {join_dino}"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=_DB)
    ap.add_argument(
        "--limit", type=int, default=40,
        help="nb de lignes spot-check à dumper (0 = aucun)",
    )
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    fn = _funnel(conn)
    print("=== FUNNEL (couverture mesurable) ===")
    print(f"  text_contradict_* discards : {fn['discards_total']}  {fn['by_axis']}")
    print(f"  → avec source_image        : {fn['with_source_image']}")
    print(f"  → avec crop (listings)     : {fn['with_crop_listings']}")
    print(f"  → avec crop (image_assets) : {fn['with_crop_assets']}  ← set mesuré ici")
    print(f"  → avec crop + DINO commemo : {fn['with_dino_assets']}")
    gap = fn["discards_total"] - fn["with_crop_listings"]
    print(f"  GAP (detect+crop requis avant mesure) : ~{gap} listings")

    rows = conn.execute(_SQL_CROPS).fetchall()
    outcomes: Counter = Counter()
    by_rule: Counter = Counter()
    by_axis_outcome: Counter = Counter()
    by_scope: Counter = Counter()
    outcome_vs_status: Counter = Counter()
    rejects: list[dict] = []
    rescues: list[dict] = []

    for r in rows:
        axis = r["reason"].replace("text_contradict_", "")
        signals = collect_signals(conn, r["asset_id"])
        if not signals:  # asset introuvable / non résolu — abstention
            outcomes["no_signals"] += 1
            continue
        cv = consensus_verdict(signals)
        dino = next((s for s in signals if s.expert == "dino"), None)
        in_scope = bool(dino and dino.raw.get("in_scope"))
        outcomes[cv.outcome] += 1
        by_rule[cv.rule] += 1
        by_axis_outcome[(axis, cv.outcome)] += 1
        by_scope[("in_scope" if in_scope else "out_of_scope", cv.outcome)] += 1
        outcome_vs_status[(r["res_status"], cv.outcome)] += 1

        rec = {
            "asset_id": r["asset_id"],
            "axis": axis,
            "target": r["target"],
            "title": (r["title"] or "")[:70],
            "rule": cv.rule,
            "outcome": cv.outcome,
            "dino_top1": dino.raw.get("top1") if dino else None,
            "dino_sim": dino.raw.get("sim") if dino else None,
            "dino_label": dino.label if dino else None,
            "in_scope": in_scope,
            "res_status": r["res_status"],
        }
        if cv.outcome == "reject":
            rejects.append(rec)
        elif cv.outcome == "needs_review":
            rescues.append(rec)

    print("\n=== VERDICTS CONSENSUS (sans écriture) ===")
    print(f"  n crops évalués : {sum(outcomes.values())}")
    print(f"  outcomes        : {dict(outcomes)}")
    print(f"  par règle       : {dict(by_rule)}")
    axis_str = ", ".join(f"{a}/{o}:{c}" for (a, o), c in sorted(by_axis_outcome.items()))
    scope_str = ", ".join(f"{s}/{o}:{c}" for (s, o), c in sorted(by_scope.items()))
    print(f"  par axe×outcome : {axis_str}")
    print(f"  par scope       : {scope_str}")
    print("  outcome vs resolution_status actuel :")
    for (st, o), c in sorted(outcome_vs_status.items()):
        print(f"    {st or 'NULL':<14} → {o:<13} : {c}")

    print(f"\n=== REJETS confirmés (dual_contradict, {len(rejects)}) ===")
    for rec in rejects:
        print(
            f"  [{rec['axis']}] {rec['asset_id'][:14]} target={rec['target']} "
            f"dino={rec['dino_label']}/{rec['dino_top1']}@{rec['dino_sim']} "
            f"scope={rec['in_scope']} | {rec['title']!r}"
        )

    if args.limit:
        print(f"\n=== SPOT-CHECK rescues → needs_review (≤{args.limit}) ===")
        for rec in rescues[: args.limit]:
            print(
                f"  [{rec['axis']}] {rec['rule']:<22} "
                f"target={rec['target']} dino={rec['dino_label']}/{rec['dino_top1']} "
                f"status={rec['res_status']} | {rec['title']!r}"
            )


if __name__ == "__main__":
    main()
