"""FastAPI routes — Crop Bench (banc de qualité du crop eBay, local-only).

Objectif du chantier crop-quality-overhaul (cf.
``docs/operations/crop-quality-overhaul/00-diagnostic-and-architecture.md``) :
donner à l'admin un banc visuel où il *voit* l'undercrop bimétal — invisible
sur le crop seul (le disque interne remplit bien le masque circulaire), il ne
se révèle qu'en comparant **crop vs raw** via l'oracle Otsu.

C'est le « chunk dédié » annoncé dans ``bench_routes.py`` (cf. la LIMITE CONNUE
documentée autour de la ligne 587 : *area_ratio ne distingue pas un vrai
undercrop bimétal ; il faut un oracle indépendant Otsu+contour*).

Chunk 0 — lecture seule :
  - ``GET /crop-bench/stats``            → agrégats (par bucket) du diagnostic
  - ``GET /crop-bench/sample``           → échantillon de cartes (filtrable, biaisable)
  - ``GET /crop-bench/overlay/{id}.png`` → raw + cercle pipeline (rouge) vs rim oracle (vert)

Source de vérité = ``ml/state/crop_diag/results.csv`` (produit par
``scripts/crop_quality_diag.py``, lecture seule, 0 quota). Les métriques NE
sont PAS recalculées par requête : seul l'overlay relance l'oracle, à la
demande, image par image (lazy depuis le navigateur).

Les colonnes alternatives (fitEllipse / EDCircles / FastSAM) arrivent aux
chunks 1-2 — le contrat ci-dessous est conçu pour les accueillir (champ
``algo`` réservé), mais Chunk 0 n'expose que le crop actuel (``algo='current'``).
"""

from __future__ import annotations

import base64
import csv
import random
import sqlite3
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

# Oracle + chemins de cache PARTAGÉS avec le diagnostic : importer ici garantit
# que les cercles tracés dans l'overlay collent exactement aux chiffres de
# results.csv (même _probe_true_rim, même convention de cache).
from scripts.crop_quality_diag import (  # noqa: E402
    _DB,
    _OUT,
    _oracle_from_raw,
    _raw_local_path,
)
# Détecteurs alternatifs pluggables (Chunk 1+ : fitellipse, puis edcircles…).
from scan.crop_detectors import DETECTORS, crop_with_detector, measure_tilt, run_detector  # noqa: E402

router = APIRouter(prefix="/crop-bench", tags=["crop-bench"])

_RESULTS_CSV = _OUT / "results.csv"

# Seuils de sévérité du r_ratio (= r_pipe / r_probe). Alignés sur le diagnostic.
_R_RATIO_AMBER = 0.85   # < 0.85 → undercrop confirmé par l'oracle
_R_RATIO_RED = 0.60     # < 0.60 → undercrop sévère (typique disque interne)

# Overlay : on borne le côté long pour un transport léger côté navigateur.
_OVERLAY_MAX_SIDE = 720


# ── Caches (invalidés au mtime) ────────────────────────────────────────────

_results_cache: tuple[float, list[dict]] | None = None
_asset_map_cache: tuple[float, dict[str, dict]] | None = None


