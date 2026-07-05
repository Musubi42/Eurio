"""FastAPI router pour le référentiel coin (page admin ``/referential``).

Architecture (cf. memory ``feedback_architecture_eurio_db_vs_supabase``):
- ``eurio.db`` = source de vérité dev.
- Images canoniques = locales sous ``ml/canonical_images/{eurio_id}/``.
- Supabase = miroir poussé manuellement.

Endpoints :
- ``GET /referential/canonical/{eurio_id}/{role}[/thumb]`` — sert les WebP locaux
- ``GET /referential/canonical-index``                     — set d'eurio_id ayant un canonical (gate UI)
- ``GET /referential/coverage``                            — Chunk B : gaps par année
- ``POST /referential/heal``                               — Chunk B : combler les gaps déjà identifiés

À venir dans Chunk C : ``POST /referential/discover`` (BCE oracle delta),
``POST /referential/push`` (sync Supabase manuel).
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from referential.canonical_image_local import (
    CANONICAL_DIR,
    canonical_dir_for,
    canonical_path,
)
from shared.storage import public_url
from store import Store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/referential", tags=["referential"])


def _store() -> Store:
    from .server import _store as shared_store
    return shared_store


def _resolve_role(role: str) -> str:
    if role not in ("obverse", "reverse"):
        raise HTTPException(status_code=400, detail=f"invalid role: {role}")
    return role


def _lookup_source(eurio_id: str, role: str) -> str | None:
    """Renvoie le ``source`` (numista/bce_comm/unknown) du fichier canonique
    de meilleure priorité pour ce (coin, role). Préfère numista > bce_comm >
    unknown — c'est l'ordre de qualité observé.
    """
    conn = _store()._connection()  # noqa: SLF001
    row = conn.execute(
        """
        SELECT source FROM coin_canonical_images
        WHERE eurio_id = ? AND role = ?
        ORDER BY CASE source
                   WHEN 'numista'      THEN 1
                   WHEN 'numista_api'  THEN 1
                   WHEN 'bce_comm'     THEN 2
                   WHEN 'bce_official' THEN 2
                   WHEN 'unknown'      THEN 3
                   ELSE 9
                 END
        LIMIT 1
        """,
        (eurio_id, role),
    ).fetchone()
    return row[0] if row else None


# Canonical images live in MinIO bucket ``numista-canonical`` (decision
# 2026-06-14, harmonisation-images). We redirect to the public CDN so the API
# server doesn't stream image bytes. The local FS (``ml/canonical_images/``)
# stays the source of truth and the fallback: any key not (yet) confirmed in the
# bucket — or any MinIO outage — degrades to serving the local file directly, so
# this change can never 404 something that used to serve.
_bucket_keys_cache: set[str] | None = None
_bucket_keys_loaded_at: float = 0.0
_BUCKET_KEYS_TTL_S = 300.0  # re-list every 5 min so canonicals enriched by other
#                             processes (write_variants write-through) flip from
#                             FS fallback to CDN without a server restart.


def _bucket_keys() -> set[str]:
    """Keys present in ``numista-canonical`` (cached, refreshed every TTL).

    On any error (MinIO down, no creds) returns an empty set → every request
    falls back to FileResponse, i.e. the pre-2026-06-14 behaviour.
    """
    global _bucket_keys_cache, _bucket_keys_loaded_at
    now = time.monotonic()
    if _bucket_keys_cache is not None and (now - _bucket_keys_loaded_at) < _BUCKET_KEYS_TTL_S:
        return _bucket_keys_cache
    keys: set[str] = set()
    try:
        from shared.storage import _client
        paginator = _client().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket="numista-canonical"):
            for obj in page.get("Contents", []):
                keys.add(obj["Key"])
    except Exception as exc:  # noqa: BLE001 — any failure → FS fallback
        logger.warning("numista-canonical list failed, serving canonicals from FS: %s", exc)
    _bucket_keys_cache = keys
    _bucket_keys_loaded_at = now
    return keys


def _serve_canonical(
    eurio_id: str, role: str, *, thumb: bool, source: str | None = None,
):
    role = _resolve_role(role)

    # Fallback chain : si l'appelant spécifie `source`, on essaie celui-ci en
    # priorité. Sinon, on essaie d'abord ce que la DB renvoie (numista_api
    # = URL externe, fichier souvent absent en local), puis on scanne les
    # tags FS connus (bce, numista, unknown). Une row coin_canonical_images
    # avec source='numista_api' n'implique PAS qu'un fichier local existe
    # (P.7c.3 stocke juste l'URL Numista en `url`, pas le binaire). Cf.
    # finding P.8b.1 audit V.2 2026-05-26.
    candidates: list[str] = []
    if source:
        candidates.append(source)
    db_source = _lookup_source(eurio_id, role)
    if db_source and db_source not in candidates:
        candidates.append(db_source)
    for fallback in ("bce_comm", "numista", "unknown"):
        if fallback not in candidates:
            candidates.append(fallback)

    # MinIO key = path relative to the canonical FS root (same convention the
    # upload script uses: ``{eurio_id}/{role}_{tag}.webp``).
    bucket = _bucket_keys()

    # 1. FS = source de vérité : un fichier local gagne. On redirige vers le CDN
    #    quand l'objet y est miroité, sinon on stream le fichier local.
    for src in candidates:
        p = canonical_path(eurio_id, role, src, thumb=thumb)
        if not p.is_file():
            continue
        storage_key = p.relative_to(CANONICAL_DIR).as_posix()
        if storage_key in bucket:
            return RedirectResponse(public_url(storage_key), status_code=302)
        return FileResponse(
            p,
            media_type="image/webp",
            headers={
                # Cache 1h côté navigateur — invalidation côté serveur via le nom (source+role).
                "Cache-Control": "public, max-age=3600",
                # Chrome bloque les `<img>` cross-origin (ORB) sans ce header. CORS suffit
                # pour les fetch() XHR mais pas pour les `<img>` no-cors qui sont opaques.
                "Cross-Origin-Resource-Policy": "cross-origin",
            },
        )

    # 2. Aucune copie locale (machine fraîche : `ml/canonical_images/` absent) —
    #    le canonique vit dans MinIO. On sert directement depuis le CDN si l'objet
    #    y est, même sans fichier local. Même ordre de candidats. C'est ce qui
    #    permet à une machine dev non hydratée d'afficher les vignettes.
    for src in candidates:
        storage_key = (
            canonical_path(eurio_id, role, src, thumb=thumb)
            .relative_to(CANONICAL_DIR)
            .as_posix()
        )
        if storage_key in bucket:
            return RedirectResponse(public_url(storage_key), status_code=302)

    raise HTTPException(
        status_code=404,
        detail=f"no canonical for {eurio_id}/{role} on disk or in MinIO "
               f"(tried sources: {candidates})",
    )


@router.get("/canonical-index")
def canonical_index() -> dict:
    """Set d'eurio_id ayant au moins un canonical_image local.

    Union DB (Numista, …) + filesystem scan (BCE depuis 2026-05-25, où
    la source-of-truth a été déplacée hors DB). L'admin Vue le récupère
    au mount de la grille ``/coins`` pour ne pas demander d'images qu'on
    n'a pas (zombies Supabase).
    """
    ids: set[str] = set()

    conn = _store()._connection()  # noqa: SLF001
    for r in conn.execute(
        "SELECT DISTINCT eurio_id FROM coin_canonical_images "
        "WHERE local_path IS NOT NULL"
    ):
        ids.add(r[0])

    # Scan fs : tout dossier ml/canonical_images/{eurio_id}/ avec ≥1
    # fichier *.webp est considéré comme ayant un canonical.
    from referential.canonical_image_local import CANONICAL_DIR
    if CANONICAL_DIR.is_dir():
        for entry in CANONICAL_DIR.iterdir():
            if entry.is_dir() and any(entry.glob("*.webp")):
                ids.add(entry.name)

    return {"eurio_ids": sorted(ids)}


@router.get("/canonical/{eurio_id}/{role}")
def canonical_detail(
    eurio_id: str, role: str,
    source: str | None = Query(default=None, description="numista|bce_comm|unknown"),
) -> Response:
    """Image canonique 400 px WebP. Redirige vers le CDN MinIO (numista-canonical),
    avec fallback FS ``ml/canonical_images/`` si l'objet n'est pas dans le bucket.

    ``source`` optionnel : sans ce param on retourne la meilleure dispo
    (numista > bce_comm > unknown). Avec ``source=bce_comm`` on cible
    exactement le fichier BCE — utile pour la galerie multi-source.
    """
    return _serve_canonical(eurio_id, role, thumb=False, source=source)


@router.get("/canonical/{eurio_id}/{role}/thumb")
def canonical_thumb(
    eurio_id: str, role: str,
    source: str | None = Query(default=None),
) -> Response:
    """Thumbnail 120 px WebP. Pour les grilles `/coins` admin."""
    return _serve_canonical(eurio_id, role, thumb=True, source=source)


class CanonicalImageEntry(BaseModel):
    source: str          # 'numista' | 'bce_comm' | 'unknown'
    role: str            # 'obverse' | 'reverse'
    detail_url: str
    thumb_url: str
    file_present: bool


_SOURCE_PRIORITY = {
    "numista": 1, "numista_api": 1,
    "bce_comm": 2, "bce_official": 2,
    "eurlex_jo": 3,
    "unknown": 4,
}
_ROLE_PRIORITY = {"obverse": 1, "reverse": 2}


@router.get(
    "/coin-canonicals/{eurio_id}",
    response_model=list[CanonicalImageEntry],
)
def coin_canonicals(eurio_id: str) -> list[CanonicalImageEntry]:
    """Toutes les images canoniques disponibles pour ``eurio_id``.

    Découverte = union DB (``coin_canonical_images``) + scan filesystem, comme
    ``canonical_index``. La SOT des images BCE est le FS (``canonical_images/
    {eurio_id}/{role}_bce.webp``) : ~430 pièces ont leur webp sur disque mais
    seule une poignée est enregistrée en DB. Sans le scan FS, la galerie admin
    ne voyait que ces quelques rows. Le service (``_serve_canonical``) sait déjà
    servir n'importe quel fichier disque ; on aligne la découverte dessus.
    """
    found: dict[tuple[str, str], CanonicalImageEntry] = {}

    def _add(src: str, role: str, *, present: bool) -> None:
        found[(src, role)] = CanonicalImageEntry(
            source=src, role=role,
            detail_url=f"/referential/canonical/{eurio_id}/{role}?source={src}",
            thumb_url=f"/referential/canonical/{eurio_id}/{role}/thumb?source={src}",
            file_present=present,
        )

    conn = _store()._connection()  # noqa: SLF001
    rows = conn.execute(
        "SELECT source, role FROM coin_canonical_images WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchall()
    for r in rows:
        src, role = r[0], r[1]
        _add(src, role, present=canonical_path(eurio_id, role, src).is_file())

    # Scan FS : ramasse les webp BCE présents sur disque mais non enregistrés
    # en DB (le gros du corpus BCE). Nom de fichier = ``{role}_{tag}.webp``.
    # On se limite au tag ``bce`` : Numista est déjà servi via son URL CDN, et
    # les éventuels webp ``unknown`` ont une provenance ambiguë (hors galerie).
    coin_dir = canonical_dir_for(eurio_id)
    if coin_dir.is_dir():
        for f in coin_dir.glob("*_bce.webp"):
            if f.stem.endswith("_thumb"):
                continue
            role, _, _tag = f.stem.partition("_")
            if role not in _ROLE_PRIORITY:
                continue
            if ("bce_official", role) not in found:
                _add("bce_official", role, present=True)

    return sorted(
        found.values(),
        key=lambda e: (_SOURCE_PRIORITY.get(e.source, 9),
                       _ROLE_PRIORITY.get(e.role, 9)),
    )


# ── Coverage (Chunk B) ────────────────────────────────────────────────────


class CoverageYear(BaseModel):
    year: int
    n_bce_listed: int
    n_eurio_db: int
    n_with_canonical: int
    n_with_local_image: int
    n_missing_canonical: int
    bce_unmatched_count: int  # BCE coins we don't have any eurio_id for


class GapEntry(BaseModel):
    eurio_id: str
    country: str
    year: int
    theme: str | None
    numista_id: int | None


class BceOnlyEntry(BaseModel):
    country: str
    year: int
    feature: str
    image_url: str


class CoverageResponse(BaseModel):
    summary: dict[str, int]
    by_year: list[CoverageYear]
    gaps_missing_canonical: list[GapEntry]
    gaps_missing_payload: list[GapEntry]
    gaps_missing_local_image: list[GapEntry]
    bce_only: list[BceOnlyEntry]


_ML_ROOT = Path(__file__).resolve().parents[1]
BCE_SNAPSHOTS_DIR = _ML_ROOT / "datasets" / "sources"


def _latest_bce_snapshot(year: int) -> Path | None:
    """Renvoie le snapshot HTML BCE le plus récent pour cette année, ou None."""
    candidates = sorted(BCE_SNAPSHOTS_DIR.glob(f"bce_comm_{year}_*.html"))
    return candidates[-1] if candidates else None


# Détection des entries BCE qui correspondent à un joint issue. La BCE
# en compte 1 par année (vs N variants nationaux). On les filtre du
# coverage par année pour ne pas créer de gap fantôme.
_BCE_JOINT_TITLE_HINTS: dict[int, list[str]] = {
    2007: ["treaty of rome", "traité de rome", "rome"],
    2009: ["economic and monetary union", "emu", "monetary union"],
    2012: ["years of the euro", "10 years", "euro cash"],
    2015: ["european union flag", "flag of the european", "eu flag"],
    2022: ["erasmus"],
}


def _is_bce_entry_joint(year: int, feature: str) -> bool:
    hints = _BCE_JOINT_TITLE_HINTS.get(year)
    if not hints:
        return False
    f = feature.lower()
    return any(h in f for h in hints)


def _parse_bce_year(year: int) -> list[dict]:
    """Parse le dernier snapshot BCE pour cette année. [] si pas de snapshot."""
    snapshot = _latest_bce_snapshot(year)
    if not snapshot:
        return []
    # parse_bce_page est dans ml/referential — on l'importe lazy pour ne pas
    # charger bs4/lxml au boot du serveur.
    from referential.scrape_bce_images import parse_bce_page
    try:
        html = snapshot.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_bce_page(html, year)


# Eurozone membership by year (officielle, https://en.wikipedia.org/wiki/Eurozone).
# Source d'autorité pour "combien de pays devraient avoir émis ce joint issue".
_EUROZONE_TIMELINE: list[tuple[int, set[str]]] = [
    (1999, {"AT", "BE", "DE", "ES", "FI", "FR", "IE", "IT", "LU", "NL", "PT"}),
    (2001, {"AT", "BE", "DE", "ES", "FI", "FR", "GR", "IE", "IT", "LU", "NL", "PT"}),
    (2007, {"AT", "BE", "DE", "ES", "FI", "FR", "GR", "IE", "IT", "LU", "NL", "PT", "SI"}),
    (2008, {"AT", "BE", "CY", "DE", "ES", "FI", "FR", "GR", "IE", "IT", "LU", "MT", "NL", "PT", "SI"}),
    (2009, {"AT", "BE", "CY", "DE", "ES", "FI", "FR", "GR", "IE", "IT", "LU", "MT", "NL", "PT", "SI", "SK"}),
    (2011, {"AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "IE", "IT", "LU", "MT", "NL", "PT", "SI", "SK"}),
    (2014, {"AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "IE", "IT", "LU", "LV", "MT", "NL", "PT", "SI", "SK"}),
    (2015, {"AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "SI", "SK"}),
    (2023, {"AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "SI", "SK"}),
    (2026, {"AT", "BE", "BG", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "SI", "SK"}),
]


def eurozone_at(year: int) -> set[str]:
    """Pays membres de l'eurozone au 1er janvier de cette année."""
    members: set[str] = set()
    for start_year, ms in _EUROZONE_TIMELINE:
        if year >= start_year:
            members = ms
    return members


