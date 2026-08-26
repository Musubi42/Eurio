"""Balayage READ-ONLY des deux seuils du verdict d'auto-validation.

    ./.venv/bin/python -m scripts.sweep_verdict_thresholds \
        --db state/eurio.replica.db [--include-bank] [--csv out.csv]

CE QUE ÇA MESURE
----------------
Le verdict `auto_candidate` (= la lane `auto_accept`) est produit par
``training/foundation/auto_validate.py``. Deux seuils y entrent, et deux
seulement : ``top1_country_sim_min`` et ``country_spread_min``. Les trois
premières règles du verdict (pas de prédiction / texte contradictoire / pas de
target / top1 != target) n'en dépendent PAS : bouger les seuils ne peut que
déplacer la frontière entre ``auto_candidate`` et ``partial``.

On rejoue donc le verdict pour chaque point d'une grille, sur le gold
labellisé, et on compte :

  - ``n_auto``    : combien d'auto-accepts la règle produirait ;
  - ``n_correct`` : combien d'entre eux écriraient le bon ``eurio_id``
                    (``decided_eurio_id == ground_truth_eurio_id``) ;
  - ``precision`` : le rapport des deux.

POPULATION — « hors banque » par défaut
---------------------------------------
Un crop qui est lui-même une ancre de ``2eur_all``/``vitl14`` se reconnaît
lui-même : l'inclure surestime la précision. Le défaut exclut donc les assets
présents dans ``dino_class_references`` pour le couple servi — c'est la même
population que la mesure du 2026-08-24 citée dans ``shared/verdict_scope.py``.
``--include-bank`` la rétablit, pour comparaison seulement.

AUCUNE ÉCRITURE
---------------
Le script ouvre la base en ``mode=ro`` et ne fait que des SELECT. Il n'écrit
aucun seuil : poser une valeur est une décision, pas un effet de bord d'une
mesure. La mutation de ``DINO_VERDICT_THRESHOLDS`` est en mémoire, dans ce
process, et sert précisément à rejouer la VRAIE fonction de décision plutôt
qu'une copie de sa règle — une copie dériverait sans le dire.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from shared.verdict_scope import VERDICT_ANCHORS_KIND, VERDICT_ENCODER_VERSION
from training.foundation import thresholds as th
from training.foundation.auto_validate import compute_auto_validate_verdict_from_row
from review.validation.replay import DEFAULT_GOLD, load_gold

_ML_ROOT = Path(__file__).resolve().parents[1]

# Le JOIN de `_SIGNALS_SQL` (auto_validate), en batch sur tout le gold.
_BATCH_SQL = """
    SELECT a.id AS asset_id,
           a.face,
           si.target_eurio_id,
           p.top1_country_eurio_id,
           p.top1_country_sim,
           p.country_spread,
           p.top1_eurio_id,
           p.top1_sim,
           p.spread,
           lts.vs_target_verdict
      FROM image_assets a
      JOIN source_images si ON si.id = a.source_image_id
      LEFT JOIN image_asset_dino_predictions p
             ON p.asset_id = a.id
            AND p.encoder_version = ?
            AND p.anchors_kind = ?
      LEFT JOIN listing_text_signals lts
             ON lts.source_image_id = si.id
     WHERE a.id IN (%s)
