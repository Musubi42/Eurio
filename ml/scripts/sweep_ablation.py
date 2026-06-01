"""Orchestrateur du sweep ablation format crop (Step 3c).

Pour CHAQUE combo (margin × edge_mode), enchaine en séquence :
  1. `recrop_with_config.py` → produit `ml/datasets/eurio-poc-<slug>/`
  2. `train_embedder.py` → produit `checkpoints/best_model_<slug>.pth`
  3. `compute_embeddings.py` → produit `output/embeddings_v1_<slug>.json`
  4. `eval_cohort_ablation.py` → produit `state/ablation_eval/<slug>.csv`
     + `state/ablation_eval/<slug>.summary.json`

À la fin, agrège tous les .summary.json en une table comparative
`state/ablation_eval/_sweep_results.{csv,md}`.

Chaque step écrit ses outputs sur disque ; le sweep est ré-entrant (skip si
l'output existe et matche). Pour forcer la regen d'une étape : delete son
fichier output ou utilise `--force-from {recrop,train,embed,eval}`.

Coût estimé : ~5h GPU par combo × 12 combos = 60h GPU 1080 Ti. À piloter en
background ou par session.

Usage :
    # Sweep complet (12 combos par défaut)
    cd ml
    .venv/bin/python -m scripts.sweep_ablation \\
        --device-pull /path/to/debug_pull/<ts> \\
        --class-kind eurio_id

    # Un seul combo (debug)
    .venv/bin/python -m scripts.sweep_ablation \\
        --device-pull /path/to/debug_pull/<ts> \\
        --class-kind eurio_id \\
        --margin-frac 0.10 --edge-mode feathered

    # Reprend là où on s'est arrêté (skip combos déjà eval)
    .venv/bin/python -m scripts.sweep_ablation --resume ...
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from scan.normalize_snap import CropConfig  # noqa: E402
from scripts.recrop_with_config import (  # noqa: E402
    _DEFAULT_SWEEP, _slug_for, recrop_one,
)


_CHECKPOINTS_DIR = _ML_DIR / "checkpoints"
_EMBEDDINGS_DIR = _ML_DIR / "output"
_EVAL_DIR = _ML_DIR / "state" / "ablation_eval"


# ---------------------------------------------------------------------------
# Per-step orchestration
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path = _ML_DIR) -> int:
    print(f"\n→ {' '.join(cmd)}\n")
    return subprocess.call(cmd, cwd=str(cwd))


def step_train(slug: str, dataset_dir: Path, *,
                epochs: int, batch_size: int, embedding_dim: int,
                force: bool) -> Path:
    ckpt = _CHECKPOINTS_DIR / f"best_model_{slug}.pth"
    if ckpt.is_file() and not force:
        print(f"✓ {ckpt.name} déjà présent → skip train.")
        return ckpt
    _CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    # train_embedder écrit best_model.pth ; on le renomme post-coup.
    cmd = [
        sys.executable, "-m", "training.train_embedder",
        "--mode", "arcface",
        "--dataset", str(dataset_dir / "train"),
        "--val-dataset", str(dataset_dir / "val"),
        "--epochs", str(epochs),
        "--batch-size", str(batch_size),
        "--embedding-dim", str(embedding_dim),
        "--output", str(_CHECKPOINTS_DIR),
        "--model-version", f"v-ablation-{slug}",
    ]
    rc = _run(cmd)
    if rc != 0:
        raise SystemExit(f"train_embedder failed (rc={rc}) for slug={slug}")
    produced = _CHECKPOINTS_DIR / "best_model.pth"
    if not produced.is_file():
        raise SystemExit(f"expected {produced} after train, not found")
    produced.replace(ckpt)
    return ckpt


def step_embed(slug: str, dataset_dir: Path, ckpt: Path, *,
                force: bool) -> Path:
    out_full = _EMBEDDINGS_DIR / f"embeddings_v1_{slug}.json"
    if out_full.is_file() and not force:
        print(f"✓ {out_full.name} déjà présent → skip embed.")
        return out_full
    _EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    # compute_embeddings écrit embeddings_v1.json dans --output-dir ; on rename.
    staging = _EMBEDDINGS_DIR / f"_staging_{slug}"
    staging.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "training.compute_embeddings",
        "--model", str(ckpt),
        "--dataset", str(dataset_dir),
        "--output-dir", str(staging),
        "--model-version", f"v-ablation-{slug}",
    ]
    rc = _run(cmd)
    if rc != 0:
        raise SystemExit(f"compute_embeddings failed (rc={rc}) for slug={slug}")
    produced = staging / "embeddings_v1.json"
    if not produced.is_file():
        raise SystemExit(f"expected {produced} after embed, not found")
    produced.replace(out_full)
    # On garde le _staging pour le coin_embeddings.json flat si besoin
    return out_full


def step_eval(slug: str, dataset_dir: Path, ckpt: Path,
               embeddings: Path, device_pull: Path, *,
               force: bool) -> Path:
    out_csv = _EVAL_DIR / f"{slug}.csv"
    if out_csv.is_file() and not force:
        print(f"✓ {out_csv.name} déjà présent → skip eval.")
        return out_csv
    cmd = [
        sys.executable, "-m", "scripts.eval_cohort_ablation",
        "--device-pull", str(device_pull),
        "--model", str(ckpt),
        "--embeddings", str(embeddings),
        "--crop-config-json", str(dataset_dir / "_crop_config.json"),
        "--output", str(out_csv),
    ]
    rc = _run(cmd)
    if rc != 0:
        raise SystemExit(f"eval_cohort_ablation failed (rc={rc}) for slug={slug}")
    return out_csv


# ---------------------------------------------------------------------------
# Sweep loop + aggregation
# ---------------------------------------------------------------------------


def _force_set(force_from: str | None) -> set[str]:
    """Renvoie le set des steps à forcer si --force-from=<step> est utilisé.
    Step ∈ {recrop, train, embed, eval}. Cascade : si recrop forcé, downstream
    aussi puisque dataset change."""
    order = ["recrop", "train", "embed", "eval"]
    if force_from is None:
        return set()
    if force_from not in order:
        raise SystemExit(f"--force-from must be in {order}, got {force_from!r}")
    return set(order[order.index(force_from):])


def aggregate_summaries() -> Path:
    """Lit tous les <slug>.summary.json sous _EVAL_DIR et produit une table."""
    summaries = sorted(_EVAL_DIR.glob("*.summary.json"))
    rows = []
    for s in summaries:
        d = json.loads(s.read_text())
        cfg = d["crop_config"]
        slug = _slug_for(CropConfig(**cfg))
        rows.append({
            "slug": slug,
            "margin_pct": int(round(cfg["margin_frac"] * 100)),
            "edge_mode": cfg["edge_mode"],
            "output_size": cfg["output_size"],
            "n_eval": d.get("n_eval", 0),
            "r_at_1_pct": (round(100 * d["r_at_1"], 2)
                            if d.get("r_at_1") is not None else None),
            "r_at_5_pct": (round(100 * d["r_at_5"], 2)
                            if d.get("r_at_5") is not None else None),
        })
    rows.sort(key=lambda r: -(r["r_at_1_pct"] or -1))
    # CSV
    import csv as _csv
    csv_path = _EVAL_DIR / "_sweep_results.csv"
    if rows:
        with csv_path.open("w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    # Markdown
    md = _EVAL_DIR / "_sweep_results.md"
    with md.open("w") as f:
        f.write("# Sweep ablation format crop — résultats\n\n")
        f.write("Trié par R@1 décroissant. Voir `<slug>.csv` pour le détail par capture.\n\n")
        f.write("| slug | margin | edge | size | n_eval | R@1 | R@5 |\n")
        f.write("|---|---:|---|---:|---:|---:|---:|\n")
        for r in rows:
            f.write(f"| `{r['slug']}` | {r['margin_pct']}% | {r['edge_mode']} | "
                    f"{r['output_size']} | {r['n_eval']} | "
                    f"{r['r_at_1_pct']:.2f}% | {r['r_at_5_pct']:.2f}% |\n"
                    if r['r_at_1_pct'] is not None
                    else f"| `{r['slug']}` | {r['margin_pct']}% | {r['edge_mode']} | "
                          f"{r['output_size']} | {r['n_eval']} | — | — |\n")
    print(f"\n→ Agrégat : {csv_path} + {md}")
    return md


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sweep ablation format crop (recrop → train → embed → eval).")
    parser.add_argument("--device-pull", type=Path, required=True,
                         help="Dir issu de pull-debug pour l'éval.")
    parser.add_argument("--class-kind", choices=["eurio_id", "design_group"],
                         required=True)
    parser.add_argument("--only-classes", type=str, default=None,
                         help="Limite training aux class_ids données (comma-separated).")
    parser.add_argument("--cohort-csv", type=Path, default=None,
                         help="Résout les classes depuis ce CSV cohort "
                              "(eurio_id;numista_id;…) au lieu de Supabase. "
                              "Bench offline : entraîne exactement les coins du CSV.")

    g = parser.add_mutually_exclusive_group()
    g.add_argument("--sweep-default", action="store_true",
                    help="12 combos par défaut.")
    g.add_argument("--margin-frac", type=float,
                    help="Combo unique. Doit fournir aussi --edge-mode.")
    parser.add_argument("--edge-mode", choices=["hard", "feathered", "none"],
                         default=None)
    parser.add_argument("--feather-width-frac", type=float, default=0.04)
    parser.add_argument("--output-size", type=int, default=224)

    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--embedding-dim", type=int, default=256)
    parser.add_argument("--force-from",
                         choices=["recrop", "train", "embed", "eval"],
                         default=None,
                         help="Force re-run à partir de cette étape (cascade downstream).")
    parser.add_argument("--aggregate-only", action="store_true",
                         help="Ne lance rien, juste l'agrégat des summary.json existants.")
    args = parser.parse_args()

    if args.aggregate_only:
        aggregate_summaries()
        return

    if args.sweep_default:
        configs = _DEFAULT_SWEEP
    elif args.margin_frac is not None:
        if args.edge_mode is None:
            parser.error("--margin-frac requires --edge-mode")
        configs = [CropConfig(
            margin_frac=args.margin_frac,
            edge_mode=args.edge_mode,
            feather_width_frac=args.feather_width_frac,
            output_size=args.output_size,
        )]
    else:
        parser.error("Provide --sweep-default OR (--margin-frac + --edge-mode)")

    forced = _force_set(args.force_from)
    _EVAL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Sweep : {len(configs)} combo(s). forced steps = {sorted(forced) or '(none)'}")

    for i, cfg in enumerate(configs, 1):
        slug = _slug_for(cfg)
        print(f"\n\n{'=' * 70}\n=== [{i}/{len(configs)}] {slug}\n{'=' * 70}")

        dataset_dir = recrop_one(
            cfg,
            class_kind=args.class_kind,
            only_classes=args.only_classes,
            force=("recrop" in forced),
            cohort_csv=args.cohort_csv,
        )
        ckpt = step_train(
            slug, dataset_dir,
            epochs=args.epochs, batch_size=args.batch_size,
            embedding_dim=args.embedding_dim,
            force=("train" in forced),
        )
        embeddings = step_embed(
            slug, dataset_dir, ckpt,
            force=("embed" in forced),
        )
        step_eval(
            slug, dataset_dir, ckpt, embeddings, args.device_pull,
            force=("eval" in forced),
        )
        print(f"\n✓ Combo {slug} terminé.")

    aggregate_summaries()


if __name__ == "__main__":
    main()