class JointIssue(BaseModel):
    design_group_id: str
    designation: str
    year: int
    n_expected: int               # taille eurozone à cette année
    n_in_db: int                  # nombre de variants nationaux en eurio.db
    n_with_canonical: int
    n_with_local_image: int
    countries_in_db: list[str]
    countries_missing: list[str]
    countries_unexpected: list[str]  # pays présents mais hors eurozone à cette année (rare)


class JointIssuesResponse(BaseModel):
    joint_issues: list[JointIssue]


@router.get("/joint-issues", response_model=JointIssuesResponse)
def joint_issues() -> JointIssuesResponse:
    """Compléttude des joint issues (Treaty of Rome, EMU, Euro cash, EU flag, Erasmus).

    Ces pièces sont émises par tous les pays de l'eurozone (à cette année). Le
    schéma actuel utilise un ``design_group_id`` ``eu-<theme>-<year>`` pointant
    chaque variant national. La compléttude = pays eurozone à cette année
    présents en eurio.db.
    """
    conn = _store()._connection()  # noqa: SLF001

    # Extrait l'année depuis l'ID du group (eu-rome-2007 → 2007).
    rows = conn.execute(
        """
        SELECT id, designation
        FROM design_groups
        WHERE id LIKE 'eu-%'
        ORDER BY id
        """
    ).fetchall()

    issues: list[JointIssue] = []
    for dg_id, designation in rows:
        # year = derniers chiffres de l'id
        year_match = "".join(c for c in dg_id.split("-")[-1] if c.isdigit())
        if not year_match:
            continue
        year = int(year_match)

        members = conn.execute(
            """
            SELECT c.country, c.eurio_id,
                   (SELECT COUNT(*) FROM coin_canonical_images ci WHERE ci.eurio_id = c.eurio_id) AS n_canon,
                   (SELECT COUNT(*) FROM coin_canonical_images ci WHERE ci.eurio_id = c.eurio_id AND ci.local_path IS NOT NULL) AS n_local
            FROM coins c
            WHERE c.design_group_id = ?
            ORDER BY c.country
            """,
            (dg_id,),
        ).fetchall()

        countries_in_db = [m[0] for m in members]
        expected = eurozone_at(year)
        missing = sorted(expected - set(countries_in_db))
        unexpected = sorted(set(countries_in_db) - expected)

        n_canon = sum(1 for m in members if m[2] > 0)
        n_local = sum(1 for m in members if m[3] > 0)

        issues.append(JointIssue(
            design_group_id=dg_id,
            designation=designation,
            year=year,
            n_expected=len(expected),
            n_in_db=len(members),
            n_with_canonical=n_canon,
            n_with_local_image=n_local,
            countries_in_db=countries_in_db,
            countries_missing=missing,
            countries_unexpected=unexpected,
        ))

    issues.sort(key=lambda j: j.year)
    return JointIssuesResponse(joint_issues=issues)


