"""Générateur du plan de capture photo du corpus de scan (P5).

Lit **en lecture seule** la réplique du canonique et sort une prescription
stratifiée : une ligne par cellule ``classe × condition``, ordonnée en sessions
de prise de vue, avec le fond imposé et le nombre de captures à faire.

> Ce script **n'écrit rien en base**. La connexion SQLite est ouverte en
> ``mode=ro`` (URI) — toute écriture lèverait ``attempt to write a readonly
> database``. Il ne crée ni cohorte, ni ligne ``scan_corpus``. Créer la cohorte
> de prescription est une écriture, elle passe par l'API du canonique
> (cf. skill ``eurio-data-writes``) — la commande est rappelée dans le
> protocole.

Contexte : ``docs/work-in-progress/scan-sans-retrain/PREREQUIS.md`` §P5 et
``docs/work-in-progress/scan-quality/corpus-spec.md`` (§4 table, §Q2
vocabulaire des conditions).

Les strates viennent du croisement ``coins.personal_owned = 1`` ×
``dino_class_references`` (banque ``2eur_all``) :

===============  =========================================================
``riche``        ≥ 9 exemplaires ``fps`` dans la banque — la borne haute
``moyenne``      1 à 8 exemplaires ``fps``
``canonique``    0 ``fps``, seulement le canonique Numista — **81 % du
                 catalogue réel**, donc sur-représenté ici
``hors_banque``  la classe n'est pas dans la banque, **mais un membre de son
                 ``design_group`` y est** — scorable en maille eq
``orpheline``    ni dans la banque, ni de frère dans la banque : **rien ne
                 peut la reconnaître**. Exclue du plan par défaut
                 (``--classes-par-strate orpheline=all`` pour l'inclure)
===============  =========================================================

Usage ::

    go-task ml:scan-corpus:prescribe
    go-task ml:scan-corpus:prescribe -- --out /tmp/p.csv --captures-riche 3

Sorties :

- le CSV de prescription (une ligne par cellule) ;
- à côté, ``<out>.cohorte.csv`` au format ``eurio_id;numista_id;display_name``
  attendu par ``store.class_resolver.coin_refs_from_cohort_csv``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_DIR.parent
DEFAULT_OUT = (
    REPO_ROOT
    / "docs"
    / "work-in-progress"
    / "scan-sans-retrain"
    / "plan-capture-scan.csv"
)

sys.path.insert(0, str(ML_DIR))
from shared.utils.i18n import display_title  # noqa: E402
from store import resolve_db_path  # noqa: E402


def default_db() -> Path:
    """La base à LIRE, ``EURIO_DB_PATH`` d'abord.

    Le chemin était codé en dur sur ``ml/state/eurio.replica.db`` — le motif
    exact corrigé le même jour dans ``build_dino_anchors.py`` (piège n°1 du
    repo, cf. skill ``eurio-data-writes``). Sous le devShell, ``EURIO_DB_PATH``
    désigne déjà la réplique ; sur une machine qui la place ailleurs, le script
    lisait silencieusement une AUTRE base — ``ml/state/eurio.db`` compte 6205
    ``image_assets`` contre 12454 dans la réplique, donc une prescription
    calculée sur un catalogue amputé, sans un mot.

    Résolu à l'appel, pas à l'import : un test qui pose ``EURIO_DB_PATH`` doit
    être entendu même si le module est déjà chargé.
    """
    return resolve_db_path(ML_DIR / "state" / "eurio.replica.db")

#: Ordre canonique des strates, du plus riche au plus pauvre.
STRATES: tuple[str, ...] = (
    "riche", "moyenne", "canonique", "hors_banque", "orpheline",
)

#: Vocabulaire prescrit du cycle (``corpus-spec.md`` §Q2). ``worn``/``dirty``
#: restent hors prescription : les pièces de test sont propres.
DEFAULT_CONDITIONS: tuple[str, ...] = ("bright", "dim", "tilt", "glare", "inhand")

#: Captures par cellule, par strate. Le régime pauvre est sur-représenté : il
#: pèse 81 % du catalogue réel et c'est le seul endroit où l'on a besoin d'un
#: intervalle de confiance serré (cf. le protocole, §Pourquoi cette répartition).
DEFAULT_CAPTURES: dict[str, int] = {
    "riche": 2,
    "moyenne": 2,
    "canonique": 3,
    "hors_banque": 3,
    "orpheline": 3,
}

#: Quota par strate quand l'opérateur n'en impose pas. ``None`` = tout prendre.
#: ``orpheline`` est le seul à 0 : photographier une pièce que RIEN ne peut
#: reconnaître ne mesure pas la reconnaissance, et la compter dans
#: ``hors_banque`` diluerait la seule strate qui mesure la maille eq.
#: L'inclure reste possible et explicite : ``--classes-par-strate orpheline=all``.
DEFAULT_QUOTAS: dict[str, int | None] = {
    "riche": None,
    "moyenne": None,
    "canonique": None,
    "hors_banque": None,
    "orpheline": 0,
}

#: Fonds imposés. Rotation par (classe, condition) : une classe ne doit jamais
#: être vue sur un seul fond, sinon le fond devient un indice de la classe.
DEFAULT_FONDS: tuple[str, ...] = (
    "bois-clair",
    "tissu-gris",
    "papier-blanc",
    "table-sombre",
)

_SQL_CLASSES = """
WITH owned AS (
  SELECT eurio_id, numista_id, country, country_name, year, face_value,
         theme, is_commemorative, design_group_id
    FROM coins
   WHERE personal_owned = 1
),
refs AS (
  SELECT class_id,
         SUM(method = 'fps')       AS n_fps,
         SUM(method = 'canonical') AS n_canonical
    FROM dino_class_references
   WHERE anchors_kind = :kind
   GROUP BY class_id
),
gold AS (
  SELECT eurio_id, COUNT(*) AS n_gold
    FROM image_assets
   WHERE training_eligible = 1
   GROUP BY eurio_id
)
SELECT o.*,
       COALESCE(r.n_fps, 0)       AS n_fps,
       COALESCE(r.n_canonical, 0) AS n_canonical,
       r.class_id IS NOT NULL     AS in_bank,
       COALESCE(g.n_gold, 0)      AS n_gold,
       (SELECT COUNT(*) FROM coins c2
          JOIN refs r2 ON r2.class_id = c2.eurio_id
         WHERE o.design_group_id IS NOT NULL
           AND c2.design_group_id = o.design_group_id) AS n_siblings_in_bank
  FROM owned o
  LEFT JOIN refs r ON r.class_id = o.eurio_id
  LEFT JOIN gold g ON g.eurio_id = o.eurio_id
 ORDER BY o.eurio_id