def _coerce_row(raw: dict) -> dict:
    """Type une ligne brute de results.csv (tout str) en dict exploitable."""
    def _f(v: str) -> float | None:
        return float(v) if v not in ("", None) else None

    def _i(v: str) -> int:
        return int(float(v)) if v not in ("", None) else 0

    return {
        "asset_id": raw["asset_id"],
        "eurio_id": raw.get("eurio_id") or "",
        "country": raw.get("country") or "",
        "year": raw.get("year") or "",
        "face_value": _f(raw.get("face_value", "")),
        "detection_method": raw.get("detection_method") or "",
        "fill_ratio": _f(raw.get("fill_ratio", "")),
        "r_pipe": _f(raw.get("r_pipe", "")),
        "r_probe": _f(raw.get("r_probe", "")),
        "r_ratio": _f(raw.get("r_ratio", "")),
        "bimetal_inner_ring": _i(raw.get("bimetal_inner_ring", "0")),
        "is_light_bg": _i(raw.get("is_light_bg", "0")),
        "is_bimetal_coin": _i(raw.get("is_bimetal_coin", "0")),
        "bucket": raw.get("bucket") or "",
        "crop_class": raw.get("crop_class") or "",
        "n_coins_in_img": _i(raw.get("n_coins_in_img", "1")),
        "coin_frac": _f(raw.get("coin_frac", "")),
        "listing_type": raw.get("listing_type") or "unknown",
        # Oracle DINOv2 (Chunk 3) — absent des anciens results.csv (→ None/unknown).
        "dino_sim": _f(raw.get("dino_sim", "")),
        "dino_class": raw.get("dino_class") or "unknown",
        # Champs tilt — absents des anciens results.csv (valeur "" → None/False).
        "axis_ratio": _f(raw.get("axis_ratio", "")),
        "tilt_deg":   _f(raw.get("tilt_deg", "")),
        "tilt_trustworthy": _i(raw.get("tilt_trustworthy", "0")),
    }


def _load_results() -> list[dict]:
    """Charge results.csv (typé), caché par mtime. 404 si le diag n'a pas tourné."""
    global _results_cache
    if not _RESULTS_CSV.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Diagnostic absent — lance d'abord "
                "`ml/.venv/bin/python -m scripts.crop_quality_diag` "
                "(produit ml/state/crop_diag/results.csv)."
            ),
        )
    mtime = _RESULTS_CSV.stat().st_mtime
    if _results_cache is None or _results_cache[0] != mtime:
        with _RESULTS_CSV.open(newline="") as f:
            rows = [_coerce_row(r) for r in csv.DictReader(f)]
        _results_cache = (mtime, rows)
    return _results_cache[1]


