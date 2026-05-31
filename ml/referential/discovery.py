"""Découverte Numista ciblée + file de review — gap-fill de la matrice de couverture.

Le bulk auto (``scripts.discover_numista_recent``) crée les références sans
review. Ce module gère le **résidu** : les pièces que la matrice signale
manquantes (rouge). Deux phases, séparées par une review humaine (doctrine
official-only + review éditoriale, cf. memory ``project_trust_model_referential``) :

- **Phase 1 — découverte légère** (``run_discover``) : ``api_search`` par pays →
  candidats Numista absents de ``coins`` → ``api_type_details`` pour l'image +
  l'eurio_id proposé (``eurio_id_from_numista_payload``) → écrit dans
  ``referential_discovery_queue`` (status ``pending``). **Rien dans ``coins``.**
- **Phase 2 — accept** (``run_accept``) : ``refetch_nids`` (ingest complet :
  coins + images + tirages + cotes) puis ``rematch_cell`` → le point passe vert.

Synchrone (admin, déclenché à la demande ; quota géré par ``KeyManager``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from referential.numista_eurio_id import eurio_id_from_numista_payload
from referential.refetch_numista_2eur import (
    NUMISTA_ISSUER_CODE,
    api_search,
    api_type_details,
)
from referential.scrape_wikipedia_coins import rematch_cell
from scripts.refetch_numista_2eur import _load_keymanager_safe, refetch_nids

logger = logging.getLogger(__name__)

_ML_ROOT = Path(__file__).resolve().parents[1]
NUMISTA_CACHE_DIR = _ML_ROOT / "state" / "numista_cache"


def _known(conn) -> tuple[set[int], set[str], set[int]]:
    """nids déjà en base, eurio_id déjà en base, nids déjà en file."""
    known_nids = {r[0] for r in conn.execute(
        "SELECT numista_id FROM coins WHERE numista_id IS NOT NULL")}
    known_eids = {r[0] for r in conn.execute("SELECT eurio_id FROM coins")}
    queued = {r[0] for r in conn.execute(
        "SELECT numista_id FROM referential_discovery_queue")}
    return known_nids, known_eids, queued


def _missing_themes(conn, country: str, year: int) -> str:
    rows = conn.execute(
        "SELECT theme FROM wikipedia_nl_coins "
        "WHERE country = ? AND year = ? AND matched_eurio_id IS NULL",
        (country, year),
    ).fetchall()
    return " · ".join(r[0] for r in rows)


def _discover_country(conn, km, country: str, years: set[int] | None) -> list[dict]:
    """Candidats Numista neufs pour ``country`` (filtrés à ``years`` si fourni).

    Neuf = nid absent de ``coins`` ET eurio_id calculé absent de ``coins`` (sinon
    c'est un trou de *matching*, pas une pièce manquante du référentiel) ET pas
    déjà en file. 1 ``api_search`` paginé + 1 ``api_type_details`` par résidu."""
    issuer = NUMISTA_ISSUER_CODE.get(country.upper())
    if not issuer:
        logger.warning("[discovery] pas de code issuer Numista pour %s", country)
        return []
    known_nids, known_eids, queued = _known(conn)

    candidates: list[dict] = []
    page = 1
    while True:
        resp = km.call(api_search, issuer, page, 50)
        types = resp.get("types") or []
        if not types:
            break
        for t in types:
            nid = int(t["id"])
            min_year = t.get("min_year") or 0
            if years is not None and min_year not in years:
                continue
            if nid in known_nids or nid in queued:
                continue
            payload = km.call(api_type_details, nid)
            slug = eurio_id_from_numista_payload(payload)
            if slug is None or slug.eurio_id in known_eids:
                continue
            obverse = payload.get("obverse") or {}
            candidates.append({
                "country": slug.country,
                "year": slug.year,
                "numista_id": nid,
                "proposed_eurio_id": slug.eurio_id,
                "numista_title": payload.get("title") or "",
                "image_url": obverse.get("picture") if isinstance(obverse, dict) else None,
                "is_commemorative": 1 if slug.is_commemorative else 0,
                "is_variant": 1 if slug.is_variant else 0,
            })
            queued.add(nid)
        if len(types) < 50:
            break
        page += 1
    return candidates


def run_discover(store, targets: list[tuple[str, int | None]]) -> dict:
    """Phase 1. ``targets`` = liste de (country, year) — year None = toutes les
    années du pays. Écrit les candidats en file ``pending``. Retourne un récap
    ``{queued, by_country, not_found}`` (not_found = cellules sans candidat neuf)."""
    conn = store._connection()  # noqa: SLF001

    by_country: dict[str, set[int] | None] = {}
    for country, year in targets:
        if year is None:
            by_country[country] = None
        elif by_country.get(country, set()) is not None:
            s = by_country.setdefault(country, set())
            if s is not None:
                s.add(year)

    km = _load_keymanager_safe()
    if km is None:
        return {"error": "no_api_key", "queued": 0, "by_country": {}, "not_found": []}

    queued = 0
    recap: dict[str, int] = {}
    found_cells: set[tuple[str, int]] = set()
    for country, years in by_country.items():
        cands = _discover_country(conn, km, country, years)
        recap[country] = len(cands)
        for c in cands:
            found_cells.add((c["country"], c["year"]))
            conn.execute(
                """
                INSERT OR IGNORE INTO referential_discovery_queue
                  (country, year, numista_id, proposed_eurio_id, numista_title,
                   image_url, theme_wiki, is_commemorative, is_variant, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (c["country"], c["year"], c["numista_id"], c["proposed_eurio_id"],
                 c["numista_title"], c["image_url"],
                 _missing_themes(conn, c["country"], c["year"]),
                 c["is_commemorative"], c["is_variant"]),
            )
            queued += 1
    conn.commit()

    not_found = [
        {"country": c, "year": y}
        for c, y in targets
        if y is not None and (c, y) not in found_cells
    ]
    return {"queued": queued, "by_country": recap, "not_found": not_found}


def run_accept(store, queue_id: int) -> dict:
    """Phase 2. Ingest complet du candidat (refetch_nids) + rematch de la
    cellule. Retourne ``{ok, eurio_id, relinked, error?}``."""
    conn = store._connection()  # noqa: SLF001
    row = conn.execute(
        "SELECT country, year, numista_id, status FROM referential_discovery_queue "
        "WHERE id = ?", (queue_id,),
    ).fetchone()
    if row is None:
        return {"ok": False, "error": "not_found"}
    if row["status"] != "pending":
        return {"ok": False, "error": f"already_{row['status']}"}

    result = refetch_nids([int(row["numista_id"])], cache_dir=NUMISTA_CACHE_DIR,
                          db_path=store.db_path)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "ingest_failed")}

    relinked = rematch_cell(conn, row["country"], row["year"])
    conn.execute(
        "UPDATE referential_discovery_queue SET status = 'accepted', "
        "resolved_at = datetime('now') WHERE id = ?", (queue_id,),
    )
    conn.commit()
    return {"ok": True, "relinked": relinked}


def run_reject(store, queue_id: int) -> dict:
    conn = store._connection()  # noqa: SLF001
    cur = conn.execute(
        "UPDATE referential_discovery_queue SET status = 'rejected', "
        "resolved_at = datetime('now') WHERE id = ? AND status = 'pending'",
        (queue_id,),
    )
    conn.commit()
    return {"ok": cur.rowcount > 0}
