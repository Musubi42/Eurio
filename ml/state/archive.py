"""Export / import / prune the training state archive.

Two export modes:
  - lite : training.db only (~few MB, history + staging).
  - full : lite + datasets/eurio-poc/ + checkpoints/best_model.pth
           + output/{embeddings_v1,model_meta,coin_embeddings,per_class_metrics}.json
           + datasets/{numista_id}/augmented/ for every numista member of a
             trained class (so another machine can resume training).

Import auto-detects lite vs full from archive contents. Cohérence checks:
  - DB readable, PRAGMA integrity_check = ok.
  - Full: classes_after of the latest run ⊂ eurio-poc/train/ folders ⊂
          embeddings_v1.json coins.

Prune keeps only the most recent N runs (CASCADE drops steps/epochs/classes/logs).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = ML_DIR / "state"
DATASETS_DIR = ML_DIR / "datasets"
EURIO_POC = DATASETS_DIR / "eurio-poc"
CHECKPOINTS_DIR = ML_DIR / "checkpoints"
OUTPUT_DIR = ML_DIR / "output"
DB_PATH = STATE_DIR / "training.db"


# ─── Export ──────────────────────────────────────────────────────────────


def _checkpoint_wal() -> None:
    """Flush WAL before packaging so the archive is a single .db file."""
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _default_archive_name(mode: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Path.cwd() / f"eurio-ml-state-{mode}-{stamp}.tar.gz"


def export_lite(dest: Path | None = None) -> Path:
    _checkpoint_wal()
    out = dest or _default_archive_name("lite")
    with tarfile.open(out, "w:gz") as tar:
        if DB_PATH.exists():
            tar.add(DB_PATH, arcname="state/training.db")
    return out


def _trained_class_ids() -> list[str]:
    """Class ids present in the current prepared dataset manifest."""
    manifest = EURIO_POC / "class_manifest.json"
    if not manifest.exists():
        return []
    data = json.loads(manifest.read_text())
    return [c["class_id"] for c in data.get("classes", [])]


def _trained_numista_ids() -> list[int]:
    """Numista ids that have augmented/ dirs (= training sources)."""
    if not DATASETS_DIR.exists():
        return []
    ids: list[int] = []
    for d in DATASETS_DIR.iterdir():
        if not d.is_dir():
            continue
        try:
            nid = int(d.name)
        except ValueError:
            continue
        if (d / "augmented").exists():
            ids.append(nid)
    return sorted(ids)


def export_full(dest: Path | None = None) -> Path:
    _checkpoint_wal()
    out = dest or _default_archive_name("full")

    with tarfile.open(out, "w:gz") as tar:
        if DB_PATH.exists():
            tar.add(DB_PATH, arcname="state/training.db")

        if EURIO_POC.exists():
            tar.add(EURIO_POC, arcname="datasets/eurio-poc")

        best = CHECKPOINTS_DIR / "best_model.pth"
        if best.exists():
            tar.add(best, arcname="checkpoints/best_model.pth")

        for name in (
            "embeddings_v1.json",
            "model_meta.json",
            "coin_embeddings.json",
            "per_class_metrics.json",
        ):
            path = OUTPUT_DIR / name
            if path.exists():
                tar.add(path, arcname=f"output/{name}")

        for nid in _trained_numista_ids():
            aug = DATASETS_DIR / str(nid) / "augmented"
            if aug.exists():
                tar.add(aug, arcname=f"datasets/{nid}/augmented")
            for stem in ("obverse.jpg", "obverse.png", "reverse.jpg", "reverse.png"):
                source = DATASETS_DIR / str(nid) / stem
                if source.exists():
                    tar.add(source, arcname=f"datasets/{nid}/{stem}")

    return out


# ─── Import ──────────────────────────────────────────────────────────────


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract with path traversal protection."""
    dest = dest.resolve()
    for member in tar.getmembers():
        target = dest / member.name
        if not _is_within(dest, target):
            raise RuntimeError(f"Refusing unsafe path in archive: {member.name}")
    tar.extractall(dest)  # noqa: S202 — traversal guarded above


