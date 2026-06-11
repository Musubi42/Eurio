"""Phase 0 — Audit chiffré des suggestions Dino (lecture seule).

Construit le set labellisé à partir des décisions de review
(`review_queue.status='done'` avec `decided_eurio_id`) et mesure, contre
les prédictions persistées dans `image_asset_dino_predictions` :

  - couverture de scope : % de crops dont la vraie pièce est dans la
    banque d'ancres (P1) ;
  - recall@1 / @5 du ranking global, de la bande pays, et de la vue UI
    (bande pays d'abord, global en fallback) (P2) ;
  - distribution des sims top1 vraies vs fausses + spread (P3/P5) ;
  - segmentation : commémo vs courante, pays vérité == pays cible ou
    non, face décidée, qualité/taille du crop.

Aucune écriture : le script ne touche ni la DB ni la banque.

Usage:
    .venv/bin/python -m scripts.audit_dino_suggestions
    .venv/bin/python -m scripts.audit_dino_suggestions --out report.md
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from training.foundation.anchors import (  # noqa: E402
    encoder_version_for_kind,
    load_anchors,
)

DB_PATH = ML_DIR / "state" / "eurio.db"


@dataclass
class LabeledCrop:
    asset_id: str
    truth_eurio_id: str
    truth_is_commemo: bool | None  # None = pièce inconnue de coins
    decided_face: str | None
    target_country: str | None  # ISO2 du listing (target_eurio_id)
    truth_country: str
    width: int | None
    quality_score: float | None
    listing_title: str | None
    # Prédiction (None si aucune ligne persistée)
    top_k: list[dict] | None
    top_k_country: list[dict] | None
    top1_sim: float | None
    spread: float | None
    in_bank: bool = False


def _load_labeled(
    conn: sqlite3.Connection, anchors_kind: str
) -> list[LabeledCrop]:
    rows = conn.execute(
        """
        SELECT rq.image_asset_id AS asset_id,
               rq.decided_eurio_id,
               rq.decided_face,
               c.is_commemorative,
               a.width, a.quality_score,
               s.target_eurio_id, s.listing_title,
               p.top_k_json, p.top_k_country_json, p.top1_sim, p.spread
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
     LEFT JOIN coins c ON c.eurio_id = rq.decided_eurio_id
     LEFT JOIN image_asset_dino_predictions p
            ON p.asset_id = rq.image_asset_id
           AND p.anchors_kind = ?
           AND p.encoder_version = ?
         WHERE rq.status = 'done' AND rq.decided_eurio_id IS NOT NULL
        """,
        (anchors_kind, encoder_version_for_kind(anchors_kind)),
    ).fetchall()
    out: list[LabeledCrop] = []
    for r in rows:
        target_eid = r["target_eurio_id"]
        out.append(
            LabeledCrop(
                asset_id=r["asset_id"],
                truth_eurio_id=r["decided_eurio_id"],
                truth_is_commemo=(
                    bool(r["is_commemorative"])
                    if r["is_commemorative"] is not None
                    else None
                ),
                decided_face=r["decided_face"],
                target_country=(
                    target_eid[:2].lower()
                    if target_eid and len(target_eid) >= 2
                    else None
                ),
                truth_country=r["decided_eurio_id"][:2].lower(),
                width=r["width"],
                quality_score=r["quality_score"],
                listing_title=r["listing_title"],
                top_k=json.loads(r["top_k_json"]) if r["top_k_json"] else None,
                top_k_country=(
                    json.loads(r["top_k_country_json"])
                    if r["top_k_country_json"]
                    else None
                ),
                top1_sim=r["top1_sim"],
                spread=r["spread"],
            )
        )
    return out


def _standard_rep_map(conn: sqlite3.Connection) -> dict[str, str]:
    """eurio_id de 2€ courante → eurio_id du REPRÉSENTANT de son design group
    (plus ancien millésime — même convention que la banque d'ancres et que
    ``_fetch_standard_candidates`` côté review). Les décisions de review
    peuvent porter n'importe quel membre du groupe ; la banque ne contient
    que le représentant → comparer au niveau du groupe."""
    rows = conn.execute(
        """
        SELECT c.eurio_id,
               COALESCE(c.design_group_id, c.eurio_id) AS class_id
          FROM coins c
         WHERE c.face_value = 2.0 AND c.is_commemorative = 0
         ORDER BY c.year ASC, c.eurio_id ASC
        """
    ).fetchall()
    rep_by_class: dict[str, str] = {}
    out: dict[str, str] = {}
    for r in rows:
        rep_by_class.setdefault(r["class_id"], r["eurio_id"])
        out[r["eurio_id"]] = rep_by_class[r["class_id"]]
    return out


def _rank_of(truth: str, top_k: list[dict] | None) -> int | None:
    """Rang 1-based de la vérité dans le top-K, None si absente."""
    if not top_k:
        return None
    for i, m in enumerate(top_k):
        if m["eurio_id"] == truth:
            return i + 1
    return None


def _ui_top_k(crop: LabeledCrop) -> list[dict] | None:
    """Liste telle que vue par le reviewer : bande pays d'abord, sinon global."""
    return crop.top_k_country if crop.top_k_country else crop.top_k


