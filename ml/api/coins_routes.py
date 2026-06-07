"""FastAPI router pour les données coin lues par l'admin Vue.

P.8a du chantier coin-richness — découpage Supabase → eurio.db. Surface :

  GET    /coins/lookups/trained          → set eurio_ids avec embedding
  GET    /coins/lookups/source-counts    → counts par source (numista, bce, …)
  GET    /coins/{eurio_id}               → Coin payload complet
  GET    /coins/{eurio_id}/i18n          → {names: [], aliases: []}
  GET    /coins/{eurio_id}/prices        → {type_level: [], mint_release_level: []}
  GET    /coins/{eurio_id}/embedding     → {model_version: str | null}
  GET    /coins/{eurio_id}/series        → coin_series row | null
  PATCH  /coins/{eurio_id}                → flip personal_owned / lent_to_me

Coexiste avec ``coin_assets_routes`` (prefix identique ``/coins``) : les
paths ne collisionnent pas. Pas de doublon de modèle, les deux fichiers
sont complémentaires (assets = images, ici = données référentiel + i18n).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from store import Store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coins", tags=["coins"])


_store: Store | None = None


def bind(store: Store) -> None:
    global _store
    _store = store


def _conn() -> sqlite3.Connection:
    if _store is None:
        raise RuntimeError("coins_routes not bound — call bind() first.")
    return _store._connection()  # noqa: SLF001


# ── Models ────────────────────────────────────────────────────────────────


class CoinImage(BaseModel):
    role: str   # 'obverse' | 'reverse'
    source: str
    url: str | None
    local_path: str | None = None


class CoinTopic(BaseModel):
    source: str       # 'numista_api' | 'bce_official' | …
    lang: str         # 'en'|'fr'|'de'|'it'|'es'|'nl'
    topic: str        # verbose commemorated_topic / BCE feature
    method: str | None = None      # 'api' | 'scrape' | 'llm_v1' | 'manual'
    confidence: str = "canon"      # 'canon' | 'assisted' | 'uncertain'


class CoinDetail(BaseModel):
    eurio_id: str
    country: str
    country_name: str | None = None
    year: int
    face_value: float
    currency: str
    is_commemorative: bool
    theme: str | None = None
    numista_id: int | None = None
    design_description: str | None = None
    design_group_id: str | None = None
    series_id: str | None = None
    personal_owned: bool = False
    lent_to_me: bool = False
    needs_review: bool = False
    images: list[CoinImage] = Field(default_factory=list)
    cross_refs: dict[str, str] = Field(default_factory=dict)
    sources_used: list[str] = Field(default_factory=list)
    topics: list[CoinTopic] = Field(default_factory=list)
    has_bce: bool = False
    has_ebay: bool = False
    has_lmdlp: bool = False
    has_wikipedia: bool = False


class I18nName(BaseModel):
    lang: str
    title: str
    source: str
    method: str | None = None
    confidence: str | None = None
    model: str | None = None


class I18nAlias(BaseModel):
    lang: str
    alias: str
    source: str
    method: str | None = None
    confidence: str | None = None


class I18nResponse(BaseModel):
    names: list[I18nName]
    aliases: list[I18nAlias]


class CoinDescription(BaseModel):
    """Titre + description officiels appariés par langue (source BCE 24 langues
    UE). Distinct de I18nName (titres Numista 6 langs, sans description)."""
    lang: str
    title: str
    description: str | None = None
    source: str
    method: str | None = None
    confidence: str | None = None
    model: str | None = None


class DescriptionsResponse(BaseModel):
    descriptions: list[CoinDescription]


class SourceStatusEntry(BaseModel):
    source: str                       # registry id (bce_official, numista_api, …)
    state: str                        # never | ok | empty_upstream | error
    axes: dict[str, Any] = Field(default_factory=dict)
    last_checked_at: str | None = None
    last_run_id: str | None = None
    updated_at: str | None = None


class SourceStatusResponse(BaseModel):
    eurio_id: str
    sources: list[SourceStatusEntry]


# Sources exposées sur la fiche (ordre = priorité d'affichage). Exclut
# mdp/manual/derived. Refresh actif seulement pour bce/numista (chunk 2) ;
# les autres restent en lecture seule. Table générique : ajouter une source
# ici suffit à l'afficher.
DISPLAYED_SOURCES = ("bce_official", "numista_api", "eurlex_jo", "ebay_browse", "lmdlp", "wikipedia")


class TypeLevelPrice(BaseModel):
    source: str
    condition_normalized: str
    condition_raw: str | None = None
    currency: str
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    sample_size: int
    period_start: str
    period_end: str


class MintReleasePrice(BaseModel):
    mint_release_id: str
    parent_type_id: str
    mint_id: str | None
    mint_year: int
    issue_type: str
    source: str
    grade_raw: str
    grade_eurio: str | None
    price: float
    currency: str
    fetched_at: str


class PricesResponse(BaseModel):
    type_level: list[TypeLevelPrice]
    mint_release_level: list[MintReleasePrice]


class EmbeddingResponse(BaseModel):
    model_version: str | None


class CoinSeries(BaseModel):
    id: str
    country: str
    designation: str
    designation_i18n: dict[str, str] | None = None
    description: str | None = None
    minting_started_at: str
    minting_ended_at: str | None = None
    minting_end_reason: str | None = None


class CoinPatch(BaseModel):
    personal_owned: bool | None = None
    lent_to_me: bool | None = None


# ── Caractéristiques : observations + crédits (Phase 4 extraction riche) ────


class CoinObservation(BaseModel):
    observation_type: str
    value: Any                       # payload_json déserialisé
    source: str
    source_ref: str | None = None
    recorded_at: str | None = None


class ObservationsResponse(BaseModel):
    """Observations Type-level brutes + raccourcis aplatis pour l'affichage.

    Les raccourcis prennent la 1re observation par type (toutes sources
    confondues, priorité d'insertion). Le front peut afficher soit la liste
    avec provenance, soit directement les raccourcis."""
    observations: list[CoinObservation]
    composition: str | None = None
    weight_g: float | None = None
    diameter_mm: float | None = None
    thickness_mm: float | None = None
    shape: str | None = None
    orientation: str | None = None
    edge_description: str | None = None
    edge_lettering: str | None = None
    edge_lettering_translation: str | None = None
    obverse_lettering: str | None = None
    reverse_lettering: str | None = None
    is_demonetized: bool | None = None


class CreditEntry(BaseModel):
    name: str
    source: str
    source_ref: str | None = None    # 'obverse' | 'reverse'
    position: int = 0


class CreditsResponse(BaseModel):
    designers: list[CreditEntry]
    engravers: list[CreditEntry]
    sculptors: list[CreditEntry]


class MintReleaseObservation(BaseModel):
    fact_type: str                   # 'mintage' | …
    value: Any
    source: str


class MintReleasePriceEntry(BaseModel):
    grade_raw: str
    grade_eurio: str | None
    price: float
    currency: str
    source: str
    fetched_at: str


class MintReleaseFull(BaseModel):
    id: str
    mint_year: int
    mint_id: str | None = None
    issue_type: str
    notes: str | None = None
    observations: list[MintReleaseObservation]
    prices: list[MintReleasePriceEntry]


class MintReleasesFullResponse(BaseModel):
    mint_releases: list[MintReleaseFull]


# ── List + filters ────────────────────────────────────────────────────────


class CoinListResponse(BaseModel):
    items: list[CoinDetail]
    total: int


@router.get("", response_model=CoinListResponse)
def list_coins(
    fv: float | None = Query(default=None, description="Filter face_value"),
    country: str | None = Query(default=None, description="CSV ISO2 (ex: 'DE,FR')"),
    commemo: int | None = Query(default=None, description="0 ou 1"),
    has_bce: bool | None = None,
    has_ebay: bool | None = None,
    has_lmdlp: bool | None = None,
    has_wikipedia: bool | None = None,
    has_numista: bool | None = None,
    in_design_group: bool | None = None,
    include_variants: bool = Query(
        default=False,
        description="Inclure les variantes (coloured/hologram/mule/pattern). "
                    "Par défaut la liste ne montre que les canoniques.",
    ),
    personal_owned: bool | None = None,
    lent_to_me: bool | None = None,
    search: str | None = Query(default=None, description="ILIKE eurio_id/theme + numista_id exact"),
    eurio_ids: str | None = Query(default=None, description="CSV restrict to these eurio_ids"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> CoinListResponse:
    """Liste paginée avec filtres pour CoinsPage.vue (P.8b.1)."""
    conn = _conn()
    where: list[str] = []
    params: list[Any] = []

    if fv is not None:
        where.append("face_value = ?")
        params.append(fv)
    if country:
        countries = [c.strip() for c in country.split(",") if c.strip()]
        if countries:
            placeholders = ",".join("?" * len(countries))
            where.append(f"country IN ({placeholders})")
            params.extend(countries)
    if commemo is not None:
        where.append("is_commemorative = ?")
        params.append(1 if commemo else 0)
    if personal_owned is not None:
        where.append("personal_owned = ?")
        params.append(1 if personal_owned else 0)
    if lent_to_me is not None:
        where.append("lent_to_me = ?")
        params.append(1 if lent_to_me else 0)
    if in_design_group is not None:
        where.append("design_group_id IS NOT NULL" if in_design_group
                     else "design_group_id IS NULL")
    if not include_variants:
        # Chantier variantes : la liste ne montre que les canoniques ; les
        # variantes (coloured/hologram/mule/pattern) sont accessibles via les
        # badges de la page détail.
        where.append("canonical_eurio_id IS NULL")

    has_filter_map = [
        ("bce_official", has_bce),
        ("ebay_browse", has_ebay),
        ("lmdlp", has_lmdlp),
        ("wikipedia", has_wikipedia),
    ]
    for registry_id, want in has_filter_map:
        if want is None:
            continue
        sub = (
            "EXISTS (SELECT 1 FROM coin_source_refs r WHERE r.target_kind='coin' "
            "AND r.target_id = c.eurio_id AND r.source = ?)"
        )
        where.append(sub if want else f"NOT {sub}")
        params.append(registry_id)

    if has_numista is not None:
        sub = (
            "(c.numista_id IS NOT NULL OR EXISTS (SELECT 1 FROM coin_source_refs r "
            "WHERE r.target_kind='coin' AND r.target_id=c.eurio_id AND r.source='numista_api'))"
        )
        where.append(sub if has_numista else f"NOT {sub}")

    if search:
        s = search.strip()
        like = f"%{s}%"
        clauses = ["c.eurio_id LIKE ?", "c.theme LIKE ?", "c.country = ?"]
        params.extend([like, like, s])
        if s.isdigit():
            clauses.append("c.numista_id = ?")
            params.append(int(s))
        where.append("(" + " OR ".join(clauses) + ")")

    if eurio_ids:
        ids = [e.strip() for e in eurio_ids.split(",") if e.strip()]
        if ids:
            placeholders = ",".join("?" * len(ids))
            where.append(f"c.eurio_id IN ({placeholders})")
            params.extend(ids)

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        f"SELECT COUNT(*) FROM coins c {where_clause}", params,
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT c.eurio_id FROM coins c {where_clause} "
        f"ORDER BY c.country, c.year DESC, c.face_value DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    items = [_build_coin_detail(conn, r[0]) for r in rows]
    return CoinListResponse(items=items, total=total)


# ── Lookups ───────────────────────────────────────────────────────────────


@router.get("/lookups/trained", response_model=list[str])
def get_trained_eurio_ids() -> list[str]:
    """Liste eurio_ids ayant un embedding (équivalent Supabase
    coin_embeddings.eurio_id distinct)."""
    rows = _conn().execute(
        "SELECT DISTINCT eurio_id FROM coin_embeddings ORDER BY eurio_id"
    ).fetchall()
    return [r[0] for r in rows]


@router.get("/lookups/source-counts", response_model=dict[str, int])
def get_source_counts() -> dict[str, int]:
    """Counts par source (numista, bce, wikipedia, lmdlp, ebay). Dérivé
    de coin_source_refs côté SQLite (vs has_* booléens Supabase). Mapping
    pipeline → ID frontend conservé pour compat (`numista` = numista_api,
    `bce` = bce_official, etc.)."""
    conn = _conn()
    # Sources lues en SQL via les noms registry, exposées sous les clés
    # frontend (court).
    sources = {
        "numista":   "numista_api",
        "bce":       "bce_official",
        "wikipedia": "wikipedia",
        "lmdlp":     "lmdlp",
        "ebay":      "ebay_browse",
    }
    out: dict[str, int] = {}
    for key, registry in sources.items():
        row = conn.execute(
            "SELECT COUNT(DISTINCT target_id) FROM coin_source_refs "
            "WHERE source = ? AND target_kind = 'coin'",
            (registry,),
        ).fetchone()
        out[key] = row[0] if row else 0
    return out


# ── Detail + sub-resources ────────────────────────────────────────────────


def _build_coin_detail(conn: sqlite3.Connection, eurio_id: str) -> CoinDetail:
    row = conn.execute(
        "SELECT * FROM coins WHERE eurio_id = ?", (eurio_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"coin {eurio_id} not found")
    d: dict[str, Any] = dict(row)

    # Images depuis coin_canonical_images
    img_rows = conn.execute(
        "SELECT role, source, url, local_path FROM coin_canonical_images "
        "WHERE eurio_id = ? ORDER BY role, source", (eurio_id,),
    ).fetchall()
    images = [CoinImage(**dict(r)) for r in img_rows]

    # cross_refs depuis coin_cross_refs (key=ref_type, value=ref_value)
    cr_rows = conn.execute(
        "SELECT ref_type, ref_value FROM coin_cross_refs WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchall()
    cross_refs = {r["ref_type"]: r["ref_value"] for r in cr_rows}

    # sources_used = distinct sources qui ont déposé une row sur ce coin
    src_rows = conn.execute(
        "SELECT DISTINCT source FROM coin_source_refs "
        "WHERE target_kind = 'coin' AND target_id = ? ORDER BY source",
        (eurio_id,),
    ).fetchall()
    sources_used = [r[0] for r in src_rows]

    has_flags = {
        "has_bce":       "bce_official" in sources_used,
        "has_ebay":      "ebay_browse"  in sources_used,
        "has_wikipedia": "wikipedia"    in sources_used,
        "has_lmdlp":     "lmdlp"        in sources_used,
    }

    # coin_topics — contexte commémoratif verbeux multi-source per lang
    # (Numista commemorated_topic + BCE feature, en + fr + LLM DE/IT/ES/NL).
    topic_rows = conn.execute(
        """
        SELECT source, lang, topic, method, confidence
          FROM coin_topics
         WHERE eurio_id = ?
         ORDER BY CASE source
                    WHEN 'numista_api'  THEN 1
                    WHEN 'bce_official' THEN 2
                    ELSE 9
                  END,
                  CASE lang
                    WHEN 'fr' THEN 1 WHEN 'en' THEN 2
                    WHEN 'de' THEN 3 WHEN 'it' THEN 4
                    WHEN 'es' THEN 5 WHEN 'nl' THEN 6
                    ELSE 9
                  END
        """,
        (eurio_id,),
    ).fetchall()
    topics = [CoinTopic(**dict(r)) for r in topic_rows]

    return CoinDetail(
        eurio_id=d["eurio_id"],
        country=d["country"],
        country_name=d.get("country_name"),
        year=d["year"],
        face_value=d["face_value"],
        currency=d.get("currency") or "EUR",
        is_commemorative=bool(d.get("is_commemorative", 0)),
        theme=d.get("theme"),
        numista_id=d.get("numista_id"),
        design_description=d.get("design_description"),
        design_group_id=d.get("design_group_id"),
        series_id=d.get("series_id"),
        personal_owned=bool(d.get("personal_owned", 0)),
        lent_to_me=bool(d.get("lent_to_me", 0)),
        needs_review=bool(d.get("needs_review", 0)),
        images=images,
        cross_refs=cross_refs,
        sources_used=sources_used,
        topics=topics,
        **has_flags,
    )


@router.get("/{eurio_id}", response_model=CoinDetail)
def get_coin(eurio_id: str) -> CoinDetail:
    return _build_coin_detail(_conn(), eurio_id)


@router.get("/{eurio_id}/i18n", response_model=I18nResponse)
def get_coin_i18n(eurio_id: str) -> I18nResponse:
    conn = _conn()
    names_rows = conn.execute(
        "SELECT lang, title, source, method, confidence, model "
        "FROM coin_names_i18n WHERE eurio_id = ? ORDER BY lang",
        (eurio_id,),
    ).fetchall()
    aliases_rows = conn.execute(
        "SELECT lang, alias, source, method, confidence FROM coin_aliases "
        "WHERE eurio_id = ? ORDER BY lang, alias", (eurio_id,),
    ).fetchall()
    return I18nResponse(
        names=[I18nName(**dict(r)) for r in names_rows],
        aliases=[I18nAlias(**dict(r)) for r in aliases_rows],
    )


@router.get("/{eurio_id}/descriptions", response_model=DescriptionsResponse)
def get_coin_descriptions(eurio_id: str) -> DescriptionsResponse:
    """Titres + descriptions officiels BCE dans les 24 langues UE
    (``coin_descriptions_i18n``). Une row par (eurio_id, source, lang) :
    title + description appariés. Sert le sélecteur de langue de la fiche."""
    conn = _conn()
    rows = conn.execute(
        "SELECT lang, title, description, source, method, confidence, model "
        "FROM coin_descriptions_i18n WHERE eurio_id = ? ORDER BY lang",
        (eurio_id,),
    ).fetchall()
    return DescriptionsResponse(
        descriptions=[CoinDescription(**dict(r)) for r in rows],
    )


@router.get("/{eurio_id}/source-status", response_model=SourceStatusResponse)
def get_coin_source_status(eurio_id: str) -> SourceStatusResponse:
    """Disponibilité de données par source pour ce coin. Renvoie une entrée
    pour CHAQUE source affichée (``DISPLAYED_SOURCES``), en défautant à
    ``never`` quand ``coin_source_status`` n'a pas de row (l'absence vaut
    never). ``axes`` = ``detail_json.axes``."""
    conn = _conn()
    rows = conn.execute(
        "SELECT source, state, detail_json, last_checked_at, last_run_id, updated_at "
        "FROM coin_source_status WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchall()
    by_source = {r["source"]: dict(r) for r in rows}
    entries: list[SourceStatusEntry] = []
    for src in DISPLAYED_SOURCES:
        row = by_source.get(src)
        if row is None:
            entries.append(SourceStatusEntry(source=src, state="never"))
            continue
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            detail = {}
        entries.append(SourceStatusEntry(
            source=src,
            state=row["state"],
            axes=detail.get("axes", {}),
            last_checked_at=row["last_checked_at"],
            last_run_id=row["last_run_id"],
            updated_at=row["updated_at"],
        ))
    return SourceStatusResponse(eurio_id=eurio_id, sources=entries)


class RefreshResponse(BaseModel):
    run_id: str
    source: str
    status: str = "started"


@router.post("/{eurio_id}/refresh", response_model=RefreshResponse, status_code=202)
def refresh_coin_source(
    eurio_id: str,
    source: str = Query(..., description="bce | numista | jo | lmdlp"),
    force: bool = Query(default=False),
) -> RefreshResponse:
    """Rejoue le fetch d'un coin pour une source (async). Lance un run dans un
    thread daemon (réutilise la plomberie source_runs), renvoie son run_id ; le
    front poll ``GET /sources/{source}/runs/{run_id}``. Le verdict est écrit
    dans ``coin_source_status`` à la fin du run."""
    if source not in ("bce", "numista", "jo", "lmdlp"):
        raise HTTPException(status_code=400,
                            detail="source must be 'bce', 'numista', 'jo' or 'lmdlp'")
    conn = _conn()
    if conn.execute("SELECT 1 FROM coins WHERE eurio_id = ?", (eurio_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail=f"coin {eurio_id} not found")

    existing = conn.execute(
        "SELECT id FROM source_runs WHERE source = ? AND status = 'running' LIMIT 1",
        (source,),
    ).fetchone()
    if existing and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "run_already_running",
                "run_id": existing["id"],
                "message": f"A run for '{source}' is already running. Pass ?force=true.",
            },
        )

    store = _store
    run_id_holder: dict[str, str] = {}
    started = threading.Event()

    def _runner() -> None:
        try:
            from referential.coin_refresh import refresh_coin
            run_id_holder["run_id"] = refresh_coin(store, eurio_id, source, force=force)
        except Exception:
            logger.exception("[coin-refresh] %s/%s crashed", eurio_id, source)
        finally:
            started.set()

    threading.Thread(target=_runner, name=f"coin-refresh-{source}", daemon=True).start()
    # Le run est ouvert (start_run) dès l'entrée de l'orchestrateur (<2s) ; on
    # attend brièvement puis on retombe sur la row running la plus récente.
    started.wait(timeout=2.0)
    rid = run_id_holder.get("run_id")
    if rid is None:
        row = conn.execute(
            "SELECT id FROM source_runs WHERE source = ? ORDER BY started_at DESC LIMIT 1",
            (source,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=500,
                                detail="refresh run did not register a source_runs row in time")
        rid = row["id"]
    return RefreshResponse(run_id=rid, source=source)


class CoinCardResponse(BaseModel):
    eurio_id: str
    image_url: str | None
    title_fr: str | None
    country: str
    year: int
    jo: bool
    joint: bool


@router.get("/{eurio_id}/card", response_model=CoinCardResponse)
def get_coin_card(eurio_id: str) -> CoinCardResponse:
    """Carte légère d'un coin pour le hover de la matrice de couverture :
    image de base (avers) + titre FR par défaut + flags JO/commune."""
    from api._coin_helpers import canonical_obverse_url, fr_title

    conn = _conn()
    row = conn.execute(
        "SELECT country, year, design_group_id FROM coins WHERE eurio_id = ?",
        (eurio_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"coin {eurio_id} not found")
    jo = conn.execute(
        "SELECT 1 FROM coin_source_refs WHERE target_kind='coin' "
        "AND target_id=? AND source='eurlex_jo' LIMIT 1",
        (eurio_id,),
    ).fetchone() is not None
    return CoinCardResponse(
        eurio_id=eurio_id,
        image_url=canonical_obverse_url(conn, eurio_id),
        title_fr=fr_title(conn, eurio_id),
        country=row["country"],
        year=row["year"],
        jo=jo,
        joint=bool(row["design_group_id"] and str(row["design_group_id"]).startswith("eu-")),
    )


@router.get("/{eurio_id}/prices", response_model=PricesResponse)
def get_coin_prices(eurio_id: str) -> PricesResponse:
    """Option B (cf. P.8 audit) — structure riche :
    * type_level   : agrégation UNC/TTB/TB depuis coin_market_quotes
    * mint_release_level : prix granulaires par atelier × grade depuis
      mint_release_prices (joint avec coin_mint_releases pour les méta)
    """
    conn = _conn()
    tl_rows = conn.execute(
        "SELECT source, condition_raw, condition_normalized, currency, "
        "p10, p50, p90, sample_size, period_start, period_end "
        "FROM coin_market_quotes WHERE eurio_id = ? "
        "ORDER BY period_start DESC, condition_normalized",
        (eurio_id,),
    ).fetchall()

    mr_rows = conn.execute(
        """
        SELECT p.mint_release_id, r.parent_type_id, r.mint_id, r.mint_year,
               r.issue_type, p.source, p.grade_raw, p.grade_eurio,
               p.price, p.currency, p.fetched_at
        FROM mint_release_prices p
        JOIN coin_mint_releases r ON r.id = p.mint_release_id
        WHERE r.parent_type_id = ?
        ORDER BY r.mint_year, r.mint_id, r.issue_type, p.grade_raw
        """,
        (eurio_id,),
    ).fetchall()

    return PricesResponse(
        type_level=[TypeLevelPrice(**dict(r)) for r in tl_rows],
        mint_release_level=[MintReleasePrice(**dict(r)) for r in mr_rows],
    )


@router.get("/{eurio_id}/observations", response_model=ObservationsResponse)
def get_coin_observations(eurio_id: str) -> ObservationsResponse:
    """Observations Type-level (compo, poids, diamètre, épaisseur, edge,
    lettering, forme, orientation, démonétisation…) avec provenance, plus des
    raccourcis aplatis pour un affichage direct."""
    conn = _conn()
    rows = conn.execute(
        "SELECT observation_type, payload_json, source, source_ref, recorded_at "
        "FROM coin_observations WHERE eurio_id = ? "
        "ORDER BY observation_type, source",
        (eurio_id,),
    ).fetchall()

    observations: list[CoinObservation] = []
    # 1re valeur par type (priorité d'insertion = ordre du SELECT).
    flat: dict[str, Any] = {}
    for r in rows:
        d = dict(r)
        try:
            value = json.loads(d["payload_json"])
        except (json.JSONDecodeError, TypeError):
            value = d["payload_json"]
        observations.append(CoinObservation(
            observation_type=d["observation_type"], value=value,
            source=d["source"], source_ref=d.get("source_ref"),
            recorded_at=d.get("recorded_at"),
        ))
        flat.setdefault(d["observation_type"], value)

    demon = flat.get("demonetization")
    is_demonetized = (
        demon.get("is_demonetized") if isinstance(demon, dict) else None
    )
    return ObservationsResponse(
        observations=observations,
        composition=flat.get("composition"),
        weight_g=flat.get("weight_g"),
        diameter_mm=flat.get("diameter_mm"),
        thickness_mm=flat.get("thickness_mm"),
        shape=flat.get("shape"),
        orientation=flat.get("orientation"),
        edge_description=flat.get("edge_description"),
        edge_lettering=flat.get("edge_lettering"),
        edge_lettering_translation=flat.get("edge_lettering_translation"),
        obverse_lettering=flat.get("obverse_lettering"),
        reverse_lettering=flat.get("reverse_lettering"),
        is_demonetized=is_demonetized,
    )


@router.get("/{eurio_id}/credits", response_model=CreditsResponse)
def get_coin_credits(eurio_id: str) -> CreditsResponse:
    """Crédits regroupés par rôle (designers / engravers / sculptors)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT role, name, source, source_ref, position "
        "FROM coin_credits WHERE eurio_id = ? ORDER BY role, position, name",
        (eurio_id,),
    ).fetchall()
    buckets: dict[str, list[CreditEntry]] = {
        "designer": [], "engraver": [], "sculptor": [],
    }
    for r in rows:
        d = dict(r)
        buckets.setdefault(d["role"], []).append(CreditEntry(
            name=d["name"], source=d["source"],
            source_ref=d.get("source_ref"), position=d.get("position") or 0,
        ))
    return CreditsResponse(
        designers=buckets["designer"],
        engravers=buckets["engraver"],
        sculptors=buckets["sculptor"],
    )