"""


@dataclass
class Classe:
    eurio_id: str
    numista_id: int | None
    country: str
    year: int | None
    titre: str
    strate: str
    n_fps: int
    n_gold: int
    n_siblings_in_bank: int
    conditions: list[str] = field(default_factory=list)


@dataclass
class Cellule:
    classe: Classe
    condition: str
    n_captures: int
    fond: str
    passe: int
    session: int = 0
    ordre: int = 0


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    """Ouvre la réplique en lecture seule stricte (URI ``mode=ro``)."""
    if not db_path.exists():
        raise SystemExit(f"error: base introuvable : {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _strate_of(row: sqlite3.Row) -> str:
    """La strate d'une classe possédée, telle que la docstring du module la définit.

    ``hors_banque`` n'est PAS « absente de la banque » : c'est « absente de la
    banque **mais avec un frère de ``design_group`` dedans** », donc scorable en
    maille eq. Une classe sans frère en banque n'est reconnaissable par rien —
    elle est ``orpheline``, et la confondre avec ``hors_banque`` gonflerait
    d'échecs structurels la strate censée mesurer la maille eq.

    ⚠️ estimation au 2026-08-19 : les 7 pièces hors banque de la réplique ont
    toutes ``n_siblings_in_bank = 1``, la distinction ne change donc encore rien
    au plan produit. Requête de contrôle (lecture seule) ::

        sqlite3 "file:ml/state/eurio.replica.db?mode=ro" "
          SELECT COUNT(*) FROM coins o
           WHERE o.personal_owned = 1
             AND o.eurio_id NOT IN (SELECT class_id FROM dino_class_references
                                     WHERE anchors_kind = '2eur_all')
             AND NOT EXISTS (SELECT 1 FROM coins c2
                              WHERE c2.design_group_id = o.design_group_id
                                AND c2.eurio_id IN (SELECT class_id
                                      FROM dino_class_references
                                     WHERE anchors_kind = '2eur_all'));"
    """
    if not row["in_bank"]:
        if not (row["n_siblings_in_bank"] or 0):
            return "orpheline"
        return "hors_banque"
    if row["n_fps"] >= 9:
        return "riche"
    if row["n_fps"] >= 1:
        return "moyenne"
    return "canonique"


def load_classes(conn: sqlite3.Connection, anchors_kind: str) -> list[Classe]:
    rows = conn.execute(_SQL_CLASSES, {"kind": anchors_kind}).fetchall()
    classes: list[Classe] = []
    for r in rows:
        coin = {k: r[k] for k in r.keys()}
        classes.append(
            Classe(
                eurio_id=r["eurio_id"],
                numista_id=r["numista_id"],
                country=(r["country"] or "").upper(),
                year=r["year"],
                titre=display_title(coin),
                strate=_strate_of(r),
                n_fps=int(r["n_fps"]),
                n_gold=int(r["n_gold"]),
                n_siblings_in_bank=int(r["n_siblings_in_bank"] or 0),
            )
        )
    return classes


def _hash_rank(seed: int, *parts: str) -> int:
    """Rang déterministe et reproductible (pas de ``random`` global)."""
    blob = f"{seed}|" + "|".join(parts)
    return int(hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12], 16)


def select_classes(
    classes: list[Classe],
    quotas: dict[str, int | None],
    seed: int,
) -> list[Classe]:
    """Applique le quota par strate ; ``None`` = tout prendre.

    L'échantillonnage est déterministe (hash du ``eurio_id``), donc rejouer la
    commande donne la même prescription.
    """
    kept: list[Classe] = []
    for strate in STRATES:
        pool = sorted(
            (c for c in classes if c.strate == strate),
            key=lambda c: _hash_rank(seed, "pick", c.eurio_id),
        )
        limit = quotas.get(strate)
        kept.extend(pool if limit is None else pool[:limit])
    return kept


def build_cells(
    classes: list[Classe],
    conditions: tuple[str, ...],
    captures: dict[str, int],
    fonds: tuple[str, ...],
    passes: int,
    seed: int,
) -> list[Cellule]:
    """Une cellule par (classe, condition), fond tourné, conditions réparties
    sur ``passes`` passages distincts de la classe."""
    cells: list[Cellule] = []
    for ci, classe in enumerate(sorted(classes, key=lambda c: c.eurio_id)):
        # Ordre des conditions propre à la classe : deux classes voisines ne
        # subissent pas la même séquence, donc pas la même dérive de lumière.
        ordered = sorted(
            conditions, key=lambda cond: _hash_rank(seed, "cond", classe.eurio_id, cond)
        )
        for k, condition in enumerate(ordered):
            cells.append(
                Cellule(
                    classe=classe,
                    condition=condition,
                    n_captures=captures[classe.strate],
                    # Décalage par classe ET par condition : chaque classe voit
                    # plusieurs fonds, chaque fond voit toutes les strates.
                    fond=fonds[(ci + k) % len(fonds)],
                    passe=k % max(1, passes) + 1,
                )
            )
    return cells


def assign_sessions(
    cells: list[Cellule], cells_per_session: int, seed: int
) -> list[Cellule]:
    """Découpe en sessions courtes. L'unité déplacée est le **bloc**
    ``(classe, passe)`` : les cellules d'une même passe restent contiguës,
    parce que sur la table on tient la pièce en main et on ne la range pas
    entre deux conditions.

    Trois invariants visés :

    - une session contient les quatre strates, au prorata (sinon « la lumière
      du jour J » devient un indice de la strate) ;
    - les ``passes`` d'une classe tombent dans des **sessions différentes**
      (sinon une classe n'est vue que sous une seule ambiance) ;
    - on ne ressort jamais une pièce plus de ``passes`` fois.
    """
    blocs: dict[tuple[str, int], list[Cellule]] = {}
    for cell in cells:
        blocs.setdefault((cell.classe.eurio_id, cell.passe), []).append(cell)

    by_passe: dict[int, list[list[Cellule]]] = {}
    for (_eid, passe), group in blocs.items():
        by_passe.setdefault(passe, []).append(group)

    ordered_blocs: list[list[Cellule]] = []
    for passe in sorted(by_passe):
        buckets: dict[str, list[list[Cellule]]] = {s: [] for s in STRATES}
        for group in by_passe[passe]:
            buckets[group[0].classe.strate].append(group)
        for s in buckets:
            buckets[s].sort(
                key=lambda g: _hash_rank(seed, "sess", g[0].classe.eurio_id)
            )
        # Round-robin pondéré : on tire dans chaque strate au prorata de sa
        # taille, ce qui garantit un mélange homogène du début à la fin.
        total = sum(len(v) for v in buckets.values())
        cursors = {s: 0 for s in STRATES}
        rates = {s: (len(buckets[s]) / total if total else 0.0) for s in STRATES}
        for _ in range(total):
            best: tuple[float, str] | None = None
            for s in STRATES:
                if cursors[s] >= len(buckets[s]):
                    continue
                score = (cursors[s] + 0.5) / rates[s] if rates[s] else float("inf")
                if best is None or score < best[0]:
                    best = (score, s)
            if best is None:
                break
            s = best[1]
            ordered_blocs.append(buckets[s][cursors[s]])
            cursors[s] += 1

    session = 1
    ordre = 0
    used = 0
    ordered: list[Cellule] = []
    for group in ordered_blocs:
        # Un bloc ne se coupe pas en deux sessions : on bascule avant.
        if used and used + len(group) > cells_per_session:
            session += 1
            ordre = 0
            used = 0
        for cell in group:
            ordre += 1
            used += 1
            cell.session = session
            cell.ordre = ordre
            ordered.append(cell)
    return ordered


FIELDS = [
    "session",
    "ordre",
    "eurio_id",
    "numista_id",
    "strate",
    "condition",
    "n_captures",
    "fond",
    "passe",
    "pays",
    "annee",
    "titre",
    "n_fps_banque",
    "n_gold_review",
]


def write_prescription(cells: list[Cellule], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter=";")
        w.writeheader()
        for c in cells:
            w.writerow(
                {
                    "session": c.session,
                    "ordre": c.ordre,
                    "eurio_id": c.classe.eurio_id,
                    "numista_id": c.classe.numista_id or "",
                    "strate": c.classe.strate,
                    "condition": c.condition,
                    "n_captures": c.n_captures,
                    "fond": c.fond,
                    "passe": c.passe,
                    "pays": c.classe.country,
                    "annee": c.classe.year or "",
                    "titre": c.classe.titre,
                    "n_fps_banque": c.classe.n_fps,
                    "n_gold_review": c.classe.n_gold,
                }
            )


def write_cohort_csv(classes: list[Classe], out: Path) -> None:
    """Format ``eurio_id;numista_id;display_name`` (``class_resolver``)."""
    lines = [
        "# Cohorte de prescription du corpus de scan (P5) — générée par",
        "# ml/scripts/build_scan_prescription.py. Une ligne par classe.",
        "eurio_id;numista_id;display_name",
    ]
    for c in sorted(classes, key=lambda c: c.eurio_id):
        lines.append(f"{c.eurio_id};{c.numista_id or ''};{c.titre}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_quotas(raw: str | None) -> dict[str, int | None]:
    """Les quotas par strate, en partant de ``DEFAULT_QUOTAS`` (pas de « tout »).

    Partir de « tout prendre » ferait entrer les orphelines dans le plan par
    omission ; elles n'y entrent que si on les nomme.
    """
    quotas: dict[str, int | None] = dict(DEFAULT_QUOTAS)
    if not raw:
        return quotas
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        key = key.strip()
        if key not in quotas:
            raise SystemExit(
                f"error: strate inconnue {key!r} (attendu : {', '.join(STRATES)})"
            )
        quotas[key] = None if value.strip() in ("", "all") else int(value)
    return quotas


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=None,
                   help="base à lire, en read-only strict. Défaut : "
                        f"store.resolve_db_path → {default_db()} "
                        "(EURIO_DB_PATH, sinon ml/state/eurio.replica.db)")
    p.add_argument("--anchors-kind", default="2eur_all")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--conditions", default=",".join(DEFAULT_CONDITIONS))
    p.add_argument("--fonds", default=",".join(DEFAULT_FONDS))
    p.add_argument(
        "--classes-par-strate", dest="quotas", default=None,
        help="ex. 'riche=15,moyenne=15,canonique=20,hors_banque=0'. "
             "Défaut : toutes les classes possédées.",
    )
    for strate, default in DEFAULT_CAPTURES.items():
        p.add_argument(f"--captures-{strate}", type=int, default=default,
                       help=f"captures par cellule pour la strate {strate}")
    p.add_argument("--passes", type=int, default=2,
                   help="passages distincts d'une même classe (défaut 2) — "
                        "chaque passe tombe dans une session différente")
    p.add_argument("--cells-per-session", type=int, default=40)
    p.add_argument("--seed", type=int, default=20260819)
    p.add_argument("--no-cohort-csv", action="store_true")
    args = p.parse_args(argv)

    conditions = tuple(c.strip() for c in args.conditions.split(",") if c.strip())
    fonds = tuple(f.strip() for f in args.fonds.split(",") if f.strip())
    if not conditions or not fonds:
        raise SystemExit("error: --conditions et --fonds ne peuvent pas être vides")
    captures = {s: getattr(args, f"captures_{s}") for s in STRATES}

    db_path = args.db or default_db()
    conn = _open_readonly(db_path)
    try:
        classes = load_classes(conn, args.anchors_kind)
    finally:
        conn.close()
    if not classes:
        raise SystemExit(
            "error: aucune pièce personal_owned=1 — mauvaise base ? "
            f"({db_path})"
        )

    quotas = _parse_quotas(args.quotas)
    kept = select_classes(classes, quotas, args.seed)
    # Ce qu'on a écarté doit se lire, sinon « 7 pièces manquantes » devient une
    # découverte de fin de séance photo.
    gardes = {c.eurio_id for c in kept}
    ecartees = [c for c in classes if c.eurio_id not in gardes]
    cells = build_cells(kept, conditions, captures, fonds, args.passes, args.seed)
    cells = assign_sessions(cells, args.cells_per_session, args.seed)
    write_prescription(cells, args.out)

    cohort_out = args.out.with_suffix(".cohorte.csv")
    if not args.no_cohort_csv:
        write_cohort_csv(kept, cohort_out)

    # Récapitulatif — tout chiffre annoncé doit être relisible dans le CSV.
    n_captures = sum(c.n_captures for c in cells)
    print(f"base (ro)        : {db_path}")
    print(f"prescription     : {args.out}")
    if not args.no_cohort_csv:
        print(f"cohorte CSV      : {cohort_out}")
    print(f"conditions       : {', '.join(conditions)}")
    print(f"fonds            : {', '.join(fonds)}")
    print(f"classes          : {len(kept)} / {len(classes)} possédées")
    if ecartees:
        par_strate: dict[str, int] = {}
        for c in ecartees:
            par_strate[c.strate] = par_strate.get(c.strate, 0) + 1
        detail = ", ".join(f"{n} {s} (quota {quotas[s]})"
                           for s, n in sorted(par_strate.items()))
        print(f"écartées         : {len(ecartees)} — {detail}")
    print(f"cellules         : {len(cells)}")
    print(f"captures visées  : {n_captures}")
    print(f"sessions         : {cells[-1].session if cells else 0}")
    print("")
    print(f"{'strate':<14}{'classes':>8}{'cellules':>10}{'captures':>10}{'part':>8}")
    for s in STRATES:
        cs = [c for c in cells if c.classe.strate == s]
        n_cls = len({c.classe.eurio_id for c in cs})
        n_cap = sum(c.n_captures for c in cs)
        part = (n_cap / n_captures * 100) if n_captures else 0.0
        print(f"{s:<14}{n_cls:>8}{len(cs):>10}{n_cap:>10}{part:>7.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