@router.get("/coverage", response_model=CoverageResponse)
def coverage() -> CoverageResponse:
    """Vue 'gaps' pour la page admin /referential.

    BCE = source d'autorité pour les commémo 2 € (publie la liste annuelle
    officielle). eurio.db = ce qu'on a. Le delta est ce qu'il faut combler.

    Limites v1 :
    - Le matching BCE → eurio_id n'est PAS recalculé ici (coûteux). On approxime
      par (country, year) — utile pour les counts, pas pour les sub-IDs.
    - ``bce_only`` liste juste les théma BCE qui n'ont pas d'équivalent
      ``(country, year)`` en eurio.db. Le matching fin viendra avec Discover (Chunk C).
    """
    conn = _store()._connection()  # noqa: SLF001

    # Set des design_groups joint-issues (eu-rome-2007, etc.) — exclus du
    # compte annuel pour ne pas polluer les gaps (cf. discussion 2026-05-24).
    joint_dg_ids = {
        r[0] for r in conn.execute(
            "SELECT id FROM design_groups WHERE id LIKE 'eu-%'"
        ).fetchall()
    }

    # ── eurio.db : commémo 2 € par année + flags par coin, hors joints ────
    rows = conn.execute(
        """
        SELECT c.eurio_id, c.country, c.year, c.theme, c.numista_id,
               (c.raw_payload_json IS NOT NULL AND c.raw_payload_json != '') AS has_payload,
               (SELECT COUNT(*) FROM coin_canonical_images ci WHERE ci.eurio_id = c.eurio_id) AS n_canon,
               (SELECT COUNT(*) FROM coin_canonical_images ci WHERE ci.eurio_id = c.eurio_id AND ci.local_path IS NOT NULL) AS n_local,
               c.design_group_id
        FROM coins c
        WHERE c.face_value = 2.0 AND c.is_commemorative = 1
        ORDER BY c.year, c.country, c.eurio_id
        """
    ).fetchall()
    # On filtre les variants de joint issues — ils sont comptés ailleurs.
    rows = [r for r in rows if r[8] not in joint_dg_ids]

    # Aggrégation par année + collecte des gaps.
    by_year_db: dict[int, dict[str, Any]] = {}
    gaps_missing_canonical: list[GapEntry] = []
    gaps_missing_payload: list[GapEntry] = []
    gaps_missing_local_image: list[GapEntry] = []

    for r in rows:
        y = r[2]
        d = by_year_db.setdefault(y, {"n_eurio_db": 0, "n_with_canonical": 0, "n_with_local_image": 0, "countries": set()})
        d["n_eurio_db"] += 1
        d["countries"].add(r[1])
        if r[6]:  # has any canonical row
            d["n_with_canonical"] += 1
        else:
            gaps_missing_canonical.append(GapEntry(
                eurio_id=r[0], country=r[1], year=r[2], theme=r[3], numista_id=r[4],
            ))
        if r[7]:  # has at least one local_path
            d["n_with_local_image"] += 1
        elif r[6]:  # has canonical row but no local_path
            gaps_missing_local_image.append(GapEntry(
                eurio_id=r[0], country=r[1], year=r[2], theme=r[3], numista_id=r[4],
            ))
        if not r[5]:
            gaps_missing_payload.append(GapEntry(
                eurio_id=r[0], country=r[1], year=r[2], theme=r[3], numista_id=r[4],
            ))

    # ── BCE par année (latest snapshot) ───────────────────────────────────
    now_year = datetime.now(timezone.utc).year
    years = sorted(set(by_year_db.keys()) | set(range(2004, now_year + 2)))

    bce_only: list[BceOnlyEntry] = []
    by_year: list[CoverageYear] = []
    for y in years:
        bce_coins_raw = _parse_bce_year(y)
        # Exclure les joint issues — comptés séparément dans /joint-issues.
        bce_coins = [bc for bc in bce_coins_raw if not _is_bce_entry_joint(y, bc["feature"])]
        bce_count = len(bce_coins)
        db_data = by_year_db.get(y, {"n_eurio_db": 0, "n_with_canonical": 0, "n_with_local_image": 0, "countries": set()})

        # Approx pairing : pour chaque BCE coin, considérer comme "non matché"
        # si aucun eurio.db coin n'existe pour ce (country, year).
        # Le matching theme-fuzzy viendra avec Discover.
        eurio_db_countries = db_data["countries"]
        unmatched = 0
        for bc in bce_coins:
            if bc["country"] not in eurio_db_countries:
                unmatched += 1
                bce_only.append(BceOnlyEntry(
                    country=bc["country"], year=y,
                    feature=bc["feature"][:120],
                    image_url=bc["image_url"],
                ))

        by_year.append(CoverageYear(
            year=y,
            n_bce_listed=bce_count,
            n_eurio_db=db_data["n_eurio_db"],
            n_with_canonical=db_data["n_with_canonical"],
            n_with_local_image=db_data["n_with_local_image"],
            n_missing_canonical=db_data["n_eurio_db"] - db_data["n_with_canonical"],
            bce_unmatched_count=unmatched,
        ))

    summary = {
        "n_bce_listed_total": sum(y.n_bce_listed for y in by_year),
        "n_eurio_db_total": sum(y.n_eurio_db for y in by_year),
        "n_with_canonical_total": sum(y.n_with_canonical for y in by_year),
        "n_with_local_image_total": sum(y.n_with_local_image for y in by_year),
        "n_missing_canonical": len(gaps_missing_canonical),
        "n_missing_payload": len(gaps_missing_payload),
        "n_missing_local_image": len(gaps_missing_local_image),
        "n_bce_only": len(bce_only),
    }

    return CoverageResponse(
        summary=summary,
        by_year=by_year,
        gaps_missing_canonical=gaps_missing_canonical[:200],
        gaps_missing_payload=gaps_missing_payload[:200],
        gaps_missing_local_image=gaps_missing_local_image[:200],
        bce_only=bce_only[:200],
    )


