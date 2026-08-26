"""FastAPI router — validation humaine du gold denom ambigu (C7 pilier 2).

Le gold ``state/denom_bench/denom_gold.jsonl`` a été labellisé par un pass visuel
Claude (2026-06-13). Les rows ``conf="lo"`` (et tous les ``unk``) sont AMBIGUËS
et demandent une validation humaine avant ré-entraînement de la probe
(C7 §H12, levier #1 du handoff).

Cette page sert ces crops ambigus un par un et persiste le verdict humain dans
``state/denom_bench/human_validation.jsonl`` (merge par ``asset_id``, dernier
gagne). Ce fichier est ensuite versé dans le gold + retrain via :

    python -m scripts.harvest_denom_gold --labels state/denom_bench/human_validation.jsonl \
        --override --source human-web --labeled-by human-web

Ne mute PAS ``denom_gold.jsonl`` ni ``eurio.db`` : le merge+retrain reste une
étape CLI explicite (sur PC, cf. doctrine training).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/denom-gold", tags=["denom-gold"])

_ML_DIR = Path(__file__).resolve().parent.parent
_DENOM_DIR = _ML_DIR / "state" / "denom_bench"
GOLD_PATH = _DENOM_DIR / "denom_gold.jsonl"
HUMAN_PATH = _DENOM_DIR / "human_validation.jsonl"

# Axe A — taxonomie des négatifs « pas un 2€ » (code stocké → libellé UI).
# Alignée sur les codes déjà présents dans le gold ; `chart` est fusionné dans
# `notcoin` et `fragment` bascule côté `unk`/crop-bad (cf. v2 page 2026-06-14).
NEG_KINDS: list[dict[str, str]] = [
    {"code": "one_euro", "label": "1 €"},
    {"code": "cent", "label": "centime"},
    {"code": "medal", "label": "médaille / jeton"},
    {"code": "banknote", "label": "billet"},
    {"code": "stamp_postmark", "label": "cachet postal"},
    {"code": "notcoin", "label": "pas une pièce"},
    {"code": "other", "label": "autre"},
]
NEG_KIND_CODES = {k["code"] for k in NEG_KINDS}

# Axe B — qualité du crop (orthogonale au verdict dénomination).
CROP_REASONS: list[dict[str, str]] = [
    {"code": "partial", "label": "partiel / rogné"},
    {"code": "multi", "label": "multi-pièces"},
    {"code": "blur", "label": "flou"},
    {"code": "text_overlay", "label": "texte incrusté"},
]
CROP_REASON_CODES = {c["code"] for c in CROP_REASONS}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _gold_rows() -> list[dict]:
    return _read_jsonl(GOLD_PATH)


def _human_by_id() -> dict[str, dict]:
    return {r["asset_id"]: r for r in _read_jsonl(HUMAN_PATH)}


class PendingItem(BaseModel):
    asset_id: str
    sp: str
    score: float
    seed_label: str            # label provisoire du gold (pass visuel Claude)
    seed_kind: str | None
    seed_conf: str
    seed_note: str | None = None
    human_label: str | None = None   # verdict humain déjà posé (re-pass)
    human_kind: str | None = None
    human_crop_bad: bool = False
    human_crop_reason: str | None = None


class PendingResponse(BaseModel):
    items: list[PendingItem]
    total: int
    validated: int
    neg_kinds: list[dict[str, str]]
    crop_reasons: list[dict[str, str]]


@router.get("/pending", response_model=PendingResponse)
def pending(conf: str = "lo") -> PendingResponse:
    """Les crops ambigus à valider (par défaut ``conf="lo"`` = les 87 douteux)."""
    human = _human_by_id()
    items: list[PendingItem] = []
    for r in _gold_rows():
        if conf != "all" and r.get("conf") != conf:
            continue
        h = human.get(r["asset_id"]) or {}
        items.append(
            PendingItem(
                asset_id=r["asset_id"],
                sp=r["sp"],
                score=float(r.get("score", 0.0)),
                seed_label=r.get("label", "unk"),
                seed_kind=r.get("kind"),
                seed_conf=r.get("conf", "lo"),
                seed_note=r.get("note"),
                human_label=h.get("label"),
                human_kind=h.get("kind"),
                human_crop_bad=bool(h.get("crop_bad", False)),
                human_crop_reason=h.get("crop_reason"),
            )
        )
    # Les non encore validés d'abord, puis triés par score (bimetal) croissant.
    items.sort(key=lambda i: (i.human_label is not None, i.score))
    return PendingResponse(
        items=items,
        total=len(items),
        validated=sum(1 for i in items if i.human_label),
        neg_kinds=NEG_KINDS,
        crop_reasons=CROP_REASONS,
    )


@router.get("/crop/{asset_id}")
def crop(asset_id: str):
    """Sert le crop PNG (depuis ``enrichment-crops`` via le ``sp`` du gold)."""
    row = next((r for r in _gold_rows() if r["asset_id"] == asset_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"asset {asset_id} absent du gold denom")
    from shared.storage import bucket_for_key
    from shared.storage.local_cache import local_path
    try:
        p = local_path(bucket_for_key(row["sp"]), row["sp"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=f"crop absent de MinIO: {exc}") from exc
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "no-cache"})


class LabelIn(BaseModel):
    asset_id: str
    label: Literal["pos", "neg", "unk"]          # axe A — dénomination
    kind: str | None = None                       # code négatif (si label=neg)
    crop_bad: bool = False                         # axe B — qualité du crop
    crop_reason: str | None = None


@router.post("/label")
def label(body: LabelIn) -> dict:
    """Persiste un verdict humain dans ``human_validation.jsonl`` (merge par asset_id).

    Deux axes orthogonaux : ``label`` (dénomination, ce que la probe apprend) et
    ``crop_bad`` (qualité du crop, sert à exclure les mauvais positifs du training
    et à remonter un signal au détecteur de crop).
    """
    gold_row = next((r for r in _gold_rows() if r["asset_id"] == body.asset_id), None)
    if gold_row is None:
        raise HTTPException(status_code=404, detail=f"asset {body.asset_id} absent du gold denom")
    if body.label == "neg" and body.kind and body.kind not in NEG_KIND_CODES:
        raise HTTPException(status_code=400, detail=f"kind invalide: {body.kind}")
    if body.crop_reason and body.crop_reason not in CROP_REASON_CODES:
        raise HTTPException(status_code=400, detail=f"crop_reason invalide: {body.crop_reason}")

    rows = [r for r in _read_jsonl(HUMAN_PATH) if r["asset_id"] != body.asset_id]
    rows.append(
        {
            "asset_id": body.asset_id,
            # `sp` porté depuis le gold : harvest_denom_gold --override l'utilise
            # directement, sans dépendre d'un lookup DB (l'asset peut avoir été purgé).
            "sp": gold_row.get("sp"),
            "label": body.label,
            "kind": body.kind if body.label == "neg" else None,
            "crop_bad": bool(body.crop_bad),
            "crop_reason": body.crop_reason if body.crop_bad else None,
            "conf": "hi",  # validé humainement → haute confiance
            "labeled_by": "human-web",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )
    _DENOM_DIR.mkdir(parents=True, exist_ok=True)
    HUMAN_PATH.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return {"ok": True, "validated": len(rows)}