def _pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "—"


def _quantiles(vals: list[float]) -> str:
    if not vals:
        return "—"
    vs = sorted(vals)

    def q(p: float) -> float:
        i = min(int(p * (len(vs) - 1)), len(vs) - 1)
        return vs[i]

    return (
        f"n={len(vs)} min={vs[0]:.3f} p25={q(0.25):.3f} med={q(0.5):.3f} "
        f"p75={q(0.75):.3f} max={vs[-1]:.3f}"
    )


def _recall_line(label: str, crops: list[LabeledCrop]) -> str:
    """Recall@1/@5 global, bande pays et vue UI sur un segment."""
    n = len(crops)
    if not n:
        return f"| {label} | 0 | — | — | — | — | — | — |"
    g1 = sum(1 for c in crops if _rank_of(c.truth_eurio_id, c.top_k) == 1)
    g5 = sum(1 for c in crops if _rank_of(c.truth_eurio_id, c.top_k) is not None)
    cc = [c for c in crops if c.top_k_country]
    c1 = sum(1 for c in cc if _rank_of(c.truth_eurio_id, c.top_k_country) == 1)
    c5 = sum(1 for c in cc if _rank_of(c.truth_eurio_id, c.top_k_country) is not None)
    u1 = sum(1 for c in crops if _rank_of(c.truth_eurio_id, _ui_top_k(c)) == 1)
    u5 = sum(1 for c in crops if _rank_of(c.truth_eurio_id, _ui_top_k(c)) is not None)
    band = f"{_pct(c1, len(cc))} / {_pct(c5, len(cc))} (n={len(cc)})"
    return (
        f"| {label} | {n} | {_pct(g1, n)} | {_pct(g5, n)} | {band} "
        f"| {_pct(u1, n)} | {_pct(u5, n)} |"
    )


RECALL_HEADER = (
    "| Segment | n | global@1 | global@5 | bande pays @1/@5 | UI@1 | UI@5 |\n"
    "|---|---|---|---|---|---|---|"
)