def import_archive(archive_path: Path) -> dict:
    """Unpack into ml/ and report what was restored + coherence warnings."""
    if not archive_path.exists():
        raise FileNotFoundError(archive_path)

    with tarfile.open(archive_path, "r:gz") as tar:
        names = tar.getnames()
        _safe_extract(tar, ML_DIR)

    restored = {
        "db": any(n.endswith("state/training.db") for n in names),
        "dataset": any(n.startswith("datasets/eurio-poc") for n in names),
        "checkpoint": any(n.endswith("checkpoints/best_model.pth") for n in names),
        "embeddings": any(n.endswith("output/embeddings_v1.json") for n in names),
    }
    warnings: list[str] = []

    if restored["db"]:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row and row[0] != "ok":
                warnings.append(f"SQLite integrity_check: {row[0]}")
            conn.close()
        except sqlite3.Error as exc:
            warnings.append(f"SQLite open failed: {exc}")

    manifest_classes = set(_trained_class_ids())
    disk_classes = set()
    train_dir = EURIO_POC / "train"
    if train_dir.exists():
        disk_classes = {d.name for d in train_dir.iterdir() if d.is_dir()}

    embedding_classes: set[str] = set()
    emb_path = OUTPUT_DIR / "embeddings_v1.json"
    if emb_path.exists():
        try:
            emb = json.loads(emb_path.read_text())
            embedding_classes = set(emb.get("coins", {}).keys())
        except json.JSONDecodeError:
            warnings.append("embeddings_v1.json not valid JSON")

    if manifest_classes and disk_classes and manifest_classes != disk_classes:
        missing = manifest_classes - disk_classes
        extra = disk_classes - manifest_classes
        if missing:
            warnings.append(f"classes in manifest but not on disk: {sorted(missing)}")
        if extra:
            warnings.append(f"classes on disk but not in manifest: {sorted(extra)}")

    if embedding_classes and manifest_classes and embedding_classes != manifest_classes:
        missing = manifest_classes - embedding_classes
        if missing:
            warnings.append(f"classes in manifest but missing embeddings: {sorted(missing)}")

    return {
        "archive": str(archive_path),
        "restored": restored,
        "warnings": warnings,
        "n_classes_on_disk": len(disk_classes),
        "n_classes_in_manifest": len(manifest_classes),
        "n_classes_in_embeddings": len(embedding_classes),
    }


# ─── Prune ───────────────────────────────────────────────────────────────


def prune_history(*, keep_last: int) -> dict:
    from .store import Store

    store = Store(DB_PATH)
    before = store.count_runs()
    deleted = store.prune_runs(keep_last=keep_last)
    store.wal_checkpoint()
    return {"kept": before - deleted, "deleted": deleted, "total_before": before}


# ─── CLI ─────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Eurio training state archive tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export", help="Export state as .tar.gz")
    e.add_argument("--mode", choices=["lite", "full"], default="lite")
    e.add_argument("--out", type=Path, default=None)

    i = sub.add_parser("import", help="Import a state .tar.gz")
    i.add_argument("archive", type=Path)

    p = sub.add_parser("prune", help="Prune old training runs")
    p.add_argument("--keep-last", type=int, default=100)

    args = parser.parse_args()

    if args.cmd == "export":
        out = export_full(args.out) if args.mode == "full" else export_lite(args.out)
        size_mb = out.stat().st_size / (1024 * 1024)
        print(f"Exported ({args.mode}): {out} ({size_mb:.1f} MB)")
        return 0

    if args.cmd == "import":
        result = import_archive(args.archive)
        print(json.dumps(result, indent=2))
        return 0 if not result["warnings"] else 1

    if args.cmd == "prune":
        result = prune_history(keep_last=args.keep_last)
        print(json.dumps(result, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
