"""Bootstrap DINOv2 anchor banks from canonical Numista obverses.

Picks coins from the local SQLite catalog (`coins` table) according to
the requested scope, encodes their `<datasets>/<numista_id>/obverse.jpg`
through DINOv2 ViT-S/14, et écrit DEUX fichiers :

  - l'artefact de banc `ml/state/foundation_anchors_<kind>__<encodeur>.npz`,
    toujours ;
  - la banque SERVIE `ml/state/foundation_anchors_<kind>.npz` (celle que lit
    la review et les scripts historiques), sauf `--no-serve`.

Usage:
    .venv/bin/python -m scripts.build_dino_anchors                # 2eur_commemo, cache hit OK
    .venv/bin/python -m scripts.build_dino_anchors --force        # force recompute
    .venv/bin/python -m scripts.build_dino_anchors --kind 2eur_commemo

`--db` choisit le FICHIER, pas le mode d'ouverture : celui-ci vient de
`EURIO_DB_READONLY` (posé par le devShell). Pour `2eur_all`, qui trace sa
sélection dans `dino_class_references`, la commande refuse de démarrer si la
base n'est pas inscriptible — plutôt que d'échouer après ~4 min d'encodage.
`--skip-references` renonce explicitement à la traçabilité.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from training.foundation.anchors import (  # noqa: E402
    DATASETS_DIR,
    build_anchors_2eur_all,
    build_anchors_2eur_commemo,
    build_anchors_2eur_standard,
    build_anchors_reverse_2eur,
    anchor_path,
    load_anchors,
    served_anchor_path,
)
from store import Store, resolve_db_path  # noqa: E402

logger = logging.getLogger(__name__)

# Défaut du `--db` : la base que le RESTE de la machine lit, c'est-à-dire celle
# que pointe `EURIO_DB_PATH` (la réplique, sous Direction A) — pas `eurio.db`
# codé en dur. Mesuré le 2026-08-19 : la banque `2eur_all` servie avait été
# bâtie sur `state/eurio.db` (périmée : 6205 image_assets contre 12454 dans la
# réplique), d'où 125 classes avec exemplaires au lieu de 182 — 57 classes de
# review déjà validée invisibles de la banque. Le même resolver est utilisé par
# ~70 autres entrypoints (`store.resolve_db_path`).
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")

# Seule `2eur_all` ÉCRIT en base : elle trace sa sélection FPS dans
# `dino_class_references`. Les autres banques ne font que lire les `coins`.
WRITING_KINDS = frozenset({"2eur_all"})

_BUILDERS = {
    "2eur_commemo": build_anchors_2eur_commemo,
    "2eur_standard": build_anchors_2eur_standard,
    "2eur_all": build_anchors_2eur_all,
    # reverse_2eur ignore conn/datasets_dir (sources = 2 webp packagés) mais
    # garde la signature homogène pour passer par le même dispatcher.
    "reverse_2eur": build_anchors_reverse_2eur,
}


class ReadOnlyTraceabilityError(RuntimeError):
    """La base choisie ne peut pas recevoir la traçabilité de la sélection."""


def preflight_db_traceability(
    store: Store, kind: str, *, skip_references: bool, push: bool = False
) -> bool:
    """Décide AVANT l'encodage si la sélection sera tracée en base.

    Le piège que cette fonction ferme : ``--db`` choisit bien le fichier, mais
    ``Store(path)`` hérite du ``read_only`` de l'environnement
    (``EURIO_DB_READONLY``, posé par le devShell). Et ``BEGIN IMMEDIATE``
    **réussit** sur une connexion ``mode=ro`` — seule la première vraie écriture
    échoue, c'est-à-dire APRÈS les ~4 minutes d'encodage. Résultat mesuré :
    ``dino_class_references`` est vide dans les 6 bases de la machine.

    On sonde donc réellement l'écriture (le probe couvre aussi les permissions
    fichier, que ``read_only`` ne dit pas), et on échoue tôt et fort.

    Rend ``True`` si la sélection sera tracée, ``False`` si on procède sans
    traçabilité (le ``.npz`` est écrit dans les deux cas — c'est le travail
    coûteux, il ne doit jamais être perdu).
    """
    if kind not in WRITING_KINDS:
        return False
    if push:
        # Direction A : la trace part au canonique par HTTP, pas dans la base
        # locale — qui est une réplique, et que le prochain pull écraserait.
        # Exiger ici une base inscriptible n'aurait aucun sens.
        logger.info(
            "traçabilité : envoyée au canonique (POST /ingest/dino-references) ; "
            "la base locale n'est pas écrite.",
        )
        return False
    if skip_references:
        logger.warning(
            "--skip-references : la sélection des ancres NE SERA PAS tracée dans "
            "dino_class_references (%s). Le .npz est écrit normalement.",
            store.db_path,
        )
        return False
    try:
        with store._writing() as conn:  # noqa: SLF001
            conn.execute("CREATE TABLE _dino_anchors_write_probe (x)")
            conn.execute("DROP TABLE _dino_anchors_write_probe")
    except Exception as exc:  # sqlite3.OperationalError et parents
        raise ReadOnlyTraceabilityError(
            f"Base non inscriptible : {store.db_path}\n"
            f"  cause      : {exc}\n"
            f"  read_only  : {store.read_only} "
            f"(EURIO_DB_READONLY={os.environ.get('EURIO_DB_READONLY', '')!r})\n"
            f"\n"
            f"Le drapeau --db choisit le FICHIER, pas le mode : Store() hérite de "
            f"EURIO_DB_READONLY, que le devShell pose. Sans ce garde-fou, "
            f"l'encodage (~4 min) tournerait pour rien et l'écriture de "
            f"dino_class_references échouerait à la toute fin.\n"
            f"\n"
            f"Trois sorties, dans l'ordre de préférence :\n"
            f"  • pousser au canonique : --push  (Direction A — la trace est de "
            f"l'état, elle va au VPS ; c'est le chemin normal sur Mac/PC)\n"
            f"  • écrire en local      : EURIO_DB_READONLY= … --db <base "
            f"inscriptible>  (seulement si tu SAIS que cette base est la bonne — "
            f"une réplique serait écrasée au prochain pull)\n"
            f"  • s'en passer          : --skip-references (le .npz est écrit, "
            f"la trace est perdue)\n"
            f"\n"
            f"Voir .claude/skills/eurio-data-writes/SKILL.md"
        ) from exc
    return True


def _holds_bank(path: Path, bank) -> bool:
    """Ce .npz contient-il BIEN la banque qu'on vient d'obtenir ?

    Comparaison par ``bank_id`` (posé par ``_write_bank_npz``), avec repli sur
    ``built_at`` + ``count`` pour les .npz d'avant ce champ."""
    if not path.exists():
        return False
    from training.foundation.anchors import _peek_meta  # noqa: PLC0415

    meta = _peek_meta(path)
    if not meta:
        return False
    if meta.get("bank_id") and bank.bank_id:
        return meta["bank_id"] == bank.bank_id
    return (meta.get("built_at"), meta.get("count")) == (bank.built_at, bank.count)


