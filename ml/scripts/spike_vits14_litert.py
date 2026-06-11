"""Spike — conversion dinov2_vits14 → LiteRT (.tflite) pour le scan Android.

Dérisque le bloquant identifié par le bench students (phase2-student-
findings.md) AVANT le fine-tune ArcFace : le backbone retenu (DINOv2
ViT-S/14) doit passer en LiteRT avec une parité numérique propre.

Étapes :
  1. Charge dinov2_vits14 (CPU) et FIGE le pos_embed à 224px — le
     checkpoint embarque un pos_embed 518px (1370 tokens) interpolé en
     bicubique à chaque forward, chemin dynamique que torch.export ne
     digère pas ; on pré-calcule via la méthode du modèle lui-même
     (``interpolate_pos_encoding``) → numériquement identique à l'eager.
  2. Wrappe avec la L2-normalisation (l'APK reçoit un embedding prêt
     pour le cosine, comme la banque d'ancres).
  3. Convertit en fp32 + variantes quantizées (dynamic-range int8, fp16)
     via ai-edge-torch.
  4. Valide chaque .tflite : cosine vs eager PyTorch sur des crops réels
     du set labellisé + accord top1 contre la banque vits14 (508 ancres
     2eur_commemo) + latence CPU (proxy desktop — la latence device
     réelle reste à mesurer dans l'APK).

Sorties : ml/output/spike/*.tflite + rapport markdown (--out).
Aucune écriture en DB.

Usage:
    .venv/bin/python -m scripts.spike_vits14_litert
    .venv/bin/python -m scripts.spike_vits14_litert --n-crops 24 --out spike.md
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

from training.foundation import (  # noqa: E402
    DINOV2_MODEL,
    DINOV2_REPO,
    bake_pos_encoding,
    build_transform,
    load_anchors,
)

DB_PATH = ML_DIR / "state" / "eurio.db"
OUT_DIR = ML_DIR / "output" / "spike"
INPUT_PX = 224


class L2Embedder(torch.nn.Module):
    """Backbone + L2-norm : l'embedding sort prêt pour le dot-product."""

    def __init__(self, backbone: torch.nn.Module):
        super().__init__()
        self.backbone = backbone

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.backbone(x), dim=1)


def load_crops(n: int) -> list[Path]:
    """N crops réels du set labellisé (cache local), déterministes."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT a.storage_path FROM review_queue rq
        JOIN image_assets a ON a.id = rq.image_asset_id
        WHERE rq.status='done' AND rq.decided_eurio_id IS NOT NULL
          AND a.storage_path IS NOT NULL
        ORDER BY rq.image_asset_id LIMIT ?
        """,
        (n * 2,),
    ).fetchall()
    conn.close()
    from shared.storage.local_cache import local_path

    out: list[Path] = []
    for r in rows:
        if len(out) >= n:
            break
        try:
            p = local_path("enrichment-crops", r["storage_path"])
        except FileNotFoundError:
            continue
        if p.is_file():
            out.append(p)
    return out


def eager_embeddings(model: torch.nn.Module, batches: torch.Tensor) -> np.ndarray:
    with torch.no_grad():
        return F.normalize(model(batches), dim=1).numpy().astype(np.float32)


