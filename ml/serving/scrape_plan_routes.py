"""La moitié ACHETER de `/besoin` — ce qui manque, ce que ça coûte, ce qu'il reste.

Lot 5 du chantier `pipeline-propre`
(``docs/work-in-progress/pipeline-propre/design/PLAN-IMPLEM.md``).

⛔ **ROUTE LOURDE, ET C'EST STRUCTUREL.** Contrairement à ``/class-need`` (SQL
pur sur le canonique, servi par l'image lean), ce module lit **deux** bases :

- le canonique / sa réplique — le besoin par classe et le ciblage eBay passé ;
- ``ml/state/eurio.local.db`` — le **budget vrai** (``api_call_log``), qui est
  de l'état d'observabilité PAR MACHINE et ne voyage jamais au canonique.

La seconde n'existe que là où on scrape. Le bloc est donc monté sur
``server.py`` (workstation) **seulement**, jamais sur ``server_serve.py`` — et
la page ``/besoin`` reste, elle, non-``heavy`` : elle s'affiche entièrement en
hébergé, ce bloc-ci grisé.

⛔ **AUCUNE ÉCRITURE, ET AUCUN APPEL eBay.** Les deux connexions sont ouvertes
en ``mode=ro`` (URI). On ne passe **pas** par ``shared.api_quota.QuotaTracker``
pour lire le quota : son ``__init__`` appelle ``ensure_schema()``, qui ouvre la
base en écriture et y fait un ``CREATE TABLE IF NOT EXISTS``. Lire un budget ne
doit rien écrire — on relit donc ``api_call_log`` à la main, sur la même clé
``(source, window, period)`` que le tracker.

LES DEUX RÉSERVES SONT PORTÉES À L'ÉCRAN, PAS TUES
--------------------------------------------------
``FLOW-ADMIN.md`` §Station 1 : « sinon la station ment ».

1. Le préflight quota de ``ml/sources/cli.py`` est **faux d'un facteur ~130** —
   il estime sur ``source_runs.n_calls``, qui ne compte que les recherches
   (mesuré : ``n_calls=3`` pour un run qui a brûlé 740 appels).
2. Le budget vrai est dans ``ml/state/eurio.local.db``, **pas au canonique**.
   Le chemin lu est renvoyé dans la réponse : un chiffre de quota sans son
   fichier n'est pas vérifiable.

CHAQUE CHIFFRE PORTE SA REQUÊTE
-------------------------------
Le rendement (« 6,6 annonces par exemplaire ») n'est pas une constante : il se
**remesure à chaque appel**, et la réponse transporte les deux requêtes SQL qui
le produisent. La mesure de référence du 2026-08-22 (7 662 / 1 160 = 6,6) est
renvoyée à côté, pour qu'un écart se lise comme un écart et non comme un
désaccord.
"""
from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from scripts.allocate_ebay_scrape import (
    COST_PER_COMMEMO_GROUP,
    COST_PER_STANDARD_GROUP,
    DEFAULT_TARGET_EXEMPLARS,
    EBAY_DAILY_QUOTA,
    QUOTA_SAFETY_FACTOR,
    ClassState,
    DiscoveryGroupKey,
    group_key_for,
)
from shared.class_need import all_needs

logger = logging.getLogger("scrape_plan")

router = APIRouter(tags=["besoin"])

ANCHORS_KIND = "2eur_all"
ENCODER_VERSION = "dinov2-vitl14"

#: Mesure du 2026-08-22 (DESIGN.md §4.5) : 7 662 annonces eBay au grain listing
#: pour 1 160 exemplaires `fps`. Gardée comme **repère**, jamais comme source :
#: le rendement servi est celui remesuré à l'appel.
REFERENCE_YIELD = 6.6
REFERENCE_YIELD_LISTINGS = 7662
REFERENCE_YIELD_EXEMPLARS = 1160

#: Les deux requêtes du rendement, renvoyées telles quelles au front. Un chiffre
#: dont on ne peut pas rejouer la requête n'est pas vérifiable, donc inutile.
Q_LISTINGS = (
    "SELECT COUNT(*) FROM (SELECT substr(source_ref, 1, instr(source_ref, '_img') - 1) k "
    "FROM source_images WHERE source = 'ebay' GROUP BY 1)"
)
Q_EXEMPLARS = (
    "SELECT COUNT(*) FROM dino_class_references "
    "WHERE anchors_kind = ? AND method = 'fps'"
)
Q_TARGETED = (
    "SELECT DISTINCT target_eurio_id FROM source_images "
    "WHERE source = 'ebay' AND target_eurio_id IS NOT NULL"
)

