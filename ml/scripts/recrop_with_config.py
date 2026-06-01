"""Re-crop dataset Numista avec un (ou plusieurs) CropConfig alternatif(s).

Wrapper batch autour de `training.prepare_dataset` (Step 3a du chantier ablation
format crop, cf. `docs/roadmap.md` "Chantier ablation format crop").

Pour CHAQUE combo crop spécifié, produit un dataset distinct sous
`ml/datasets/eurio-poc-<slug>/{train,val,test}/<class_id>/*.jpg` avec :
  - un `_crop_config.json` à la racine (traçabilité combo utilisé)
  - le même class_manifest.json que prepare_dataset (compat training)

Idempotent : si `eurio-poc-<slug>/_crop_config.json` existe et matche, le combo
est skip. Pour forcer la regen → `--force`.

Le sweep complet (`sweep_ablation.py`) appelle ce script en boucle sur tous les
combos de la matrice margin × edge_mode.

Usage :
    # Combo unique manuel
    cd ml
    .venv/bin/python -m scripts.recrop_with_config \\
        --class-kind eurio_id \\
        --margin-frac 0.10 --edge-mode feathered

    # Batch sweep (12 combos de la matrice ablation)
    .venv/bin/python -m scripts.recrop_with_config --sweep-default --class-kind eurio_id

    # Sweep custom (matrice JSON)
    .venv/bin/python -m scripts.recrop_with_config --sweep-from configs.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parents[1]
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from scan.normalize_snap import CropConfig  # noqa: E402


# Matrice par défaut du sweep ablation (cf. memory project_crop_format_ablation).
# 4 margins × 3 edges = 12 combos, résolution 224 fixe.
_DEFAULT_SWEEP: list[CropConfig] = [
    CropConfig(margin_frac=m, edge_mode=e, output_size=224)
    for m in (0.02, 0.05, 0.10, 0.15)
    for e in ("hard", "feathered", "none")
]


def _slug_for(config: CropConfig) -> str:
    """Slug filesystem-safe pour identifier un combo dans le nom du dossier."""
    margin_pct = int(round(config.margin_frac * 100))
    feather_pct = int(round(config.feather_width_frac * 100))
    base = f"m{margin_pct:02d}-{config.edge_mode}-s{config.output_size}"
    if config.edge_mode == "feathered":
        base += f"-fw{feather_pct:02d}"
    return base


def _write_crop_config_json(output_dir: Path, config: CropConfig) -> None:
    payload = asdict(config)
    payload["_slug"] = _slug_for(config)
    (output_dir / "_crop_config.json").write_text(
        json.dumps(payload, indent=2) + "\n"
    )


def _existing_config(output_dir: Path) -> CropConfig | None:
    f = output_dir / "_crop_config.json"
    if not f.is_file():
        return None
    try:
        d = json.loads(f.read_text())
        d.pop("_slug", None)
        return CropConfig(**d)
    except Exception:
        return None


def _run_prepare(config: CropConfig, output_dir: Path, class_kind: str,
                  raw_dir: Path | None, only_classes: str | None,
                  seed: int, cohort_csv: Path | None) -> int:
    """Invoke prepare_dataset.py with CropConfig args. Returns exit code."""
    cmd = [
        sys.executable, "-m", "training.prepare_dataset",
        "--output-dir", str(output_dir),
        "--class-kind", class_kind,
        "--seed", str(seed),
        "--crop-margin-frac", str(config.margin_frac),
        "--crop-edge-mode", config.edge_mode,
        "--crop-feather-width-frac", str(config.feather_width_frac),
        "--crop-output-size", str(config.output_size),
    ]
    if raw_dir is not None:
        cmd += ["--raw-dir", str(raw_dir)]
    if only_classes:
        cmd += ["--only-classes", only_classes]
    if cohort_csv is not None:
        cmd += ["--cohort-csv", str(cohort_csv)]
    print(f"\n→ {' '.join(cmd)}\n")
    return subprocess.call(cmd, cwd=str(_ML_DIR))


def recrop_one(config: CropConfig, *,
                class_kind: str,
                raw_dir: Path | None = None,
                only_classes: str | None = None,
                seed: int = 42,
                force: bool = False,
                output_root: Path | None = None,
                cohort_csv: Path | None = None) -> Path:
    """Re-crop le dataset complet avec `config`. Retourne le path du dataset."""
    root = output_root or (_ML_DIR / "datasets")
    slug = _slug_for(config)
    output_dir = root / f"eurio-poc-{slug}"

    existing = _existing_config(output_dir)
    if existing is not None and existing == config and not force:
        print(f"✓ {output_dir.name} déjà à jour (config match) — skip "
              "(use --force pour regen).")
        return output_dir

    if output_dir.exists():
        if force:
            print(f"[force] suppression de {output_dir} avant regen")
            shutil.rmtree(output_dir)
        else:
            print(f"[regen] config différente détectée → suppression de {output_dir}")
            shutil.rmtree(output_dir)

    rc = _run_prepare(config, output_dir, class_kind, raw_dir, only_classes,
                      seed, cohort_csv)
    if rc != 0:
        raise SystemExit(f"prepare_dataset failed (rc={rc}) for slug={slug}")
    _write_crop_config_json(output_dir, config)
    print(f"\n✓ {output_dir} prêt (slug={slug}).")
    return output_dir


def load_sweep_from_json(path: Path) -> list[CropConfig]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise SystemExit(f"--sweep-from {path}: expected JSON list of config objs")
    return [CropConfig(**c) for c in raw]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-crop dataset avec CropConfig(s) alternatif(s)")
    parser.add_argument("--class-kind", choices=["eurio_id", "design_group"],
                         required=True,
                         help="Cohérent avec prepare_dataset (cf. iteration mode).")
    parser.add_argument("--raw-dir", type=Path, default=None,
                         help="Override raw_dir (défaut = ml/datasets/).")
    parser.add_argument("--only-classes", type=str, default=None,
                         help="Liste comma-separated des class_ids à garder. "
                              "Utile pour sweep ciblé (ex: 17 classes cohort).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true",
                         help="Regénère même si _crop_config.json matche.")
    parser.add_argument("--output-root", type=Path, default=None,
                         help="Override root output (défaut = ml/datasets/).")
    parser.add_argument("--cohort-csv", type=Path, default=None,
                         help="Résout les classes depuis ce CSV cohort "
                              "(eurio_id;numista_id;…) au lieu de Supabase. "
                              "Source de vérité offline ; entraîne exactement "
                              "les coins du CSV.")

    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--sweep-default", action="store_true",
                    help="Lance la matrice par défaut (12 combos margin×edge).")
    g.add_argument("--sweep-from", type=Path,
                    help="JSON list de CropConfig dicts à exécuter.")
    g.add_argument("--margin-frac", type=float,
                    help="Combo unique. Doit fournir aussi --edge-mode.")

    parser.add_argument("--edge-mode", choices=["hard", "feathered", "none"],
                         default=None)
    parser.add_argument("--feather-width-frac", type=float, default=0.04)
    parser.add_argument("--output-size", type=int, default=224)

    args = parser.parse_args()

    if args.sweep_default:
        configs = _DEFAULT_SWEEP
    elif args.sweep_from is not None:
        configs = load_sweep_from_json(args.sweep_from)
    else:
        if args.edge_mode is None:
            parser.error("--margin-frac requires --edge-mode")
        configs = [CropConfig(
            margin_frac=args.margin_frac,
            edge_mode=args.edge_mode,
            feather_width_frac=args.feather_width_frac,
            output_size=args.output_size,
        )]

    print(f"Sweep: {len(configs)} combo(s)")
    for i, c in enumerate(configs, 1):
        print(f"\n=== [{i}/{len(configs)}] {_slug_for(c)} ===")
        recrop_one(
            c,
            class_kind=args.class_kind,
            raw_dir=args.raw_dir,
            only_classes=args.only_classes,
            seed=args.seed,
            force=args.force,
            output_root=args.output_root,
            cohort_csv=args.cohort_csv,
        )
    print(f"\n✓ done — {len(configs)} dataset(s) sous "
          f"{(args.output_root or _ML_DIR / 'datasets')}/eurio-poc-*")


if __name__ == "__main__":
    main()