# ── Zero-canon résiduels (BCE-aware) ──────────────────────────────────────


class ZeroCanonEntry(BaseModel):
    eurio_id: str
    country: str
    year: int
    theme: str | None
    numista_id: int | None


class ZeroCanonResponse(BaseModel):
    n_db_zero_canon: int        # coins commémo 2 € sans row dans coin_canonical_images
    n_covered_by_bce_fs: int    # parmi eux, ceux qui ont obverse_bce.webp sur disque
    n_residuals: int            # = n_db_zero_canon - n_covered_by_bce_fs
    residuals: list[ZeroCanonEntry]


@router.get("/zero-canon", response_model=ZeroCanonResponse)
def zero_canon() -> ZeroCanonResponse:
    """Coins commémo 2 € sans aucune image canonique, ni en DB ni sur disque BCE.

    Croise ``coin_canonical_images`` (DB, alimenté par Numista) avec le FS
    ``ml/canonical_images/{eurio_id}/obverse_bce.webp`` (BCE depuis 2026-05-25,
    cf. ``ml/sources/bce/sidecar.py`` — FS = SOT pour BCE).

    Exclut les joint issues (``design_groups.id LIKE 'eu-%'``) — comptés
    séparément dans ``/joint-issues``.

    Cible théorique : 14 résiduels (cf. ``docs/roadmap.md`` §J0). Cet endpoint
    rend la cible mesurable et permet de pister la résolution (slug-aliases,
    LLM matching, ajout manuel).
    """
    from referential.canonical_image_local import canonical_dir_for

    conn = _store()._connection()  # noqa: SLF001
    rows = conn.execute(
        """
        SELECT c.eurio_id, c.country, c.year, c.theme, c.numista_id
        FROM coins c
        WHERE c.face_value = 2.0 AND c.is_commemorative = 1
          AND NOT EXISTS (
            SELECT 1 FROM coin_canonical_images ci WHERE ci.eurio_id = c.eurio_id
          )
          AND NOT EXISTS (
            SELECT 1 FROM design_groups dg
            WHERE dg.id = c.design_group_id AND dg.id LIKE 'eu-%'
          )
        ORDER BY c.year, c.country, c.eurio_id
        """
    ).fetchall()

    residuals: list[ZeroCanonEntry] = []
    n_covered = 0
    for r in rows:
        eurio_id = r[0]
        bce_webp = canonical_dir_for(eurio_id) / "obverse_bce.webp"
        if bce_webp.is_file():
            n_covered += 1
        else:
            residuals.append(ZeroCanonEntry(
                eurio_id=eurio_id, country=r[1], year=r[2],
                theme=r[3], numista_id=r[4],
            ))

    return ZeroCanonResponse(
        n_db_zero_canon=len(rows),
        n_covered_by_bce_fs=n_covered,
        n_residuals=len(residuals),
        residuals=residuals,
    )


