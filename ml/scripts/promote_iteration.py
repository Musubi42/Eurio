"""Promote a lab iteration to ``ml/prod/current/`` (phase 3, lab-prod-refacto).

Une seule action déclenche : copie atomique des artefacts lab → prod,
backup de la prod précédente sous ``prod/archive/``, écriture de
``promoted_from.json`` (avec sha256), puis push Supabase via
``seed_supabase.py``.

Usage::

    .venv/bin/python -m scripts.promote_iteration <iteration_id>
    .venv/bin/python -m scripts.promote_iteration <iid> --dry-run
    .venv/bin/python -m scripts.promote_iteration <iid> --force
    .venv/bin/python -m scripts.promote_iteration <iid> --replace-all

Voir ``docs/lab-prod-refacto/phase-3-promote.md`` pour la sémantique
complète (Option B équivalence, accumulate par défaut, lock concurrent).
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store, resolve_db_path  # noqa: E402

LAB_ITERATIONS_DIR = ML_DIR / "lab" / "iterations"
PROD_DIR = ML_DIR / "prod"
PROD_CURRENT = PROD_DIR / "current"
PROD_ARCHIVE = PROD_DIR / "archive"
PROD_LOCK = PROD_DIR / ".promote.lock"
# Même DB que le serveur et que les entrypoints détachés (`training/run_*.py`) :
# `EURIO_DB_PATH` d'abord, `state/eurio.db` en repli. Le chemin était codé en dur
# ici, ce qui rendait la promotion IMPOSSIBLE dès que l'itération avait été
# calculée ailleurs — le mode compute du flip Direction A écrit dans
# `state/eurio.work.db`, et `promote_iteration <iid>` répondait « not found in
# …/eurio.db » alors que le modèle et ses artefacts étaient complets sur disque.
STATE_DB = resolve_db_path(ML_DIR / "state" / "eurio.db")
VENV_PYTHON = str(ML_DIR / ".venv" / "bin" / "python")

VALID_VERDICTS = {"baseline", "better"}
ARTIFACT_SUBDIRS = ("checkpoints", "embeddings", "tflite")

logger = logging.getLogger("promote")


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_tree(root: Path) -> dict[str, str]:
    """sha256 every regular file under root, keyed by repo-relative path."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = _sha256(p)
    return out


@contextlib.contextmanager
def _promote_lock():
    """File lock — bails out if another promotion is in flight.

    Cf. phase-3-promote.md §"Pièges à éviter — Supabase eventually
    consistent". Si plusieurs promotions s'enchaînent, l'ordre des
    PATCH/POST/DELETE peut donner un état intermédiaire incohérent.
    """
    PROD_DIR.mkdir(parents=True, exist_ok=True)
    if PROD_LOCK.exists():
        try:
            pid = int(PROD_LOCK.read_text().strip())
        except (ValueError, OSError):
            pid = -1
        raise SystemExit(
            f"Promotion already in flight (lock {PROD_LOCK} owned by pid {pid}). "
            "Si le processus est mort, supprime le fichier à la main."
        )
    PROD_LOCK.write_text(str(os.getpid()))
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            PROD_LOCK.unlink()


