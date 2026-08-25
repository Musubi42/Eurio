"""
Sync golden-set device snaps from a debug pull into ml/datasets/eval_real_norm/.

Walks ``<debug_pull_dir>/eurio_debug/eval_real/<eurio_id>/<step>_raw.jpg``,
runs ``normalize_device`` on each (mirrors the live Android Hough pipeline),
and writes the normalized 224×224 crop to
``ml/datasets/eval_real_norm/<class_id>/<step>.jpg``.

The output folder is keyed by **class_id** (= ``design_group_id`` when one
exists, otherwise ``eurio_id``), not by raw ``eurio_id``.  This matches the
layout expected by ``prepare_dataset.py``, which looks up val snaps under
``eval_real_norm/<class_id>/``.

The mapping is read from ``class_manifest.json`` produced by
``prepare_dataset.py``.  If the manifest is absent, output folders fall back
to the raw ``eurio_id`` (backward-compatible for commemoratives, where
class_id == eurio_id anyway).

⚠️ **Le nom de fichier porte le PROTOCOLE de prise de vue**, en premier token :
``<protocole>_<step>.jpg``. Ce n'est pas cosmétique. Mesuré le 2026-08-25 : les
pulls d'avril et de juin 2026 partagent deux noms d'étape (``bright_plain`` et
``bright_textured``), donc cumuler les deux corpus SANS ce préfixe écraserait
silencieusement les photos d'avril. Le token est lu par
``training.eval.real_photo_meta.parse_filename`` (axe ``protocol``), ce qui
permet de noter chaque protocole séparément ou ensemble.

⚠️ **``sync()`` est le SEUL chemin de traitement, et ``main()`` n'en est qu'une
enveloppe.** Les deux ont divergé pendant des mois, chacun n'implémentant que la
moitié du contrat : ``sync()`` — le chemin appelé par l'API — écrivait par
``eurio_id`` en ignorant le manifeste (d'où 7 dossiers sur 19 mal nommés), et
``main()`` résolvait bien la classe mais parsait ``--also-write-captures`` sans
jamais l'honorer. Ne réintroduis pas de seconde boucle de traitement ici.

Usage:
    python -m vision.sync_eval_real <debug_pull_dir> --protocol proto-2026-06
    python -m vision.sync_eval_real <debug_pull_dir> --also-write-captures

When ``--also-write-captures`` is set, every successfully normalized image is
*additionally* copied into ``ml/datasets/<numista_id>/captures/<step>.jpg``
(canonical capture store, eurio_id → numista_id via api.coin_lookup). Existing
files in captures/ are not overwritten unless ``--overwrite`` is given.

After running, prepare_dataset.py auto-detects the eval_real_norm/ tree and
populates each class's val/ split with these normalized device snaps,
replacing the (often empty) studio val split.

The :func:`sync` function is also called directly by the FastAPI endpoint
``POST /lab/cohorts/{id}/captures/sync`` and returns a structured report.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from .normalize_snap import normalize_device_path


ML_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ML_DIR / "datasets" / "eval_real_norm"
DEFAULT_MANIFEST = ML_DIR / "datasets" / "eurio-poc" / "class_manifest.json"
CAPTURES_BASE = ML_DIR / "datasets"


def _load_eurio_to_class(manifest_path: Path) -> dict[str, str]:
    """Build eurio_id → class_id map from class_manifest.json."""
    if not manifest_path.exists():
        return {}
    data = json.loads(manifest_path.read_text())
    mapping: dict[str, str] = {}
    for cls in data.get("classes", []):
        class_id = cls["class_id"]
        for eid in cls.get("eurio_ids", []):
            mapping[eid] = class_id
    return mapping


def _catalogue_eurio_to_class() -> dict[str, str]:
    """eurio_id → ``COALESCE(design_group_id, eurio_id)``, depuis le CATALOGUE.

    ⚠️ **C'est la source primaire, et le manifeste ne peut pas la remplacer.**
    Mesuré le 2026-08-25 : ``ml/datasets/eurio-poc/class_manifest.json`` date du
    5 mai, porte 414 mappings, et ne couvre que **5 des 17 classes** du pull de
    juin — dont **aucun** des 5 membres qui ont justement besoin d'être traduits
    (``ad-2014-2eur-standard-1st-type`` → ``ad-2euro-standard-t1``…). Le
    catalogue, lui, les résout tous les 17.

    La raison de fond : un ``class_manifest.json`` décrit le schéma de classes
    d'UNE itération (qui peut être ``class_kind='eurio_id'``), alors que le
    corpus d'évaluation survit aux itérations. Sa maille stable est celle du
    catalogue.

    Réutilise ``store.class_resolver`` (C3, stdlib-only, honore ``EURIO_DB_PATH``)
    plutôt que de refaire un COALESCE à la main — c'est le piège n°1 de ce dépôt.
    """
    try:
        from store.class_resolver import coin_refs_from_sqlite
    except Exception:
        return {}
    try:
        return {r.eurio_id: r.class_id for r in coin_refs_from_sqlite()}
    except Exception:
        # Base absente ou illisible : on retombe sur le manifeste seul, et le
        # rapport le dira via ``unmapped_to_class``.
        return {}


def _resolve_eval_real(pull_dir: Path) -> Path:
    """Accept either a raw pull root, the eurio_debug subfolder, or eval_real itself."""
    for candidate in (
        pull_dir / "eurio_debug" / "eval_real",
        pull_dir / "eval_real",
        pull_dir,
    ):
        if candidate.is_dir() and any(candidate.glob("*/*.jpg")):
            return candidate
    raise FileNotFoundError(
        f"Could not locate eval_real/ under {pull_dir} "
        "(expected <pull>/eurio_debug/eval_real/<class>/<step>_raw.jpg)"
    )


@dataclass
class SyncReport:
    pull_dir: str
    output_dir: str
    total_files: int = 0
    normalized: int = 0
    failures: list[str] = field(default_factory=list)
    per_class: dict[str, dict] = field(default_factory=dict)
    captures_copied: int = 0
    captures_skipped_existing: int = 0
    captures_unmapped_eurio_ids: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    protocol: str | None = None
    # eurio_id des dossiers source que le manifeste ne sait pas traduire. Ils
    # retombent sur leur eurio_id brut — c'est le repli documenté, mais il est
    # la cause des « classes fantômes » quand le manifeste est incomplet, donc
    # il se COMPTE au lieu de passer inaperçu.
    unmapped_to_class: list[str] = field(default_factory=list)
    overwritten: list[str] = field(default_factory=list)
    # Cas où le catalogue et le class_manifest.json ne donnent pas la même
    # classe pour un eurio_id. Le catalogue gagne ; le désaccord se dit.
    class_map_disagreements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pull_dir": self.pull_dir,
            "output_dir": self.output_dir,
            "protocol": self.protocol,
            "total_files": self.total_files,
            "normalized": self.normalized,
            "failures": self.failures,
            "per_class": self.per_class,
            "captures_copied": self.captures_copied,
            "captures_skipped_existing": self.captures_skipped_existing,
            "captures_unmapped_eurio_ids": self.captures_unmapped_eurio_ids,
            "unmapped_to_class": self.unmapped_to_class,
            "overwritten": self.overwritten,
            "class_map_disagreements": self.class_map_disagreements,
            "duration_s": round(self.duration_s, 2),
        }


def sync(
    pull_dir: Path,
    *,
    output: Path = DEFAULT_OUTPUT,
    manifest: Path = DEFAULT_MANIFEST,
    protocol: str | None = None,
    clear: bool = False,
    also_write_captures: bool = False,
    overwrite: bool = False,
) -> SyncReport:
    """Programmatic entry point — le SEUL chemin de traitement (cf. module docstring).

    ``protocol`` devient le premier token du nom de fichier. Sans lui, deux pulls
    qui partagent un nom d'étape s'écrasent l'un l'autre en silence ; les
    écrasements effectifs sont donc comptés dans ``report.overwritten``.
    """
    started = time.time()
    src_root = _resolve_eval_real(pull_dir)
    if clear and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    # Résolution eurio_id → class_id. C'était la moitié du contrat que ce chemin
    # n'honorait pas : sans elle, une pièce COURANTE atterrit dans un dossier
    # nommé par son membre au lieu de son groupe de dessin, et toute lecture du
    # corpus compte des classes qui n'existent pas.
    #
    # Le CATALOGUE est primaire (cf. _catalogue_eurio_to_class) ; le manifeste ne
    # comble que ce qu'il ignore. Leurs désaccords sont comptés, jamais absorbés
    # en silence — c'est précisément une divergence muette qui a produit le défaut.
    eurio_to_class = _catalogue_eurio_to_class()
    manifest_map = _load_eurio_to_class(manifest)
    disagreements: list[str] = []
    for eid, cls in manifest_map.items():
        if eid not in eurio_to_class:
            eurio_to_class[eid] = cls
        elif eurio_to_class[eid] != cls:
            disagreements.append(f"{eid}: catalogue={eurio_to_class[eid]} manifeste={cls}")

    raw_files = sorted(src_root.glob("*/*_raw.jpg"))
    report = SyncReport(
        pull_dir=str(pull_dir), output_dir=str(output), protocol=protocol
    )
    report.total_files = len(raw_files)
    report.class_map_disagreements = disagreements

    if also_write_captures:
        # Lazy import — keep the script usable without FastAPI deps.
        from serving import coin_lookup  # noqa: WPS433
    else:
        coin_lookup = None  # type: ignore[assignment]

    by_class: dict[str, list[bool]] = {}
    for raw in raw_files:
        eurio_id = raw.parent.name
        class_id = eurio_to_class.get(eurio_id, eurio_id)
        if eurio_id not in eurio_to_class and eurio_id not in report.unmapped_to_class:
            report.unmapped_to_class.append(eurio_id)
        step_id = raw.stem.removesuffix("_raw")
        out_name = f"{protocol}_{step_id}.jpg" if protocol else f"{step_id}.jpg"
        result = normalize_device_path(raw)
        ok = result.image is not None
        by_class.setdefault(class_id, []).append(ok)
        if not ok:
            report.failures.append(str(raw))
            continue
        out_dir = output / class_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / out_name
        if out_path.exists():
            report.overwritten.append(str(out_path.relative_to(output)))
        cv2.imwrite(
            str(out_path),
            result.image,
            [cv2.IMWRITE_JPEG_QUALITY, 95],
        )
        report.normalized += 1

        if also_write_captures and coin_lookup is not None:
            nid = coin_lookup.numista_id_for(eurio_id)
            if nid is None:
                if eurio_id not in report.captures_unmapped_eurio_ids:
                    report.captures_unmapped_eurio_ids.append(eurio_id)
            else:
                cap_dir = CAPTURES_BASE / str(nid) / "captures"
                cap_dir.mkdir(parents=True, exist_ok=True)
                cap_path = cap_dir / f"{step_id}.jpg"
                if cap_path.exists() and not overwrite:
                    report.captures_skipped_existing += 1
                else:
                    cv2.imwrite(
                        str(cap_path),
                        result.image,
                        [cv2.IMWRITE_JPEG_QUALITY, 95],
                    )
                    report.captures_copied += 1

    for cls, results in sorted(by_class.items()):
        report.per_class[cls] = {"normalized": sum(results), "total": len(results)}

    report.duration_s = time.time() - started
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pull_dir", type=Path,
                    help="Path to the debug pull (e.g. debug_pull/<ts>/)")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                    help=f"Output root (default: {DEFAULT_OUTPUT})")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                    help=f"class_manifest.json for eurio_id→class_id resolution "
                         f"(default: {DEFAULT_MANIFEST})")
    ap.add_argument("--clear", action="store_true",
                    help="Wipe the output dir before writing (avoids stale classes)")
    ap.add_argument("--also-write-captures", action="store_true",
                    help="Also copy each normalized image to ml/datasets/<numista_id>/captures/")
    ap.add_argument("--overwrite", action="store_true",
                    help="With --also-write-captures, overwrite existing captures/<step>.jpg")
    ap.add_argument("--protocol", default=None,
                    help="Protocole de prise de vue, premier token du nom de fichier "
                         "(ex. proto-2026-06). SANS lui, deux pulls qui partagent un nom "
                         "d'étape s'écrasent en silence — cf. docstring du module.")
    args = ap.parse_args()

    # ⚠️ Une SEULE boucle de traitement existe, c'est sync(). main() ne fait que
    # l'appeler et mettre en forme. Réintroduire une boucle ici recréerait la
    # divergence qui a produit 7 dossiers mal nommés sur 19.
    try:
        report = sync(
            args.pull_dir,
            output=args.output,
            manifest=args.manifest,
            protocol=args.protocol,
            clear=args.clear,
            also_write_captures=args.also_write_captures,
            overwrite=args.overwrite,
        )
    except FileNotFoundError as exc:
        print(f"  {exc}", file=sys.stderr)
        return 1

    if report.total_files == 0:
        print(f"  no *_raw.jpg under {args.pull_dir}", file=sys.stderr)
        return 1

    print(f"Source: {args.pull_dir}")
    print(f"Output: {args.output}")
    print(f"Protocole: {args.protocol or '(aucun — risque d écrasement en cumul)'}")
    print()
    for class_id, stats in sorted(report.per_class.items()):
        print(f"  {class_id:55s}  {stats['normalized']}/{stats['total']} normalized")

    print(f"\nTotal: {report.normalized}/{report.total_files} → {args.output}")

    # Les trois compteurs qui rendent visible ce qui était muet.
    if report.unmapped_to_class:
        print(f"\n⚠️  {len(report.unmapped_to_class)} eurio_id absents du manifeste "
              f"(repli sur l'eurio_id brut — classes fantômes possibles) :")
        for eid in report.unmapped_to_class:
            print(f"  ~ {eid}")
    if report.class_map_disagreements:
        print(f"\n⚠️  {len(report.class_map_disagreements)} désaccord(s) "
              f"catalogue ↔ manifeste (le catalogue gagne) :")
        for d in report.class_map_disagreements:
            print(f"  ≠ {d}")
    if report.overwritten:
        print(f"\n⚠️  {len(report.overwritten)} fichier(s) ÉCRASÉ(S) :")
        for p in report.overwritten:
            print(f"  ! {p}")
    if report.failures:
        print(f"\nFailures ({len(report.failures)}):")
        for f in report.failures:
            print(f"  ✗ {f}")
    return 0 if not report.failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