RESERVES = [
    "Le préflight quota de `ml/sources/cli.py` est faux d'un facteur ~130 : il "
    "estime sur `source_runs.n_calls`, qui ne compte que les recherches "
    "(mesuré : n_calls=3 pour un run qui a brûlé 740 appels).",
    "Le budget vrai est dans `ml/state/eurio.local.db` (`api_call_log`), pas au "
    "canonique — c'est de l'état d'observabilité par machine.",
]


# ── Modèles de réponse ───────────────────────────────────────────────────────


class BuildInfo(BaseModel):
    """Quelle banque a été lue. Même bloc que `/class-need`, même raison : la
    banque a été rebâtie deux fois pendant la seule session de design."""

    anchors_kind: str
    encoder_version: str
    build_id: str | None
    built_at: str | None
    n_anchors: int


class YieldMeasure(BaseModel):
    """Le rendement, REMESURÉ, avec ses deux requêtes."""

    n_listings: int
    n_exemplars: int
    #: annonces eBay par exemplaire posé en banque. `None` si la banque est vide
    #: — un rendement infini n'est pas un rendement.
    listings_per_exemplar: float | None
    query_listings: str
    query_exemplars: str
    #: Les paramètres liés de `query_exemplars`. Rendus à part plutôt
    #: qu'interpolés : une requête qu'on rejoue doit être la MÊME que celle
    #: qu'on a exécutée, paramètres compris — et interpoler ouvrirait une
    #: injection sur un `anchors_kind` qui vient de la query string.
    query_exemplars_params: list[str]
    reference: float = REFERENCE_YIELD
    reference_listings: int = REFERENCE_YIELD_LISTINGS
    reference_exemplars: int = REFERENCE_YIELD_EXEMPLARS


class QuotaReading(BaseModel):
    """Le quota eBay du jour, lu là où il est vrai."""

    #: Le fichier lu, en clair. Sans lui le chiffre n'est pas vérifiable — et
    #: c'est exactement la réserve n°2.
    db_path: str
    source: str
    window: str
    period: str
    limit: int
    calls: int
    remaining: int
    #: Ce qu'on peut PLANIFIER : le restant divisé par la marge du préflight.
    safe_budget: int
    safety_factor: float
    readable: bool
    error: str | None = None


class CountryNeed(BaseModel):
    country: str
    #: Classes dont le goulot est `scrape` (aucun candidat en file).
    n_classes: int
    #: Sous-ensemble à `have == 0` : le palier 1, celles qui sont aveugles.
    n_zero: int
    #: JAMAIS visées par une annonce eBay (`source_images.target_eurio_id`).
    n_never_targeted: int
    #: Visées, mais sans exemplaire ni candidat au bout. Ce n'est PAS la même
    #: population : la première se répare en scrapant, la seconde en cherchant
    #: pourquoi le scrape n'a rien donné.
    n_targeted_no_result: int
    #: Σ `need` — exemplaires manquants à la cible.
    sum_need: int
    #: Groupes de découverte (pays · dénomination · année) à interroger.
    n_groups: int
    n_groups_standard: int
    #: Coût quota estimé : 130 appels/groupe commémo, 240/groupe standard.
    estimated_calls: int
    #: Coût en annonces pour poser UN premier exemplaire dans chacune des
    #: classes JAMAIS VISÉES (`n_never_targeted`, la base du chiffre du design :
    #: 274 × 6,6 ≈ 1 808), au rendement REMESURÉ. Ce n'est pas `n_zero` × ratio :
    #: une classe déjà visée sans résultat ne se répare pas en rescrapant.
    #: `None` si le rendement est inconnu — un rendement infini n'en est pas un.
    estimated_listings_palier1: int | None


class ScrapeTotals(BaseModel):
    n_classes: int
    n_zero: int
    n_never_targeted: int
    n_targeted_no_result: int
    sum_need: int
    n_groups: int
    estimated_calls: int
    estimated_listings_palier1: int | None