def _validate_iteration(iid: str, *, force: bool) -> dict:
    """Check that the iteration exists, is completed, and has a valid verdict."""
    store = Store(STATE_DB)
    it = store.get_iteration(iid)
    if it is None:
        raise SystemExit(
            f"Iteration {iid} not found in {STATE_DB} "
            f"(EURIO_DB_PATH={os.environ.get('EURIO_DB_PATH') or '<absent>'}). "
            "Si l'itération a été calculée sous un autre EURIO_DB_PATH (mode "
            "compute, réplique…), relance la promotion avec le même."
        )
    if it.status != "completed" and not force:
        raise SystemExit(
            f"Iteration {iid} is status={it.status!r}, expected 'completed' "
            "(use --force to override)."
        )
    verdict = it.verdict_override or it.verdict
    if verdict not in VALID_VERDICTS and not force:
        raise SystemExit(
            f"Iteration {iid} verdict={verdict!r}, expected one of "
            f"{sorted(VALID_VERDICTS)} (use --force to override)."
        )
    # Promouvoir depuis une base qui ne porte pas le run, c'est perdre la
    # traçabilité en silence : `promoted_from.json` enregistrerait
    # `training_run_id: null`, et plus rien ne relierait le modèle en prod à ce
    # qui l'a produit. Le cas est atteignable sans le vouloir — le devShell
    # pointe `EURIO_DB_PATH` sur la RÉPLIQUE, et le canonique null les
    # `*_run_id` (les tables de run ne lui sont jamais poussées, cf.
    # `serving/iteration_sync_routes.py`). La réplique dit donc `completed`
    # avec `run=NULL` pendant que la base de calcul porte le vrai lien.
    # Constaté pendant l'exercice #1 du parcours 4 (2026-08-16).
    if it.training_run_id is None and not force:
        raise SystemExit(
            f"Iteration {iid} est 'completed' mais SANS training_run_id dans "
            f"{STATE_DB}. Cette base ne porte pas le run — c'est typiquement la "
            "réplique du canonique, qui n'a jamais reçu les tables de run. "
            "Promeus depuis la base de CALCUL (celle où l'entraînement a "
            "tourné) : EURIO_DB_PATH=<…/eurio.work*.db>. "
            "--force passe outre, au prix d'un promoted_from.json sans lien "
            "vers le run."
        )
    iter_dir = LAB_ITERATIONS_DIR / iid
    missing = [
        sub for sub in ARTIFACT_SUBDIRS
        if not (iter_dir / sub).is_dir()
        or not any((iter_dir / sub).iterdir())
    ]
    if missing:
        raise SystemExit(
            f"Iteration {iid} missing artifact dirs: {missing}. "
            f"Expected non-empty under {iter_dir}/. "
            "Re-run training before promoting."
        )
    return {
        "id": it.id,
        "name": it.name,
        "cohort_id": it.cohort_id,
        "status": it.status,
        "verdict": verdict,
        "training_run_id": it.training_run_id,
        "benchmark_run_id": it.benchmark_run_id,
        "iter_dir": iter_dir,
    }


def _diff_classes(iter_dir: Path) -> dict:
    """Compare iter embeddings classes vs current prod embeddings classes."""
    new_path = iter_dir / "embeddings" / "embeddings_v1.json"
    cur_path = PROD_CURRENT / "embeddings" / "embeddings_v1.json"
    new_classes = set(json.loads(new_path.read_text()).get("coins", {}))
    cur_classes: set[str] = set()
    if cur_path.exists():
        cur_classes = set(json.loads(cur_path.read_text()).get("coins", {}))
    return {
        "added": sorted(new_classes - cur_classes),
        "kept": sorted(new_classes & cur_classes),
        "absent_in_promotion": sorted(cur_classes - new_classes),
        "n_new": len(new_classes),
        "n_current": len(cur_classes),
    }


def _atomic_copy(src_iter_dir: Path, dest_dir: Path) -> None:
    """Copy iter_dir/{checkpoints,embeddings,tflite}/ → dest_dir/, atomically.

    The atomic guarantee : we build the full new tree under a sibling
    ``<dest>.new-<ts>/`` directory, then ``os.replace`` it onto dest_dir
    after backing dest_dir up. A concurrent reader sees either the old
    tree or the new one — never a half-written one.
    """
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = dest_dir.parent / f"{dest_dir.name}.new-{int(time.time() * 1000)}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for sub in ARTIFACT_SUBDIRS:
        shutil.copytree(src_iter_dir / sub, staging / sub)
    # os.replace is atomic on POSIX for same-filesystem renames. We move
    # the old dest aside first (already done by caller via _archive), so
    # this rename is into a non-existent path.
    os.replace(staging, dest_dir)


def _archive_current(promoted_from_iid: str | None) -> Path | None:
    """Move PROD_CURRENT → PROD_ARCHIVE/<previous_iid>-<timestamp>/.

    Returns the archive path, or None if there was nothing to archive.
    """
    if not PROD_CURRENT.exists():
        return None
    PROD_ARCHIVE.mkdir(parents=True, exist_ok=True)
    label = promoted_from_iid or "unknown"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = PROD_ARCHIVE / f"{label}-{ts}"
    # Defensive : if the same-second target exists (very unlikely), append a
    # microsecond suffix so we never collide.
    while target.exists():
        target = PROD_ARCHIVE / f"{label}-{ts}-{int(time.time_ns())}"
    shutil.move(str(PROD_CURRENT), str(target))
    logger.info("Archived previous prod → %s", target)
    return target


def _read_prev_iid() -> str | None:
    meta = PROD_CURRENT / "promoted_from.json"
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text()).get("iteration_id")
    except (json.JSONDecodeError, OSError):
        return None


