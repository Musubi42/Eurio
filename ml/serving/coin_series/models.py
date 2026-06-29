"""Schémas Pydantic du domaine `coin_series`."""
from __future__ import annotations

from pydantic import BaseModel


class CoinSeries(BaseModel):
    """Une série de circulation (ex. `be-albert-ii`, `de-circ`).

    Forme alignée sur le modèle `CoinSeries` de `coins_routes.py` (réutilisé par
    `GET /coins/{eurio_id}/series`), enrichie des refs de filiation.
    """

    id: str
    country: str
    designation: str
    designation_i18n: dict[str, str] | None = None
    description: str | None = None
    minting_started_at: str
    minting_ended_at: str | None = None
    minting_end_reason: str | None = None
    supersedes_series_id: str | None = None
    superseded_by_series_id: str | None = None