class ScrapePlanSummary(BaseModel):
    build: BuildInfo
    target: int
    totals: ScrapeTotals
    countries: list[CountryNeed]
    measured_yield: YieldMeasure
    quota: QuotaReading
    reserves: list[str] = Field(default_factory=lambda: list(RESERVES))
    #: La commande qui ouvre le plan détaillé — dry-run par défaut. Affichée,
    #: jamais exécutée d'ici.
    plan_command: list[str]


# ── Lecture ──────────────────────────────────────────────────────────────────


def connect_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def build_info(
    conn: sqlite3.Connection, anchors_kind: str, encoder_version: str
) -> BuildInfo:
    row = conn.execute(
        "SELECT build_id, MAX(built_at) AS built_at, COUNT(*) AS n "
        "  FROM dino_class_references "
        " WHERE anchors_kind = ? AND encoder_version = ?",
        (anchors_kind, encoder_version),
    ).fetchone()
    n = int(row["n"] or 0) if row is not None else 0
    return BuildInfo(
        anchors_kind=anchors_kind,
        encoder_version=encoder_version,
        build_id=row["build_id"] if row is not None else None,
        built_at=row["built_at"] if row is not None else None,
        n_anchors=n,
    )


def measure_yield(conn: sqlite3.Connection, anchors_kind: str) -> YieldMeasure:
    """Combien d'annonces eBay il a fallu, jusqu'ici, pour poser un exemplaire.

    Le grain est le **listing**, pas l'image : une annonce porte plusieurs
    photos, et compter les photos gonflerait le rendement d'un facteur 3 à 4.
    D'où le `substr(source_ref, 1, instr(source_ref, '_img') - 1)`.
    """
    n_listings = int(conn.execute(Q_LISTINGS).fetchone()[0] or 0)
    n_exemplars = int(conn.execute(Q_EXEMPLARS, (anchors_kind,)).fetchone()[0] or 0)
    ratio = round(n_listings / n_exemplars, 2) if n_exemplars else None
    return YieldMeasure(
        n_listings=n_listings,
        n_exemplars=n_exemplars,
        listings_per_exemplar=ratio,
        query_listings=Q_LISTINGS,
        query_exemplars=Q_EXEMPLARS,
        query_exemplars_params=[anchors_kind],
    )


def read_quota(
    db_path: Path,
    *,
    source: str = "ebay",
    window: str = "daily",
    limit: int = EBAY_DAILY_QUOTA,
    now: datetime | None = None,
) -> QuotaReading:
    """Le compteur d'appels du jour, lu en READ-ONLY dans la DB **locale**.

    ⛔ On n'instancie PAS `QuotaTracker` : son `__init__` appelle
    `ensure_schema()`, donc ouvre la base en écriture et y crée la table. Lire
    un budget ne doit rien écrire — c'est la contrainte du lot.

    Une base illisible rend `readable=False` et `remaining=0`, jamais un quota
    supposé plein : planifier sur un quota inventé est exactement le bug B1
    (le widget affichait 5000/5000 pendant qu'on brûlait 4 733 appels).
    """
    ts = now or datetime.now(timezone.utc)
    period = ts.strftime("%Y-%m") if window == "monthly" else ts.strftime("%Y-%m-%d")
    base = QuotaReading(
        db_path=str(db_path),
        source=source,
        window=window,
        period=period,
        limit=limit,
        calls=0,
        remaining=0,
        safe_budget=0,
        safety_factor=QUOTA_SAFETY_FACTOR,
        readable=False,
        error=None,
    )
    if not db_path.exists():
        return base.model_copy(update={"error": f"{db_path} est introuvable"})
    try:
        conn = connect_ro(db_path)
    except sqlite3.Error as exc:
        return base.model_copy(update={"error": str(exc)})
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(calls), 0) AS calls FROM api_call_log "
            " WHERE source = ? AND window = ? AND period = ?",
            (source, window, period),
        ).fetchone()
    except sqlite3.Error as exc:  # table absente = jamais aucun appel enregistré
        return base.model_copy(update={"error": f"api_call_log illisible : {exc}"})
    finally:
        conn.close()
    calls = int(row["calls"] or 0)
    remaining = max(0, limit - calls)
    return base.model_copy(update={
        "calls": calls,
        "remaining": remaining,
        "safe_budget": int(remaining / QUOTA_SAFETY_FACTOR),
        "readable": True,
    })