def _write_promoted_from(iter_meta: dict, hashes: dict[str, str]) -> Path:
    payload = {
        "iteration_id": iter_meta["id"],
        "iteration_name": iter_meta["name"],
        "cohort_id": iter_meta["cohort_id"],
        "training_run_id": iter_meta["training_run_id"],
        "benchmark_run_id": iter_meta["benchmark_run_id"],
        "verdict": iter_meta["verdict"],
        "promoted_at": _iso_now(),
        "promoted_by": getpass.getuser(),
        "sha256": hashes,
    }
    out = PROD_CURRENT / "promoted_from.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return out


def _delete_supabase_classes_not_in(coin_class_ids: set[str]) -> None:
    """--replace-all : DELETE rows from model_classes / coin_embeddings whose
    class_id (or eurio_id) is absent from the new promotion. Cf.
    phase-3-promote.md §"Mismatch class set"."""
    import httpx
    from training.eval.class_resolver import load_env

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise SystemExit(
            "--replace-all requires SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY"
        )
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Prefer": "return=minimal",
    }
    rest_base = url.rstrip("/") + "/rest/v1"
    keep_quoted = ",".join(f'"{cid}"' for cid in sorted(coin_class_ids))
    if not keep_quoted:
        return
    with httpx.Client(headers=headers, timeout=60) as client:
        resp = client.delete(
            f"{rest_base}/model_classes?class_id=not.in.({keep_quoted})",
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Supabase DELETE model_classes failed ({resp.status_code}): "
                f"{resp.text}"
            )
        resp = client.delete(
            f"{rest_base}/coin_embeddings?eurio_id=not.in.({keep_quoted})",
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Supabase DELETE coin_embeddings failed ({resp.status_code}): "
                f"{resp.text}"
            )
    logger.info("--replace-all: pruned Supabase rows outside %d-class set",
                len(coin_class_ids))


def _push_supabase(embeddings_path: Path) -> None:
    cmd = [
        VENV_PYTHON,
        str(ML_DIR / "bootstrap" / "seed_supabase.py"),
        "--embeddings", str(embeddings_path),
    ]
    logger.info("Pushing Supabase via %s", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(ML_DIR))
    if rc != 0:
        raise RuntimeError(f"seed_supabase.py exited with {rc}")


def promote(args: argparse.Namespace) -> int:
    iter_meta = _validate_iteration(args.iteration_id, force=args.force)
    iter_dir: Path = iter_meta["iter_dir"]

    diff = _diff_classes(iter_dir)
    print(json.dumps({
        "iteration": iter_meta["id"],
        "verdict": iter_meta["verdict"],
        "diff": diff,
        "replace_all": args.replace_all,
        "dry_run": args.dry_run,
    }, indent=2))

    if args.dry_run:
        print("--dry-run: no copy, no Supabase write.")
        return 0

    with _promote_lock():
        prev_iid = _read_prev_iid()
        archived = _archive_current(prev_iid)

        try:
            _atomic_copy(iter_dir, PROD_CURRENT)
        except Exception:
            # Recovery : restore archive if the copy died mid-way and the
            # archive is the only surviving snapshot.
            if archived is not None and not PROD_CURRENT.exists():
                shutil.move(str(archived), str(PROD_CURRENT))
                logger.warning(
                    "Atomic copy failed — restored prod from archive %s",
                    archived,
                )
            raise

        hashes: dict[str, str] = {}
        for sub in ARTIFACT_SUBDIRS:
            hashes.update(
                {f"{sub}/{k}": v for k, v in _hash_tree(PROD_CURRENT / sub).items()}
            )
        meta_path = _write_promoted_from(iter_meta, hashes)
        logger.info("Wrote %s", meta_path)

        embeddings_path = PROD_CURRENT / "embeddings" / "embeddings_v1.json"
        if args.replace_all:
            new_classes = set(
                json.loads(embeddings_path.read_text()).get("coins", {})
            )
            _delete_supabase_classes_not_in(new_classes)
        _push_supabase(embeddings_path)

    print(json.dumps({
        "promoted": iter_meta["id"],
        "prod_current": str(PROD_CURRENT),
        "archived_previous": str(archived) if archived else None,
    }, indent=2))
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Promote a lab iteration to prod/current/",
    )
    parser.add_argument("iteration_id")
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass status / verdict checks. Use with care.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the diff and exit without copying or writing Supabase.",
    )
    parser.add_argument(
        "--replace-all", action="store_true",
        help="DELETE Supabase rows whose class_id/eurio_id is absent from the "
             "promotion before upserting. Default: accumulate (keep stale rows).",
    )
    return promote(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