def build_report(conn: sqlite3.Connection, anchors_kind: str) -> str:
    bank = load_anchors(anchors_kind)
    if bank is None:
        raise RuntimeError(
            f"Banque d'ancres {anchors_kind} introuvable — lancer "
            "`go-task ml:dino-anchors:build`"
        )
    bank_ids = set(bank.eurio_ids)

    crops = _load_labeled(conn, anchors_kind)
    # Vérité des courantes normalisée au représentant de design group (la
    # banque n'ancre que lui) — sans ça, une décision posée sur un autre
    # membre du groupe compte à tort comme hors-scope / mismatch.
    rep_map = _standard_rep_map(conn)
    for c in crops:
        c.truth_eurio_id = rep_map.get(c.truth_eurio_id, c.truth_eurio_id)
        c.in_bank = c.truth_eurio_id in bank_ids

    lines: list[str] = []
    add = lines.append
    add("# Phase 0 — Audit suggestions Dino")
    add("")
    add(f"- Banque : `{bank.anchors_kind}` — {bank.count} ancres, "
        f"encodeur `{bank.encoder_version}`, bâtie le {bank.built_at}")
    add(f"- Set labellisé : {len(crops)} crops décidés en review "
        f"(`review_queue.status='done'` + `decided_eurio_id`)")
    no_pred = [c for c in crops if c.top_k is None]
    add(f"- Sans prédiction Dino persistée : {len(no_pred)} "
        f"({_pct(len(no_pred), len(crops))})")
    add("")

    # ---- P1 : couverture de scope -------------------------------------
    add("## P1 — Couverture de scope (vraie pièce dans la banque ?)")
    add("")
    in_scope = [c for c in crops if c.in_bank]
    oos = [c for c in crops if not c.in_bank]
    add(f"- In-scope : {len(in_scope)} ({_pct(len(in_scope), len(crops))})")
    add(f"- Hors-scope : {len(oos)} ({_pct(len(oos), len(crops))})")
    oos_std = [c for c in oos if c.truth_is_commemo is False]
    oos_com = [c for c in oos if c.truth_is_commemo is True]
    oos_unk = [c for c in oos if c.truth_is_commemo is None]
    add(f"  - dont courantes (is_commemorative=0) : {len(oos_std)}")
    add(f"  - dont commémo absentes de la banque : {len(oos_com)}")
    if oos_unk:
        add(f"  - dont eurio_id inconnu de coins : {len(oos_unk)}")
    if oos_com:
        from collections import Counter
        missing = Counter(c.truth_eurio_id for c in oos_com)
        add("")
        add("  Commémo manquantes les plus fréquentes :")
        for eid, n in missing.most_common(10):
            add(f"  - `{eid}` × {n}")
    add("")
    add("> ⚠️ Biais de sélection : le pipeline ne prédit/enqueue que les "
        "listings ciblés 2€ commémo. Les lots de courantes (cas kickoff) "
        "sont encore majoritairement `open` — le % hors-scope réel en "
        "production est plus haut que sur ce set décidé.")
    add("")

    # ---- Recall global / bande pays / UI -------------------------------
    add("## Recall (sur crops avec prédiction)")
    add("")
    preds = [c for c in crops if c.top_k]
    preds_in = [c for c in preds if c.in_bank]
    add(RECALL_HEADER)
    add(_recall_line("Tous (avec prédiction)", preds))
    add(_recall_line("In-scope (vérité dans banque)", preds_in))
    add(_recall_line("Hors-scope", [c for c in preds if not c.in_bank]))
    add("")

    # ---- P2 : pays vérité vs pays cible --------------------------------
    add("## P2 — Effet du biais pays (in-scope uniquement)")
    add("")
    same = [c for c in preds_in if c.target_country and c.truth_country == c.target_country]
    diff = [c for c in preds_in if c.target_country and c.truth_country != c.target_country]
    notgt = [c for c in preds_in if not c.target_country]
    add(RECALL_HEADER)
    add(_recall_line("Pays vérité == pays cible", same))
    add(_recall_line("Pays vérité ≠ pays cible", diff))
    add(_recall_line("Pas de pays cible", notgt))
    add("")
    add("> Sur « vérité ≠ cible », la bande pays ne peut PAS contenir la "
        "bonne pièce (filtre dur) : l'écart UI vs global mesure le coût "
        "du biais. La part « ≠ » va croître avec les lots multi-pays.")
    add("")

    # ---- Segments complémentaires --------------------------------------
    add("## Segments")
    add("")
    add(RECALL_HEADER)
    add(_recall_line(
        "Commémo (vérité)", [c for c in preds_in if c.truth_is_commemo]))
    add(_recall_line(
        "Courante (vérité)",
        [c for c in preds_in if c.truth_is_commemo is False]))
    add(_recall_line(
        "Face = obverse", [c for c in preds_in if c.decided_face == "obverse"]))
    add(_recall_line(
        "Face = unknown/None",
        [c for c in preds_in if c.decided_face != "obverse"]))
    small = [c for c in preds_in if c.width and c.width < 200]
    big = [c for c in preds_in if c.width and c.width >= 200]
    add(_recall_line("Crop < 200px", small))
    add(_recall_line("Crop ≥ 200px", big))
    add("")

    # ---- P3/P5 : distributions sim & spread ----------------------------
    add("## P3/P5 — Sims top1 et spread (global, in-scope)")
    add("")
    tp = [c for c in preds_in if _rank_of(c.truth_eurio_id, c.top_k) == 1]
    fp = [c for c in preds_in if _rank_of(c.truth_eurio_id, c.top_k) != 1]
    add(f"- top1_sim quand top1 **correct** : "
        f"{_quantiles([c.top1_sim for c in tp if c.top1_sim is not None])}")
    add(f"- top1_sim quand top1 **faux**    : "
        f"{_quantiles([c.top1_sim for c in fp if c.top1_sim is not None])}")
    add(f"- top1_sim **hors-scope** (toujours faux) : "
        f"{_quantiles([c.top1_sim for c in preds if not c.in_bank and c.top1_sim is not None])}")
    add(f"- spread quand top1 correct : "
        f"{_quantiles([c.spread for c in tp if c.spread is not None])}")
    add(f"- spread quand top1 faux    : "
        f"{_quantiles([c.spread for c in fp if c.spread is not None])}")
    add(f"- spread **hors-scope** : "
        f"{_quantiles([c.spread for c in preds if not c.in_bank and c.spread is not None])}")
    add("")

    # ---- P5 : pouvoir d'abstention d'un seuil --------------------------
    add("## P5 — Si on s'abstenait sous un seuil top1_sim ?")
    add("")
    add("| seuil | couverture (≥ seuil) | précision top1 au-dessus | "
        "% hors-scope éliminé |")
    add("|---|---|---|---|")
    scored = [c for c in preds if c.top1_sim is not None]
    for thr in (0.70, 0.74, 0.78, 0.80, 0.82, 0.84, 0.86):
        above = [c for c in scored if c.top1_sim >= thr]
        ok = sum(
            1 for c in above if c.in_bank and _rank_of(c.truth_eurio_id, c.top_k) == 1
        )
        oos_below = sum(1 for c in scored if not c.in_bank and c.top1_sim < thr)
        oos_total = sum(1 for c in scored if not c.in_bank)
        add(
            f"| {thr:.2f} | {_pct(len(above), len(scored))} "
            f"| {_pct(ok, len(above))} | {_pct(oos_below, oos_total)} |"
        )
    add("")

    add("### …et avec un seuil sur le spread (top1−top2) ?")
    add("")
    add("| seuil spread | couverture (≥ seuil) | précision top1 au-dessus | "
        "% hors-scope éliminé | % de top1 corrects perdus |")
    add("|---|---|---|---|---|")
    spreaded = [c for c in preds if c.spread is not None]
    n_correct_total = sum(
        1 for c in spreaded if c.in_bank and _rank_of(c.truth_eurio_id, c.top_k) == 1
    )
    for thr in (0.01, 0.02, 0.03, 0.04, 0.05, 0.07):
        above = [c for c in spreaded if c.spread >= thr]
        ok = sum(
            1 for c in above if c.in_bank and _rank_of(c.truth_eurio_id, c.top_k) == 1
        )
        oos_below = sum(1 for c in spreaded if not c.in_bank and c.spread < thr)
        oos_total = sum(1 for c in spreaded if not c.in_bank)
        lost = n_correct_total - ok
        add(
            f"| {thr:.2f} | {_pct(len(above), len(spreaded))} "
            f"| {_pct(ok, len(above))} | {_pct(oos_below, oos_total)} "
            f"| {_pct(lost, n_correct_total)} |"
        )
    add("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--kind", default="2eur_commemo",
                        choices=["2eur_commemo", "2eur_standard", "2eur_all"],
                        help="Banque/prédictions à auditer.")
    parser.add_argument("--out", default=None,
                        help="Écrire le rapport markdown dans ce fichier.")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    report = build_report(conn, args.kind)
    conn.close()

    print(report)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"\n→ écrit dans {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