def _coin_meta(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {
        r["eurio_id"]: r
        for r in conn.execute(
            "SELECT eurio_id, country, year, is_commemorative FROM coins"
        )
    }


def _targeted_class_ids(conn: sqlite3.Connection) -> set[str]:
    """Les classes qu'une annonce eBay a DÉJÀ visées.

    Le complément dans les classes `scrape` est la population « jamais visée » :
    elle se répare en scrapant. Celles qui ont été visées et n'ont toujours
    rien sont un autre problème — les confondre ferait relancer un scrape qui
    a déjà échoué.
    """
    return {r[0] for r in conn.execute(Q_TARGETED) if r[0]}


# ── Le calcul ────────────────────────────────────────────────────────────────


def summarize(
    conn: sqlite3.Connection,
    quota_db: Path,
    *,
    anchors_kind: str = ANCHORS_KIND,
    encoder_version: str = ENCODER_VERSION,
    target: int = DEFAULT_TARGET_EXEMPLARS,
    now: datetime | None = None,
) -> ScrapePlanSummary:
    """Le besoin `scrape`, par pays, avec son coût et le quota du jour.

    ⛔ Le verdict `scrape` vient de `shared.class_need`, jamais d'une seconde
    rédaction de la règle ici : deux rédactions divergent, et l'écran
    annoncerait un besoin que la page principale ne montre pas.
    """
    build = build_info(conn, anchors_kind, encoder_version)
    if build.n_anchors == 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"aucune ancre pour ({anchors_kind!r}, {encoder_version!r}) — "
                "le couple (banque, encodeur) est indissociable. Une banque "
                "introuvable se lirait « tout est à acheter », ce qui est faux."
            ),
        )

    needs = all_needs(conn, anchors_kind=anchors_kind, encoder_version=encoder_version)
    scrape = [n for n in needs if n.bottleneck == "scrape"]
    targeted = _targeted_class_ids(conn)
    meta = _coin_meta(conn)
    y = measure_yield(conn, anchors_kind)
    ratio = y.listings_per_exemplar

    # Groupes de découverte, par pays. La maille est celle de l'allocateur et
    # de personne d'autre : une recherche eBay ramène un groupe entier
    # (commémo → pays·année, standard → pays·toutes ères).
    groups_by_country: dict[str, set[DiscoveryGroupKey]] = defaultdict(set)
    per_country: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n_classes": 0, "n_zero": 0, "n_never": 0, "n_tried": 0, "need": 0}
    )

    for n in scrape:
        country = n.country or "—"
        c = per_country[country]
        c["n_classes"] += 1
        if n.have == 0:
            c["n_zero"] += 1
        if n.class_id in targeted:
            c["n_tried"] += 1
        else:
            c["n_never"] += 1
        c["need"] += n.need
        m = meta.get(n.class_id)
        if m is None:
            # Une classe de la banque absente de `coins` est une anomalie de
            # données. On la journalise : elle ne doit pas disparaître en
            # silence d'un écran qui prétend dire ce qui manque.
            logger.warning("classe %s absente de `coins` — sans groupe", n.class_id)
            continue
        groups_by_country[country].add(group_key_for(ClassState(
            class_id=n.class_id,
            country=m["country"],
            year=m["year"],
            is_commemorative=bool(m["is_commemorative"]),
        )))

    countries: list[CountryNeed] = []
    for country, c in per_country.items():
        keys = groups_by_country.get(country, set())
        n_std = sum(1 for k in keys if k.is_standard)
        countries.append(CountryNeed(
            country=country,
            n_classes=c["n_classes"],
            n_zero=c["n_zero"],
            n_never_targeted=c["n_never"],
            n_targeted_no_result=c["n_tried"],
            sum_need=c["need"],
            n_groups=len(keys),
            n_groups_standard=n_std,
            estimated_calls=(
                n_std * COST_PER_STANDARD_GROUP
                + (len(keys) - n_std) * COST_PER_COMMEMO_GROUP
            ),
            estimated_listings_palier1=(
                round(c["n_never"] * ratio) if ratio is not None else None
            ),
        ))
    # Le pays qui coûte le plus de classes en premier : c'est l'ordre du geste,
    # pas l'ordre alphabétique.
    countries.sort(key=lambda x: (-x.n_classes, x.country))

    n_never = sum(x.n_never_targeted for x in countries)
    quota = read_quota(quota_db, now=now)
    return ScrapePlanSummary(
        build=build,
        target=target,
        totals=ScrapeTotals(
            n_classes=len(scrape),
            n_zero=sum(x.n_zero for x in countries),
            n_never_targeted=n_never,
            n_targeted_no_result=sum(x.n_targeted_no_result for x in countries),
            sum_need=sum(x.sum_need for x in countries),
            n_groups=sum(x.n_groups for x in countries),
            estimated_calls=sum(x.estimated_calls for x in countries),
            estimated_listings_palier1=(
                round(n_never * ratio) if ratio is not None else None
            ),
        ),
        countries=countries,
        measured_yield=y,
        quota=quota,
        plan_command=[
            "go-task", "ml:ebay:allocate", "--",
            "--budget", str(quota.safe_budget),
        ],
    )