@router.get("/{eurio_id}/mint-releases-full", response_model=MintReleasesFullResponse)
def get_coin_mint_releases_full(eurio_id: str) -> MintReleasesFullResponse:
    """Millésimes (coin_mint_releases) centralisés avec leurs observations
    (mintage…) ET leurs prix par grade. Les prix étant historisés par
    fetched_at, on ne renvoie que le snapshot le plus récent par millésime."""
    conn = _conn()
    releases = conn.execute(
        "SELECT id, mint_year, mint_id, issue_type, notes "
        "FROM coin_mint_releases WHERE parent_type_id = ? "
        "ORDER BY mint_year, mint_id, issue_type",
        (eurio_id,),
    ).fetchall()

    out: list[MintReleaseFull] = []
    for rel in releases:
        rid = rel["id"]
        obs_rows = conn.execute(
            "SELECT fact_type, value_json, source FROM mint_release_observations "
            "WHERE mint_release_id = ? ORDER BY fact_type, source",
            (rid,),
        ).fetchall()
        observations: list[MintReleaseObservation] = []
        for o in obs_rows:
            try:
                value = json.loads(o["value_json"])
            except (json.JSONDecodeError, TypeError):
                value = o["value_json"]
            observations.append(MintReleaseObservation(
                fact_type=o["fact_type"], value=value, source=o["source"],
            ))

        # Snapshot prix le plus récent (max fetched_at) pour ce millésime.
        latest = conn.execute(
            "SELECT MAX(fetched_at) FROM mint_release_prices WHERE mint_release_id = ?",
            (rid,),
        ).fetchone()[0]
        prices: list[MintReleasePriceEntry] = []
        if latest is not None:
            price_rows = conn.execute(
                "SELECT grade_raw, grade_eurio, price, currency, source, fetched_at "
                "FROM mint_release_prices WHERE mint_release_id = ? AND fetched_at = ? "
                "ORDER BY grade_eurio, grade_raw",
                (rid, latest),
            ).fetchall()
            prices = [MintReleasePriceEntry(**dict(p)) for p in price_rows]

        out.append(MintReleaseFull(
            id=rid, mint_year=rel["mint_year"], mint_id=rel["mint_id"],
            issue_type=rel["issue_type"], notes=rel["notes"],
            observations=observations, prices=prices,
        ))
    return MintReleasesFullResponse(mint_releases=out)


