"""Import des captures device dans le corpus de scan rejouable (Lot 3).

Spec : ``docs/work-in-progress/scan-quality/corpus-spec.md`` (§6 contrat
d'archivage, §12 Lot 3). Lit le JSONL live-tests pullé
(``ml/state/live_test_logs/<iteration>.jsonl``) + les frames pullées
(``ml/state/live_test_logs/frames/<iteration>/``), hash-vérifie
(``capture_id == sha256(raw)[:16]``), copie dans ``ml/state/scan_corpus/frames/``
et upsert la table ``scan_corpus``. Idempotent (dédup par ``capture_id``).

**Une ligne JSONL = une capture** — pas de best-of ici : le corpus garde chaque
frame (le best-of est la métrique produit §5, hors périmètre).

Mode backfill (``--backfill-debug-snaps``) : pour les sessions antérieures à
l'archivage Lot 2 (JSONL sans ``raw_sha``), reconstruit le lien frame↔ligne à
partir des snaps debug ``eurio_debug/photo_snaps/snap_<ts>/`` en matchant la
signature top-3 (eurio_id + similarité) du ``meta.json`` du snap contre la
ligne JSONL. Le crop debug est un JPEG q95 → transcodé en PNG (noté dans
``notes`` : la perte JPEG amont est actée, pas masquée).

Usage :
    python -m scripts.import_scan_corpus --iteration 5bf8edb0ad7d
    python -m scripts.import_scan_corpus --iteration 5bf8edb0ad7d \
        --backfill-debug-snaps debug_pull/<ts>/eurio_debug/photo_snaps

Interdit ici : toute référence à eurio.db / eurio.replica.db /
local_state_store() — le corpus est un store lab isolé (§4).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from store.scan_corpus import ScanCapture, ScanCorpusStore  # noqa: E402

LIVE_TEST_LOGS_DIR = ML_DIR / "state" / "live_test_logs"
COHORT_BUNDLE_OUTPUT_DIR = ML_DIR / "output"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as im:
        return im.width, im.height


def _load_jsonl(path: Path) -> list[dict]:
    lines: list[dict] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{i}: JSON invalide — {exc}")
        if obj.get("schema_version") != 1:
            raise SystemExit(f"{path}:{i}: schema_version != 1")
        lines.append(obj)
    return lines


def _resolve_cohort_id(iteration_id: str, explicit: str | None) -> str | None:
    if explicit:
        return explicit
    meta_path = COHORT_BUNDLE_OUTPUT_DIR / f"cohort_test_{iteration_id}" / "bundle_meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8")).get("cohort_id")
        except (json.JSONDecodeError, OSError):
            return None
    return None


@dataclass
class ImportStats:
    inserted: int = 0
    updated: int = 0
    skipped_error: int = 0
    skipped_no_sha: int = 0
    skipped_unmatched: int = 0
    hash_failures: int = 0

    def summary(self) -> str:
        return (
            f"inserted={self.inserted} updated={self.updated} "
            f"skipped_error={self.skipped_error} skipped_no_sha={self.skipped_no_sha} "
            f"skipped_unmatched={self.skipped_unmatched} hash_failures={self.hash_failures}"
        )


def _ingest_frame(
    store: ScanCorpusStore,
    line: dict,
    raw_src: Path,
    crop_src: Path | None,
    capture_id: str,
    cohort_id: str | None,
    notes: str | None,
    stats: ImportStats,
    crop_png_bytes: bytes | None = None,
) -> None:
    """Copie raw/crop dans le corpus (append-only) + upsert la ligne.

    ``crop_png_bytes`` : en backfill le crop vient d'un JPEG transcodé — les
    bytes PNG sont fournis directement au lieu d'un fichier source.
    """
    frames_dir = store.frames_dir
    frames_dir.mkdir(parents=True, exist_ok=True)
    readme = store.frames_root / "README.txt"
    if not readme.exists():
        readme.write_text(
            "source de vérité = table scan_corpus (store lab dédié scan_corpus.db, "
            "cf. docs/work-in-progress/scan-quality/corpus-spec.md §4)\n",
            encoding="utf-8",
        )
    raw_dst = frames_dir / f"{capture_id}.raw.jpg"
    crop_dst = frames_dir / f"{capture_id}.crop.png"

    if not raw_dst.exists():
        shutil.copyfile(raw_src, raw_dst)
    if not crop_dst.exists():
        if crop_png_bytes is not None:
            crop_dst.write_bytes(crop_png_bytes)
        elif crop_src is not None:
            shutil.copyfile(crop_src, crop_dst)

    raw_w, raw_h = _image_size(raw_dst)
    crop_w, crop_h = (None, None)
    if crop_dst.exists():
        crop_w, crop_h = _image_size(crop_dst)
        if (crop_w, crop_h) != (224, 224):
            print(f"  ⚠ {capture_id}: crop {crop_w}x{crop_h} (attendu 224x224)")

    capture = ScanCapture(
        capture_id=capture_id,
        eurio_id=str(line["expected_eurio_id"]),
        condition=str(line["condition"]),
        captured_at=str(line["ts"]),
        raw_path=str(raw_dst.relative_to(store.frames_root)),
        crop_path=str(crop_dst.relative_to(store.frames_root)),
        cohort_id=cohort_id,
        source_iteration_id=str(line["iteration_id"]),
        bundle_source=line.get("bundle_source"),
        raw_w=raw_w,
        raw_h=raw_h,
        crop_w=crop_w,
        crop_h=crop_h,
        device_model=line.get("device_model"),
        notes=notes,
    )
    if store.upsert_capture(capture):
        stats.inserted += 1
    else:
        stats.updated += 1


def import_archived(
    store: ScanCorpusStore,
    lines: list[dict],
    frames_dir: Path,
    cohort_id: str | None,
    stats: ImportStats,
) -> None:
    """Chemin nominal : JSONL avec raw_sha/crop_sha + frames archivées (Lot 2)."""
    for line in lines:
        if line.get("error"):
            stats.skipped_error += 1
            continue
        raw_sha = line.get("raw_sha")
        if not raw_sha:
            stats.skipped_no_sha += 1
            continue
        capture_id = raw_sha[:16]
        raw_src = frames_dir / f"{capture_id}.raw.jpg"
        crop_src = frames_dir / f"{capture_id}.crop.png"
        if not raw_src.exists():
            print(f"  ✗ {capture_id}: raw absent de {frames_dir}")
            stats.skipped_unmatched += 1
            continue
        actual = _sha256_file(raw_src)
        if actual != raw_sha:
            print(f"  ✗ {capture_id}: sha256(raw) = {actual[:16]}… ≠ raw_sha JSONL")
            stats.hash_failures += 1
            continue
        crop_sha = line.get("crop_sha")
        if crop_src.exists() and crop_sha and _sha256_file(crop_src) != crop_sha:
            print(f"  ✗ {capture_id}: sha256(crop) ≠ crop_sha JSONL")
            stats.hash_failures += 1
            continue
        _ingest_frame(
            store,
            line,
            raw_src,
            crop_src if crop_src.exists() else None,
            capture_id,
            cohort_id,
            notes=None,
            stats=stats,
        )


def _top3_signature(entries: list[dict], id_key: str, sim_key: str) -> tuple:
    return tuple((str(e[id_key]), round(float(e[sim_key]), 4)) for e in entries)


def import_backfill(
    store: ScanCorpusStore,
    lines: list[dict],
    snaps_dir: Path,
    cohort_id: str | None,
    stats: ImportStats,
) -> None:
    """Backfill pré-Lot 2 : matche snap debug ↔ ligne JSONL par signature top-3.

    Les JSONL d'avant l'archivage n'ont pas de ``raw_sha`` ; le seul lien
    frame↔prédiction est la prédiction elle-même (top-3 eurio_id+similarité,
    présente des deux côtés). Les timestamps ne sont PAS utilisés comme clé
    (device local vs UTC) — uniquement comme ordre au sein d'une signature
    dupliquée.
    """
    from PIL import Image
    import io

    # Index JSONL par signature top-3.
    by_sig: dict[tuple, list[dict]] = {}
    for line in lines:
        if line.get("error") or line.get("raw_sha"):
            continue  # les lignes archivées passent par import_archived
        sig = _top3_signature(line.get("predicted_top3") or [], "eurio_id", "similarity")
        by_sig.setdefault(sig, []).append(line)
    for group in by_sig.values():
        group.sort(key=lambda l: str(l.get("ts") or ""))

    snap_dirs = sorted(p for p in snaps_dir.iterdir() if p.is_dir())
    matched: dict[tuple, list[Path]] = {}
    for snap in snap_dirs:
        meta_path = snap / "meta.json"
        raw_path = snap / "raw.jpg"
        crop_path = snap / "crop.jpg"
        if not (meta_path.exists() and raw_path.exists()):
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        sig = _top3_signature(meta.get("matches") or [], "class", "sim")
        if sig in by_sig:
            matched.setdefault(sig, []).append(snap)

    for sig, snaps in matched.items():
        snaps.sort(key=lambda p: p.name)  # snap_<ts> → ordre chronologique device
        group = by_sig[sig]
        if len(snaps) != len(group):
            print(
                f"  ⚠ signature {sig[0] if sig else '∅'}: {len(snaps)} snaps vs "
                f"{len(group)} lignes JSONL — appariés dans l'ordre, surplus ignoré"
            )
        for snap, line in zip(snaps, group):
            raw_path = snap / "raw.jpg"
            crop_path = snap / "crop.jpg"
            capture_id = hashlib.sha256(raw_path.read_bytes()).hexdigest()[:16]
            crop_png: bytes | None = None
            if crop_path.exists():
                with Image.open(crop_path) as im:
                    buf = io.BytesIO()
                    im.convert("RGB").save(buf, format="PNG")
                    crop_png = buf.getvalue()
            _ingest_frame(
                store,
                line,
                raw_path,
                None,
                capture_id,
                cohort_id,
                notes=f"backfill photo_snaps {snap.name} (crop transcodé JPEG q95→PNG)",
                stats=stats,
                crop_png_bytes=crop_png,
            )

    n_matched_lines = sum(
        min(len(matched.get(sig, [])), len(group)) for sig, group in by_sig.items()
    )
    stats.skipped_unmatched += sum(len(g) for g in by_sig.values()) - n_matched_lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--iteration", required=True, help="iteration_id (ex. 5bf8edb0ad7d)")
    parser.add_argument("--jsonl", type=Path, default=None, help="override du JSONL pullé")
    parser.add_argument(
        "--frames-dir",
        type=Path,
        default=None,
        help="override du dossier frames pullé (défaut: live_test_logs/frames/<iteration>)",
    )
    parser.add_argument("--cohort-id", default=None, help="override (défaut: bundle_meta.json)")
    parser.add_argument(
        "--backfill-debug-snaps",
        type=Path,
        default=None,
        help="dossier photo_snaps pullé (sessions pré-archivage, match par top-3)",
    )
    parser.add_argument("--db", type=Path, default=None, help="override scan_corpus.db (tests)")
    args = parser.parse_args()

    jsonl_path = args.jsonl or (LIVE_TEST_LOGS_DIR / f"{args.iteration}.jsonl")
    if not jsonl_path.exists():
        raise SystemExit(f"JSONL introuvable : {jsonl_path}")
    lines = _load_jsonl(jsonl_path)
    lines = [l for l in lines if str(l.get("iteration_id")) == args.iteration]
    if not lines:
        raise SystemExit(f"Aucune ligne pour iteration {args.iteration} dans {jsonl_path}")

    cohort_id = _resolve_cohort_id(args.iteration, args.cohort_id)
    store = ScanCorpusStore(db_path=args.db)
    stats = ImportStats()

    frames_dir = args.frames_dir or (LIVE_TEST_LOGS_DIR / "frames" / args.iteration)
    if frames_dir.exists():
        import_archived(store, lines, frames_dir, cohort_id, stats)
    else:
        n_sha = sum(1 for l in lines if l.get("raw_sha"))
        if n_sha:
            print(f"⚠ {n_sha} lignes avec raw_sha mais pas de frames pullées ({frames_dir})")
        stats.skipped_no_sha += sum(1 for l in lines if not l.get("raw_sha") and not l.get("error"))
        stats.skipped_error += sum(1 for l in lines if l.get("error"))

    if args.backfill_debug_snaps:
        if not args.backfill_debug_snaps.is_dir():
            raise SystemExit(f"Dossier snaps introuvable : {args.backfill_debug_snaps}")
        # Le backfill re-considère les lignes sans raw_sha comptées skipped ci-dessus.
        stats.skipped_no_sha = 0
        import_backfill(store, lines, args.backfill_debug_snaps, cohort_id, stats)

    print(f"Import {args.iteration} → {store.db_path}")
    print(stats.summary())
    print(f"Corpus total : {store.count()} captures")
    if stats.hash_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