"""


def _bank_assets(conn: sqlite3.Connection, kind: str, encoder: str) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT asset_id FROM dino_class_references "
            " WHERE anchors_kind = ? AND encoder_version = ? AND asset_id IS NOT NULL",
            (kind, encoder),
        )
    }


def _rows_for(
    conn: sqlite3.Connection, asset_ids: list[str], kind: str, encoder: str
) -> dict[str, sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    out: dict[str, sqlite3.Row] = {}
    for i in range(0, len(asset_ids), 500):
        chunk = asset_ids[i : i + 500]
        sql = _BATCH_SQL % ",".join("?" * len(chunk))
        for r in conn.execute(sql, (encoder, kind, *chunk)):
            out[r["asset_id"]] = r
    return out


def _frange(lo: float, hi: float, step: float) -> list[float]:
    n = round((hi - lo) / step)
    return [round(lo + i * step, 4) for i in range(n + 1)]


def _bloque_par_le_seul_texte(v, *, sim_min: float, spread_min: float) -> bool:
    """Ce crop serait-il `auto_candidate` si l'étape 5 n'exigeait pas
    `texte == convergent` ?

    Vrai quand la fonction réelle a rendu `partial` alors que les DEUX critères
    Dino passent : à ce stade les règles 1 à 4 sont franchies, donc la seule
    cause restante de `partial` est la porte texte. Dérivation, pas copie.
    """
    if v.level != "partial":
        return False
    return (
        v.sim is not None and v.sim >= sim_min
        and v.spread is not None and v.spread >= spread_min
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=_ML_ROOT / "state" / "eurio.replica.db")
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--anchors-kind", default=VERDICT_ANCHORS_KIND)
    ap.add_argument("--encoder-version", default=VERDICT_ENCODER_VERSION)
    ap.add_argument("--include-bank", action="store_true",
                    help="ne pas exclure les crops qui SONT des ancres")
    ap.add_argument("--sim-grid", default="0.0:0.75:0.05")
    ap.add_argument("--spread-grid", default="0.0:0.15:0.01")
    ap.add_argument(
        "--text-gate", choices=("convergent", "any"), default="convergent",
        help="porte texte de l'étape 5. 'convergent' = la règle en vigueur. "
             "'any' = le point A (texte ≠ contradict) — équivalent à AUCUNE "
             "condition de texte, la règle 2 ayant déjà renvoyé les "
             "contradictions en `divergent`.",
    )
    ap.add_argument("--csv", type=Path, default=None)
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    gold = [g for g in load_gold(args.gold) if g.ground_truth_eurio_id]
    bank = set() if args.include_bank else _bank_assets(
        conn, args.anchors_kind, args.encoder_version)
    pop = [g for g in gold if g.asset_id not in bank]
    rows = _rows_for(conn, [g.asset_id for g in pop], args.anchors_kind,
                     args.encoder_version)
    pop = [g for g in pop if g.asset_id in rows]

    print(f"db          : {args.db}")
    print(f"couple      : {args.anchors_kind} / {args.encoder_version}")
    print(f"gold        : {args.gold} — {len(gold)} entrées labellisées")
    print(f"ancres      : {len(bank)} assets exclus" if bank else "ancres      : incluses")
    print(f"population  : {len(pop)} crops notés")
    print(f"porte texte : {args.text_gate}"
          f"{'  (règle en vigueur)' if args.text_gate == 'convergent' else '  (point A)'}\n")

    sim_lo, sim_hi, sim_st = (float(x) for x in args.sim_grid.split(":"))
    sp_lo, sp_hi, sp_st = (float(x) for x in args.spread_grid.split(":"))
    sims = _frange(sim_lo, sim_hi, sim_st)
    spreads = _frange(sp_lo, sp_hi, sp_st)

    results: list[tuple[float, float, int, int]] = []
    for sim_min in sims:
        for spread_min in spreads:
            th.DINO_VERDICT_THRESHOLDS["top1_country_sim_min"] = sim_min
            th.DINO_VERDICT_THRESHOLDS["country_spread_min"] = spread_min
            n_auto = n_ok = 0
            for g in pop:
                v = compute_auto_validate_verdict_from_row(rows[g.asset_id])
                decide = v.decided_eurio_id
                if v.level == "auto_candidate":
                    pass
                elif args.text_gate == "any" and _bloque_par_le_seul_texte(
                    v, sim_min=sim_min, spread_min=spread_min
                ):
                    # Point A. On ne RECOPIE pas la règle : on DÉRIVE de la
                    # sortie de la vraie fonction. `partial` avec les deux
                    # critères Dino passants ne peut avoir qu'une cause — le
                    # texte n'était pas `convergent` (et il n'est pas
                    # `contradict`, la règle 2 l'aurait renvoyé en `divergent`
                    # avant d'arriver ici). Et `top1 == cible` est acquis par
                    # la règle 4, donc la cible EST `v.top1_eurio_id`.
                    decide = v.top1_eurio_id
                else:
                    continue
                n_auto += 1
                if decide == g.ground_truth_eurio_id:
                    n_ok += 1
            results.append((sim_min, spread_min, n_auto, n_ok))

    hdr = "sim_min  spread_min   n_auto  justes   faux  précision"
    print(hdr)
    print("-" * len(hdr))
    for sim_min, spread_min, n_auto, n_ok in results:
        prec = f"{100 * n_ok / n_auto:6.2f} %" if n_auto else "     — "
        print(f"{sim_min:7.2f}  {spread_min:10.3f}   {n_auto:6d}  {n_ok:6d}  "
              f"{n_auto - n_ok:5d}  {prec}")

    if args.csv:
        args.csv.write_text(
            "sim_min,spread_min,n_auto,n_correct,n_false,precision\n"
            + "".join(
                f"{s},{d},{a},{o},{a - o},"
                f"{(o / a) if a else ''}\n" for s, d, a, o in results
            )
        )
        print(f"\ncsv → {args.csv}")


if __name__ == "__main__":
    main()