# ─── Groupe de variantes (chantier variantes) ────────────────────────────

class VariantGroupEntry(BaseModel):
    eurio_id: str
    variant_kind: str
    variant_label: str | None = None
    title: str | None = None          # titre EN (coin_names_i18n) pour affichage
    is_self: bool = False             # True = la pièce courante


class VariantGroupResponse(BaseModel):
    canonical_eurio_id: str           # eurio_id de la canonique du groupe
    members: list[VariantGroupEntry]  # canonique + variantes (None si pas de groupe)


@router.get("/{eurio_id}/variant-group", response_model=VariantGroupResponse)
def get_coin_variant_group(eurio_id: str) -> VariantGroupResponse:
    """Groupe canonique + variantes pour les badges de la page détail.

    Le groupe est défini par ``canonical_eurio_id`` : la canonique du groupe
    est ``coin.canonical_eurio_id`` (si la pièce courante est une variante)
    sinon son propre eurio_id. Les membres = la canonique + toutes les pièces
    pointant vers elle. Renvoie un groupe à 1 membre si la pièce n'a aucune
    variante (le front masque alors les badges)."""
    conn = _conn()
    row = conn.execute(
        "SELECT canonical_eurio_id FROM coins WHERE eurio_id = ?", (eurio_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"coin {eurio_id} not found")
    canonical = row["canonical_eurio_id"] or eurio_id

    members_rows = conn.execute(
        "SELECT eurio_id, variant_kind, variant_label FROM coins "
        "WHERE eurio_id = ? OR canonical_eurio_id = ? "
        "ORDER BY (variant_kind = 'classic') DESC, variant_kind, eurio_id",
        (canonical, canonical),
    ).fetchall()
    members: list[VariantGroupEntry] = []
    for m in members_rows:
        t = conn.execute(
            "SELECT title FROM coin_names_i18n WHERE eurio_id = ? AND lang = 'en'",
            (m["eurio_id"],),
        ).fetchone()
        members.append(VariantGroupEntry(
            eurio_id=m["eurio_id"],
            variant_kind=m["variant_kind"],
            variant_label=m["variant_label"],
            title=t["title"] if t else None,
            is_self=(m["eurio_id"] == eurio_id),
        ))
    return VariantGroupResponse(canonical_eurio_id=canonical, members=members)


# ─── Design group (pièces partageant un AVERS) ───────────────────────────────
# Distinct des variantes (variant_kind, ci-dessus) : ici ce sont des pièces
# DIFFÉRENTES (pays/années) qui partagent la même face nationale — donc une
# seule classe ArcFace (COALESCE(design_group_id, eurio_id)). Couvre tous les
# design_groups : avers-standards (be-…-t1), joint-issues eu-*, numista_id.

class DesignGroupMember(BaseModel):
    eurio_id: str
    country: str
    year: int
    variant_kind: str
    title: str | None = None          # titre FR pour affichage
    obverse_url: str | None = None    # vignette avers canonique
    is_self: bool = False             # True = la pièce courante


class DesignGroupResponse(BaseModel):
    design_group_id: str | None = None   # None si la pièce n'appartient à aucun groupe
    designation: str | None = None       # libellé humain du groupe (= classe ArcFace)
    members: list[DesignGroupMember]     # [] si pas de groupe


@router.get("/{eurio_id}/design-group", response_model=DesignGroupResponse)
def get_coin_design_group(eurio_id: str) -> DesignGroupResponse:
    """Pièces partageant l'AVERS de ``eurio_id`` (membres de son design_group).

    Le ``design_group`` est l'unité de classe ArcFace : be-1999 + be-2007 (même
    effigie, carte différente) → une classe. Renvoie ``members=[]`` si la pièce
    n'a pas de ``design_group_id`` (le front masque alors la section). Générique
    pour tous les groupes (avers-standards, joint-issues, numista_id)."""
    from api._coin_helpers import canonical_obverse_url, fr_title

    conn = _conn()
    row = conn.execute(
        "SELECT design_group_id FROM coins WHERE eurio_id = ?", (eurio_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"coin {eurio_id} not found")
    dgid = row["design_group_id"]
    if not dgid:
        return DesignGroupResponse(design_group_id=None, designation=None, members=[])

    dg = conn.execute(
        "SELECT designation FROM design_groups WHERE id = ?", (dgid,),
    ).fetchone()
    member_rows = conn.execute(
        "SELECT eurio_id, country, year, variant_kind FROM coins "
        "WHERE design_group_id = ? ORDER BY year, eurio_id",
        (dgid,),
    ).fetchall()
    members = [
        DesignGroupMember(
            eurio_id=m["eurio_id"],
            country=m["country"],
            year=m["year"],
            variant_kind=m["variant_kind"],
            title=fr_title(conn, m["eurio_id"]),
            obverse_url=canonical_obverse_url(conn, m["eurio_id"]),
            is_self=(m["eurio_id"] == eurio_id),
        )
        for m in member_rows
    ]
    return DesignGroupResponse(
        design_group_id=dgid,
        designation=dg["designation"] if dg else None,
        members=members,
    )


@router.get("/{eurio_id}/embedding", response_model=EmbeddingResponse)
def get_coin_embedding(eurio_id: str) -> EmbeddingResponse:
    """Renvoie le model_version le plus récent (par created_at) si présent."""
    row = _conn().execute(
        "SELECT model_version FROM coin_embeddings WHERE eurio_id = ? "
        "ORDER BY created_at DESC LIMIT 1", (eurio_id,),
    ).fetchone()
    return EmbeddingResponse(model_version=row[0] if row else None)


@router.get("/{eurio_id}/series", response_model=CoinSeries | None)
def get_coin_series(eurio_id: str) -> CoinSeries | None:
    conn = _conn()
    coin = conn.execute(
        "SELECT series_id FROM coins WHERE eurio_id = ?", (eurio_id,),
    ).fetchone()
    if coin is None or coin[0] is None:
        return None
    row = conn.execute(
        "SELECT id, country, designation, designation_i18n_json, description, "
        "minting_started_at, minting_ended_at, minting_end_reason "
        "FROM coin_series WHERE id = ?", (coin[0],),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    designation_i18n = (
        json.loads(d["designation_i18n_json"]) if d.get("designation_i18n_json") else None
    )
    return CoinSeries(
        id=d["id"], country=d["country"], designation=d["designation"],
        designation_i18n=designation_i18n,
        description=d.get("description"),
        minting_started_at=d["minting_started_at"],
        minting_ended_at=d.get("minting_ended_at"),
        minting_end_reason=d.get("minting_end_reason"),
    )


@router.patch("/{eurio_id}", response_model=CoinDetail)
def patch_coin(eurio_id: str, payload: CoinPatch) -> CoinDetail:
    """Flip personal_owned / lent_to_me. Pas-d'-op si payload vide."""
    conn = _conn()
    updates: list[str] = []
    params: list[Any] = []
    if payload.personal_owned is not None:
        updates.append("personal_owned = ?")
        params.append(1 if payload.personal_owned else 0)
    if payload.lent_to_me is not None:
        updates.append("lent_to_me = ?")
        params.append(1 if payload.lent_to_me else 0)
    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(eurio_id)
        sql = f"UPDATE coins SET {', '.join(updates)} WHERE eurio_id = ?"
        result = conn.execute(sql, params)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"coin {eurio_id} not found")
    return _build_coin_detail(conn, eurio_id)
