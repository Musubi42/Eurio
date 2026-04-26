"""Benchmark a trained embedder against the real-photo hold-out library.

PRD Bloc 3 core script. Stateless CLI — given a model checkpoint + (optionally)
a zone/eurio_id filter, it detects each real photo via YOLO (falling back to
centre-crop), computes the embedding, matches it against the centroids persisted
in ``ml/output/embeddings_v1.json``, and aggregates R@1/R@3/R@5, per-zone
metrics, per-coin metrics, a confusion matrix and the top-N confusions.

The resulting row is persisted in ``benchmark_runs`` (shared training.db) and
a full JSON report is written under ``ml/reports/``.

Strict hold-out: the photos consumed here MUST NOT appear in any training set —
this is asserted upstream (see ``ml/train_embedder.py::_assert_no_real_photos``).

Usage:
    .venv/bin/python evaluate_real_photos.py --model checkpoints/best_model.pth
    .venv/bin/python evaluate_real_photos.py \
        --model checkpoints/best_model.pth --zones green --recipe-id green-v2
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from eval.real_photo_meta import AXES, parse_filename  # noqa: E402
from state import BenchmarkRunRow, Store  # noqa: E402

logger = logging.getLogger("evaluate_real_photos")

DEFAULT_REAL_PHOTOS = ML_DIR / "data" / "real_photos"
DEFAULT_REPORTS_DIR = ML_DIR / "reports"
DEFAULT_CENTROIDS = ML_DIR / "output" / "embeddings_v1.json"
DEFAULT_DETECTOR = ML_DIR / "output" / "detection" / "coin_detector" / "weights" / "best.pt"
STATE_DB = ML_DIR / "state" / "training.db"


# ─── Centroids ──────────────────────────────────────────────────────────────


@dataclass
class Centroid:
    class_id: str
    class_kind: str
    eurio_ids: set[str]
    vector: np.ndarray  # shape (D,), L2-normalised

    def covers(self, eurio_id: str) -> bool:
        """Whether this centroid's class covers the given eurio_id.

        A design_group centroid covers every member eurio_id; an eurio_id
        centroid covers only itself. This mirrors the Android matching
        semantics (`EmbeddingMatcher`).
        """
        return eurio_id in self.eurio_ids or self.class_id == eurio_id


def load_centroids(path: Path) -> list[Centroid]:
    data = json.loads(path.read_text())
    out: list[Centroid] = []
    for class_id, info in data.get("coins", {}).items():
        vec = np.asarray(info["embedding"], dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        eurio_ids = set(info.get("eurio_ids", []))
        if info.get("class_kind", "eurio_id") == "eurio_id" and not eurio_ids:
            eurio_ids = {class_id}
        out.append(
            Centroid(
                class_id=class_id,
                class_kind=info.get("class_kind", "eurio_id"),
                eurio_ids=eurio_ids,
                vector=vec,
            )
        )
    return out


# ─── Models ─────────────────────────────────────────────────────────────────


class TorchEmbedder:
    """Thin adapter over the existing CoinEmbedder checkpoint."""

    def __init__(self, checkpoint_path: Path):
        import torch
        from train_embedder import CoinEmbedder, get_val_transforms

        self._torch = torch
        self._device = torch.device("cpu")  # CPU is fast enough for the bench volume
        ckpt = torch.load(checkpoint_path, map_location=self._device, weights_only=False)
        self._transform = get_val_transforms()
        self.embedding_dim = ckpt.get("embedding_dim", 256)
        self.model = CoinEmbedder(embedding_dim=self.embedding_dim)
        self.model.load_state_dict(ckpt["model_state_dict"])
        self.model.eval()
        self.model_name = ckpt.get("model_version") or f"v1-{ckpt.get('mode', 'unknown')}"

    def embed(self, image: Image.Image) -> np.ndarray:
        import torch

        tensor = self._transform(image).unsqueeze(0)
        with torch.no_grad():
            emb = self.model(tensor).cpu().numpy()[0]
        return emb.astype(np.float32)


class TFLiteEmbedder:
    """Fallback for `.tflite` checkpoints (deployed inference format)."""

    def __init__(self, checkpoint_path: Path):
        import tensorflow as tf  # type: ignore

        self.interpreter = tf.lite.Interpreter(model_path=str(checkpoint_path))
        self.interpreter.allocate_tensors()
        self.input_detail = self.interpreter.get_input_details()[0]
        self.output_detail = self.interpreter.get_output_details()[0]
        _, h, w, _ = self.input_detail["shape"]
        self._hw = (int(h), int(w))
        self.embedding_dim = int(self.output_detail["shape"][-1])
        self.model_name = checkpoint_path.stem

    def embed(self, image: Image.Image) -> np.ndarray:
        resized = image.resize(self._hw, Image.LANCZOS)
        arr = np.asarray(resized, dtype=np.float32) / 255.0
        # Match the TFLite mean/std: we follow the same torchvision normalisation
        # used by `get_val_transforms`.
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        arr = arr[None, ...]
        self.interpreter.set_tensor(self.input_detail["index"], arr)
        self.interpreter.invoke()
        out = self.interpreter.get_tensor(self.output_detail["index"])[0]
        norm = np.linalg.norm(out)
        if norm > 0:
            out = out / norm
        return out.astype(np.float32)


def load_embedder(checkpoint_path: Path):
    suffix = checkpoint_path.suffix.lower()
    if suffix in (".pth", ".pt"):
        return TorchEmbedder(checkpoint_path)
    if suffix == ".tflite":
        return TFLiteEmbedder(checkpoint_path)
    raise SystemExit(f"Unsupported model format: {suffix} (expected .pth/.pt/.tflite)")


# ─── Detection + cropping ──────────────────────────────────────────────────


class CoinCropper:
    """YOLO-backed coin cropper; falls back to centre-crop if YOLO is unavailable."""

    def __init__(self, detector_path: Path | None):
        self._yolo = None
        if detector_path is not None and detector_path.exists():
            try:
                from ultralytics import YOLO  # type: ignore

                self._yolo = YOLO(str(detector_path))
                logger.info("Loaded YOLO detector: %s", detector_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Cannot load YOLO detector (%s) — falling back to centre-crop", exc
                )
        else:
            logger.warning(
                "No YOLO detector at %s — falling back to centre-crop", detector_path
            )

    def crop(self, image: Image.Image) -> Image.Image:
        if self._yolo is None:
            return _centre_crop(image)
        try:
            results = self._yolo.predict(
                source=image, conf=0.25, iou=0.5, verbose=False
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("YOLO predict failed (%s) — centre-cropping", exc)
            return _centre_crop(image)
        if not results:
            return _centre_crop(image)
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or boxes.xyxy is None or len(boxes.xyxy) == 0:
            return _centre_crop(image)
        confs = boxes.conf.cpu().numpy() if hasattr(boxes.conf, "cpu") else np.asarray(boxes.conf)
        best = int(np.argmax(confs))
        xyxy = boxes.xyxy[best]
        if hasattr(xyxy, "cpu"):
            xyxy = xyxy.cpu().numpy()
        x1, y1, x2, y2 = [int(round(float(v))) for v in xyxy]
        w, h = image.size
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return _centre_crop(image)
        # Expand to a square bounding box centred on the detection.
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        side = max(x2 - x1, y2 - y1)
        side = int(round(side * 1.1))  # 10% margin
        half = side // 2
        sx1 = max(0, int(cx - half))
        sy1 = max(0, int(cy - half))
        sx2 = min(w, sx1 + side)
        sy2 = min(h, sy1 + side)
        return image.crop((sx1, sy1, sx2, sy2))


def _centre_crop(image: Image.Image) -> Image.Image:
    w, h = image.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return image.crop((left, top, left + side, top + side))


# ─── Matching + metrics ────────────────────────────────────────────────────


@dataclass
class PhotoResult:
    photo_path: str  # repo-relative
    ground_truth: str
    zone: str | None
    top5: list[tuple[str, float]]  # (class_id, similarity)
    hit_at: dict[int, bool]  # {1: True, 3: True, 5: True}
    conditions: dict = None  # type: ignore[assignment]  # populated post-init

    def __post_init__(self) -> None:
        if self.conditions is None:
            self.conditions = {}


def match_topk(embedding: np.ndarray, centroids: list[Centroid], k: int = 5) -> list[tuple[str, float]]:
    """Return top-K (class_id, similarity) pairs."""
    sims = np.array([float(np.dot(embedding, c.vector)) for c in centroids])
    order = np.argsort(-sims)[:k]
    return [(centroids[i].class_id, float(sims[i])) for i in order]


def _centroid_by_class_id(centroids: list[Centroid]) -> dict[str, Centroid]:
    return {c.class_id: c for c in centroids}


def compute_hits(top5: list[tuple[str, float]], ground_truth: str, centroids_by_id: dict[str, Centroid]) -> dict[int, bool]:
    hits: dict[int, bool] = {}
    for k in (1, 3, 5):
        covered = False
        for cls_id, _ in top5[:k]:
            c = centroids_by_id.get(cls_id)
            if c is not None and c.covers(ground_truth):
                covered = True
                break
        hits[k] = covered
    return hits


# ─── Photo library ─────────────────────────────────────────────────────────


SUPPORTED_EXTS = {".jpg", ".jpeg", ".png"}


def _iter_photos(
    root: Path,
    *,
    eurio_ids: set[str] | None,
) -> list[tuple[Path, str]]:
    """Return list of (path, eurio_id) under root, optional eurio_id filter."""
    if not root.exists():
        return []
    out: list[tuple[Path, str]] = []
    for coin_dir in sorted(root.iterdir()):
        if not coin_dir.is_dir() or coin_dir.name.startswith("_"):
            continue
        eid = coin_dir.name
        if eurio_ids is not None and eid not in eurio_ids:
            continue
        for f in sorted(coin_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                out.append((f, eid))
    return out


def _load_zones_from_manifest(root: Path) -> dict[str, str]:
    manifest = root / "_manifest.json"
    if not manifest.exists():
        return {}
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {c["eurio_id"]: c["zone"] for c in data.get("coins", []) if c.get("zone")}


# ─── Runner ────────────────────────────────────────────────────────────────


def run_benchmark(args: argparse.Namespace) -> int:
    root = Path(args.real_photos).resolve()
    model_path = Path(args.model).resolve()
    centroids_path = Path(args.centroids).resolve()
    reports_dir = Path(args.output_dir).resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)

    if not model_path.exists():
        raise SystemExit(f"Model checkpoint not found: {model_path}")
    if not centroids_path.exists():
        raise SystemExit(f"Centroids file not found: {centroids_path}")

    eurio_filter: set[str] | None = (
        set(_split_list(args.eurio_ids)) if args.eurio_ids else None
    )
    zone_filter: set[str] | None = (
        set(_split_list(args.zones)) if args.zones else None
    )

    zones_from_manifest = _load_zones_from_manifest(root)

    photos = _iter_photos(root, eurio_ids=eurio_filter)
    if zone_filter is not None:
        photos = [
            (p, eid) for (p, eid) in photos
            if zones_from_manifest.get(eid) in zone_filter
        ]

    if not photos:
        logger.error(
            "No photos to evaluate under %s "
            "(eurio_ids=%s, zones=%s). "
            "Run `go-task ml:benchmark:photos:check` to inspect the library.",
            root, eurio_filter, zone_filter,
        )
        return 2

    run_id = args.run_id or uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    store = Store(STATE_DB)

    # Resolve recipe_id (id or name) for traceability.
    resolved_recipe_id: str | None = None
    if args.recipe_id:
        r = store.get_recipe(args.recipe_id)
        if r is None:
            logger.warning(
                "Recipe %r not found in training.db — proceeding without link",
                args.recipe_id,
            )
        else:
            resolved_recipe_id = r.id

    centroids = load_centroids(centroids_path)
    centroids_by_id = _centroid_by_class_id(centroids)
    logger.info("Loaded %d centroids from %s", len(centroids), centroids_path)

    embedder = load_embedder(model_path)
    logger.info("Loaded model %s (%s)", embedder.model_name, model_path.suffix)

    detector_path = Path(args.detector) if args.detector else DEFAULT_DETECTOR
    cropper = CoinCropper(detector_path if detector_path.exists() else None)

    # Seed a "running" row so the API can surface progress.
    report_path = reports_dir / f"benchmark_{embedder.model_name}_{run_id}.json"
    store.create_benchmark_run(
        BenchmarkRunRow(
            id=run_id,
            model_path=str(model_path.relative_to(ML_DIR.parent) if model_path.is_relative_to(ML_DIR.parent) else model_path),
            model_name=embedder.model_name,
            training_run_id=None,
            recipe_id=resolved_recipe_id,
            eurio_ids=[],
            zones=sorted(zone_filter) if zone_filter else [],
            num_photos=0,
            num_coins=0,
            report_path=str(report_path.relative_to(ML_DIR.parent) if report_path.is_relative_to(ML_DIR.parent) else report_path),
            status="running",
            started_at=started_at,
        )
    )

    t0 = time.time()
    try:
        results = _evaluate_all(
            photos=photos,
            embedder=embedder,
            cropper=cropper,
            centroids=centroids,
            centroids_by_id=centroids_by_id,
            zones_from_manifest=zones_from_manifest,
        )
    except Exception as exc:  # noqa: BLE001
        store.update_benchmark_run(
            run_id,
            status="failed",
            error=str(exc),
            finished_at=_iso_now(),
        )
        raise

    duration_ms = int((time.time() - t0) * 1000)

    metrics, per_zone, per_coin, per_condition, confusion, top_confusions = _aggregate(
        results,
        top_n=args.top_confusions,
    )

    report = {
        "run_id": run_id,
        "model_path": str(model_path),
        "model_name": embedder.model_name,
        "recipe_id": resolved_recipe_id,
        "started_at": started_at,
        "finished_at": _iso_now(),
        "duration_ms": duration_ms,
        "num_photos": len(results),
        "num_coins": len({r.ground_truth for r in results}),
        "zones": sorted(zone_filter) if zone_filter else sorted({
            zones_from_manifest.get(r.ground_truth) or "unknown" for r in results
        }),
        "metrics": metrics,
        "per_zone": per_zone,
        "per_coin": per_coin,
        "per_condition": per_condition,
        "confusion_matrix": confusion,
        "top_confusions": top_confusions,
    }
    report_path.write_text(json.dumps(report, indent=2))

    store.update_benchmark_run(
        run_id,
        status="completed",
        num_photos=report["num_photos"],
        num_coins=report["num_coins"],
        r_at_1=metrics["r_at_1"],
        r_at_3=metrics["r_at_3"],
        r_at_5=metrics["r_at_5"],
        mean_spread=metrics["mean_spread"],
        per_zone=per_zone,
        per_coin=per_coin,
        per_condition=per_condition,
        confusion=confusion,
        top_confusions=top_confusions,
        report_path=str(report_path),
        finished_at=_iso_now(),
    )

    logger.info(
        "Benchmark %s done in %dms — R@1=%.3f R@3=%.3f R@5=%.3f",
        run_id, duration_ms, metrics["r_at_1"], metrics["r_at_3"], metrics["r_at_5"],
    )
    print(json.dumps({
        "run_id": run_id,
        "report_path": str(report_path),
        **metrics,
    }, indent=2))
    return 0


def _evaluate_all(
    *,
    photos: list[tuple[Path, str]],
    embedder,
    cropper: CoinCropper,
    centroids: list[Centroid],
    centroids_by_id: dict[str, Centroid],
    zones_from_manifest: dict[str, str],
) -> list[PhotoResult]:
    results: list[PhotoResult] = []
    for idx, (path, eurio_id) in enumerate(photos):
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                crop = cropper.crop(im)
            vec = embedder.embed(crop)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            top5 = match_topk(vec, centroids, k=5)
            hits = compute_hits(top5, eurio_id, centroids_by_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping %s: %s", path, exc)
            continue
        conditions = parse_filename(path.stem).to_dict()
        results.append(
            PhotoResult(
                photo_path=str(path.relative_to(ML_DIR.parent) if path.is_relative_to(ML_DIR.parent) else path),
                ground_truth=eurio_id,
                zone=zones_from_manifest.get(eurio_id),
                top5=top5,
                hit_at=hits,
                conditions=conditions,
            )
        )
        if (idx + 1) % 25 == 0:
            logger.info("  %d/%d photos scored", idx + 1, len(photos))
    return results


def _aggregate(results: list[PhotoResult], *, top_n: int) -> tuple[dict, dict, list, dict, dict, list]:
    n = len(results)
    if n == 0:
        return (
            {"r_at_1": 0.0, "r_at_3": 0.0, "r_at_5": 0.0, "mean_spread": 0.0, "median_spread": 0.0},
            {},
            [],
            {},
            {},
            [],
        )

    def _mean_hit(k: int) -> float:
        return float(sum(1 for r in results if r.hit_at.get(k)) / n)

    spreads = [
        (r.top5[0][1] - r.top5[1][1]) if len(r.top5) >= 2 else r.top5[0][1]
        for r in results
    ]
    metrics = {
        "r_at_1": round(_mean_hit(1), 6),
        "r_at_3": round(_mean_hit(3), 6),
        "r_at_5": round(_mean_hit(5), 6),
        "mean_spread": round(float(np.mean(spreads)), 6),
        "median_spread": round(float(np.median(spreads)), 6),
    }

    per_zone: dict[str, dict] = {}
    by_zone: dict[str, list[PhotoResult]] = {}
    for r in results:
        z = r.zone or "unknown"
        by_zone.setdefault(z, []).append(r)
    for z, rs in by_zone.items():
        per_zone[z] = {
            "r_at_1": round(sum(1 for r in rs if r.hit_at.get(1)) / len(rs), 6),
            "r_at_3": round(sum(1 for r in rs if r.hit_at.get(3)) / len(rs), 6),
            "r_at_5": round(sum(1 for r in rs if r.hit_at.get(5)) / len(rs), 6),
            "num_photos": len(rs),
        }

    per_coin_map: dict[str, list[PhotoResult]] = {}
    for r in results:
        per_coin_map.setdefault(r.ground_truth, []).append(r)
    per_coin = [
        {
            "eurio_id": eid,
            "zone": rs[0].zone,
            "num_photos": len(rs),
            "r_at_1": round(sum(1 for r in rs if r.hit_at.get(1)) / len(rs), 6),
            "r_at_3": round(sum(1 for r in rs if r.hit_at.get(3)) / len(rs), 6),
            "r_at_5": round(sum(1 for r in rs if r.hit_at.get(5)) / len(rs), 6),
        }
        for eid, rs in sorted(per_coin_map.items())
    ]

    # Per-condition metrics: R@1 / R@3 per axis value (lighting, background,
    # angle, distance, state). Only values observed in this run are returned;
    # unknown-axis photos are skipped for that axis specifically.
    per_condition: dict[str, dict[str, dict]] = {axis: {} for axis in AXES}
    for axis in AXES:
        buckets: dict[str, list[PhotoResult]] = {}
        for r in results:
            val = (r.conditions or {}).get(axis)
            if val is None:
                continue
            buckets.setdefault(val, []).append(r)
        for val, rs in buckets.items():
            per_condition[axis][val] = {
                "r_at_1": round(sum(1 for r in rs if r.hit_at.get(1)) / len(rs), 6),
                "r_at_3": round(sum(1 for r in rs if r.hit_at.get(3)) / len(rs), 6),
                "num_photos": len(rs),
            }
    # Drop axes with no data so the JSON stays readable.
    per_condition = {k: v for k, v in per_condition.items() if v}

    # Confusion matrix: ground_truth → predicted_top1 → count. Predicted is the
    # top-1 centroid's canonical eurio_id representative (first element of the
    # centroid's eurio_ids set, sorted for determinism) so the matrix keys are
    # all eurio_ids.
    confusion: dict[str, dict[str, int]] = {}
    for r in results:
        pred_top1 = r.top5[0][0] if r.top5 else ""
        # If the centroid name itself is an eurio_id, use it as predicted; else
        # map to sorted first eurio_id member (design_group case).
        predicted_label = pred_top1
        confusion.setdefault(r.ground_truth, {})
        confusion[r.ground_truth][predicted_label] = (
            confusion[r.ground_truth].get(predicted_label, 0) + 1
        )

    # Top-N confusions: lowest spread AND incorrect at top-1.
    incorrects = [
        r for r in results if not r.hit_at.get(1)
    ]
    incorrects.sort(key=lambda r: (r.top5[0][1] - r.top5[1][1]) if len(r.top5) >= 2 else 0.0)
    top_confusions = [
        {
            "photo_path": r.photo_path,
            "ground_truth": r.ground_truth,
            "zone": r.zone,
            "spread": round(
                (r.top5[0][1] - r.top5[1][1]) if len(r.top5) >= 2 else r.top5[0][1],
                6,
            ),
            "top_3": [
                {"class_id": cls, "similarity": round(sim, 6)}
                for cls, sim in r.top5[:3]
            ],
        }
        for r in incorrects[:top_n]
    ]

    return metrics, per_zone, per_coin, per_condition, confusion, top_confusions


# ─── Helpers ───────────────────────────────────────────────────────────────


def _split_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ─── CLI ───────────────────────────────────────────────────────────────────


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Benchmark a trained embedder on the real-photo hold-out."
    )
    p.add_argument("--model", required=True, help="Path to model (.pth/.pt/.tflite)")
    p.add_argument("--real-photos", default=str(DEFAULT_REAL_PHOTOS))
    p.add_argument("--centroids", default=str(DEFAULT_CENTROIDS))
    p.add_argument("--detector", default=None, help="YOLO weights for auto-crop")
    p.add_argument("--output-dir", default=str(DEFAULT_REPORTS_DIR))
    p.add_argument(
        "--eurio-ids",
        default=None,
        help="Optional CSV of eurio_ids to restrict the eval to.",
    )
    p.add_argument(
        "--zones",
        default=None,
        help="Optional CSV of zones (green,orange,red) to filter coins by.",
    )
    p.add_argument("--recipe-id", default=None, help="Recipe id/name for traceability.")
    p.add_argument("--run-id", default=None, help="Optional explicit run_id.")
    p.add_argument("--top-confusions", type=int, default=20)
    p.add_argument("--log-level", default="INFO")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return run_benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())
