"""Bundle generator for the per-cohort test app (Sprint 3).

Reads a cohort + iteration from the training SQLite store, copies the freshly
trained TFLite model + per-class embeddings, filters the prod catalog
snapshot to the cohort's eurio_ids, and emits two metadata files describing
the bundle and the prescribed live-test sequence.

Layout produced (under ``--out``)::

    cohort_bundle/
      eurio_embedder_v1.tflite   ← from ml/output/
      embeddings_v1.json         ← filtered to cohort eurio_ids
      model_meta.json            ← from ml/output/
      catalog_snapshot.json      ← filtered to cohort eurio_ids
      cohort_meta.json           ← cohort + iteration identity
      live_tests_manifest.json   ← test prescription (sprint 4 will read this)

Invoked from ``app-android/Taskfile.yml`` via ``cohort-test:bundle``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ML_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_DIR.parent
STATE_DB = ML_DIR / "state" / "training.db"
OUTPUT_DIR = ML_DIR / "output"
TFLITE_PATH = OUTPUT_DIR / "eurio_embedder_v1.tflite"
EMBEDDINGS_PATH = OUTPUT_DIR / "embeddings_v1.json"
MODEL_META_PATH = OUTPUT_DIR / "model_meta.json"
PROD_SNAPSHOT_PATH = (
    REPO_ROOT / "app-android" / "src" / "main" / "assets" / "catalog_snapshot.json"
)

# OQ-4 — when the cohort holds many coins (≥30) the prescribed test list
# (one per coin × 3 conditions) becomes unmanageable. Cap at 9 tests
# (3 coins × 3 conditions) sampled deterministically. Sprint 4 may revisit
# the sampling strategy (zone-stratified, etc).
TEST_CONDITIONS: tuple[str, ...] = ("bright", "dim", "tilt")
SAMPLE_COIN_THRESHOLD = 30
SAMPLED_COIN_COUNT = 3

sys.path.insert(0, str(ML_DIR))
from state import Store  # noqa: E402


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _filter_snapshot(snapshot: dict[str, Any], eurio_ids: set[str]) -> dict[str, Any]:
    """Trim coins/series/sets/set_members to entries that touch the cohort.

    Coins are filtered by membership; series are kept if at least one of
    their coins survives; sets are kept if any of their set_members
    survives; set_members are filtered to surviving coins.
    """
    coins = [c for c in snapshot.get("coins", []) if c.get("eurio_id") in eurio_ids]
    surviving_series = {c.get("series_id") for c in coins if c.get("series_id")}
    series = [
        s for s in snapshot.get("coin_series", [])
        if s.get("id") in surviving_series
    ]
    set_members = [
        m for m in snapshot.get("set_members", [])
        if m.get("eurio_id") in eurio_ids
    ]
    surviving_sets = {m.get("set_id") for m in set_members}
    sets = [s for s in snapshot.get("sets", []) if s.get("id") in surviving_sets]
    return {
        "catalog_version": snapshot.get("catalog_version"),
        "generated_at": snapshot.get("generated_at"),
        "coins": coins,
        "coin_series": series,
        "sets": sets,
        "set_members": set_members,
    }


def _filter_embeddings(
    embeddings: dict[str, Any], eurio_ids: set[str]
) -> dict[str, Any]:
    """Filter the per-class centroid bundle to the cohort.

    The embeddings file contains a ``coins`` dict keyed by class label
    (eurio_id by convention). Anything outside the cohort is dropped.
    """
    coins = embeddings.get("coins", {})
    filtered = {k: v for k, v in coins.items() if k in eurio_ids}
    return {
        **{k: v for k, v in embeddings.items() if k != "coins"},
        "coins": filtered,
    }


def _build_test_list(eurio_ids: list[str]) -> tuple[list[dict[str, Any]], bool]:
    """Generate the prescribed test sequence.

    Returns ``(tests, sampled)`` where ``sampled`` is True when the cohort
    was big enough to trigger OQ-4 stratification.
    """
    sampled = len(eurio_ids) >= SAMPLE_COIN_THRESHOLD
    coins = sorted(eurio_ids)
    if sampled:
        # Round-robin pick of the first SAMPLED_COIN_COUNT coins for now.
        # Sprint 4 may stratify by zone (vert/orange/rouge).
        coins = coins[:SAMPLED_COIN_COUNT]
    tests: list[dict[str, Any]] = []
    idx = 1
    for eid in coins:
        for condition in TEST_CONDITIONS:
            tests.append(
                {
                    "idx": idx,
                    "expected_eurio_id": eid,
                    "condition": condition,
                }
            )
            idx += 1
    return tests, sampled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cohort", required=True,
        help="Cohort id or name (passed verbatim to Store.get_cohort)",
    )
    parser.add_argument("--iteration", required=True, help="Iteration id")
    parser.add_argument(
        "--out", required=True,
        help="Destination directory (created if missing)",
    )
    parser.add_argument(
        "--allow-stale-tflite", action="store_true",
        help=(
            "Skip the mtime check that warns when the TFLite is older than "
            "the iteration's finished_at. Use with care."
        ),
    )
    args = parser.parse_args()

    store = Store(STATE_DB)
    cohort = store.get_cohort(args.cohort)
    if cohort is None:
        print(f"error: cohort {args.cohort!r} not found", file=sys.stderr)
        return 2

    iteration = store.get_iteration(args.iteration)
    if iteration is None:
        print(f"error: iteration {args.iteration!r} not found", file=sys.stderr)
        return 2
    if iteration.cohort_id != cohort.id:
        print(
            f"error: iteration {iteration.id} belongs to cohort "
            f"{iteration.cohort_id!r}, not {cohort.id!r}",
            file=sys.stderr,
        )
        return 2
    if iteration.status != "completed":
        print(
            f"error: iteration {iteration.id} status is {iteration.status!r}, "
            "expected 'completed'. Bundle the model only after the run finishes.",
            file=sys.stderr,
        )
        return 2

    if not TFLITE_PATH.exists():
        print(
            f"error: {TFLITE_PATH.relative_to(REPO_ROOT)} missing. "
            "Run `python -m training.export_tflite` after training.",
            file=sys.stderr,
        )
        return 3
    if not EMBEDDINGS_PATH.exists():
        print(
            f"error: {EMBEDDINGS_PATH.relative_to(REPO_ROOT)} missing.",
            file=sys.stderr,
        )
        return 3
    if not MODEL_META_PATH.exists():
        print(
            f"error: {MODEL_META_PATH.relative_to(REPO_ROOT)} missing.",
            file=sys.stderr,
        )
        return 3
    if not PROD_SNAPSHOT_PATH.exists():
        print(
            f"error: {PROD_SNAPSHOT_PATH.relative_to(REPO_ROOT)} missing. "
            "Run `go-task android:snapshot` first.",
            file=sys.stderr,
        )
        return 3

    # Sanity check on TFLite freshness — the file is a global export, so a
    # stale one would silently bundle the wrong weights. Compare mtime to
    # iteration.finished_at when available.
    if iteration.finished_at and not args.allow_stale_tflite:
        try:
            finished_dt = datetime.fromisoformat(
                iteration.finished_at.replace("Z", "+00:00")
            )
            tflite_dt = datetime.fromtimestamp(
                TFLITE_PATH.stat().st_mtime, tz=timezone.utc,
            )
            if tflite_dt < finished_dt:
                print(
                    f"warning: {TFLITE_PATH.name} mtime ({tflite_dt.isoformat()}) "
                    f"is older than iteration.finished_at ({iteration.finished_at}). "
                    "Re-run `python -m training.export_tflite` or pass --allow-stale-tflite.",
                    file=sys.stderr,
                )
                return 4
        except ValueError:
            pass

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    eurio_ids = set(cohort.eurio_ids)

    # Copy raw model artefacts.
    shutil.copy2(TFLITE_PATH, out_dir / TFLITE_PATH.name)
    shutil.copy2(MODEL_META_PATH, out_dir / MODEL_META_PATH.name)

    # Filter embeddings to the cohort.
    embeddings = json.loads(EMBEDDINGS_PATH.read_text())
    filtered_embeddings = _filter_embeddings(embeddings, eurio_ids)
    (out_dir / EMBEDDINGS_PATH.name).write_text(
        json.dumps(filtered_embeddings, ensure_ascii=False, indent=2)
    )

    # Filter catalog snapshot to the cohort.
    snapshot = json.loads(PROD_SNAPSHOT_PATH.read_text())
    filtered_snapshot = _filter_snapshot(snapshot, eurio_ids)
    (out_dir / "catalog_snapshot.json").write_text(
        json.dumps(filtered_snapshot, ensure_ascii=False, indent=2)
    )

    # Identity card.
    cohort_meta = {
        "cohort_id": cohort.id,
        "cohort_name": cohort.name,
        "iteration_id": iteration.id,
        "iteration_name": iteration.name,
        "model_version": embeddings.get("model") or "unknown",
        "trained_at": iteration.finished_at,
        "generated_at": _iso_now(),
        "num_coins": len(cohort.eurio_ids),
    }
    (out_dir / "cohort_meta.json").write_text(
        json.dumps(cohort_meta, ensure_ascii=False, indent=2)
    )

    # Live tests prescription.
    tests, sampled = _build_test_list(cohort.eurio_ids)
    manifest = {
        "version": 1,
        "cohort_id": cohort.id,
        "iteration_id": iteration.id,
        "conditions": list(TEST_CONDITIONS),
        "sampled": sampled,
        "tests": tests,
    }
    (out_dir / "live_tests_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )

    print(
        f"OK · bundle written to {out_dir} "
        f"({len(filtered_snapshot['coins'])} coins, "
        f"{len(filtered_embeddings['coins'])} embeddings, "
        f"{len(tests)} tests{', sampled' if sampled else ''})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