# ── Divergences BCE ↔ Numista (lecture seule) ─────────────────────────────


class DivergenceFieldDiff(BaseModel):
    field: str           # 'country' | 'year' | 'theme'
    numista_value: str | None
    bce_value: str | None
    similarity: float | None  # 0..1 pour theme (fuzzy), None pour exact


class DivergenceEntry(BaseModel):
    eurio_id: str
    severity: str        # 'hard' | 'soft'
    country: str
    year: int
    numista_theme: str | None
    bce_feature: str | None
    diffs: list[DivergenceFieldDiff]
    bce_run_id: str | None
    bce_page_url: str | None
    numista_id: int | None


class DivergencesResponse(BaseModel):
    n_matched_bce: int
    n_hard: int
    n_soft: int
    n_clean: int
    soft_threshold: float
    divergences: list[DivergenceEntry]


def _normalize_text(s: str | None) -> str:
    """Normalise pour comparaison fuzzy : lowercase + strip non-alphanum.

    Garde uniquement [a-z0-9] et espaces (collapsed). Évite que la ponctuation
    BCE (apostrophes typographiques, parenthèses) crée du bruit.
    """
    if not s:
        return ""
    import re
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _theme_similarity(a: str | None, b: str | None) -> float:
    """Similarité 0..1 entre deux titres. SequenceMatcher sur texte normalisé."""
    from difflib import SequenceMatcher
    na, nb = _normalize_text(a), _normalize_text(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


# Au-dessus = considéré "même titre". En dessous = divergence soft. Le seuil
# 0.65 vient d'un test manuel : "Treaty of Rome 2007" vs "50e anniversaire du
# traité de Rome" → 0.42 ; "Leonardo da Vinci" vs "500th anniversary of the
# death of Leonardo da Vinci" → 0.55. Ajustable depuis le frontend si besoin.
_SOFT_THRESHOLD_DEFAULT = 0.65


@router.get("/divergences", response_model=DivergencesResponse)
def divergences(
    soft_threshold: float = Query(default=_SOFT_THRESHOLD_DEFAULT, ge=0.0, le=1.0),
) -> DivergencesResponse:
    """Liste les divergences métadonnées entre BCE (sidecar JSON) et Numista (DB)
    pour les coins matched (cad ayant un ``obverse_bce.webp`` rattaché).

    Classification :
    - **hard** : country ou year différents → quasi toujours un bug de matcher
      slug (mauvais rattachement BCE ↔ eurio_id). Geste de résolution
      = détacher.
    - **soft** : country/year OK mais titre (theme/feature) trop différents
      (similarité < ``soft_threshold``). Généralement deux formulations
      valides de la même chose. Geste de résolution = arbitrage éditorial
      (Chunk 2).
    """
    from referential.canonical_image_local import CANONICAL_DIR

    conn = _store()._connection()  # noqa: SLF001

    # Index coins par eurio_id pour O(1) lookup.
    coins_index: dict[str, tuple[str, int, str | None, int | None]] = {
        r[0]: (r[1], r[2], r[3], r[4])
        for r in conn.execute(
            "SELECT eurio_id, country, year, theme, numista_id FROM coins"
        )
    }

    if not CANONICAL_DIR.is_dir():
        return DivergencesResponse(
            n_matched_bce=0, n_hard=0, n_soft=0, n_clean=0,
            soft_threshold=soft_threshold, divergences=[],
        )

    import json as _json
    divs: list[DivergenceEntry] = []
    n_matched = 0
    n_clean = 0

    for coin_dir in sorted(CANONICAL_DIR.iterdir()):
        sidecar = coin_dir / "obverse_bce.json"
        if not sidecar.is_file():
            continue
        try:
            data = _json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            continue

        eurio_id = data.get("eurio_id") or coin_dir.name
        coin = coins_index.get(eurio_id)
        if coin is None:
            # Sidecar BCE pour un eurio_id qui n'existe plus en DB — orphelin.
            # Pas une divergence métadonnées, plutôt un nettoyage à part.
            continue
        n_matched += 1

        db_country, db_year, db_theme, db_numista_id = coin
        bce_country = data.get("country")
        bce_year = data.get("year")
        bce_feature = data.get("feature")

        diffs: list[DivergenceFieldDiff] = []
        is_hard = False

        if bce_country and db_country and bce_country != db_country:
            diffs.append(DivergenceFieldDiff(
                field="country", numista_value=db_country,
                bce_value=bce_country, similarity=None,
            ))
            is_hard = True
        if bce_year and db_year and int(bce_year) != int(db_year):
            diffs.append(DivergenceFieldDiff(
                field="year", numista_value=str(db_year),
                bce_value=str(bce_year), similarity=None,
            ))
            is_hard = True

        sim = _theme_similarity(db_theme, bce_feature)
        if sim < soft_threshold and (db_theme or bce_feature):
            diffs.append(DivergenceFieldDiff(
                field="theme", numista_value=db_theme,
                bce_value=bce_feature, similarity=round(sim, 3),
            ))

        if not diffs:
            n_clean += 1
            continue

        divs.append(DivergenceEntry(
            eurio_id=eurio_id,
            severity="hard" if is_hard else "soft",
            country=db_country, year=db_year,
            numista_theme=db_theme, bce_feature=bce_feature,
            diffs=diffs,
            bce_run_id=data.get("run_id"),
            bce_page_url=data.get("bce_page_url"),
            numista_id=db_numista_id,
        ))

    # Tri : hard d'abord, puis par similarité croissante (les plus différents en haut).
    def _sort_key(d: DivergenceEntry) -> tuple[int, float]:
        sev_rank = 0 if d.severity == "hard" else 1
        # Plus petite similarité theme = plus intéressant en haut.
        sim_min = min(
            (df.similarity for df in d.diffs if df.similarity is not None),
            default=1.0,
        )
        return (sev_rank, sim_min)

    divs.sort(key=_sort_key)

    n_hard = sum(1 for d in divs if d.severity == "hard")
    n_soft = sum(1 for d in divs if d.severity == "soft")

    return DivergencesResponse(
        n_matched_bce=n_matched, n_hard=n_hard, n_soft=n_soft,
        n_clean=n_clean, soft_threshold=soft_threshold,
        divergences=divs,
    )


# ── Heal (Chunk B) ────────────────────────────────────────────────────────


class HealResponse(BaseModel):
    started_at: str
    finished_at: str
    duration_sec: float
    enrich_payloads: dict
    migrate_canonical_schema: dict
    migrate_local_images: dict


def _run_python_module(module: str, *extra_args: str) -> dict:
    """Lance ``python -m <module>`` et capture la sortie JSON finale.

    Les scripts existants impriment ``json.dumps(summary, ...)`` à la fin.
    On capture le dernier bloc JSON valide du stdout.
    """
    proc = subprocess.run(
        [sys.executable, "-m", module, *extra_args],
        capture_output=True,
        text=True,
        cwd=_ML_ROOT,
        timeout=600,
    )
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"{module} failed (rc={proc.returncode}): {proc.stderr[-2000:]}",
        )
    # Le dernier bloc { ... } du stdout est le summary.
    import json
    out = proc.stdout
    # On cherche le dernier '{' qui ouvre un JSON complet et on prend tout jusqu'à la fin.
    last_open = out.rfind("\n{")
    if last_open < 0:
        last_open = out.find("{")
    if last_open < 0:
        return {"raw_stdout_tail": out[-500:]}
    try:
        return json.loads(out[last_open:].strip())
    except json.JSONDecodeError:
        return {"raw_stdout_tail": out[-500:]}


