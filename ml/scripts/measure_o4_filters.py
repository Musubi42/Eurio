"""Ce que les filtres par signaux (O4) retirent, et ce qu'ils coûtent — mesure.

POURQUOI CE SCRIPT EXISTE ICI ET PAS DANS UN SCRATCHPAD
-------------------------------------------------------
Les chiffres d'`O4-filtres-par-signaux.md` (les quatre régimes, les pools
BE/ES/IT, le lot belge « 14 Stück (1999–2012) ») ont été mesurés le 2026-08-20
par un script de session, donc irrejouables. Un chiffre qu'on ne peut pas
rejouer n'est pas une mesure, c'est un souvenir : le plan d'implémentation
exige explicitement que ce script déménage ici.

CE QU'IL MESURE
---------------
1. **Les quatre régimes** — lots/singles × courantes/commémos, sur les crops
   déjà tranchés par un humain : combien chaque réglage SERT, et quelle est sa
   précision. C'est la mesure qui dit que l'ère ne coûte aucun vrai positif.
2. **L'effet sur les pools réels** de la file ouverte, par classe.
3. **Le déplacement des verdicts** `pleine`/`review`/`scrape` une fois
   `pending_scoped` réellement filtré (lot 6, D2).

LA MUTATION, ET COMMENT LA JOUER
--------------------------------
`--enumeration` lit `years_json` comme une ÉNUMÉRATION au lieu d'un INTERVALLE.
C'est la faute que la spec interdit ; le script existe aussi pour en montrer le
prix, mesuré à l'origine : rappel des lots 85,4 % → 74,2 %.

    ./.venv/bin/python -m scripts.measure_o4_filters --db state/eurio.replica.db
    ./.venv/bin/python -m scripts.measure_o4_filters --enumeration

⚠️ **Lecture seule**, réplique comprise : le script ouvre la base en
`mode=ro`. Aucun chiffre d'ici n'a le droit de se poser en base.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from shared.class_need import all_needs  # noqa: E402
from shared.dino_scope import class_country, class_era  # noqa: E402
from shared.verdict_scope import (  # noqa: E402
    SUGGESTIONS_ANCHORS_KIND,
    SUGGESTIONS_ENCODER_VERSION,
)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _era_ok(era: tuple[int, int] | None, years: list[int], *, enumeration: bool) -> bool:
    """L'ère est-elle compatible avec les années du titre ?

    Intervalle (la règle) : `min(Y) <= era_hi AND era_lo <= max(Y)`.
    Énumération (la mutation) : au moins une année du titre DANS l'ère.
    """
    if era is None or not years:
        return True
    if enumeration:
        return any(era[0] <= y <= era[1] for y in years)
    return min(years) <= era[1] and era[0] <= max(years)


def quatre_regimes(conn: sqlite3.Connection, *, enumeration: bool) -> None:
    rows = conn.execute(
        """
        SELECT a.id AS aid,
               COALESCE(c.design_group_id, a.eurio_id) AS cls,
               c.is_commemorative AS commemo,
               COALESCE(cp.design_group_id, p.top1_eurio_id) AS pcls,
               si.listing_country AS listing_country,
               COALESCE(l.years_json, '[]') AS years_json,
               rq.kind AS kind,
               p.denom_2eur_score AS denom
          FROM image_assets a
          JOIN coins c ON c.eurio_id = a.eurio_id
          JOIN source_images si ON si.id = a.source_image_id
          JOIN image_asset_dino_predictions p ON p.asset_id = a.id
          LEFT JOIN coins cp ON cp.eurio_id = p.top1_eurio_id
          LEFT JOIN listing_text_signals l ON l.source_image_id = si.id
          JOIN review_queue rq ON rq.image_asset_id = a.id
         WHERE a.resolution_status = 'manual' AND a.eurio_id IS NOT NULL
           AND p.anchors_kind = ? AND p.encoder_version = ?
           AND p.top1_eurio_id IS NOT NULL
        """,
        (SUGGESTIONS_ANCHORS_KIND, SUGGESTIONS_ENCODER_VERSION),
    ).fetchall()

    era_cache: dict[str, tuple[int, int] | None] = {}
    country_cache: dict[str, str | None] = {}
    buckets: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        pcls = r["pcls"]
        if pcls not in era_cache:
            era_cache[pcls] = class_era(conn, pcls)
            country_cache[pcls] = class_country(conn, pcls)
        years = [int(y) for y in json.loads(r["years_json"])]
        key = (
            "lots" if r["kind"] == "lot" else "singles",
            "commémos" if r["commemo"] else "courantes",
        )
        buckets.setdefault(key, []).append({
            "correct": r["cls"] == pcls,
            "pays": country_cache[pcls] is None
                    or r["listing_country"] == country_cache[pcls],
            "ere": _era_ok(era_cache[pcls], years, enumeration=enumeration),
            "denom": r["denom"] is None or r["denom"] >= 0.4,
        })

    print(f"\n{'régime':22} {'n':>5}  {'pays seul':>18}  {'pays + ère':>18}  {'+ dénom':>18}")
    for key in (("lots", "courantes"), ("lots", "commémos"),
                ("singles", "courantes"), ("singles", "commémos")):
        items = buckets.get(key, [])
        cells = []
        for filtres in (("pays",), ("pays", "ere"), ("pays", "ere", "denom")):
            servis = [i for i in items if all(i[f] for f in filtres)]
            ok = sum(1 for i in servis if i["correct"])
            prec = 100.0 * ok / len(servis) if servis else 0.0
            cells.append(f"{len(servis):5d} · {prec:5.1f} %")
        print(f"{key[0] + ' / ' + key[1]:22} {len(items):5d}  "
              + "  ".join(f"{c:>18}" for c in cells))

    # Le RAPPEL des lots — la grandeur que la mutation « énumération » fait
    # chuter (85,4 % → 74,2 % à l'origine). Sur les crops CORRECTS des lots :
    # combien survivent au filtre d'ère ?
    for regime in ("lots", "singles"):
        vrais = [i for k, v in buckets.items() if k[0] == regime
                 for i in v if i["correct"]]
        gardes = [i for i in vrais if i["ere"]]
        print(f"rappel de l'ère · {regime:8} : {len(gardes)}/{len(vrais)} = "
              f"{100.0 * len(gardes) / max(len(vrais), 1):.1f} %")


def pools(conn: sqlite3.Connection, classes: list[str]) -> None:
    """L'effet des filtres sur des pools RÉELS, classe par classe."""
    from shared.dino_scope import build_dino_scope, suggestions_join_sql

    print(f"\n{'classe':46} {'brut':>6} {'+pays':>7} {'+ère':>7} {'+dénom':>8}")
    for cid in classes:
        counts = []
        for kwargs in ({"country_only": False, "era_only": False},
                       {"country_only": True, "era_only": False},
                       {"country_only": True, "era_only": True},
                       {"country_only": True, "era_only": True, "min_denom": 0.4}):
            sc = build_dino_scope(conn, dino_class=cid, **kwargs)
            counts.append(int(conn.execute(
                f"""
                SELECT COUNT(*) FROM review_queue rq
                  JOIN image_assets a ON a.id = rq.image_asset_id
                  JOIN source_images si ON si.id = a.source_image_id
                  {suggestions_join_sql("ps")}
                 WHERE rq.status = 'open' AND {sc.sql}
                """,
                sc.args,
            ).fetchone()[0]))
        print(f"{cid:46} " + " ".join(
            f"{n:6d}" if i == 0 else f"{n:7d}" for i, n in enumerate(counts)))


