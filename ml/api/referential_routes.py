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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from referential.canonical_image_local import (
    canonical_path,
)
from state import Store

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
                   WHEN 'numista'  THEN 1
                   WHEN 'bce_comm' THEN 2
                   WHEN 'unknown'  THEN 3
                   ELSE 9
                 END
        LIMIT 1
        """,
        (eurio_id, role),
    ).fetchone()
    return row[0] if row else None


def _serve_canonical(eurio_id: str, role: str, *, thumb: bool) -> FileResponse:
    role = _resolve_role(role)
    source = _lookup_source(eurio_id, role)
    if not source:
        raise HTTPException(status_code=404, detail=f"no canonical image for {eurio_id}/{role}")

    path: Path = canonical_path(eurio_id, role, source, thumb=thumb)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"canonical file missing on disk: {path.name} (source={source})",
        )

    return FileResponse(
        path,
        media_type="image/webp",
        headers={
            # Cache 1h côté navigateur — invalidation côté serveur via le nom (source+role).
            "Cache-Control": "public, max-age=3600",
            # Chrome bloque les `<img>` cross-origin (ORB) sans ce header. CORS suffit
            # pour les fetch() XHR mais pas pour les `<img>` no-cors qui sont opaques.
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )


@router.get("/canonical-index")
def canonical_index() -> dict:
    """Set d'eurio_id ayant au moins un canonical_image local en eurio.db.

    L'admin Vue le récupère au mount de la grille ``/coins`` pour ne pas
    demander d'images qu'on n'a pas (zombies Supabase) — éviter le bruit
    log + les icônes cassées dans le navigateur.
    """
    conn = _store()._connection()  # noqa: SLF001
    rows = conn.execute(
        "SELECT DISTINCT eurio_id FROM coin_canonical_images "
        "WHERE local_path IS NOT NULL"
    ).fetchall()
    return {"eurio_ids": [r[0] for r in rows]}


@router.get("/canonical/{eurio_id}/{role}")
def canonical_detail(eurio_id: str, role: str) -> FileResponse:
    """Image canonique 400 px WebP. Sert depuis ``ml/canonical_images/`` local."""
    return _serve_canonical(eurio_id, role, thumb=False)


@router.get("/canonical/{eurio_id}/{role}/thumb")
def canonical_thumb(eurio_id: str, role: str) -> FileResponse:
    """Thumbnail 120 px WebP. Pour les grilles `/coins` admin."""
    return _serve_canonical(eurio_id, role, thumb=True)


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