def _asset_map() -> dict[str, dict]:
    """``asset_id → {source_image_id, raw_storage_path, bbox_json}`` (eBay présents).

    Nécessaire pour construire les URLs raw et rendre l'overlay. Caché par
    mtime de la DB ; connexion read-only (R0 : le banc ne peut rien écrire).
    """
    global _asset_map_cache
    mtime = _DB.stat().st_mtime
    if _asset_map_cache is None or _asset_map_cache[0] != mtime:
        conn = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT a.id AS asset_id,
                   a.source_image_id AS source_image_id,
                   a.bbox_json AS bbox_json,
                   si.storage_path AS raw_storage_path
              FROM image_assets a
              JOIN source_images si ON si.id = a.source_image_id
             WHERE si.source = 'ebay'
               AND a.storage_status = 'present'
               AND si.storage_status = 'present'
            """
        ).fetchall()
        conn.close()
        _asset_map_cache = (mtime, {
            r["asset_id"]: {
                "source_image_id": r["source_image_id"],
                "raw_storage_path": r["raw_storage_path"],
                "bbox_json": r["bbox_json"],
            }
            for r in rows
        })
    return _asset_map_cache[1]


def _severity(r_ratio: float | None) -> str:
    """🔴 red < 0.60 ≤ 🟡 amber < 0.85 ≤ ✅ green ; ⚪ gray si oracle N/A."""
    if r_ratio is None:
        return "gray"
    if r_ratio < _R_RATIO_RED:
        return "red"
    if r_ratio < _R_RATIO_AMBER:
        return "amber"
    return "green"


# ── Modèles de réponse ──────────────────────────────────────────────────────

class CropBenchBucket(BaseModel):
    bucket: str
    n: int
    undercrop_pct: float
    wrong_pct: float
    ok_pct: float
    mean_fill_ratio: float
    bimetal_inner_ring_pct: float
    r_ratio_median: float | None
    # Oracle DINOv2 (Chunk 3) — la VRAIE qualité (voit le mauvais objet que la
    # géométrie Otsu rate). bad = wrong + suspect.
    dino_bad_pct: float | None = None
    dino_wrong_pct: float | None = None
    dino_suspect_pct: float | None = None
    dino_good_pct: float | None = None
    dino_sim_median: float | None = None


class CropBenchStats(BaseModel):
    total: int                       # crops dans le corpus diag
    judged: int                      # avec oracle valide (r_ratio non NULL)
    judged_pct: float                # couverture oracle (%)
    n_undercrop: int                 # crop_class == 'undercrop'
    undercrop_pct_judged: float      # part d'undercrop parmi les jugés
    n_wrong: int
    n_bimetal_inner_ring: int
    buckets: list[CropBenchBucket]
    listing_buckets: list[CropBenchBucket]  # Chunk 2 : strates single/multi × tight/small
    oracle_blind_pct: float          # % de crops sans r_ratio (oracle Otsu muet → 'ok' par défaut)
    # Oracle DINOv2 (Chunk 3) — la vraie qualité globale.
    dino_coverage_pct: float         # % de crops avec un dino_sim (≠ unknown)
    dino_bad_pct: float              # % bad (wrong+suspect) parmi les crops couverts
    generated_at: str                # mtime ISO de results.csv


class CropBenchCard(BaseModel):
    asset_id: str
    source_image_id: str | None
    eurio_id: str
    country: str
    year: str
    detection_method: str
    bucket: str
    listing_type: str                # single/multi × tight/small | unknown (Chunk 2)
    n_coins_in_img: int
    coin_frac: float | None
    dino_sim: float | None           # DINOv2 top1_sim crop↔ancre (Chunk 3)
    dino_class: str                  # good | suspect | wrong | unknown
    crop_class: str                  # undercrop | wrong | ok (géométrie, AVEUGLE au mauvais objet)
    fill_ratio: float | None
    r_pipe: float | None
    r_probe: float | None
    r_ratio: float | None
    severity: str                    # red | amber | green | gray
    bimetal_inner_ring: bool
    is_light_bg: bool
    is_bimetal_coin: bool
    # Tilt mesuré à la volée par measure_tilt (None si oracle absent ou raw
    # non chargeable ; calculé uniquement pour les n cartes renvoyées).
    axis_ratio: float | None         # minor/major — 1.0 = cercle parfait
    tilt_deg: float | None           # angle estimé [0–90°], None si non mesuré
    tilt_trustworthy: bool           # True si les 3 critères (center_drift, r_ratio, arc_cov) OK
    has_bbox: bool                   # bbox stockée → overlay fiable
    raw_url: str | None              # /sources/ebay/raws/{sid}/file
    crop_url: str                    # /sources/ebay/assets/{aid}/file (= algo 'current')
    overlay_url: str                 # /crop-bench/overlay/{aid}.png


class CropBenchSampleResponse(BaseModel):
    cards: list[CropBenchCard]
    total_matched: int               # après filtres, avant échantillonnage
    n_returned: int
    seed: int


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/stats", response_model=CropBenchStats)
def get_crop_bench_stats() -> CropBenchStats:
    """Agrégats du diagnostic (par bucket) — recalculés depuis results.csv."""
    from datetime import datetime, timezone

    from scripts.crop_quality_diag import _bucket_stats, _listing_stats

    rows = _load_results()
    total = len(rows)
    judged = sum(1 for r in rows if r["r_ratio"] is not None)
    n_undercrop = sum(1 for r in rows if r["crop_class"] == "undercrop")
    n_wrong = sum(1 for r in rows if r["crop_class"] == "wrong")
    n_inner = sum(1 for r in rows if r["bimetal_inner_ring"])
    dino_cov = sum(1 for r in rows if r["dino_class"] in ("good", "suspect", "wrong"))
    dino_bad = sum(1 for r in rows if r["dino_class"] in ("suspect", "wrong"))

    def _to_buckets(stats: dict[str, dict]) -> list[CropBenchBucket]:
        return [
            CropBenchBucket(
                bucket=name,
                n=s["n"],
                undercrop_pct=s["undercrop_pct"],
                wrong_pct=s["wrong_pct"],
                ok_pct=s["ok_pct"],
                mean_fill_ratio=s["mean_fill_ratio"],
                bimetal_inner_ring_pct=s["bimetal_inner_ring_pct"],
                r_ratio_median=s.get("r_ratio_median"),
                dino_bad_pct=s.get("dino_bad_pct"),
                dino_wrong_pct=s.get("dino_wrong_pct"),
                dino_suspect_pct=s.get("dino_suspect_pct"),
                dino_good_pct=s.get("dino_good_pct"),
                dino_sim_median=s.get("dino_sim_median"),
            )
            for name, s in stats.items()
        ]

    buckets = _to_buckets(_bucket_stats(rows))
    listing_buckets = _to_buckets(_listing_stats(rows))

    mtime_iso = datetime.fromtimestamp(
        _RESULTS_CSV.stat().st_mtime, tz=timezone.utc
    ).isoformat()

    return CropBenchStats(
        total=total,
        judged=judged,
        judged_pct=round(100 * judged / total, 1) if total else 0.0,
        n_undercrop=n_undercrop,
        undercrop_pct_judged=round(100 * n_undercrop / judged, 1) if judged else 0.0,
        n_wrong=n_wrong,
        n_bimetal_inner_ring=n_inner,
        buckets=buckets,
        listing_buckets=listing_buckets,
        # Part des crops où l'oracle Otsu est MUET (r_ratio None) → classés 'ok'
        # par défaut faute de mieux. C'est l'angle mort du banc automatique :
        # un crop sur le mauvais objet (numisbrief, capsule, tissu) y échappe.
        oracle_blind_pct=round(100 * (total - judged) / total, 1) if total else 0.0,
        dino_coverage_pct=round(100 * dino_cov / total, 1) if total else 0.0,
        dino_bad_pct=round(100 * dino_bad / dino_cov, 1) if dino_cov else 0.0,
        generated_at=mtime_iso,
    )


@router.get("/sample", response_model=CropBenchSampleResponse)
def get_crop_bench_sample(
    n: int = Query(30, ge=1, le=200),
    bucket: str | None = Query(None, description="bimetal_light|bimetal_textured|mono_light|mono_textured"),
    listing_type: str | None = Query(None, description="single_tight|single_small|multi_tight|multi_small"),
    klass: str | None = Query(None, description="undercrop|wrong|ok"),
    dino_class: str | None = Query(None, description="good|suspect|wrong — filtre sur l'oracle DINOv2"),
    bias: str | None = Query(None, description="undercrop|worst|bimetal|tilt|dino_bad — biaise/trie l'échantillon"),
    strata: bool = Query(False, description="échantillon ÉQUILIBRÉ par listing_type (n réparti entre strates)"),
    seed: int = Query(42, ge=0),
) -> CropBenchSampleResponse:
    """Échantillon de cartes raw↔crop, filtrable et biaisable vers les défauts.

    `strata=true` répartit `n` également entre les strates listing_type : c'est
    le mode à utiliser pour le gold humain, sinon l'échantillon aléatoire est
    écrasé par les single_tight propres (majoritaires) et rate les capsules /
    sets / numisbriefs où sont les vrais échecs."""
    rows = _load_results()
    amap = _asset_map()

    matched = rows
    if bucket:
        matched = [r for r in matched if r["bucket"] == bucket]
    if listing_type:
        matched = [r for r in matched if r["listing_type"] == listing_type]
    if klass:
        matched = [r for r in matched if r["crop_class"] == klass]
    if dino_class:
        matched = [r for r in matched if r["dino_class"] == dino_class]
    if bias == "undercrop":
        matched = [r for r in matched if r["crop_class"] == "undercrop"]
    elif bias == "bimetal":
        matched = [r for r in matched if r["is_bimetal_coin"]]
    elif bias == "dino_bad":
        matched = [r for r in matched if r["dino_class"] in ("suspect", "wrong")]

    total_matched = len(matched)

    if bias == "worst":
        # Les pires d'abord : r_ratio croissant (None relégué en fin via 2.0).
        ordered = sorted(matched, key=lambda r: (r["r_ratio"] if r["r_ratio"] is not None else 2.0))
        chosen = ordered[:n]
    elif bias == "tilt":
        # Les plus ovales d'abord : axis_ratio croissant (plus éloigné de 1 =
        # plus incliné). axis_ratio None → relégué en fin via sentinel 1.0.
        ordered = sorted(
            matched,
            key=lambda r: (r["axis_ratio"] if r["axis_ratio"] is not None else 1.0),
        )
        chosen = ordered[:n]
    elif bias == "dino_bad":
        # Les moins "pièce" d'abord : dino_sim croissant (None relégué via 2.0).
        ordered = sorted(matched, key=lambda r: (r["dino_sim"] if r["dino_sim"] is not None else 2.0))
        chosen = ordered[:n]
    elif strata:
        # Échantillon équilibré : ~n/k par strate listing_type présente.
        by_strata: dict[str, list] = {}
        for r in matched:
            by_strata.setdefault(r["listing_type"], []).append(r)
        rng = random.Random(seed)
        per = max(1, n // max(1, len(by_strata)))
        chosen = []
        for _name, items in sorted(by_strata.items()):
            pool = list(items)
            rng.shuffle(pool)
            chosen.extend(pool[:per])
        chosen = chosen[:n]
    else:
        pool = list(matched)
        random.Random(seed).shuffle(pool)
        chosen = pool[:n]

    cards: list[CropBenchCard] = []
    for r in chosen:
        meta = amap.get(r["asset_id"], {})
        sid = meta.get("source_image_id")
        aid = r["asset_id"]

        # Tilt calculé à la volée UNIQUEMENT pour les n cartes renvoyées (jamais
        # sur tout le corpus). On tente de charger le raw ; si indisponible on
        # utilise les colonnes CSV si présentes (résultats d'un diag enrichi).
        axis_ratio_val: float | None = r.get("axis_ratio")
        tilt_deg_val: float | None   = r.get("tilt_deg")
        tilt_trust_val: bool         = bool(r.get("tilt_trustworthy", 0))

        if axis_ratio_val is None and meta.get("raw_storage_path"):
            # Raw disponible → mesure fraîche.
            raw_path = _raw_local_path(meta["raw_storage_path"])
            if raw_path.exists():
                raw_img = cv2.imread(str(raw_path), cv2.IMREAD_COLOR)
                if raw_img is not None:
                    oracle = _oracle_from_raw(raw_img, meta.get("bbox_json"))
                    hint = {
                        "cx": oracle["hint_cx"],
                        "cy": oracle["hint_cy"],
                        "r":  oracle["r_pipe"],
                    }
                    tilt = measure_tilt(raw_img, hint)
                    if tilt["ok"]:
                        axis_ratio_val = tilt["axis_ratio"]
                        tilt_deg_val   = tilt["tilt_deg"]
                        tilt_trust_val = tilt["trustworthy"]

        cards.append(CropBenchCard(
            asset_id=aid,
            source_image_id=sid,
            eurio_id=r["eurio_id"],
            country=r["country"],
            year=str(r["year"]),
            detection_method=r["detection_method"],
            bucket=r["bucket"],
            listing_type=r["listing_type"],
            n_coins_in_img=r["n_coins_in_img"],
            coin_frac=r["coin_frac"],
            dino_sim=r["dino_sim"],
            dino_class=r["dino_class"],
            crop_class=r["crop_class"],
            fill_ratio=r["fill_ratio"],
            r_pipe=r["r_pipe"],
            r_probe=r["r_probe"],
            r_ratio=r["r_ratio"],
            severity=_severity(r["r_ratio"]),
            bimetal_inner_ring=bool(r["bimetal_inner_ring"]),
            is_light_bg=bool(r["is_light_bg"]),
            is_bimetal_coin=bool(r["is_bimetal_coin"]),
            axis_ratio=axis_ratio_val,
            tilt_deg=tilt_deg_val,
            tilt_trustworthy=tilt_trust_val,
            has_bbox=bool(meta.get("bbox_json")),
            raw_url=f"/sources/ebay/raws/{sid}/file" if sid else None,
            crop_url=f"/sources/ebay/assets/{aid}/file",
            overlay_url=f"/crop-bench/overlay/{aid}.png",
        ))

    return CropBenchSampleResponse(
        cards=cards,
        total_matched=total_matched,
        n_returned=len(cards),
        seed=seed,
    )


# Couleurs BGR par algo détecteur, pour l'overlay (pipeline=rouge, oracle=vert
# sont réservés). Bleu pour fitellipse ; cyan/magenta pour les futurs algos.
_ALGO_COLORS: dict[str, tuple[int, int, int]] = {
    "fitellipse": (255, 0, 0),    # bleu
    "adaptive": (255, 0, 255),    # magenta
    "bbox_refine": (0, 165, 255),  # orange
    "edcircles": (255, 200, 0),   # cyan
    "fastsam": (200, 0, 200),
}


def _load_raw(asset_id: str) -> tuple[np.ndarray, dict]:
    """Charge le raw d'un asset depuis le cache. Lève 404/422 sinon."""
    meta = _asset_map().get(asset_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"asset {asset_id} inconnu (eBay présent).")
    raw_path = _raw_local_path(meta["raw_storage_path"])
    if not raw_path.exists():
        raise HTTPException(status_code=404, detail=f"raw absent du cache : {raw_path}")
    raw = cv2.imread(str(raw_path), cv2.IMREAD_COLOR)
    if raw is None:
        raise HTTPException(status_code=422, detail="raw illisible.")
    return raw, meta