def tflite_embeddings(
    tflite_path: Path, batches: torch.Tensor, *, runs_for_latency: int = 10
) -> tuple[np.ndarray, float]:
    """Run le .tflite image par image (batch=1, comme sur device).
    Renvoie (embeddings (N,D), latence moyenne ms/img)."""
    from ai_edge_litert.interpreter import Interpreter

    interp = Interpreter(model_path=str(tflite_path), num_threads=4)
    interp.allocate_tensors()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]

    embs: list[np.ndarray] = []
    times: list[float] = []
    for i in range(batches.shape[0]):
        x = batches[i : i + 1].numpy().astype(np.float32)
        t0 = time.perf_counter()
        interp.set_tensor(inp["index"], x)
        interp.invoke()
        times.append(time.perf_counter() - t0)
        embs.append(interp.get_tensor(out["index"])[0].astype(np.float32))
    # Latence : médiane des invocations au-delà du warm-up.
    lat = sorted(times[2:] or times)[len(times[2:] or times) // 2] * 1000
    return np.vstack(embs), lat


def cosine_rows(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    b = b / np.linalg.norm(b, axis=1, keepdims=True)
    return (a * b).sum(axis=1)


def top1_ids(embs: np.ndarray, bank_matrix: np.ndarray, bank_ids: list[str]) -> list[str]:
    sims = embs @ bank_matrix.T
    return [bank_ids[int(i)] for i in sims.argmax(axis=1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-crops", type=int, default=24)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: list[str] = [
        "# Spike — dinov2_vits14 → LiteRT",
        "",
        f"- ai-edge-torch + ai-edge-litert, torch {torch.__version__}, "
        f"input {INPUT_PX}×{INPUT_PX}, batch 1 (comme on-device)",
        "- Parité mesurée sur crops réels du set labellisé ; accord top1 "
        "contre la banque vits14 `2eur_commemo` (508 ancres).",
        "- Latence = médiane CPU 4 threads sur cette machine (PROXY — la "
        "latence device réelle se mesure dans l'APK).",
        "",
    ]
    add = report.append

    print("Loading dinov2_vits14 (CPU)…", file=sys.stderr)
    backbone = torch.hub.load(DINOV2_REPO, DINOV2_MODEL, pretrained=True)
    backbone.eval()

    # Référence eager AVANT bake (= exactement le modèle des prédictions serveur).
    transform = build_transform()
    crop_paths = load_crops(args.n_crops)
    if len(crop_paths) < 8:
        raise RuntimeError(f"Seulement {len(crop_paths)} crops locaux — cache vide ?")
    from PIL import Image

    batch = torch.stack(
        [transform(Image.open(p).convert("RGB")) for p in crop_paths]
    )
    ref = eager_embeddings(backbone, batch)

    # Bake pos_embed 224 + vérif numérique du bake en eager.
    bake_pos_encoding(backbone)
    baked = eager_embeddings(backbone, batch)
    bake_cos = cosine_rows(ref, baked)
    add(f"- Crops de test : {len(crop_paths)}")
    add(f"- Bake pos_embed 518→224 : cosine vs original min={bake_cos.min():.6f} "
        f"mean={bake_cos.mean():.6f} (attendu ≈ 1.0)")
    add("")
    print(f"bake cosine min={bake_cos.min():.6f}", file=sys.stderr)

    bank = load_anchors("2eur_commemo")
    if bank is None:
        raise RuntimeError("Banque 2eur_commemo absente")
    ref_top1 = top1_ids(ref, bank.matrix, bank.eurio_ids)

    wrapper = L2Embedder(backbone).eval()
    sample = (torch.randn(1, 3, INPUT_PX, INPUT_PX),)

    # `ai_edge_torch` est un shim déprécié sans API — le module actif est
    # `litert_torch` (même usage que training/export_tflite.py).
    import litert_torch
    import tensorflow as tf

    # Flags = dict IMBRIQUÉ (cf. litert_torch/_convert/conversion_utils.py :
    # l'arbre est parcouru récursivement, une clé pointée serait posée par
    # setattr sous son nom littéral et silencieusement ignorée).
    variants: list[tuple[str, dict | None]] = [
        ("fp32", None),
        ("int8-dynamic", {"optimizations": [tf.lite.Optimize.DEFAULT]}),
        ("fp16", {
            "optimizations": [tf.lite.Optimize.DEFAULT],
            "target_spec": {"supported_types": [tf.float16]},
        }),
    ]

    add("| Variante | taille | cosine vs eager (min / mean) | top1 == eager "
        "| latence CPU (médiane) |")
    add("|---|---|---|---|---|")

    for name, flags in variants:
        path = OUT_DIR / f"dinov2_vits14_emb_{name}.tflite"
        print(f"\n=== convert {name} ===", file=sys.stderr)
        try:
            t0 = time.perf_counter()
            edge = litert_torch.convert(
                wrapper, sample, _ai_edge_converter_flags=flags
            )
            edge.export(str(path))
            dt = time.perf_counter() - t0
            size_mb = path.stat().st_size / 1e6
            print(f"converted in {dt:.0f}s → {size_mb:.1f} MB", file=sys.stderr)

            embs, lat_ms = tflite_embeddings(path, batch)
            cos = cosine_rows(ref, embs)
            agree = sum(
                1 for a, b in zip(top1_ids(embs, bank.matrix, bank.eurio_ids), ref_top1)
                if a == b
            )
            add(
                f"| {name} | {size_mb:.1f} MB "
                f"| {cos.min():.4f} / {cos.mean():.4f} "
                f"| {agree}/{len(ref_top1)} | {lat_ms:.0f} ms |"
            )
            print(
                f"{name}: cos min={cos.min():.4f} top1 {agree}/{len(ref_top1)} "
                f"lat={lat_ms:.0f}ms",
                file=sys.stderr,
            )
        except Exception as exc:  # noqa: BLE001 — le spike documente les échecs
            add(f"| {name} | ÉCHEC | — | — | — |")
            add(f"  - `{name}` : {type(exc).__name__}: {str(exc)[:300]}")
            print(f"{name} FAILED: {exc}", file=sys.stderr)

    add("")
    add(f"Fichiers : `{OUT_DIR}/dinov2_vits14_emb_<variante>.tflite`")
    text = "\n".join(report)
    print()
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"\n→ écrit dans {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