# ── Routes ───────────────────────────────────────────────────────────────────


def _canonical_db() -> Path:
    from store import resolve_db_path

    return resolve_db_path(Path(__file__).resolve().parents[1] / "state" / "eurio.replica.db")


def _quota_db() -> Path:
    from store import resolve_local_state_db

    return resolve_local_state_db()


@router.get("/scrape-plan/summary", response_model=ScrapePlanSummary)
def get_scrape_plan_summary(
    anchors_kind: str = Query(default=ANCHORS_KIND),
    encoder_version: str = Query(default=ENCODER_VERSION),
    target: int = Query(default=DEFAULT_TARGET_EXEMPLARS, ge=1, le=10),
) -> ScrapePlanSummary:
    """Ce qui manque, par groupe de découverte, ce que ça coûterait, et le reste
    du quota. **Lecture pure** : deux bases ouvertes en `mode=ro`, zéro appel eBay."""
    conn = connect_ro(_canonical_db())
    try:
        return summarize(
            conn, _quota_db(),
            anchors_kind=anchors_kind,
            encoder_version=encoder_version,
            target=target,
        )
    finally:
        conn.close()


@router.get("/scrape-plan/allocation")
def get_scrape_plan_allocation(
    country: str | None = Query(default=None, description="ISO2, ex. LU"),
    budget: int | None = Query(default=None, ge=0),
    target: int = Query(default=DEFAULT_TARGET_EXEMPLARS, ge=1, le=10),
    max_groups: int | None = Query(default=None, ge=1),
) -> dict:
    """Le plan de l'allocateur, **en dry-run**, servi tel qu'il l'écrit lui-même.

    ⛔ Ce n'est pas un lancement, et ça ne peut pas le devenir : `execute()` de
    l'allocateur n'est jamais appelé ici. Le plan porte sa propre commande —
    l'exécuter reste un geste de terminal, explicite, qui consomme de l'argent.
    """
    import json
    from datetime import date

    from scripts.allocate_ebay_scrape import (
        DEFAULT_COOLDOWN_DAYS,
        DEFAULT_REGRESSION_WEIGHT,
        DEFAULT_SPREAD_MIN,
        build_allocation,
        render_json,
    )

    quota = read_quota(_quota_db())
    effective_budget = budget if budget is not None else quota.safe_budget
    conn = connect_ro(_canonical_db())
    try:
        alloc = build_allocation(
            conn,
            target=target,
            spread_min=DEFAULT_SPREAD_MIN,
            regression_weight=DEFAULT_REGRESSION_WEIGHT,
            min_need=2,
            budget=effective_budget,
            today=date.today().isoformat(),
            cooldown_days=DEFAULT_COOLDOWN_DAYS,
            max_groups=max_groups,
            countries=frozenset({country.upper()}) if country else None,
        )
    finally:
        conn.close()
    payload = json.loads(render_json(alloc, groups_per_run=8))
    payload["country"] = country.upper() if country else None
    payload["quota"] = quota.model_dump()
    payload["budget_source"] = "explicite" if budget is not None else "quota du jour"
    payload["reserves"] = RESERVES
    return payload