def verdicts(conn: sqlite3.Connection) -> None:
    """Le déplacement des verdicts, une fois `pending_scoped` réellement filtré."""
    needs = all_needs(
        conn, anchors_kind=SUGGESTIONS_ANCHORS_KIND,
        encoder_version=SUGGESTIONS_ENCODER_VERSION,
    )
    from shared.class_need import bottleneck_for

    avant: dict[str, int] = {}
    apres: dict[str, int] = {}
    bascule = []
    for n in needs:
        # « avant » = le verdict que l'ancien code rendait, `pending_scoped`
        # étant alors une copie de `pending`.
        a = bottleneck_for(have=n.have, target=n.target, pending_scoped=n.pending,
                           accepted_pending=n.accepted_pending)
        avant[a] = avant.get(a, 0) + 1
        apres[n.bottleneck] = apres.get(n.bottleneck, 0) + 1
        if a != n.bottleneck:
            bascule.append((n.class_id, a, n.bottleneck, n.pending, n.pending_scoped))

    print("\nverdicts   avant → après")
    for k in ("pleine", "review", "scrape"):
        print(f"  {k:8} {avant.get(k, 0):5d} → {apres.get(k, 0):5d}")
    print(f"  classes qui basculent : {len(bascule)}")
    for cid, a, b, p, ps in bascule[:20]:
        print(f"    {cid:46} {a} → {b}   pending {p} → {ps}")
    total_hidden = sum(n.n_hidden_by_era for n in needs)
    print(f"  crops écartés par l'ère, toutes classes : {total_hidden}")
    print(f"  Σ pending {sum(n.pending for n in needs)} → "
          f"Σ pending_scoped {sum(n.pending_scoped for n in needs)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(ML_DIR / "state" / "eurio.replica.db"))
    ap.add_argument("--enumeration", action="store_true",
                    help="MUTATION : lire years_json en énumération (la faute)")
    ap.add_argument("--classes", default=(
        "be-2euro-philippe-t1,es-2euro-juan-carlos-i-t1,it-2euro-standard-t1"))
    args = ap.parse_args()

    conn = _connect(args.db)
    quatre_regimes(conn, enumeration=args.enumeration)
    pools(conn, [c for c in args.classes.split(",") if c])
    verdicts(conn)


if __name__ == "__main__":
    main()
