"""Bundle generator for the per-cohort test app.

Reads a cohort + a model source (lab iteration OR prod current), copies
the trained TFLite + per-class embeddings, filters the prod catalog
snapshot to the cohort's eurio_ids, and emits metadata describing the
bundle, the prescribed live-test sequence, and the equivalence map.

Phase 4 (lab-prod-refacto) — `--source` est explicit :

    --source lab --iteration <iid>
        Reads from ``ml/lab/iterations/<iid>/{embeddings,tflite}/``.
        Used to A/B-test a candidate iteration on device.
    --source prod
        Reads from ``ml/prod/current/{embeddings,tflite}/`` (built by
        ``scripts.promote_iteration``). ``--iteration`` is optional ;
        when omitted, resolves the iteration that was promoted via
        ``prod/current/promoted_from.json``.

Layout produced (under ``--out``)::

    cohort_bundle/
      eurio_embedder_v1.tflite
      embeddings_v1.json         ← filtered to cohort eurio_ids
      model_meta.json
      catalog_snapshot.json      ← filtered to cohort eurio_ids
      bundle_meta.json           ← source + sha256 + identity
      live_tests_manifest.json
      equivalence_map.json       ← {eurio_id → design_group_id|null}

Invoked from ``app-android/Taskfile.yml`` via ``cohort-test:bundle``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ML_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_DIR.parent
STATE_DB = ML_DIR / "state" / "eurio.db"
LAB_ITERATIONS_DIR = ML_DIR / "lab" / "iterations"
PROD_CURRENT = ML_DIR / "prod" / "current"
# Catalogue d'affichage = app_core.db (P6 ; remplace le legacy
# catalog_snapshot.json). On en tire country/year/face_value/titres pour le
# manifest des live-tests (coin_display).
APP_CORE_DB = (
    REPO_ROOT / "app-android" / "src" / "main" / "assets" / "app_core.db"
)
BUNDLE_META_VERSION = 2

# OQ-4 — when the cohort holds many coins (≥30) the prescribed test list
# (one per coin × 3 conditions) becomes unmanageable. Cap at 9 tests
# (3 coins × 3 conditions) sampled deterministically. Sprint 4 may revisit
# the sampling strategy (zone-stratified, etc).
TEST_CONDITIONS: tuple[str, ...] = ("bright", "dim", "tilt")
SAMPLE_COIN_THRESHOLD = 30
SAMPLED_COIN_COUNT = 3

sys.path.insert(0, str(ML_DIR))
from training.eval.equivalence import build_equivalence_map  # noqa: E402
from store import Store, resolve_db_path  # noqa: E402
from shared.utils.i18n import coin_display  # noqa: E402

LIVE_TESTS_MANIFEST_VERSION = 2


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _coins_from_app_core_db(eurio_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Métadonnées d'affichage par eurio_id, lues depuis app_core.db (P6).

    Remplace le legacy catalog_snapshot.json. On ne ramène que ce dont
    ``coin_display`` a besoin pour le manifest des live-tests : pays, année,
    valeur faciale (en euros, dérivée de ``face_value_cents``), titres i18n
    (``coin_name_i18n``) et ``issue_type`` (circulation vs commémo). Les coins
    de la cohorte absents du catalogue sont simplement omis (coin_display gère
    le fallback slug côté appelant).
    """
    import sqlite3

    conn = sqlite3.connect(str(APP_CORE_DB))
    conn.row_factory = sqlite3.Row
    try:
        names: dict[str, dict[str, str]] = {}
        for r in conn.execute("SELECT eurio_id, lang, title FROM coin_name_i18n"):
            if r["eurio_id"] in eurio_ids:
                names.setdefault(r["eurio_id"], {})[r["lang"]] = r["title"]
        out: dict[str, dict[str, Any]] = {}
        qmarks = ",".join("?" * len(eurio_ids))
        rows = conn.execute(
            f"SELECT eurio_id, country, year, face_value_cents, is_commemorative "
            f"FROM coin WHERE eurio_id IN ({qmarks})",
            tuple(sorted(eurio_ids)),
        )
        for r in rows:
            eid = r["eurio_id"]
            n = names.get(eid, {})
            fvc = r["face_value_cents"]
            out[eid] = {
                "eurio_id": eid,
                "country": r["country"],
                "year": r["year"],
                "face_value": (fvc / 100) if fvc is not None else None,
                "name_fr": n.get("fr"),
                "name_en": n.get("en"),
                "issue_type": (
                    "circulation" if not r["is_commemorative"] else "commemorative"
                ),
            }
        return out
    finally:
        conn.close()


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


