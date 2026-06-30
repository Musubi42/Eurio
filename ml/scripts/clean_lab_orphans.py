"""Nettoie les artefacts disque d'itérations lab ORPHELINES (plus en DB).

Filet de sécurité complémentaire de l'« événement de fin » (delete_iteration
purge déjà à la suppression). Utile pour les artefacts laissés par un run mort
(subprocess tué) ou une suppression directe en DB.

Couvre les 3 emplacements régénérables d'une itération :
- ``ml/lab/iterations/<iid>``            (modèle/tflite/embeddings/previews/manifests)
- ``ml/datasets/iterations/<iid>``       (staging ImageFolder)
- ``ml/datasets/*/augmentations/<iid>``  (bakes par-coin, set design_group inclus)

Usage :
    .venv/bin/python -m scripts.clean_lab_orphans            # dry-run (liste)
    .venv/bin/python -m scripts.clean_lab_orphans --apply    # supprime
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
LAB_ITERATIONS_DIR = ML_DIR / "lab" / "iterations"
ITERATION_TRAIN_ROOTS = ML_DIR / "datasets" / "iterations"
DATASETS_DIR = ML_DIR / "datasets"


def _live_iteration_ids() -> set[str]:
    db = Path(os.environ.get("EURIO_DB_PATH") or (ML_DIR / "state" / "eurio.db"))
    if not db.exists():
        raise SystemExit(f"eurio.db introuvable : {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {r[0] for r in conn.execute("SELECT id FROM experiment_iterations")}
    finally:
        conn.close()


def _disk_iteration_ids() -> set[str]:
    ids: set[str] = set()
    for base in (LAB_ITERATIONS_DIR, ITERATION_TRAIN_ROOTS):
        if base.is_dir():
            ids |= {p.name for p in base.iterdir() if p.is_dir()}
    for aug in DATASETS_DIR.glob("*/augmentations/*"):
        if aug.is_dir():
            ids.add(aug.name)
    return ids


def _paths_for(iid: str) -> list[Path]:
    paths = [LAB_ITERATIONS_DIR / iid, ITERATION_TRAIN_ROOTS / iid]
    paths += list(DATASETS_DIR.glob(f"*/augmentations/{iid}"))
    return [p for p in paths if p.exists()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.clean_lab_orphans",
                                     description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="supprime réellement (sinon dry-run)")
    args = parser.parse_args(argv)

    live = _live_iteration_ids()
    orphans = sorted(_disk_iteration_ids() - live)
    if not orphans:
        print("Aucune itération orpheline sur disque. ✅")
        return 0

    total = 0
    for iid in orphans:
        paths = _paths_for(iid)
        n = sum(1 for _ in paths)
        total += n
        verb = "supprime" if args.apply else "[dry-run] supprimerait"
        print(f"{verb} {iid} ({n} emplacement(s))")
        if args.apply:
            for p in paths:
                shutil.rmtree(p, ignore_errors=True)
    if not args.apply:
        print(f"\n{len(orphans)} itération(s) orpheline(s). Relancer avec --apply.")
    else:
        print(f"\n{len(orphans)} itération(s) orpheline(s) nettoyée(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
