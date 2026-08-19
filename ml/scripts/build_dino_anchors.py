"""Bootstrap DINOv2 anchor banks from canonical Numista obverses.

Picks coins from the local SQLite catalog (`coins` table) according to
the requested scope, encodes their `<datasets>/<numista_id>/obverse.jpg`
through DINOv2 ViT-S/14, and writes the bank to
`ml/state/foundation_anchors_<kind>.npz`.

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
    load_anchors,
)
from store import Store  # noqa: E402

logger = logging.getLogger(__name__)

DB_PATH = ML_DIR / "state" / "eurio.db"

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


def _build_dispatcher(kind: str, store: Store, force: bool, *, write_references: bool):
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise ValueError(f"Unknown anchors kind: {kind!r}")
    kwargs = {"datasets_dir": DATASETS_DIR, "force_recompute": force}
    if kind in WRITING_KINDS:
        kwargs["write_references"] = write_references
    if write_references:
        with store._writing() as conn:  # noqa: SLF001 — trace dino_class_references
            return builder(conn=conn, **kwargs)
    # Aucune écriture attendue : pas de transaction, la connexion de lecture suffit.
    return builder(conn=store._connection(), **kwargs)  # noqa: SLF001


def main() -> int:
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
        help="Path to the training SQLite DB (default: ml/state/eurio.db). "
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
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

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

    t0 = time.perf_counter()
    bank = _build_dispatcher(
        args.kind, store, args.force, write_references=write_references,
    )
    dt = time.perf_counter() - t0

    print(f"\nKind:        {bank.anchors_kind}")
    print(f"Encoder:     {bank.encoder_version}")
    print(f"Built at:    {bank.built_at}")
    print(f"Anchors:     {bank.count}")
    print(f"Dim:         {bank.dim}")
    print(f"Path:        {ML_DIR / 'state' / f'foundation_anchors_{bank.anchors_kind}.npz'}")
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