class DiscoverResponse(BaseModel):
    started_at: str
    finished_at: str
    duration_sec: float
    year_from: int
    year_to: int
    discover_numista: dict
    cascade_images: dict | None  # cascade migration des images si découvertes


class DiscoverRequest(BaseModel):
    year_from: int | None = None
    year_to: int | None = None
    countries: list[str] | None = None


@router.post("/discover", response_model=DiscoverResponse)
def discover(req: DiscoverRequest | None = None) -> DiscoverResponse:
    """Sweep Numista pour les pièces récentes (cf. doc dans
    ``scripts/discover_numista_recent.py``).

    Si des pièces sont trouvées, enchaîne automatiquement les migrations pour
    télécharger les images localement.
    """
    started = datetime.now(timezone.utc)
    now_year = started.year

    args: list[str] = []
    yf = (req.year_from if req else None) or now_year - 1
    yt = (req.year_to if req else None) or now_year + 1
    args += ["--year-from", str(yf), "--year-to", str(yt)]
    if req and req.countries:
        args += ["--countries", *req.countries]

    summary = _run_python_module("scripts.discover_numista_recent", *args)
    cascade = None
    if isinstance(summary, dict) and summary.get("n_discovered", 0) > 0:
        # Au moins une nouvelle pièce : on déclenche la cascade.
        # migrate_canonical_schema n'a rien à faire ici car notre discover insère
        # déjà les rows coin_canonical_images directement — on saute donc
        # ce step et on va direct au download des images locales.
        cascade = _run_python_module("scripts.migrate_canonical_images_local")

    finished = datetime.now(timezone.utc)
    return DiscoverResponse(
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        duration_sec=(finished - started).total_seconds(),
        year_from=yf,
        year_to=yt,
        discover_numista=summary if isinstance(summary, dict) else {"raw": str(summary)},
        cascade_images=cascade,
    )


class PushResponse(BaseModel):
    started_at: str
    finished_at: str
    duration_sec: float
    summary: dict


@router.post("/push", response_model=PushResponse)
def push() -> PushResponse:
    """Push eurio.db → Supabase (miroir manuel pour Android future).

    4 étapes : rewrite URLs canoniques → upload Storage → sync tables PostgREST →
    DELETE zombies. Idempotent.
    """
    started = datetime.now(timezone.utc)
    result = _run_python_module("scripts.push_to_supabase")
    finished = datetime.now(timezone.utc)
    return PushResponse(
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        duration_sec=(finished - started).total_seconds(),
        summary=result if isinstance(result, dict) else {"raw": str(result)},
    )


@router.post("/heal", response_model=HealResponse)
def heal() -> HealResponse:
    """Idempotent : enrichit les payloads vides, propage canonical_images,
    et migre les images vers le stockage local.

    Étapes :
      1) ``scripts.enrich_missing_payloads`` (Numista per-coin) — comble payloads vides
      2) ``scripts.migrate_canonical_schema`` — repropage ``raw_payload_json.images``
         vers la table ``coin_canonical_images``
      3) ``scripts.migrate_canonical_images_local`` — download + WebP + ``local_path``
    """
    started = datetime.now(timezone.utc)
    enrich = _run_python_module("scripts.enrich_missing_payloads")
    migrate_schema = _run_python_module("scripts.migrate_canonical_schema")
    migrate_local = _run_python_module("scripts.migrate_canonical_images_local")
    finished = datetime.now(timezone.utc)

    return HealResponse(
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        duration_sec=(finished - started).total_seconds(),
        enrich_payloads=enrich,
        migrate_canonical_schema=migrate_schema,
        migrate_local_images=migrate_local,
    )


