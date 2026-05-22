"""FastAPI routes — studio bench du theme-matcher eBay (local-only).

Sert le gold gelé (`ml/state/discovery_bench/theme_match_gold.jsonl`)
rejoué par le pipeline, pour que l'admin puisse *juger* lui-même chaque
décision de filtrage au lieu de faire confiance au juge LLM.

Chunk 1 — lecture seule : `GET /bench/theme-match` renvoie, par listing,
la donnée + le label humain + les sorties étape par étape + les métriques
agrégées, plus le contexte des groupes (sœurs : thème, titres i18n,
alias). Le ré-étiquetage (POST) arrive au chunk 3.

Le replay est déterministe et hors quota — recalculé à chaque appel
(196 listings, instantané).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scripts.bench_theme_match import SEED_YEARS, replay_bench

router = APIRouter(prefix="/bench", tags=["bench"])

# Sidecar images du gold (cf. scripts/enrich_bench_images.py).
_IMAGES_PATH = (
    Path(__file__).resolve().parent.parent
    / "state" / "discovery_bench" / "gold_images.jsonl"
)


def _store():
    """Store partagé du process API (cf. sources_routes._store)."""
    from .server import _store as shared_store
    return shared_store


# ── Modèles de réponse ─────────────────────────────────────────────────────

class BenchGroupCoin(BaseModel):
    eurio_id: str
    theme: str | None
    i18n: dict[str, str]          # {lang: titre}
    aliases: list[str]            # alias normalisés (coin_aliases)
    obverse_url: str | None       # face de la pièce (URL publique Supabase)


class BenchReplayResponse(BaseModel):
    metrics: dict                 # agrégats (cf. replay_bench)
    listings: list[dict]          # une entrée par listing du gold
    groups: dict[str, list[BenchGroupCoin]]  # {année: [sœurs]}


# ── Contexte des groupes ───────────────────────────────────────────────────

def _obverse_url(raw_payload_json: str | None) -> str | None:
    """URL de la face (obverse) depuis `coins.raw_payload_json.images`."""
    if not raw_payload_json:
        return None
    try:
        payload = json.loads(raw_payload_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return (payload.get("images") or {}).get("obverse")


def _groups_context(conn: sqlite3.Connection) -> dict[str, list[BenchGroupCoin]]:
    """Pour chaque année du gold, les commémos-sœurs avec leur thème,
    leurs titres i18n, leurs alias et la face de la pièce — le contexte
    de jugement du front."""
    out: dict[str, list[BenchGroupCoin]] = {}
    for year in SEED_YEARS:
        rows = conn.execute(
            "SELECT eurio_id, theme, raw_payload_json FROM coins WHERE "
            "country='BE' AND face_value=2.0 AND is_commemorative=1 "
            "AND year=? ORDER BY eurio_id",
            (year,),
        ).fetchall()
        coins: list[BenchGroupCoin] = []
        for r in rows:
            i18n = {
                lr["lang"]: lr["title"]
                for lr in conn.execute(
                    "SELECT lang, title FROM coin_names_i18n WHERE eurio_id=?",
                    (r["eurio_id"],),
                ).fetchall()
            }
            try:
                aliases = [
                    ar["alias"] for ar in conn.execute(
                        "SELECT alias FROM coin_aliases WHERE eurio_id=? "
                        "ORDER BY alias",
                        (r["eurio_id"],),
                    ).fetchall()
                ]
            except sqlite3.OperationalError:
                aliases = []
            coins.append(BenchGroupCoin(
                eurio_id=r["eurio_id"],
                theme=r["theme"],
                i18n=i18n,
                aliases=aliases,
                obverse_url=_obverse_url(r["raw_payload_json"]),
            ))
        out[str(year)] = coins
    return out


def _gold_image_urls() -> dict[str, str]:
    """{listing_id → image_url} depuis le sidecar gold_images.jsonl."""
    if not _IMAGES_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for ln in _IMAGES_PATH.read_text().splitlines():
        if not ln.strip():
            continue
        rec = json.loads(ln)
        if rec.get("image_url"):
            out[rec["listing_id"]] = rec["image_url"]
    return out


# ── Endpoints ──────────────────────────────────────────────────────────────

# Consumed by: admin/.../features/bench
@router.get("/theme-match", response_model=BenchReplayResponse)
def get_theme_match_bench() -> BenchReplayResponse:
    """Rejoue le gold gelé et renvoie le détail par listing + métriques."""
    conn = _store()._connection()  # noqa: SLF001
    try:
        result = replay_bench(conn)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    images = _gold_image_urls()
    for ls in result["listings"]:
        ls["image_url"] = images.get(ls["listing_id"])
    return BenchReplayResponse(
        metrics=result["metrics"],
        listings=result["listings"],
        groups=_groups_context(conn),
    )
