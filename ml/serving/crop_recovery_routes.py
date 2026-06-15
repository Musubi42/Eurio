"""Front d'analyse du banc crop-recovery (cf. docs/work-in-progress/crop-recovery/).

Sert, en lecture seule : la liste des runs de stratégie, le détail d'un run (métriques
D1/D2/D3 + cas avec candidats/scores/IoU), et les raws (pour overlay des cercles côté
client). Aucune écriture. Non câblé dans la nav (page d'analyse).
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

router = APIRouter(prefix="/crop-recovery", tags=["crop-recovery"])

_ML_DIR = Path(__file__).resolve().parent.parent
_DIR = _ML_DIR / "state" / "crop_recovery"


@router.get("/runs")
def runs() -> dict:
    """Runs de stratégie disponibles + tailles des jeux."""
    rs = []
    for p in sorted(_DIR.glob("run_*.json")):
        try:
            d = json.loads(p.read_text())
            rs.append({"strategy": d.get("strategy", p.stem), "file": p.name,
                       "n_cases": len(d.get("cases", []))})
        except Exception:
            continue
    datasets = {}
    for ds in ("D1", "D2", "D3a", "D3b"):
        f = _DIR / f"{ds}.json"
        if f.exists():
            datasets[ds] = len(json.loads(f.read_text()).get("cases", []))
    return {"runs": rs, "datasets": datasets}


@router.get("/run/{strategy}")
def run_detail(strategy: str) -> dict:
    p = _DIR / f"run_{strategy.replace(':', '_')}.json"
    if not p.exists():
        raise HTTPException(404, f"run absent: {p.name}")
    result = json.loads(p.read_text())
    from bench.crop_recovery.harness import metrics
    m = metrics(result)  # imprime + renvoie le dict
    return {"strategy": result["strategy"], "tau": result["tau"],
            "metrics": m, "cases": result["cases"]}


@router.get("/raw")
def raw(key: str = Query(...)) -> FileResponse:
    """Sert un raw (clé bucket enrichment-raws OU chemin local D3b)."""
    p = Path(key)
    if p.is_absolute() and p.exists():
        return FileResponse(str(p))
    from shared.storage.local_cache import local_path
    try:
        fp = local_path("enrichment-raws", key)
    except Exception as exc:
        raise HTTPException(404, f"raw introuvable: {exc}")
    if not Path(fp).exists():
        raise HTTPException(404, "raw introuvable")
    return FileResponse(str(fp))


@router.get("/crop")
def crop(key: str = Query(...), cx: float = Query(...), cy: float = Query(...),
         r: float = Query(...)) -> Response:
    """Sert le crop 224 NORMALISÉ d'un cercle (cx, cy, r) sur un raw — EXACTEMENT le format
    prod (`_crop_mask_resize_int`, masque dur, ce que le modèle voit). Pour la vue par image
    brute : on affiche le vrai découpage, pas une approximation canvas."""
    import cv2
    from bench.crop_recovery.common import crop_candidate, load_raw
    raw = load_raw(key)
    if raw is None:
        raise HTTPException(404, "raw introuvable")
    img = crop_candidate(raw, cx, cy, r)
    if img is None:
        raise HTTPException(422, "crop hors cadre")
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise HTTPException(500, "encodage png échoué")
    return Response(content=buf.tobytes(), media_type="image/png")