# ── Fix proposals (cf. docs/operations/referential-fixes-kickoff.md) ────────

_FIX_PROPOSALS_PATH = _ML_ROOT / "state" / "referential_fix_proposals.json"


class FixProposalSummary(BaseModel):
    case_id: str
    country: str
    year: int
    shape: str
    confidence: str
    swap_eurio_id: str | None
    swap_current_numista_id: int | None
    swap_new_numista_id: int | None
    new_row_eurio_id: str
    new_row_numista_id: int
    n_warnings: int


class FixProposalsListResponse(BaseModel):
    generated_at: str | None
    n_proposals: int
    by_shape: dict[str, int]
    by_confidence: dict[str, int]
    proposals: list[FixProposalSummary]


def _read_fix_proposals() -> dict:
    if not _FIX_PROPOSALS_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "referential_fix_proposals.json not found. "
                "Run POST /referential/fix-proposals/refresh or "
                "`python -m scripts.discover_referential_fixes`."
            ),
        )
    import json
    try:
        return json.loads(_FIX_PROPOSALS_PATH.read_text())
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Corrupted proposals JSON: {e}")


def _summarize_proposal(p: dict) -> FixProposalSummary:
    swap = p.get("swap") or {}
    new_row = p.get("new_row") or {}
    return FixProposalSummary(
        case_id=p["case_id"],
        country=p["country"],
        year=p["year"],
        shape=p["shape"],
        confidence=p["confidence"],
        swap_eurio_id=swap.get("eurio_id"),
        swap_current_numista_id=swap.get("current_numista_id"),
        swap_new_numista_id=swap.get("new_numista_id"),
        new_row_eurio_id=new_row.get("eurio_id", ""),
        new_row_numista_id=new_row.get("numista_id", 0),
        n_warnings=len(p.get("warnings") or []),
    )


@router.get("/fix-proposals", response_model=FixProposalsListResponse)
def fix_proposals_list() -> FixProposalsListResponse:
    """Liste les propositions de fix discovery (lecture seule de
    ``ml/state/referential_fix_proposals.json``).

    Pour le détail complet d'un cas, voir
    ``GET /referential/fix-proposals/{case_id}``.
    """
    data = _read_fix_proposals()
    return FixProposalsListResponse(
        generated_at=data.get("generated_at"),
        n_proposals=data.get("n_proposals", 0),
        by_shape=data.get("by_shape", {}),
        by_confidence=data.get("by_confidence", {}),
        proposals=[_summarize_proposal(p) for p in data.get("proposals", [])],
    )


@router.get("/fix-proposals/{case_id}")
def fix_proposal_detail(case_id: str) -> dict:
    """Retourne la proposition complète (swap, new_row, source_attributions,
    warnings, reasoning) pour ``case_id``.

    Réponse : objet brut tel que stocké dans le JSON discovery.
    """
    data = _read_fix_proposals()
    for p in data.get("proposals", []):
        if p.get("case_id") == case_id:
            return p
    raise HTTPException(status_code=404, detail=f"case_id not found: {case_id}")


@router.post("/fix-proposals/{case_id}/apply")
def fix_proposal_apply(case_id: str) -> dict:
    """Applique la cascade de fix pour ``case_id`` (cf.
    ``docs/operations/referential-fixes-kickoff.md`` Chunk 2).

    8 étapes : preflight → backup eurio.db → mutate DB → move BCE sidecars
    → fetch Numista images → push Supabase → audit. Réponse :
    ``{success, steps:[{name,status,diagnostic}], backup_path, ...}``.

    Décision actée 2026-05-25 : push Supabase fail = non-fatal, l'opérateur
    relance ``POST /referential/push`` séparément.
    """
    from .referential_fix_apply import ApplyError, apply_fix

    try:
        return apply_fix(case_id)
    except ApplyError as e:
        raise HTTPException(status_code=e.http_status, detail=str(e))


class FixProposalsRefreshResponse(BaseModel):
    started_at: str
    finished_at: str
    duration_sec: float
    generated_at: str | None
    n_proposals: int
    by_shape: dict[str, int]
    by_confidence: dict[str, int]


@router.post("/fix-proposals/refresh", response_model=FixProposalsRefreshResponse)
def fix_proposals_refresh() -> FixProposalsRefreshResponse:
    """Re-run ``scripts.discover_referential_fixes`` et renvoie la nouvelle méta.

    Le script écrit ``ml/state/referential_fix_proposals.json``. On le relit
    après et on renvoie le sommaire (sans embarquer les 9 proposals).
    """
    started = datetime.now(timezone.utc)
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.discover_referential_fixes"],
        capture_output=True,
        text=True,
        cwd=_ML_ROOT,
        timeout=300,
    )
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"discover_referential_fixes failed (rc={proc.returncode}): {proc.stderr[-2000:]}",
        )
    data = _read_fix_proposals()
    finished = datetime.now(timezone.utc)
    return FixProposalsRefreshResponse(
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        duration_sec=(finished - started).total_seconds(),
        generated_at=data.get("generated_at"),
        n_proposals=data.get("n_proposals", 0),
        by_shape=data.get("by_shape", {}),
        by_confidence=data.get("by_confidence", {}),
    )


# ── Matrice de couverture 2€ commémoratives (nl.wikipedia par pièce) ────────
# Source « attendu » = table wikipedia_nl_coins (une ligne/pièce, thème NL,
# matched_eurio_id). État = couverture du RÉFÉRENTIEL (référencée en base), pas
# possession physique. Remplace les ex-vues jo-coverage + wikipedia-matrix.

_ALWAYS_IN_ZONE = {"AD", "MC", "SM", "VA"}


def _in_zone(country: str, year: int) -> bool:
    if country in _ALWAYS_IN_ZONE:
        return True
    return country in eurozone_at(year)


class CoinMarker(BaseModel):
    eurio_id: str | None
    theme: str
    state: Literal["have", "partial", "missing", "planned"]
    jo: bool
    joint: bool


