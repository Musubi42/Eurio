"""ccproxy_minibench.py — mini-benchmark ccproxy (Claude vision) sur une cohorte.

But (WS5) : valider ccproxy sur un PETIT lot avant d'y verser le volume. Oracle =
les décisions MANUELLES déjà prises par l'admin (pas de re-labellisation) :
- truth='match'    : crop accepté (resolution_status='manual') ET attribué à SA
                     cible (ia.eurio_id == source_images.target_eurio_id).
- truth='no_match' : crop rejeté (resolution_status='rejected') OU réattribué à
                     une autre pièce (ia.eurio_id != target).

On rejoue ccproxy (foundation.claude_review.judge) sur ces crops et on compare au
verdict humain. LECTURE SEULE : aucune écriture en base (ne touche pas
review_claude_verdicts). Échantillon équilibré, capé, 1-2 pièces.

Usage (depuis ml/, PYTHONPATH=.):
  .venv/bin/python scripts/ccproxy_minibench.py --cohort b0299ca0252b --per-truth 5
  .venv/bin/python scripts/ccproxy_minibench.py --coins at-2005-... es-2016-... --per-truth 4 --model sonnet
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="b0299ca0252b")
    ap.add_argument("--coins", nargs="*", default=None,
                    help="restreindre à ces eurio_ids (défaut : auto, les + fournis)")
    ap.add_argument("--per-truth", type=int, default=5,
                    help="nombre de crops par classe de vérité (match / no_match)")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--dry", action="store_true",
                    help="liste l'échantillon + URLs sans appeler Claude (gratuit)")
    args = ap.parse_args()

    from review.review_queue_routes import _canonical_path, _crop_path
    from training.foundation.claude_review import judge

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    coins = json.loads(conn.execute(
        "SELECT eurio_ids_json FROM experiment_cohorts WHERE id=?",
        (args.cohort,)).fetchone()[0])
    scope = args.coins or coins
    inq = ",".join("?" * len(scope))

    # Candidats : décidés par l'admin, crop+canonical résolubles. truth dérivée.
    rows = conn.execute(
        f"""
        SELECT rq.id AS review_id, ia.id AS asset_id, ia.storage_path,
               ia.resolution_status AS rs, ia.eurio_id AS decided_eid,
               si.target_eurio_id AS tgt, si.listing_title,
               c.country_name AS t_country_name, c.year AS t_year,
               c.theme AS t_theme, c.numista_id AS t_numista_id
          FROM review_queue rq
          JOIN image_assets ia ON ia.id = rq.image_asset_id
          JOIN source_images si ON si.id = ia.source_image_id
          LEFT JOIN coins c ON c.eurio_id = si.target_eurio_id
         WHERE si.source='ebay' AND rq.status='done' AND rq.decided_by='admin'
           AND si.target_eurio_id IN ({inq})
           AND ia.resolution_status IN ('manual','rejected')
         ORDER BY rq.decided_at DESC
        """,
        scope,
    ).fetchall()

    def truth_of(r: sqlite3.Row) -> str:
        if r["rs"] == "rejected":
            return "no_match"
        return "match" if r["decided_eid"] == r["tgt"] else "no_match"

    # Échantillon équilibré, capé à --per-truth par vérité.
    buckets: dict[str, list[sqlite3.Row]] = {"match": [], "no_match": []}
    for r in rows:
        t = truth_of(r)
        if len(buckets[t]) >= args.per_truth:
            continue
        canonical = _canonical_path(r["t_numista_id"])
        crop = _crop_path(r["storage_path"]) if r["storage_path"] else None
        if canonical is None or crop is None or not crop.exists():
            continue
        buckets[t].append(r)
    sample = buckets["match"] + buckets["no_match"]
    if not sample:
        print("Aucun crop décidé+résoluble dans le périmètre — élargis --coins.")
        return 1

    if args.dry:
        print(f"[DRY] échantillon ({len(sample)} crops) — URLs (backend :8042) :\n")
        print(f"{'vérité':>9}  {'coin':28} review_id  crop / canonical")
        print("-" * 100)
        for r in sample:
            print(f"{truth_of(r):>9}  {r['tgt'][:28]:28} {r['review_id'][:8]}  "
                  f"crop=http://127.0.0.1:8042/sources/ebay/assets/{r['asset_id']}/file"
                  f"  canon=http://127.0.0.1:8042/images/{r['t_numista_id']}/source")
        return 0

    print(f"Mini-bench ccproxy — modèle={args.model} — {len(sample)} crops "
          f"({len(buckets['match'])} match / {len(buckets['no_match'])} no_match)\n")
    print(f"{'coin':30}{'vérité':>9}{'ccproxy':>9}{'conf':>6}  ok  {'ms':>5}")
    print("-" * 78)

    confusion = {("match", "match"): 0, ("match", "no_match"): 0,
                 ("no_match", "match"): 0, ("no_match", "no_match"): 0}
    n_uncertain = n_error = 0
    cost = 0.0
    for r in sample:
        truth = truth_of(r)
        label_bits = [r["t_country_name"], str(r["t_year"]) if r["t_year"] else None, r["t_theme"]]
        target_label = " · ".join(b for b in label_bits if b) or r["tgt"]
        j = judge(
            crop_path=_crop_path(r["storage_path"]),
            canonical_path=_canonical_path(r["t_numista_id"]),
            target_label=target_label,
            listing_title=r["listing_title"] or "",
            model_alias=args.model,
        )
        cost += j.cost_usd or 0.0
        v = j.verdict or "ERR"
        if j.error and not j.verdict:
            n_error += 1
        elif v == "uncertain":
            n_uncertain += 1
        else:
            confusion[(truth, v)] = confusion.get((truth, v), 0) + 1
        ok = "✓" if v == truth else ("~" if v == "uncertain" else "✗")
        conf = f"{j.confidence:.2f}" if j.confidence is not None else "—"
        print(f"{r['tgt'][:30]:30}{truth:>9}{v:>9}{conf:>6}  {ok}  {j.duration_ms:>5}")

    # Métriques sur les verdicts tranchés (match/no_match), uncertain/error à part.
    tp = confusion[("match", "match")]
    fn = confusion[("match", "no_match")]
    fp = confusion[("no_match", "match")]
    tn = confusion[("no_match", "no_match")]
    decided = tp + fn + fp + tn
    acc = (tp + tn) / decided if decided else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    print("-" * 78)
    print(f"tranchés={decided}  uncertain={n_uncertain}  erreurs={n_error}")
    print(f"confusion  TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"accuracy={acc:.0%}  precision(match)={prec:.0%}  recall(match)={rec:.0%}")
    print(f"coût total ≈ ${cost:.4f}  (modèle {args.model})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
