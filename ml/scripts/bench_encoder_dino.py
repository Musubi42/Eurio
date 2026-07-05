"""Bench encodeurs zero-shot sur le set labellisé review (offline).

Ré-encode la banque d'ancres (même composition que ``2eur_all`` : on
reprend les ``source_paths`` du .npz) ET les crops labellisés (décisions
de review) avec chaque encodeur, puis mesure recall@1/@5 global et bande
pays sur les crops in-scope. AUCUNE écriture en DB ni dans les .npz —
c'est un chiffre pour décider, pas une bascule.

Deux familles de specs :
  - noms torch.hub DINOv2 (``dinov2_vits14``, ``dinov2_vitl14``…) —
    transform foundation (224, ImageNet) ;
  - ``timm:<model_name>`` — n'importe quel backbone timm pré-entraîné
    (TinyViT, EfficientFormer, MobileViT, RepViT…), avec SA transform
    recommandée (résolution/normalisation par modèle). Sert au bench des
    candidats STUDENTS ArcFace on-device : le ranking zero-shot est un
    proxy du potentiel post-fine-tune (cf. phase1-delivery.md).

Usage:
    .venv/bin/python -m scripts.bench_encoder_dino
    .venv/bin/python -m scripts.bench_encoder_dino --models dinov2_vits14 timm:tiny_vit_21m_224.dist_in22k_ft_in1k
    .venv/bin/python -m scripts.bench_encoder_dino --out bench.md
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from training.foundation import (  # noqa: E402
    DINOV2_REPO,
    AnchorBank,
    build_transform,
    encode_paths,
    load_anchors,
    pick_device,
    top_k_match,
    top_k_match_country,
)
from store import resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")
BENCH_KIND = "2eur_all"
TOP_K = 5


def _load_labeled(conn: sqlite3.Connection) -> list[dict]:
    """Crops décidés en review = vérité terrain (cf. audit Phase 0)."""
    rows = conn.execute(
        """
        SELECT rq.image_asset_id AS asset_id,
               rq.decided_eurio_id,
               a.storage_path,
               s.target_eurio_id
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
         WHERE rq.status = 'done' AND rq.decided_eurio_id IS NOT NULL
           AND a.storage_path IS NOT NULL
        """
    ).fetchall()
    from shared.storage.local_cache import local_path

    out: list[dict] = []
    skipped = 0
    for r in rows:
        try:
            p = local_path("enrichment-crops", r["storage_path"])
        except FileNotFoundError:
            skipped += 1
            continue
        if not p.is_file():
            skipped += 1
            continue
        target_eid = r["target_eurio_id"]
        out.append(
            {
                "asset_id": r["asset_id"],
                "truth": r["decided_eurio_id"],
                "path": p,
                "target_country": (
                    target_eid[:2].lower()
                    if target_eid and len(target_eid) >= 2
                    else None
                ),
            }
        )
    if skipped:
        print(f"  ({skipped} crops sans fichier local — exclus)", file=sys.stderr)
    return out


def _load_model(spec: str, device) -> tuple[Any, Any, int, int]:
    """Charge un encodeur d'après sa spec → (model, transform, n_params, input_px).

    ``timm:<name>`` charge via timm avec la transform recommandée du modèle
    (num_classes=0 → features poolées) ; sinon torch.hub DINOv2 + transform
    foundation (224).
    """
    if spec.startswith("timm:"):
        import timm
        name = spec[len("timm:"):]
        model = timm.create_model(name, pretrained=True, num_classes=0)
        cfg = timm.data.resolve_model_data_config(model)
        transform = timm.data.create_transform(**cfg, is_training=False)
        input_px = cfg["input_size"][-1]
    else:
        model = torch.hub.load(DINOV2_REPO, spec, pretrained=True)
        transform = build_transform()
        input_px = 224
    model.eval()
    model.to(device)
    n_params = sum(p.numel() for p in model.parameters())
    return model, transform, n_params, input_px


def _bench_model(
    model_name: str,
    anchor_eids: list[str],
    anchor_paths: list[Path],
    crops: list[dict],
) -> dict:
    device = pick_device()
    print(f"\n=== {model_name} on {device} ===", file=sys.stderr)
    t0 = time.perf_counter()
    encoder, transform, n_params, input_px = _load_model(model_name, device)
    t_load = time.perf_counter() - t0

    t0 = time.perf_counter()
    kept_anchor_paths, anchor_matrix = encode_paths(
        anchor_paths, encoder=encoder, device=device, transform=transform
    )
    t_anchors = time.perf_counter() - t0
    kept_set = {str(p) for p in kept_anchor_paths}
    eids = [e for e, p in zip(anchor_eids, anchor_paths) if str(p) in kept_set]
    bank = AnchorBank(
        eurio_ids=eids,
        matrix=anchor_matrix,
        encoder_version=model_name,
        anchors_kind=BENCH_KIND,
        built_at="bench",
    )
    bank_ids = set(eids)

    t0 = time.perf_counter()
    crop_paths = [c["path"] for c in crops]
    kept_crop_paths, crop_matrix = encode_paths(
        crop_paths, encoder=encoder, device=device, transform=transform
    )
    t_crops = time.perf_counter() - t0
    kept_crop_set = {str(p): i for i, p in enumerate(kept_crop_paths)}

    n_in_scope = 0
    g1 = g5 = 0
    c_total = c1 = c5 = 0
    for c in crops:
        idx = kept_crop_set.get(str(c["path"]))
        if idx is None:
            continue
        if c["truth"] not in bank_ids:
            continue
        n_in_scope += 1
        vec = crop_matrix[idx]
        matches = top_k_match(vec, bank, top_k=TOP_K)
        ranked = [m.eurio_id for m in matches]
        if ranked and ranked[0] == c["truth"]:
            g1 += 1
        if c["truth"] in ranked:
            g5 += 1
        if c["target_country"]:
            cm = top_k_match_country(
                vec, bank, target_country=c["target_country"], top_k=TOP_K
            )
            if cm:
                c_total += 1
                cranked = [m.eurio_id for m in cm]
                if cranked[0] == c["truth"]:
                    c1 += 1
                if c["truth"] in cranked:
                    c5 += 1

    n_imgs = len(kept_anchor_paths) + len(kept_crop_paths)
    return {
        "model": model_name,
        "anchors": bank.count,
        "dim": bank.dim,
        "params_m": n_params / 1e6,
        "input_px": input_px,
        "n_in_scope": n_in_scope,
        "g1": g1, "g5": g5,
        "c_total": c_total, "c1": c1, "c5": c5,
        "t_load": t_load,
        "t_encode": t_anchors + t_crops,
        "ms_per_img": 1000 * (t_anchors + t_crops) / max(n_imgs, 1),
    }


def _pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "—"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models", nargs="+",
        default=["dinov2_vits14", "dinov2_vitl14"],
    )
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    base = load_anchors(BENCH_KIND)
    if base is None or not base.source_paths:
        raise RuntimeError(
            f"Banque {BENCH_KIND} introuvable ou sans source_paths — lancer "
            "`go-task ml:dino-anchors:build` (kind 2eur_all) d'abord"
        )
    anchor_paths = [Path(p) for p in base.source_paths]

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    crops = _load_labeled(conn)
    conn.close()
    print(f"Set labellisé : {len(crops)} crops · banque : {base.count} ancres",
          file=sys.stderr)

    results = []
    for m in args.models:
        try:
            results.append(_bench_model(m, base.eurio_ids, anchor_paths, crops))
        except Exception as exc:  # noqa: BLE001 — un candidat KO ne tue pas le banc
            print(f"!! {m} failed: {exc}", file=sys.stderr)
    if not results:
        raise RuntimeError("Aucun modèle benché avec succès.")

    lines = [
        "# Bench encodeurs zero-shot (banque 2eur_all, set labellisé review)",
        "",
        f"- {len(crops)} crops labellisés · {base.count} ancres "
        f"(composition de la banque `{BENCH_KIND}` live)",
        "- Recall mesuré sur crops in-scope (vérité dans la banque) ; bande "
        "pays = ancres du pays cible du listing (même logique que la prod).",
        "- Chaque modèle utilise SA transform recommandée (résolution/"
        "normalisation) — le zero-shot est un proxy du potentiel "
        "post-fine-tune ArcFace, pas une mesure absolue.",
        "",
        "| Modèle | M params | px | dim | global@1 | global@5 | pays@1 "
        "| pays@5 | ms/img |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: -r["c1"] / max(r["c_total"], 1)):
        lines.append(
            f"| {r['model']} | {r['params_m']:.1f} | {r['input_px']} "
            f"| {r['dim']} "
            f"| {_pct(r['g1'], r['n_in_scope'])} "
            f"| {_pct(r['g5'], r['n_in_scope'])} "
            f"| {_pct(r['c1'], r['c_total'])} "
            f"| {_pct(r['c5'], r['c_total'])} "
            f"| {r['ms_per_img']:.0f} |"
        )
    lines.append("")
    report = "\n".join(lines)
    print(report)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print(f"\n→ écrit dans {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