def written_paths(bank, *, serve: bool) -> list[tuple[str, str]]:
    """Les chemins à IMPRIMER, chacun vérifié sur disque — pas un nom codé en dur.

    D13 : l'ancienne ligne « Path: » affichait toujours
    ``state/foundation_anchors_<kind>.npz``, c'est-à-dire la banque SERVIE,
    même quand le run n'avait écrit que son artefact de banc — voire rien du
    tout (cache hit). Ici chaque ligne dit si le fichier contient BIEN la
    banque que ce run vient de rendre."""
    scoped = anchor_path(bank.anchors_kind, bank.encoder_version)
    served = served_anchor_path(bank.anchors_kind)
    rows: list[tuple[str, str]] = []
    for label, path in (("Path", scoped), ("Servie", served)):
        if label == "Servie" and served == scoped:
            continue
        if _holds_bank(path, bank):
            rows.append((label, str(path)))
            continue
        why = ("--no-serve" if label == "Servie" and not serve
               else "non écrit — cache hit (relancer avec --force)")
        rows.append((label, f"{path}  (NE CONTIENT PAS cette banque : {why})"))
    return rows


def _build_dispatcher(
    kind: str, store: Store, force: bool, *,
    write_references: bool, write_legacy: bool = True,
    seed_order: str = "medoid",
):
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise ValueError(f"Unknown anchors kind: {kind!r}")
    kwargs = {
        "datasets_dir": DATASETS_DIR,
        "force_recompute": force,
        "write_legacy": write_legacy,
    }
    if kind in WRITING_KINDS:
        kwargs["write_references"] = write_references
        # L'amorce du FPS (O6) n'a de sens que pour la banque multi-exemplaires.
        kwargs["medoid_first"] = seed_order == "medoid"
    if write_references:
        with store._writing() as conn:  # noqa: SLF001 — trace dino_class_references
            return builder(conn=conn, **kwargs)
    # Aucune écriture attendue : pas de transaction, la connexion de lecture suffit.
    return builder(conn=store._connection(), **kwargs)  # noqa: SLF001


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        default="2eur_commemo",
        choices=sorted(_BUILDERS),
        help="Anchor scope (default: 2eur_commemo).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even if the .npz cache exists.",
    )
    parser.add_argument(
        "--db",
        default=str(DB_PATH),
        help=f"Fichier SQLite à lire (défaut : {DB_PATH}, résolu par "
             "store.resolve_db_path — c'est EURIO_DB_PATH quand il est posé, "
             "et donc la RÉPLIQUE sous Direction A ; ml/state/eurio.db n'est "
             "que le repli quand la variable est absente). "
             "ATTENTION : choisit le fichier, pas le mode — le mode vient de "
             "EURIO_DB_READONLY. La commande refuse de démarrer si la base "
             "n'est pas inscriptible et que la traçabilité est demandée.",
    )
    parser.add_argument(
        "--skip-references",
        action="store_true",
        help="Ne pas tracer la sélection dans dino_class_references (2eur_all). "
             "Permet de bâtir le .npz depuis une base read-only.",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        default=None,
        help="Envoyer la traçabilité au canonique (POST /ingest/dino-references). "
             "Activé par défaut dès que la sync est configurée (EURIO_API_URL) — "
             "c'est le chemin normal sous Direction A.",
    )
    parser.add_argument(
        "--no-push", dest="push", action="store_false",
        help="Ne pas envoyer la traçabilité au canonique.",
    )
    parser.add_argument(
        "--no-serve", dest="serve", action="store_false", default=True,
        help="Bâtir l'artefact de banc SANS mettre à jour la banque servie "
             f"({served_anchor_path('<kind>').name}). À utiliser pour un bras "
             "baseline de banc : sans ce drapeau, la banque que la review sert "
             "est remplacée (c'est le comportement voulu d'un rebuild de prod).",
    )
    parser.add_argument(
        "--seed-order", choices=("medoid", "fps"), default="medoid",
        help="Amorce du FPS par classe (2eur_all) : 'medoid' (défaut, O6) "
             "retient d'abord le crop le plus représentatif de la classe ; "
             "'fps' retient d'abord le plus lointain du canonique — l'ancien "
             "comportement, mesuré -4 pts à taille de banque égale. La note "
             "du build dit laquelle a servi (amorce=medoide|fps).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    # Always echo INFO from the foundation module to give visibility on
    # this CLI.
    logging.getLogger("training.foundation").setLevel(logging.INFO)

    from client.http import sync_enabled

    push = sync_enabled() if args.push is None else bool(args.push)

    store = Store(Path(args.db))
    # AVANT l'encodage (~4 min) : une base non inscriptible doit se voir ici,
    # pas à la dernière ligne du build.
    try:
        write_references = preflight_db_traceability(
            store, args.kind, skip_references=args.skip_references, push=push,
        )
    except ReadOnlyTraceabilityError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 2

    if args.kind in WRITING_KINDS:
        logger.info(
            "amorce du FPS : --seed-order %s (%s)", args.seed_order,
            "médoïde d'abord, O6" if args.seed_order == "medoid"
            else "point lointain d'abord, FPS nu",
        )
    t0 = time.perf_counter()
    bank = _build_dispatcher(
        args.kind, store, args.force, write_references=write_references,
        write_legacy=args.serve, seed_order=args.seed_order,
    )
    dt = time.perf_counter() - t0

    print(f"\nKind:        {bank.anchors_kind}")
    print(f"Encoder:     {bank.encoder_version}")
    print(f"Built at:    {bank.built_at}")
    print(f"Anchors:     {bank.count}")
    print(f"Dim:         {bank.dim}")
    # D13 : imprimer les chemins RÉELLEMENT écrits, pas un nom codé en dur.
    # Une banque bâtie avec un encodeur non-production n'écrit pas la banque
    # servie ; annoncer celle-ci désignait un fichier que le run n'a pas touché.
    for label, path in written_paths(bank, serve=args.serve):
        print(f"{label + ':':<13}{path}")
    print(f"Total time:  {dt:.1f}s")
    # Envoi de la trace au canonique. Ce n'est PAS du best-effort : sans elle,
    # personne ne peut dire ce que contient la banque qu'on vient de servir.
    pushed = None
    if push and getattr(bank, "build", None) is not None:
        from client.ingest import push_dino_references

        pushed = push_dino_references(
            bank.build.to_dict(), [r.to_dict() for r in bank.ref_rows],
        )
        if pushed is None:
            print(
                "\nATTENTION : --push demandé mais la sync n'est pas configurée "
                "(EURIO_API_URL/TOKEN absents) — la trace n'a été écrite NULLE PART.",
                file=sys.stderr,
            )

    if write_references:
        trace = "tracées en base locale"
    elif pushed:
        trace = f"poussées au canonique (build {pushed.get('build_id','?')[:12]}, "\
                f"{pushed.get('n_rows', 0)} lignes)"
    else:
        trace = "NON tracées"
    print(f"References:  {trace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