def _build_test_list(
    eurio_ids: list[str],
    coin_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Generate the prescribed test sequence.

    Each test entry carries a precomputed ``display`` block so the Android
    client renders human metadata (country FR, year, denom, image URL,
    title) without parsing the eurio_id slug on device.

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
        coin = coin_by_id.get(eid, {"eurio_id": eid})
        display = coin_display(coin)
        for condition in TEST_CONDITIONS:
            tests.append(
                {
                    "idx": idx,
                    "expected_eurio_id": eid,
                    "condition": condition,
                    "display": display,
                }
            )
            idx += 1
    return tests, sampled


def _build_coins_display(
    coin_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Per-cohort lookup map used by the Android sheet's "Le modèle a vu".

    Predictions stay inside the cohort's embedding bank, so this covers
    every reachable ``predicted_top1`` candidate. If that ever changes
    (full prod ranking from cohortTest), add a network fallback client-side.
    """
    return {eid: coin_display(coin) for eid, coin in coin_by_id.items()}


def _infer_class_kind(embeddings: dict[str, Any]) -> str:
    """Heuristic : majority class_kind across the bundled centroids.

    Lab iterations sortent toujours en eurio_id (cf. phase 1). La prod
    pourrait, hypothétiquement, mixer (option fusion). On reporte le
    plus fréquent, falling back sur 'eurio_id' si le manifest est vide
    ou ne porte pas l'info.
    """
    coins = embeddings.get("coins", {})
    counts: dict[str, int] = {}
    for v in coins.values():
        if isinstance(v, dict):
            kind = v.get("class_kind") or "eurio_id"
        else:
            kind = "eurio_id"
        counts[kind] = counts.get(kind, 0) + 1
    if not counts:
        return "eurio_id"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_source(
    args: argparse.Namespace, store: Store,
) -> tuple[Path, Path, Path, str | None]:
    """Resolve (tflite_path, embeddings_path, model_meta_path, iteration_id_or_none)
    based on ``--source``. Exits with a clear error if the source is incomplete.
    """
    if args.source == "lab":
        if not args.iteration:
            raise SystemExit(
                "error: --source lab requires --iteration <iid>",
            )
        iter_dir = LAB_ITERATIONS_DIR / args.iteration
        if not iter_dir.is_dir():
            raise SystemExit(
                f"error: lab iteration dir missing: {iter_dir}. "
                "Re-run training under the iteration runner."
            )
        return (
            iter_dir / "tflite" / "eurio_embedder_v1.tflite",
            iter_dir / "embeddings" / "embeddings_v1.json",
            iter_dir / "tflite" / "model_meta.json",
            args.iteration,
        )

    # --source prod
    if not PROD_CURRENT.is_dir():
        raise SystemExit(
            f"error: prod/current/ missing at {PROD_CURRENT}. "
            "Run `python -m scripts.promote_iteration <iid>` to populate "
            "it from a completed lab iteration before bundling --source prod."
        )
    promoted_meta = PROD_CURRENT / "promoted_from.json"
    iteration_id: str | None = args.iteration
    if iteration_id is None and promoted_meta.exists():
        try:
            iteration_id = json.loads(promoted_meta.read_text()).get("iteration_id")
        except (json.JSONDecodeError, OSError):
            iteration_id = None
    return (
        PROD_CURRENT / "tflite" / "eurio_embedder_v1.tflite",
        PROD_CURRENT / "embeddings" / "embeddings_v1.json",
        PROD_CURRENT / "tflite" / "model_meta.json",
        iteration_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", required=True, choices=["lab", "prod"],
        help="Where to read the model artefacts from. Phase 4 (lab-prod-refacto).",
    )
    parser.add_argument(
        "--cohort", required=True,
        help="Cohort id or name (passed verbatim to Store.get_cohort)",
    )
    parser.add_argument(
        "--iteration", default=None,
        help="Iteration id. Required with --source lab. Optional with --source "
             "prod (defaults to the iteration recorded in promoted_from.json).",
    )
    parser.add_argument(
        "--out", required=True,
        help="Destination directory (created if missing)",
    )
    args = parser.parse_args()

    # Honore EURIO_DB_PATH (Model B : itérations dans la réplique, pas le
    # eurio.db local legacy). Défaut = STATE_DB quand l'env est absent.
    store = Store(resolve_db_path(STATE_DB))
    cohort = store.get_cohort(args.cohort)
    if cohort is None:
        print(f"error: cohort {args.cohort!r} not found", file=sys.stderr)
        return 2

    tflite_path, embeddings_path, model_meta_path, iteration_id = (
        _resolve_source(args, store)
    )

    # When we have an iteration_id, validate it exists, belongs to the cohort,
    # and is completed. Tolerated only for --source prod when promoted_from.json
    # is missing — bundle the prod state without a strict iteration link.
    iteration = None
    if iteration_id is not None:
        iteration = store.get_iteration(iteration_id)
        if iteration is None:
            print(
                f"error: iteration {iteration_id!r} not found in {STATE_DB}",
                file=sys.stderr,
            )
            return 2
        if iteration.cohort_id != cohort.id:
            print(
                f"error: iteration {iteration.id} belongs to cohort "
                f"{iteration.cohort_id!r}, not {cohort.id!r}",
                file=sys.stderr,
            )
            return 2
        if args.source == "lab" and iteration.status != "completed":
            print(
                f"error: iteration {iteration.id} status is {iteration.status!r}, "
                "expected 'completed'. Bundle the model only after the run finishes.",
                file=sys.stderr,
            )
            return 2

    for label, p in (
        ("tflite", tflite_path),
        ("embeddings", embeddings_path),
        ("model_meta", model_meta_path),
    ):
        if not p.exists():
            print(
                f"error: {label} missing at {p} (source={args.source}). "
                "Check that training + export ran for this source.",
                file=sys.stderr,
            )
            return 3
    if not APP_CORE_DB.exists():
        print(
            f"error: {APP_CORE_DB.relative_to(REPO_ROOT)} missing (catalogue P6) "
            "— build/sync l'app_core.db Android d'abord.",
            file=sys.stderr,
        )
        return 3

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    eurio_ids = set(cohort.eurio_ids)

    # Maille des labels = COALESCE(design_group_id, eurio_id). Les embeddings
    # sont clés par class_id design_group pour les standards pluri-millésimes
    # (ex. be-2euro-albert-ii-t1), PAS par eurio_id. On résout donc les labels
    # de classe de la cohorte pour ne pas droper ces classes du bundle (sinon
    # le test on-device ne reconnaîtrait pas les coins standard). full_map est
    # réutilisé plus bas pour equivalence_map.json.
    full_map = build_equivalence_map()
    class_labels = {full_map.eurio_to_group.get(eid) or eid for eid in eurio_ids}

    # Copy raw model artefacts.
    shutil.copy2(tflite_path, out_dir / tflite_path.name)
    shutil.copy2(model_meta_path, out_dir / model_meta_path.name)

    # Filter embeddings to the cohort (par label de classe, design_group-aware).
    embeddings = json.loads(embeddings_path.read_text())
    filtered_embeddings = _filter_embeddings(embeddings, class_labels)
    (out_dir / embeddings_path.name).write_text(
        json.dumps(filtered_embeddings, ensure_ascii=False, indent=2)
    )

    # Métadonnées d'affichage des coins de la cohorte (app_core.db, P6).
    # Plus de catalog_snapshot.json filtré dans le bundle : il n'était lu par
    # aucun consommateur (l'app cohortTest lit equivalence_map + manifest, et
    # son catalogue vient du code partagé / app_core.db).
    coin_by_id = _coins_from_app_core_db(eurio_ids)

    # bundle_meta.json : source + identity + sha256. Source canonique côté
    # Android (BundleMeta.kt) pour l'écran "status / source du bundle".
    bundle_meta = {
        "schema_version": BUNDLE_META_VERSION,
        "source": args.source,
        "cohort_id": cohort.id,
        "cohort_name": cohort.name,
        "iteration_id": iteration_id,
        "iteration_name": iteration.name if iteration else None,
        "training_run_id": iteration.training_run_id if iteration else None,
        "model_version": embeddings.get("model") or "unknown",
        "num_classes": len(filtered_embeddings.get("coins", {})),
        "class_kind": _infer_class_kind(filtered_embeddings),
        "built_at": _iso_now(),
        "sha256": {
            tflite_path.name: _sha256(out_dir / tflite_path.name),
            embeddings_path.name: _sha256(out_dir / embeddings_path.name),
            model_meta_path.name: _sha256(out_dir / model_meta_path.name),
        },
    }
    (out_dir / "bundle_meta.json").write_text(
        json.dumps(bundle_meta, ensure_ascii=False, indent=2)
    )

    # Live tests prescription.
    tests, sampled = _build_test_list(cohort.eurio_ids, coin_by_id)
    coins_display = _build_coins_display(coin_by_id)
    manifest = {
        "version": LIVE_TESTS_MANIFEST_VERSION,
        "cohort_id": cohort.id,
        "iteration_id": iteration.id,
        "conditions": list(TEST_CONDITIONS),
        "sampled": sampled,
        "tests": tests,
        "coins_display": coins_display,
    }
    (out_dir / "live_tests_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )

    # Equivalence map (design_group_id) for the cohort. Source-of-truth unique
    # partagée avec le bench Python et le miroir Kotlin EquivalenceMap.kt (cf.
    # ml/eval/equivalence.py, ml/tests/test_equivalence.py). full_map déjà
    # construit plus haut (réutilisé pour le filtrage des embeddings).
    cohort_map = {
        eid: full_map.eurio_to_group.get(eid) for eid in sorted(eurio_ids)
    }
    (out_dir / "equivalence_map.json").write_text(
        json.dumps(cohort_map, ensure_ascii=False, indent=2, sort_keys=True)
    )

    print(
        f"OK · bundle written to {out_dir} "
        f"({len(coin_by_id)} coins, "
        f"{len(filtered_embeddings['coins'])} embeddings, "
        f"{len(tests)} tests{', sampled' if sampled else ''})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