class CoverageCell(BaseModel):
    markers: list[CoinMarker]
    out_of_zone: bool


class CoverageMatrixResponse(BaseModel):
    years: list[int]
    countries: list[str]
    cells: dict[str, dict[str, CoverageCell]]
    summary: dict[str, float]


@router.get("/coverage-matrix", response_model=CoverageMatrixResponse)
def coverage_matrix() -> CoverageMatrixResponse:
    """Matrice pays × année : un marqueur par pièce attendue (nl.wikipedia),
    coloré par son état dans eurio.db, badge JO officiel, losange commune.

    « possédée » = pièce référencée en base (matched_eurio_id) — couverture du
    référentiel, pas vault perso. Le rouge (manquante : nl la liste, pas
    d'eurio_id) = la worklist. cf. memory project_eurlex_source."""
    conn = _store()._connection()  # noqa: SLF001

    jo_refs = {
        r[0] for r in conn.execute(
            "SELECT target_id FROM coin_source_refs "
            "WHERE target_kind='coin' AND source='eurlex_jo'"
        )
    }
    has_obverse = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT eurio_id FROM coin_canonical_images WHERE role='obverse'"
        )
    }
    joint_eids = {
        r[0] for r in conn.execute(
            "SELECT eurio_id FROM coins WHERE design_group_id LIKE 'eu-%'"
        )
    }

    raw = conn.execute(
        "SELECT country, year, theme, matched_eurio_id, planned "
        "FROM wikipedia_nl_coins"
    ).fetchall()

    grid: dict[tuple[str, int], list[CoinMarker]] = {}
    countries: set[str] = set()
    years: set[int] = set()
    summ = {"expected": 0, "owned": 0, "partial": 0, "missing": 0, "jo_official": 0}
    for r in raw:
        country, year = r["country"], r["year"]
        eid = r["matched_eurio_id"]
        countries.add(country)
        years.add(year)
        if eid is None:
            state = "planned" if r["planned"] else "missing"
        elif eid in has_obverse:
            state = "have"
        else:
            state = "partial"
        is_jo = eid is not None and eid in jo_refs
        grid.setdefault((country, year), []).append(CoinMarker(
            eurio_id=eid, theme=r["theme"], state=state,
            jo=is_jo, joint=(eid is not None and eid in joint_eids),
        ))
        summ["expected"] += 1
        if state == "have":
            summ["owned"] += 1
        elif state == "partial":
            summ["partial"] += 1
        elif state == "missing":
            summ["missing"] += 1
        if is_jo:
            summ["jo_official"] += 1

    year_list = sorted(years)
    if year_list:
        year_list = list(range(min(year_list), max(year_list) + 1))
    country_list = sorted(countries)
    cells: dict[str, dict[str, CoverageCell]] = {}
    for country in country_list:
        bucket: dict[str, CoverageCell] = {}
        for year in year_list:
            bucket[str(year)] = CoverageCell(
                markers=grid.get((country, year), []),
                out_of_zone=not _in_zone(country, year),
            )
        cells[country] = bucket

    referenced = summ["owned"] + summ["partial"]
    coverage_pct = round(referenced / summ["expected"] * 100, 1) if summ["expected"] else 0.0
    summary = {**{k: float(v) for k, v in summ.items()},
               "referenced": float(referenced), "coverage_pct": coverage_pct}
    return CoverageMatrixResponse(
        years=year_list, countries=country_list, cells=cells, summary=summary,
    )


# ── Découverte ciblée Numista + file de review (gap-fill matrice) ───────────
# cf. referential/discovery.py. Phase 1 (discover) alimente la file ; Phase 2
# (accept) déclenche l'ingest complet. Synchrone (admin, à la demande).


class DiscoverRequest(BaseModel):
    country: str
    year: int


class DiscoveryQueueItem(BaseModel):
    id: int
    country: str
    year: int
    numista_id: int
    proposed_eurio_id: str | None
    numista_title: str | None
    image_url: str | None
    theme_wiki: str | None
    is_commemorative: bool
    is_variant: bool
    status: str


@router.post("/discover-coin")
def discover_coin(req: DiscoverRequest) -> dict:
    """Phase 1 ciblée sur une cellule (pays, année) : cherche les candidats
    Numista neufs et les met en file de review (sans écrire dans coins)."""
    from referential.discovery import run_discover
    return run_discover(_store(), [(req.country, req.year)])


@router.post("/discover-all")
def discover_all() -> dict:
    """Phase 1 sur toutes les cellules manquantes de la matrice (un search par
    pays concerné). Peut consommer plusieurs appels Numista."""
    from referential.discovery import run_discover

    conn = _store()._connection()  # noqa: SLF001
    targets = [
        (r[0], r[1]) for r in conn.execute(
            "SELECT DISTINCT country, year FROM wikipedia_nl_coins "
            "WHERE matched_eurio_id IS NULL ORDER BY country, year"
        )
    ]
    return run_discover(_store(), targets)


@router.get("/discovery-queue", response_model=list[DiscoveryQueueItem])
def discovery_queue(status: str = Query(default="pending")) -> list[DiscoveryQueueItem]:
    """File de review (par défaut les ``pending``)."""
    conn = _store()._connection()  # noqa: SLF001
    rows = conn.execute(
        "SELECT id, country, year, numista_id, proposed_eurio_id, numista_title, "
        "image_url, theme_wiki, is_commemorative, is_variant, status "
        "FROM referential_discovery_queue WHERE status = ? "
        "ORDER BY country, year, numista_id",
        (status,),
    ).fetchall()
    return [
        DiscoveryQueueItem(
            id=r["id"], country=r["country"], year=r["year"],
            numista_id=r["numista_id"], proposed_eurio_id=r["proposed_eurio_id"],
            numista_title=r["numista_title"], image_url=r["image_url"],
            theme_wiki=r["theme_wiki"], is_commemorative=bool(r["is_commemorative"]),
            is_variant=bool(r["is_variant"]), status=r["status"],
        )
        for r in rows
    ]


@router.post("/discovery-queue/{queue_id}/accept")
def discovery_accept(queue_id: int) -> dict:
    """Phase 2 : ingest complet (refetch_nids) + rematch de la cellule."""
    from referential.discovery import run_accept
    res = run_accept(_store(), queue_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "accept_failed"))
    return res


@router.post("/discovery-queue/{queue_id}/reject")
def discovery_reject(queue_id: int) -> dict:
    from referential.discovery import run_reject
    return run_reject(_store(), queue_id)
