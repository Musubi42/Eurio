"""Bench C2 — pré-classement VISION sur le gold theme-match.

Compare, sur les listings du gold (`theme_match_gold.jsonl`) étiquetés
``coin:<eurio_id>``, deux systèmes de pré-classement visuel :

  - ``zs``  : DINOv2 zero-shot contre une anchor bank (par défaut
              ``2eur_all`` vitl14 — la banque des suggestions review) ;
  - ``arc`` : notre embedder fine-tuné (checkpoint ArcFace) contre les
              centroïdes ``embeddings_v1.json`` (train-mean recommandé, cf. C1).

Chaque système est mesuré en deux variantes : bank/centroïdes complets
(``full``) et restreints au pays du gold (``country``, re-rank §matcher).

Protocole crop (sans YOLO — les poids `coin_detector` ne sont pas requis) :
multi-Hough bench-only aux mêmes passes que la prod (`_DEVICE_HOUGH_PASSES`,
WORKING_RES) mais minDist réduit pour le multi-pièces, + le crop studio
(Otsu) en candidat. Chaque candidat passe par `_crop_mask_resize_float`
(le MÊME contrat de crop 224 que la prod). Le score d'un listing est le
meilleur top-1 parmi ses crops (l'avers doit gagner — matching obverse-only).

Métriques (alignées sur bench_theme_match) : top-1 accuracy, et
auto-attribution % à précision cible via sweep de seuil sur top1_sim.
Sous-ensemble « résiduel texte » : les listings que le matcher texte route
en review (là où la vision jouerait réellement en prod).

Usage :
  python -m scripts.bench_vision_preclass [--bank 2eur_all]
      [--checkpoint output/arcface_vits14_v1_best_model.pth]
      [--centroids output/trainmean/embeddings_v1.json]
      [--target-precision 0.949] [--report PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

from scripts.bench_theme_match import BENCH_DIR, DB_PATH, GOLD_PATH, replay_bench
from store import Store
from training.foundation.anchors import load_anchors
from training.foundation.encoder import build_transform, load_encoder, pick_device
from training.foundation.matcher import spread as _spread
from training.train_embedder import build_embedder, get_val_transforms
from vision.normalize_snap import (
    _DEVICE_HOUGH_PASSES, _crop_mask_resize_float, _downscale_to_working_res,
    normalize_studio_path,
)

RAW_DIR = BENCH_DIR / "gold_raw"
IMAGES_PATH = BENCH_DIR / "gold_images.jsonl"
DEFAULT_REPORT = BENCH_DIR / "vision_preclass_report.json"

# Renommages de slugs entre la DB de référence et le gold (figé au 2026-06-01).
# Résolution par identité de classe ; le pont générique est numista_id mais le
# gold ne porte que le slug. Toute entrée non résolue fait échouer le bench
# (pas de drop silencieux).
GOLD_TO_DB_SLUG = {
    "be-2017-2eur-200-years-ghent-university":
        "be-2017-2eur-200-years-of-the-university-of-ghent",
}

_MAX_CIRCLES = 8


def _multi_hough_candidates(bgr: np.ndarray) -> list[tuple[float, float, float]]:
    """Cercles candidats (cx, cy, r) en pixels natifs — multi-pièces.

    Mêmes passes que `_detect_circle_hough` mais minDist abaissé (plusieurs
    pièces par photo listing) et sans contrainte de centrage (la pièce peut
    être n'importe où). Première passe productive = résultat.
    """
    work, scale = _downscale_to_working_res(bgr)
    sh, sw = work.shape[:2]
    short = min(sh, sw)
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)

    for _pass_name, p1, p2, rmin_frac, rmax_frac in _DEVICE_HOUGH_PASSES:
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.0,
            minDist=max(1.0, short * 0.22),
            param1=p1, param2=p2,
            minRadius=int(short * max(rmin_frac, 0.08)),
            maxRadius=int(short * rmax_frac),
        )
        if circles is None or len(circles[0]) == 0:
            continue
        out: list[tuple[float, float, float]] = []
        for c in circles[0][:_MAX_CIRCLES]:  # ordre accumulateur OpenCV
            cx, cy, r = float(c[0]) * scale, float(c[1]) * scale, float(c[2]) * scale
            if any((cx - ox) ** 2 + (cy - oy) ** 2 < (0.6 * max(r, orr)) ** 2
                   for ox, oy, orr in out):
                continue
            out.append((cx, cy, r))
        if out:
            return out
    return []


def _listing_crops(path: Path) -> list[np.ndarray]:
    """Crops candidats 224×224 BGR uint8 pour une photo listing."""
    crops: list[np.ndarray] = []
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return crops
    for cx, cy, r in _multi_hough_candidates(bgr):
        res = _crop_mask_resize_float(bgr, cx, cy, r, method="bench_multi_hough")
        if res.image is not None:
            crops.append(res.image)
    studio = normalize_studio_path(path)
    if studio.image is not None:
        crops.append(studio.image)
    return crops


def _to_pil(bgr: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


@torch.no_grad()
def _encode_zs(crops: list[Image.Image], encoder_version: str) -> np.ndarray:
    model, device = load_encoder(encoder_version=encoder_version)
    tf = build_transform()
    vecs = []
    for i in range(0, len(crops), 32):
        batch = torch.stack([tf(im) for im in crops[i:i + 32]]).to(device)
        feat = model(batch)
        feat = torch.nn.functional.normalize(feat, dim=1)
        vecs.append(feat.cpu().numpy())
    return np.concatenate(vecs).astype(np.float32)


@torch.no_grad()
def _encode_arc(crops: list[Image.Image], checkpoint_path: Path) -> tuple[np.ndarray, dict]:
    ckpt = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    model = build_embedder(ckpt.get("backbone", "mobilenet_v3_small"), ckpt["embedding_dim"])
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    device = pick_device()
    model = model.to(device)
    tf = get_val_transforms()
    vecs = []
    for i in range(0, len(crops), 32):
        batch = torch.stack([tf(im) for im in crops[i:i + 32]]).to(device)
        feat = model(batch)
        feat = torch.nn.functional.normalize(feat, dim=1)
        vecs.append(feat.cpu().numpy())
    return np.concatenate(vecs).astype(np.float32), ckpt


def _top1(matrix: np.ndarray, ids: list[str], vec: np.ndarray,
          country: str | None, expected: str) -> tuple[str, float, float, int] | None:
    """(pred_id, top1_sim, spread, rang du label attendu) — matrice L2-normée."""
    if country:
        mask = np.array([i[:2].lower() == country for i in ids], dtype=bool)
        if not mask.any():
            return None
    sims = matrix @ vec
    if country:
        sims = np.where(mask, sims, -np.inf)
    order = np.argsort(-sims)
    top1, top2 = order[0], (order[1] if len(order) > 1 else order[0])
    s1 = float(sims[top1])
    s2 = float(sims[top2]) if np.isfinite(sims[top2]) else s1
    try:
        rank = 1 + int(np.where(np.array(ids)[order] == expected)[0][0])
    except IndexError:
        rank = len(ids) + 1  # label hors scope de la matrice
    return ids[int(top1)], s1, s1 - s2, rank


def _operating_points(rows: list[dict], n_valid: int,
                      targets: tuple[float, ...]) -> dict:
    """Sweep du seuil top1_sim → auto-attribution % à précision ≥ cible.

    Sémantique alignée sur bench_theme_match : auto-attribution % =
    autos *corrects* / listings valides ; précision = corrects / autos.
    """
    out = {}
    sims = sorted({r["sim"] for r in rows}, reverse=True)
    best_acc = sum(r["correct"] for r in rows) / n_valid if n_valid else 0.0
    out["top1_accuracy"] = best_acc
    for target in targets:
        best = {"threshold": None, "auto_rate": 0.0, "precision": None, "n_auto": 0}
        for th in sims:
            autos = [r for r in rows if r["sim"] >= th]
            n_ok = sum(r["correct"] for r in autos)
            prec = n_ok / len(autos)
            if prec >= target and n_ok / n_valid > best["auto_rate"]:
                best = {"threshold": th, "auto_rate": n_ok / n_valid,
                        "precision": prec, "n_auto": len(autos)}
        out[f"auto@p{target:.2f}"] = best
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bank", default="2eur_all")
    ap.add_argument("--checkpoint", type=Path,
                    default=Path("output/arcface_vits14_v1_best_model.pth"))
    ap.add_argument("--centroids", type=Path,
                    default=Path("output/trainmean/embeddings_v1.json"))
    ap.add_argument("--target-precision", type=float, default=0.949,
                    help="précision du matcher texte (baseline H4) pour le point de comparaison")
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = ap.parse_args()

    # ── gold + images ────────────────────────────────────────────────────
    gold = [json.loads(l) for l in GOLD_PATH.read_text().splitlines() if l.strip()]
    img_by_lid = {r["listing_id"]: r for r in
                  (json.loads(l) for l in IMAGES_PATH.read_text().splitlines() if l.strip())}
    valid = [g for g in gold if g["verdict"].startswith("coin:")]
    print(f"gold: {len(gold)} listings, {len(valid)} étiquetés coin:*")

    # ── mapping gold slug → slug DB (pont des renommages) ────────────────
    store = Store(DB_PATH)
    conn = store._connection()  # noqa: SLF001
    db_slugs = {r[0]: r[1] for r in
                conn.execute("SELECT eurio_id, numista_id FROM coins").fetchall()}
    unresolved = []
    label_db_slug: dict[str, str] = {}
    for g in valid:
        slug = g["verdict"].split(":", 1)[1]
        db_slug = slug if slug in db_slugs else GOLD_TO_DB_SLUG.get(slug)
        if db_slug is None or db_slug not in db_slugs:
            unresolved.append(slug)
        else:
            label_db_slug[g["listing_id"]] = db_slug
    if unresolved:
        sys.exit(f"labels gold non résolus vers la DB (compléter GOLD_TO_DB_SLUG) : "
                 f"{sorted(set(unresolved))}")

    # ── crops ────────────────────────────────────────────────────────────
    crops_by_lid: dict[str, list[Image.Image]] = {}
    n_zero = 0
    for g in valid:
        lid = g["listing_id"]
        raw = RAW_DIR / f"{lid.replace('|', '_')}.jpg"
        if not raw.exists():
            sys.exit(f"image gold manquante : {raw} (relancer le download gold_raw)")
        crops = _listing_crops(raw)
        if not crops:
            n_zero += 1
        crops_by_lid[lid] = [_to_pil(c) for c in crops]
    flat: list[Image.Image] = []
    slices: dict[str, slice] = {}
    for lid, crops in crops_by_lid.items():
        slices[lid] = slice(len(flat), len(flat) + len(crops))
        flat.extend(crops)
    print(f"crops: {len(flat)} candidats sur {len(valid)} listings "
          f"({n_zero} listings sans crop — comptés faux)")

    # ── systèmes ─────────────────────────────────────────────────────────
    bank = load_anchors(args.bank)
    if bank is None:
        sys.exit(f"bank absente : {args.bank} — lancer ml:dino-anchors:build")
    cen = json.loads(args.centroids.read_text())
    arc_ids = list(cen["coins"].keys())
    arc_matrix = np.stack([np.asarray(c["embedding"], dtype=np.float32)
                           for c in cen["coins"].values()])
    arc_matrix /= np.linalg.norm(arc_matrix, axis=1, keepdims=True)

    # Classe arcface attendue pour un slug DB. Les classes du modèle portent
    # les slugs d'une époque antérieure aux renommages (le dataset
    # d'entraînement n'a pas de class_manifest → pas de pont numista).
    # Résolution : exact match, sinon recouvrement de tokens au sein du même
    # (pays, année) avec gagnant unique exigé — échec bruyant sinon.
    _STOP = {"2eur", "the", "of", "years", "since", "anniversary", "year",
             "th", "in", "a", "an", "and"}

    def _tokens(slug: str) -> set[str]:
        return {t for t in slug.split("-") if t and t not in _STOP}

    arc_class_for_db_slug: dict[str, str] = {}
    arc_set = set(arc_ids)
    for db_slug in set(label_db_slug.values()):
        if db_slug in arc_set:
            arc_class_for_db_slug[db_slug] = db_slug
            continue
        prefix = db_slug[:8]  # 'cc-yyyy-'
        cands = [a for a in arc_ids if a.startswith(prefix)]
        want = _tokens(db_slug)
        scored = sorted(
            ((len(want & _tokens(a)) / max(1, len(want | _tokens(a))), a)
             for a in cands), reverse=True)
        if len(scored) >= 1 and scored[0][0] > 0 and (
                len(scored) == 1 or scored[0][0] > scored[1][0]):
            arc_class_for_db_slug[db_slug] = scored[0][1]
        else:
            sys.exit(f"classe arcface introuvable pour {db_slug!r} "
                     f"(candidats: {[s for s in scored[:3]]})")
    renamed = {k: v for k, v in arc_class_for_db_slug.items() if k != v}
    if renamed:
        print(f"slugs réalignés DB→arcface ({len(renamed)}):")
        for k, v in sorted(renamed.items()):
            print(f"  {k}  →  {v}")

    def arc_correct(pred_class: str, db_slug: str) -> bool:
        return pred_class == arc_class_for_db_slug[db_slug]

    print(f"zs : bank {bank.anchors_kind} ({bank.count} ancres, {bank.encoder_version})")
    zs_vecs = _encode_zs(flat, bank.encoder_version)
    print(f"arc: {args.checkpoint.name} + {args.centroids} ({len(arc_ids)} classes)")
    arc_vecs, ckpt = _encode_arc(flat, args.checkpoint)

    # ── scoring par listing ──────────────────────────────────────────────
    country = "be"  # le gold est 100% groupes BE ; cf. top_k_match_country
    rows: dict[str, list[dict]] = defaultdict(list)
    for g in valid:
        lid = g["listing_id"]
        db_slug = label_db_slug[lid]
        sl = slices[lid]
        variants = {
            "zs_full": (zs_vecs[sl], bank.matrix, list(bank.eurio_ids), None),
            "zs_country": (zs_vecs[sl], bank.matrix, list(bank.eurio_ids), country),
            "arc_full": (arc_vecs[sl], arc_matrix, arc_ids, None),
            "arc_country": (arc_vecs[sl], arc_matrix, arc_ids, country),
        }
        for name, (vecs, matrix, ids, ctry) in variants.items():
            expected = (arc_class_for_db_slug[db_slug] if name.startswith("arc")
                        else db_slug)
            best = None
            for v in vecs:
                t = _top1(matrix, ids, v, ctry, expected)
                if t and (best is None or t[1] > best[1]):
                    best = t
            if best is None:  # aucun crop → item non auto-attribuable
                rows[name].append({"listing_id": lid, "pred": None, "sim": -1.0,
                                   "spread": 0.0, "correct": False, "rank": None})
                continue
            pred, sim, spr, rank = best
            rows[name].append({"listing_id": lid, "pred": pred, "sim": sim,
                               "spread": spr, "correct": rank == 1, "rank": rank})

    # ── sous-ensemble « résiduel texte » (rôle réel en prod) ─────────────
    replay = replay_bench(conn)
    text_outcome = {l["listing_id"]: l["outcome"] for l in replay["listings"]}
    residual_lids = {g["listing_id"] for g in valid
                     if text_outcome.get(g["listing_id"]) == "review"}

    targets = (0.90, args.target_precision, 0.99)
    report = {"n_valid": len(valid), "n_crops": len(flat), "n_zero_crop": n_zero,
              "bank": {"kind": bank.anchors_kind, "count": bank.count,
                       "encoder": bank.encoder_version},
              "checkpoint": str(args.checkpoint),
              "centroids": str(args.centroids),
              "text_residual_n": len(residual_lids),
              "systems": {}}
    print("\n" + "=" * 72)
    print(f"VISION pré-classement — {len(valid)} listings gold, "
          f"résiduel texte = {len(residual_lids)}")
    print("=" * 72)
    for name, rws in rows.items():
        full = _operating_points(rws, len(valid), targets)
        sub = [r for r in rws if r["listing_id"] in residual_lids]
        resid = _operating_points(sub, len(residual_lids), targets) if residual_lids else {}
        report["systems"][name] = {"all": full, "text_residual": resid,
                                   "rows": rws}
        op = full[f"auto@p{args.target_precision:.2f}"]
        hit5 = sum(1 for r in rws if r["rank"] is not None and r["rank"] <= 5) / len(rws)
        full["hit_at_5"] = hit5
        print(f"\n  {name:12s} top-1 acc {full['top1_accuracy']:6.1%}   "
              f"hit@5 {hit5:6.1%}   "
              f"auto@p≥{args.target_precision:.0%} : {op['auto_rate']:6.1%} "
              f"(seuil {op['threshold'] if op['threshold'] is not None else '—'})")
        if resid:
            rop = resid[f"auto@p{args.target_precision:.2f}"]
            print(f"  {'':12s} résiduel texte ({len(sub)}) : top-1 "
                  f"{resid['top1_accuracy']:6.1%}, auto {rop['auto_rate']:6.1%}")

    args.report.write_text(json.dumps(report, indent=2))
    print(f"\nrapport → {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
