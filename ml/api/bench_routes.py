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

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scripts.bench_theme_match import SEED_YEARS, replay_bench

router = APIRouter(prefix="/bench", tags=["bench"])


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


class BenchReplayResponse(BaseModel):
    metrics: dict                 # agrégats (cf. replay_bench)
    listings: list[dict]          # une entrée par listing du gold
    groups: dict[str, list[BenchGroupCoin]]  # {année: [sœurs]}


# ── Contexte des groupes ───────────────────────────────────────────────────

def _groups_context(conn: sqlite3.Connection) -> dict[str, list[BenchGroupCoin]]:
    """Pour chaque année du gold, les commémos-sœurs avec leur thème,
    leurs titres i18n et leurs alias — le contexte de jugement du front."""
    out: dict[str, list[BenchGroupCoin]] = {}
    for year in SEED_YEARS:
        rows = conn.execute(
            "SELECT eurio_id, theme FROM coins WHERE country='BE' "
            "AND face_value=2.0 AND is_commemorative=1 AND year=? "
            "ORDER BY eurio_id",
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
            ))
        out[str(year)] = coins
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
    return BenchReplayResponse(
        metrics=result["metrics"],
        listings=result["listings"],
        groups=_groups_context(conn),
    )
