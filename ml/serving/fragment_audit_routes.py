"""Page ONE-SHOT d'audit du gate anti-fragment (C7, diagnostic 2026-06-15).

Sert les crops éjectés par le gate `gated_fragment` d'un run eBay, avec leur
score `face_scores` et le palier τ, pour qu'un humain constate de visu combien
de VRAIS 2€ sont tués. Données préparées par ``scripts.prep_fragment_audit``.

Non câblé dans la nav (page jetable). Tag coin/fragment persisté pour quantifier.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/fragment-audit", tags=["fragment-audit"])

_ML_DIR = Path(__file__).resolve().parent.parent
_DIR = _ML_DIR / "state" / "fragment_audit"
_MANIFEST = _DIR / "manifest.json"
_TAGS = _DIR / "tags.json"


def _load_tags() -> dict[str, str]:
    if _TAGS.exists():
        return json.loads(_TAGS.read_text())
    return {}


@router.get("/items")
def items() -> dict:
    if not _MANIFEST.exists():
        raise HTTPException(status_code=404,
                            detail="manifest absent — lance scripts.prep_fragment_audit --run <id>")
    data = json.loads(_MANIFEST.read_text())
    tags = _load_tags()
    for it in data["items"]:
        it["verdict"] = tags.get(it["name"])
    data["tagged"] = len(tags)
    data["coin_tagged"] = sum(1 for v in tags.values() if v == "coin")
    return data


@router.get("/crop/{name}")
def crop(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="nom invalide")
    p = _DIR / name
    if not p.is_file():
        raise HTTPException(status_code=404, detail="crop introuvable")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-cache"})


class TagIn(BaseModel):
    name: str
    verdict: str | None  # "coin" | "fragment" | null (efface)


@router.post("/tag")
def tag(body: TagIn) -> dict:
    if body.verdict not in (None, "coin", "fragment"):
        raise HTTPException(status_code=400, detail="verdict invalide")
    tags = _load_tags()
    if body.verdict is None:
        tags.pop(body.name, None)
    else:
        tags[body.name] = body.verdict
    _DIR.mkdir(parents=True, exist_ok=True)
    _TAGS.write_text(json.dumps(tags))
    return {
        "ok": True,
        "tagged": len(tags),
        "coin": sum(1 for v in tags.values() if v == "coin"),
        "fragment": sum(1 for v in tags.values() if v == "fragment"),
    }
