"""Domain `coin_series` — pattern layered (cf. ARCHITECTURE.md §2).

D2 data-layer-unification : expose la table `coin_series` (référentiel des
séries de circulation, ~32 lignes pour toute l'aire euro) en lecture seule
depuis `eurio.db`. Ne dépend que de sqlite3 stdlib → montable sur l'image
lean du VPS.

Remplace le dernier `supabase.from('coin_series')` runtime de studio-local
(`useCoinSeries.ts`).
"""
from .router import router

__all__ = ["router"]