@router.get("/overlay/{asset_id}.png")
def get_crop_bench_overlay(
    asset_id: str,
    algos: str | None = Query(None, description="liste d'algos séparés par ',' à dessiner (ex: fitellipse)"),
    show_tilt: int = Query(0, description="1 = superpose l'ellipse tilt (jaune) mesurée par measure_tilt"),
) -> Response:
    """Raw avec cercles : ROUGE = cercle pipeline (ce qui a été croppé, depuis
    la bbox), VERT = vrai rim détecté par l'oracle Otsu, puis un cercle par
    algo demandé (bleu = fitellipse).

    Avec ``show_tilt=1`` : ellipse JAUNE ajustée par Canny+fitEllipseAMS sur
    l'anneau de bords — visualise directement l'inclinaison de la pièce.
    L'écart rouge↔vert EST l'undercrop ; le cercle algo montre s'il rattrape
    le rim externe."""
    raw, meta = _load_raw(asset_id)

    oracle = _oracle_from_raw(raw, meta["bbox_json"])
    cx, cy = oracle["hint_cx"], oracle["hint_cy"]
    r_pipe = oracle["r_pipe"]
    r_probe = oracle["r_probe"]

    vis = raw.copy()
    diag = max(vis.shape[:2])
    thick = max(2, int(diag * 0.004))
    # Cercle pipeline (rouge BGR) — ce que le crop actuel a cadré.
    if r_pipe:
        cv2.circle(vis, (cx, cy), int(r_pipe), (0, 0, 255), thick)
    # Cercle oracle (vert) — le vrai rim externe.
    if r_probe:
        cv2.circle(vis, (cx, cy), int(r_probe), (0, 200, 0), thick)
    # Ellipse tilt (jaune) — superposée si show_tilt=1.
    if show_tilt:
        hint_for_tilt = {"cx": cx, "cy": cy, "r": r_pipe or (r_probe or 0)}
        tilt = measure_tilt(raw, hint_for_tilt)
        if tilt["ok"] and tilt["major"] and tilt["minor"]:
            cv2.ellipse(
                vis,
                (int(tilt["cx"]), int(tilt["cy"])),
                (int(tilt["major"]), int(tilt["minor"])),
                tilt["angle"],   # angle axe principal (OpenCV convention)
                0, 360,
                (0, 220, 220),   # jaune BGR
                thick,
            )
    # Cercles des algos demandés (sur leur propre centre détecté).
    hint = {"cx": cx, "cy": cy, "r": r_pipe}
    for algo in [a.strip() for a in (algos or "").split(",") if a.strip()]:
        det = run_detector(algo, raw, hint=hint)
        if det.ok:
            color = _ALGO_COLORS.get(algo, (255, 255, 255))
            cv2.circle(vis, (int(det.cx), int(det.cy)), int(det.r), color, thick)
    cv2.circle(vis, (cx, cy), max(3, thick), (255, 255, 255), -1)

    # Downscale pour le transport.
    h, w = vis.shape[:2]
    long_side = max(h, w)
    if long_side > _OVERLAY_MAX_SIDE:
        scale = _OVERLAY_MAX_SIDE / long_side
        vis = cv2.resize(vis, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    # JPEG (et non PNG) : photo + cercles → ~70 KB vs ~900 KB, léger pour une grille.
    ok, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise HTTPException(status_code=500, detail="encodage JPEG échoué.")
    return Response(content=buf.tobytes(), media_type="image/jpeg")


class CropBenchRecropResponse(BaseModel):
    asset_id: str
    algo: str
    ok: bool
    method: str | None
    reason: str | None
    cx: float | None
    cy: float | None
    r: float | None
    r_ratio_oracle: float | None      # r détecté / r_probe (oracle) — comparable au r_ratio actuel
    r_probe: float | None
    severity: str                     # red|amber|green|gray (sur r_ratio_oracle)
    crop_b64: str | None              # data URI PNG du crop 224 (None si échec)
    debug: dict


@router.get("/recrop/{asset_id}", response_model=CropBenchRecropResponse)
def get_crop_bench_recrop(
    asset_id: str,
    algo: str = Query("fitellipse", description="détecteur à appliquer"),
) -> CropBenchRecropResponse:
    """Re-croppe un raw avec un détecteur alternatif (zéro re-scrape) et renvoie
    le crop 224 (base64) + son r_ratio vs oracle, pour comparaison au crop actuel.

    Format de crop IDENTIQUE à la prod (``_crop_mask_resize_float``) — seule la
    détection change."""
    if algo not in DETECTORS:
        raise HTTPException(status_code=400, detail=f"algo inconnu : {algo} (dispo: {list(DETECTORS)})")
    raw, meta = _load_raw(asset_id)

    # Oracle d'abord : fournit la référence r_probe ET le hint (centre/rayon du
    # crop actuel) pour les détecteurs qui raffinent autour de la pièce connue.
    oracle = _oracle_from_raw(raw, meta["bbox_json"])
    r_probe = oracle.get("r_probe")
    hint = {"cx": oracle["hint_cx"], "cy": oracle["hint_cy"], "r": oracle["r_pipe"]}

    res, det = crop_with_detector(algo, raw, hint=hint)
    r_ratio = (det.r / r_probe) if (det.ok and r_probe) else None

    crop_b64: str | None = None
    if res is not None and res.image is not None:
        ok, buf = cv2.imencode(".png", res.image)
        if ok:
            crop_b64 = "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")

    return CropBenchRecropResponse(
        asset_id=asset_id,
        algo=algo,
        ok=det.ok and crop_b64 is not None,
        method=det.method or None,
        reason=det.reason,
        cx=det.cx if det.ok else None,
        cy=det.cy if det.ok else None,
        r=det.r if det.ok else None,
        r_ratio_oracle=round(r_ratio, 4) if r_ratio is not None else None,
        r_probe=r_probe,
        severity=_severity(r_ratio),
        crop_b64=crop_b64,
        debug=det.debug,
    )


# ── Gold labeling (Chunk 3) ─────────────────────────────────────────────────
#
# Le gold humain est la VÉRITÉ (l'oracle Otsu est bruité). Pour chaque crop,
# l'admin juge le crop ACTUEL et le crop d'un détecteur alternatif : ✅ bon /
# ❌ mauvais. On en déduit le head-to-head (refine bat-il l'actuel ?) et un set
# de régression CI. Stocké en JSONL (upsert par (asset_id, target)).

import json as _json
import threading
from datetime import datetime, timezone

_GOLD_PATH = _OUT.parent / "crop_scores" / "gold" / "crop_gold.jsonl"
_gold_lock = threading.Lock()
_gold_records: dict[str, dict] | None = None   # clé "asset_id|target" → record


def _gold_key(asset_id: str, target: str) -> str:
    return f"{asset_id}|{target}"


def _load_gold() -> dict[str, dict]:
    global _gold_records
    if _gold_records is None:
        recs: dict[str, dict] = {}
        if _GOLD_PATH.exists():
            for ln in _GOLD_PATH.read_text().splitlines():
                if not ln.strip():
                    continue
                try:
                    r = _json.loads(ln)
                except _json.JSONDecodeError:
                    continue
                recs[_gold_key(r["asset_id"], r["target"])] = r  # last wins
        _gold_records = recs
    return _gold_records


def _save_gold() -> None:
    recs = _load_gold()
    _GOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [_json.dumps(r, ensure_ascii=False) for r in recs.values()]
    _GOLD_PATH.write_text("\n".join(lines) + ("\n" if lines else ""))


class CropBenchLabelIn(BaseModel):
    asset_id: str
    target: str                 # 'actuel' ou nom d'algo (ex: 'bbox_refine')
    verdict: str                # 'good' | 'bad'
    algo: str | None = None     # algo affiché (contexte)
    method: str | None = None   # méthode du détecteur (contexte)
    r_ratio: float | None = None
    dino_sim: float | None = None  # DINOv2 top1_sim — pour caler les seuils sur le gold
    note: str | None = None


class CropBenchLabelsResponse(BaseModel):
    labels: dict[str, dict]     # asset_id → {target: verdict}
    n_labels: int
    per_target: dict[str, dict] # target → {good, bad}
    head_to_head: dict[str, dict]  # algo → {wins, losses, both_good, both_bad, n}


def _gold_stats(recs: dict[str, dict]) -> tuple[dict, dict, dict]:
    by_asset: dict[str, dict] = {}
    per_target: dict[str, dict] = {}
    for r in recs.values():
        by_asset.setdefault(r["asset_id"], {})[r["target"]] = r["verdict"]
        pt = per_target.setdefault(r["target"], {"good": 0, "bad": 0})
        pt[r["verdict"]] = pt.get(r["verdict"], 0) + 1

    # head-to-head : pour chaque target ≠ 'actuel', comparer aux assets où
    # 'actuel' est aussi jugé.
    h2h: dict[str, dict] = {}
    for tgt in per_target:
        if tgt == "actuel":
            continue
        d = {"wins": 0, "losses": 0, "both_good": 0, "both_bad": 0, "n": 0}
        for verdicts in by_asset.values():
            if "actuel" in verdicts and tgt in verdicts:
                d["n"] += 1
                a, b = verdicts["actuel"], verdicts[tgt]
                if b == "good" and a == "bad":
                    d["wins"] += 1
                elif b == "bad" and a == "good":
                    d["losses"] += 1
                elif a == "good" and b == "good":
                    d["both_good"] += 1
                else:
                    d["both_bad"] += 1
        h2h[tgt] = d
    return by_asset, per_target, h2h


@router.post("/label", response_model=CropBenchLabelsResponse)
def post_crop_bench_label(body: CropBenchLabelIn) -> CropBenchLabelsResponse:
    if body.verdict not in ("good", "bad"):
        raise HTTPException(status_code=400, detail="verdict doit être 'good' ou 'bad'")
    with _gold_lock:
        recs = _load_gold()
        recs[_gold_key(body.asset_id, body.target)] = {
            "asset_id": body.asset_id,
            "target": body.target,
            "verdict": body.verdict,
            "algo": body.algo,
            "method": body.method,
            "r_ratio": body.r_ratio,
            "dino_sim": body.dino_sim,
            "note": body.note,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        _save_gold()
        return _labels_response(recs)


@router.get("/labels", response_model=CropBenchLabelsResponse)
def get_crop_bench_labels() -> CropBenchLabelsResponse:
    return _labels_response(_load_gold())


def _labels_response(recs: dict[str, dict]) -> CropBenchLabelsResponse:
    by_asset, per_target, h2h = _gold_stats(recs)
    return CropBenchLabelsResponse(
        labels=by_asset, n_labels=len(recs),
        per_target=per_target, head_to_head=h2h,
    )
