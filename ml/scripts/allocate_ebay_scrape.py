"""Allocateur de scrape eBay par déficit d'exemplaires (banque DINO).

À quota donné, décide **quels groupes de découverte eBay scraper et dans quel
ordre**, pour amener le maximum de classes de la banque `2eur_all` vers la cible
de 8 exemplaires (plafond 10 — au-delà, un crop validé n'entre plus dans la
banque).

> Ce script **n'écrit rien** : la connexion SQLite est ouverte en ``mode=ro``
> (URI). Il **n'appelle pas eBay** : le défaut est ``--dry-run``, et le mode réel
> (``--execute --yes``) se contente d'invoquer ``go-task ml:src:ebay:run``.

Conception, mesures et refus assumés :
``docs/work-in-progress/scan-sans-retrain/ALLOCATEUR-SCRAPE.md``.

La maille d'allocation est le **groupe de découverte**, jamais la classe : une
recherche eBay ramène toujours un groupe entier (commémo → ``(2€, pays, année)``,
standard → ``(2€, pays, None)``, cf. ``EbayAdapter._resolve_group``). 671 classes
se replient sur 416 groupes.

Usage ::

    go-task ml:ebay:allocate
    go-task ml:ebay:allocate -- --budget 20000
    go-task ml:ebay:allocate -- --format json --out /tmp/plan.json
    go-task ml:ebay:allocate -- --execute --yes
"""

from __future__ import annotations

import argparse
import json
import logging
import shlex
import sqlite3
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

ML_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_DIR.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import resolve_db_path  # noqa: E402
from training.foundation.anchors import (  # noqa: E402
    DATASETS_DIR,
    DEFAULT_EXEMPLARS_PER_CLASS,
    _class_specs_2eur_all,
)

logger = logging.getLogger("allocate_ebay_scrape")

# ── Constantes de planification ──────────────────────────────────────────────
# Cible d'exemplaires par classe. 8 et non 10 : la courbe références/classe
# (COURBE-REFERENCES) plafonne autour de N=8 (73,9 %) et ne gagne que 1,6 pt
# jusqu'à N=10 — pour 25 % de quota en plus.
DEFAULT_TARGET_EXEMPLARS = 8
# Plafond dur de la banque : au-delà, `build_anchors_2eur_all` ignore les crops.
HARD_CAP = DEFAULT_EXEMPLARS_PER_CLASS  # 10

# Coût quota d'UN groupe, en appels. 2 recherches (EBAY_DE + EBAY_ES) + 1
# `item/{id}` par annonce retenue. Mesuré sur `api_call_log` × `discovery_searches` :
#   2026-06-13 : 10 groupes commémo → 1163 appels (116/groupe)
#   2026-06-14 :  2 groupes commémo →  281 appels (~138/groupe)
#   2026-06-15 :  3 groupes standard → 717 appels (239/groupe)
# Le standard coûte ~2× : il ratisse `limit=200` au lieu de 75
# (SEARCH_LIMIT_STANDARD_MULT, sources/ebay/queries.py).
COST_PER_COMMEMO_GROUP = 130
COST_PER_STANDARD_GROUP = 240

# Quota eBay journalier — source unique : le registre de sources.
EBAY_DAILY_QUOTA = 5000
# Marge de sécurité du préflight quota du CLI (`sources/cli.py`) : on ne planifie
# jamais plus que remaining / 1,3.
QUOTA_SAFETY_FACTOR = 1.3

# Marge DINO en-dessous de laquelle un candidat de la file n'est pas un candidat
# (`country_spread` avec repli sur `spread`, cf. skill eurio-review).
DEFAULT_SPREAD_MIN = 0.05

# Une classe à 1 exemplaire est MESURÉE pire qu'une classe nue (held-out
# N=0 : 53,1 % · N=1 : 50,1 %). Elle doit sortir de là en priorité.
DEFAULT_REGRESSION_WEIGHT = 2.0

# Cadence de re-visite d'un groupe : `expected_cadence_days` du registre eBay.
DEFAULT_COOLDOWN_DAYS = 30

ANCHORS_KIND = "2eur_all"


def default_db() -> Path:
    """Réplique du canonique — jamais `state/eurio.db`, qui est périmée."""
    return resolve_db_path(ML_DIR / "state" / "eurio.replica.db")


# ── Modèle ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DiscoveryGroupKey:
    """Unité d'allocation : ce qu'une recherche eBay ramène en un appel."""

    country: str
    year: int | None  # None = groupe STANDARD (toutes les ères du pays)

    @property
    def is_standard(self) -> bool:
        return self.year is None

    @property
    def cost(self) -> int:
        return COST_PER_STANDARD_GROUP if self.is_standard else COST_PER_COMMEMO_GROUP

    def label(self) -> str:
        return f"{self.country}/{self.year if self.year is not None else 'std'}"


@dataclass
class ClassState:
    class_id: str
    country: str
    year: int | None
    is_commemorative: bool
    have: int = 0       # exemplaires 'fps' déjà dans la banque
    pending: int = 0    # candidats en file ouverte au-dessus de la marge
    need: int = 0       # besoin résiduel vers la cible
    weight: float = 0.0  # need pondéré (régression N=1)


@dataclass
class GroupPlan:
    key: DiscoveryGroupKey
    rep_eurio_id: str
    classes: list[ClassState]
    served: float
    need: int
    n_classes_needing: int
    n_zero: int
    n_regression: int
    pending: int
    last_searched: str | None
    cost: int

    @property
    def score(self) -> float:
        return self.served / self.cost if self.cost else 0.0


@dataclass
class Allocation:
    planned: list[GroupPlan]
    skipped_cooldown: list[GroupPlan] = field(default_factory=list)
    skipped_empty_upstream: list[GroupPlan] = field(default_factory=list)
    deferred_budget: list[GroupPlan] = field(default_factory=list)
    review_covered: list[ClassState] = field(default_factory=list)
    budget: int = 0

    @property
    def cost(self) -> int:
        return sum(g.cost for g in self.planned)


# ── Lecture (read-only) ──────────────────────────────────────────────────────


def connect_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _exemplar_counts(conn: sqlite3.Connection, anchors_kind: str) -> dict[str, int]:
    return {
        r["class_id"]: r["n"]
        for r in conn.execute(
            "SELECT class_id, COUNT(*) AS n FROM dino_class_references "
            "WHERE anchors_kind = ? AND method = 'fps' GROUP BY class_id",
            (anchors_kind,),
        )
    }


def _pending_counts(
    conn: sqlite3.Connection, anchors_kind: str, spread_min: float
) -> dict[str, int]:
    """Candidats exploitables : file OUVERTE, top1 sur la classe, marge suffisante.

    `coalesce(country_spread, spread)` : c'est ce que fait le verdict du projet.
    Filtrer la seule colonne `country_spread` exclurait en silence des crops que
    la review, elle, évalue.
    """
    return {
        r["class_id"]: r["n"]
        for r in conn.execute(
            """
            SELECT p.top1_eurio_id AS class_id, COUNT(*) AS n
              FROM review_queue rq
              JOIN image_asset_dino_predictions p ON p.asset_id = rq.image_asset_id
             WHERE rq.status IN ('open','in_progress')
               AND p.anchors_kind = ?
               AND COALESCE(p.country_spread, p.spread) >= ?
             GROUP BY p.top1_eurio_id
            """,
            (anchors_kind, spread_min),
        )
    }


def _coin_meta(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {
        r["eurio_id"]: r
        for r in conn.execute(
            "SELECT eurio_id, country, year, is_commemorative FROM coins"
        )
    }


def _search_history(conn: sqlite3.Connection) -> dict[str, str]:
    """`query_q` → date de la dernière recherche. Ce que la base sait du passé.

    Mesuré le 2026-08-20 : 367 des 416 groupes n'ont JAMAIS été interrogés, et
    **aucune** recherche n'est jamais revenue vide. La distinction « jamais
    cherché » / « introuvable » n'existe pas encore en base — c'est l'allocateur
    qui la produira, tour après tour.
    """
    last: dict[str, str] = {}
    for r in conn.execute("SELECT query_q, created_at FROM discovery_searches"):
        q = r["query_q"]
        if q is None:
            continue
        prev = last.get(q)
        if prev is None or r["created_at"] > prev:
            last[q] = r["created_at"]
    return last


def _empty_upstream_members(conn: sqlite3.Connection) -> set[str]:
    """eurio_ids que le pipeline a déjà classés « rien en amont » côté eBay."""
    try:
        rows = conn.execute(
            "SELECT eurio_id FROM coin_source_status "
            "WHERE source LIKE 'ebay%' AND state = 'empty_upstream'"
        ).fetchall()
    except sqlite3.OperationalError as exc:  # table absente d'un fixture minimal
        logger.warning("coin_source_status illisible (%s) — aucun groupe écarté", exc)
        return set()
    return {r["eurio_id"] for r in rows}


def _group_queries(key: DiscoveryGroupKey) -> list[str]:
    """Les requêtes eBay exactes d'un groupe, une par marketplace interrogé."""
    from sources.ebay.marketplaces import DISCOVERY_MARKETPLACES
    from sources.ebay.queries import build_group_query

    return [
        build_group_query(2.0, key.country, key.year, query_lang=call.query_lang).q
        for call in DISCOVERY_MARKETPLACES
    ]


# ── Le cœur : besoin, score, remplissage ─────────────────────────────────────


def build_class_states(
    conn: sqlite3.Connection,
    *,
    anchors_kind: str = ANCHORS_KIND,
    target: int = DEFAULT_TARGET_EXEMPLARS,
    spread_min: float = DEFAULT_SPREAD_MIN,
    regression_weight: float = DEFAULT_REGRESSION_WEIGHT,
    datasets_dir: Path = DATASETS_DIR,
) -> list[ClassState]:
    """Une ligne par classe de la banque, au grain EXACT de la banque.

    Le grain vient de `_class_specs_2eur_all` et de nulle part ailleurs : la
    banque indexe une commémo sous son propre eurio_id (même si elle a un
    design_group) et un standard sous le représentant de son groupe. Un
    `COALESCE(design_group_id, eurio_id)` naïf rend 592 classes là où la banque
    en a 671 — on compterait le déficit de classes qui n'existent pas.
    """
    if target > HARD_CAP:
        raise SystemExit(
            f"--target {target} dépasse le plafond de la banque ({HARD_CAP}) : "
            "les exemplaires au-delà ne seraient jamais retenus."
        )
    specs = _class_specs_2eur_all(conn, datasets_dir)
    meta = _coin_meta(conn)
    have = _exemplar_counts(conn, anchors_kind)
    pending = _pending_counts(conn, anchors_kind, spread_min)

    states: list[ClassState] = []
    for spec in specs:
        cid = spec["class_id"]
        m = meta.get(cid)
        if m is None:
            # La banque référence une classe sans pièce : anomalie de données,
            # pas un cas silencieux. On la journalise et on l'écarte.
            logger.warning("classe %s absente de `coins` — écartée du plan", cid)
            continue
        h = have.get(cid, 0)
        p = pending.get(cid, 0)
        need = max(0, target - h - p)
        st = ClassState(
            class_id=cid,
            country=m["country"],
            year=m["year"],
            is_commemorative=bool(m["is_commemorative"]),
            have=h,
            pending=p,
            need=need,
            weight=need * (regression_weight if h == 1 else 1.0),
        )
        states.append(st)
    return states


def group_key_for(state: ClassState) -> DiscoveryGroupKey:
    """Le groupe de découverte qui ramènerait des crops pour cette classe."""
    return DiscoveryGroupKey(
        country=state.country,
        year=state.year if state.is_commemorative else None,
    )


def build_group_plans(
    states: Iterable[ClassState],
    *,
    history: dict[str, str],
    min_need: int = 2,
) -> list[GroupPlan]:
    """Replie les classes sur leurs groupes et calcule ce que chaque groupe sert.

    `min_need` matérialise la règle « ne jamais viser 1 » : une classe dont le
    besoin résiduel est inférieur à ce seuil ne **pilote** pas la décision (son
    poids ne compte pas dans `served`), mais elle reste passagère du groupe si
    celui-ci est financé pour d'autres.
    """
    by_group: dict[DiscoveryGroupKey, list[ClassState]] = defaultdict(list)
    for st in states:
        by_group[group_key_for(st)].append(st)

    plans: list[GroupPlan] = []
    for key, members in by_group.items():
        drivers = [c for c in members if c.need >= min_need]
        served = sum(c.weight for c in drivers)
        last = None
        for q in _group_queries(key):
            d = history.get(q)
            if d is not None and (last is None or d > last):
                last = d
        # Représentant : ordre stable, et on préfère une classe qui a du besoin.
        rep = sorted(drivers or members, key=lambda c: c.class_id)[0].class_id
        plans.append(
            GroupPlan(
                key=key,
                rep_eurio_id=rep,
                classes=sorted(members, key=lambda c: c.class_id),
                served=served,
                need=sum(c.need for c in drivers),
                n_classes_needing=len(drivers),
                n_zero=sum(1 for c in drivers if c.have == 0),
                n_regression=sum(1 for c in drivers if c.have == 1),
                pending=sum(c.pending for c in members),
                last_searched=last,
                cost=key.cost,
            )
        )
    plans.sort(key=lambda g: (-g.score, -g.served, g.key.label()))
    return plans


def _days_since(iso: str, today: str) -> float:
    """Écart en jours entre deux dates ISO (`YYYY-MM-DD…`), sur les dates seules."""
    from datetime import date

    def _d(s: str) -> date:
        return date.fromisoformat(s[:10])

    return (_d(today) - _d(iso)).days


def allocate(
    plans: Sequence[GroupPlan],
    *,
    budget: int,
    today: str,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    max_groups: int | None = None,
    empty_upstream: frozenset[str] = frozenset(),
) -> Allocation:
    """Remplissage glouton par score décroissant, sous contrainte de budget."""
    alloc = Allocation(planned=[], budget=budget)
    spent = 0
    for plan in plans:
        if plan.served <= 0:
            continue
        if all(c.class_id in empty_upstream for c in plan.classes):
            alloc.skipped_empty_upstream.append(plan)
            continue
        if plan.last_searched is not None and _days_since(plan.last_searched, today) < cooldown_days:
            alloc.skipped_cooldown.append(plan)
            continue
        if max_groups is not None and len(alloc.planned) >= max_groups:
            alloc.deferred_budget.append(plan)
            continue
        if spent + plan.cost > budget:
            alloc.deferred_budget.append(plan)
            continue
        alloc.planned.append(plan)
        spent += plan.cost
    return alloc


# ── Budget ───────────────────────────────────────────────────────────────────


def remaining_quota_today() -> int:
    """Appels eBay encore disponibles aujourd'hui, d'après le compteur RÉEL.

    Le seul compteur vrai est `api_call_log` dans la DB locale : `source_runs
    .n_calls` ne compte que les recherches (3 pour un run qui a brûlé 740
    appels). En cas d'illisibilité on **journalise et on rend 0** : planifier sur
    un quota supposé plein est exactement le bug B1.
    """
    try:
        from shared.api_quota import QuotaTracker

        used = QuotaTracker("ebay", "daily", EBAY_DAILY_QUOTA).total().calls
    except Exception as exc:  # pragma: no cover - dépend de l'environnement
        logger.error(
            "compteur de quota illisible (%s) — budget forcé à 0. "
            "Passe --budget explicitement si tu sais ce que tu fais.", exc,
        )
        return 0
    return max(0, EBAY_DAILY_QUOTA - used)


def safe_budget(remaining: int) -> int:
    """Budget planifiable : le restant, divisé par la marge du préflight CLI."""
    return int(remaining / QUOTA_SAFETY_FACTOR)


# ── Sorties ──────────────────────────────────────────────────────────────────


def waves(plans: Sequence[GroupPlan], groups_per_run: int) -> list[list[GroupPlan]]:
    return [
        list(plans[i : i + groups_per_run])
        for i in range(0, len(plans), groups_per_run)
    ]


def command_for(wave: Sequence[GroupPlan]) -> list[str]:
    """La commande qui exécute une vague.

    `go-task` et pas `python -m sources.cli` : la tâche pose
    `EURIO_CENSUS_RECOVER=1` (OFF par défaut), sans quoi une grosse part des raws
    bimétal repart en `zero_crops`, en silence.
    Un seul représentant par groupe : deux ids d'un même groupe lanceraient deux
    fois la même recherche pour la même moisson.
    """
    ids = ",".join(g.rep_eurio_id for g in wave)
    return ["go-task", "ml:src:ebay:run", "--", "--target-eurio-ids", ids, "--push"]


def render_text(alloc: Allocation, *, groups_per_run: int) -> str:
    out: list[str] = []
    a = out.append
    a("=" * 96)
    a("PLAN D'ALLOCATION eBay — par déficit d'exemplaires (banque 2eur_all)")
    a("=" * 96)
    a(f"budget planifiable  {alloc.budget} appels")
    a(f"groupes retenus     {len(alloc.planned)}")
    a(f"coût prévu          {alloc.cost} appels")
    a(f"exemplaires visés   {sum(g.need for g in alloc.planned)} "
      f"sur {sum(g.need for g in alloc.planned) + sum(g.need for g in alloc.deferred_budget)} "
      "de déficit finançable")
    a("")
    a(f"{'#':>3}  {'groupe':10} {'kind':9} {'cls':>3} {'need':>4} {'zéro':>4} "
      f"{'N=1':>3} {'file':>4} {'coût':>5} {'score':>6}  représentant")
    a("-" * 96)
    for i, g in enumerate(alloc.planned, 1):
        a(f"{i:3}  {g.key.label():10} "
          f"{'standard' if g.key.is_standard else 'commémo':9} "
          f"{g.n_classes_needing:3} {g.need:4} {g.n_zero:4} {g.n_regression:3} "
          f"{g.pending:4} {g.cost:5} {g.score:6.3f}  {g.rep_eurio_id}")
    a("")
    a("Écartés :")
    a(f"  cooldown (< {DEFAULT_COOLDOWN_DAYS} j)      {len(alloc.skipped_cooldown)} groupe(s)")
    a(f"  empty_upstream connu       {len(alloc.skipped_empty_upstream)} groupe(s)")
    a(f"  hors budget (reportés)     {len(alloc.deferred_budget)} groupe(s), "
      f"{sum(g.cost for g in alloc.deferred_budget)} appels")
    a(f"  déficit couvert par la review, pas par le quota : "
      f"{len(alloc.review_covered)} classe(s)")
    a("")
    a("Commandes (mode réel — chacune consomme du quota) :")
    for w in waves(alloc.planned, groups_per_run):
        a("  " + " ".join(shlex.quote(p) for p in command_for(w)))
    return "\n".join(out)


def render_json(alloc: Allocation, *, groups_per_run: int) -> str:
    payload = {
        "budget": alloc.budget,
        "cost": alloc.cost,
        "n_groups": len(alloc.planned),
        "groups": [
            {
                "country": g.key.country,
                "year": g.key.year,
                "kind": "standard" if g.key.is_standard else "commemorative",
                "rep_eurio_id": g.rep_eurio_id,
                "cost": g.cost,
                "score": round(g.score, 4),
                "need": g.need,
                "n_classes_needing": g.n_classes_needing,
                "n_zero": g.n_zero,
                "n_regression": g.n_regression,
                "pending": g.pending,
                "last_searched": g.last_searched,
                "classes": [c.class_id for c in g.classes if c.need > 0],
            }
            for g in alloc.planned
        ],
        "skipped": {
            "cooldown": [g.key.label() for g in alloc.skipped_cooldown],
            "empty_upstream": [g.key.label() for g in alloc.skipped_empty_upstream],
            "over_budget": [g.key.label() for g in alloc.deferred_budget],
        },
        "review_covered_classes": [c.class_id for c in alloc.review_covered],
        "commands": [command_for(w) for w in waves(alloc.planned, groups_per_run)],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ── Exécution (geste explicite) ──────────────────────────────────────────────


Runner = Callable[[list[str]], int]


def _subprocess_runner(cmd: list[str]) -> int:
    logger.info("→ %s", " ".join(shlex.quote(p) for p in cmd))
    return subprocess.run(cmd, cwd=REPO_ROOT, check=False).returncode


def execute(
    alloc: Allocation,
    *,
    groups_per_run: int,
    runner: Runner = _subprocess_runner,
    quota_reader: Callable[[], int] | None = None,
) -> int:
    """Lance les vagues. Appelé UNIQUEMENT sous `--execute --yes`.

    Le quota RÉEL est relu avant CHAQUE vague (défaut S4). Le budget du plan
    est une estimation adossée à 15 groupes observés (130 / 240 appels) : un
    plan à 4920 appels peut en coûter 6000. Le préflight de `sources.cli` ne
    rattrape pas ce dérapage — il estime sur `source_runs.n_calls`, le
    compteur mesuré faux (3 pour 740 appels réels), et rend `estimate=8` pour
    une vague budgétée 1040. Le seul compteur vrai est `api_call_log`, et il
    n'était lu qu'une fois, avant la première vague.
    """
    lire_restant = quota_reader or remaining_quota_today
    for i, wave in enumerate(waves(alloc.planned, groups_per_run), 1):
        prevu = sum(g.cost for g in wave)
        restant = lire_restant()
        if restant < prevu * QUOTA_SAFETY_FACTOR:
            logger.error(
                "vague %d : quota restant %d < coût prévu %d × marge %.1f — "
                "arrêt AVANT l'appel. Les vagues déjà lancées comptent ; "
                "relance demain, ou passe --max-groups.",
                i, restant, prevu, QUOTA_SAFETY_FACTOR,
            )
            return 1
        cmd = command_for(wave)
        rc = runner(cmd)
        if rc != 0:
            logger.error("vague %d en échec (rc=%d) — arrêt, quota préservé", i, rc)
            return rc
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────


def build_allocation(
    conn: sqlite3.Connection,
    *,
    target: int,
    spread_min: float,
    regression_weight: float,
    min_need: int,
    budget: int,
    today: str,
    cooldown_days: int,
    max_groups: int | None,
    anchors_kind: str = ANCHORS_KIND,
    datasets_dir: Path = DATASETS_DIR,
    countries: frozenset[str] | None = None,
) -> Allocation:
    """`countries` cadre le plan à un ou plusieurs pays (ISO2), sans rien changer
    d'autre : mêmes coûts, même score, même budget.

    Le filtre s'applique aux **classes**, avant le repli sur les groupes — et
    non aux groupes après coup : un groupe appartient à un pays et un seul
    (`DiscoveryGroupKey.country`), donc les deux rendraient le même ensemble,
    mais filtrer en amont garde `review_covered` cohérent avec le cadrage.
    Un pays inconnu rend un plan **vide**, jamais le plan complet : un
    périmètre qui rate ne s'élargit pas en silence.
    """
    states = build_class_states(
        conn,
        anchors_kind=anchors_kind,
        target=target,
        spread_min=spread_min,
        regression_weight=regression_weight,
        datasets_dir=datasets_dir,
    )
    if countries is not None:
        states = [s for s in states if s.country in countries]
    plans = build_group_plans(
        states, history=_search_history(conn), min_need=min_need
    )
    alloc = allocate(
        plans,
        budget=budget,
        today=today,
        cooldown_days=cooldown_days,
        max_groups=max_groups,
        empty_upstream=frozenset(_empty_upstream_members(conn)),
    )
    # Ce que l'allocateur refuse de financer parce que la review suffit.
    alloc.review_covered = [
        c for c in states if c.need == 0 and c.have < target and c.pending > 0
    ]
    return alloc


def main(argv: list[str] | None = None) -> int:
    from datetime import date

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=None,
                   help=f"Base à LIRE (read-only). Défaut : {default_db()}")
    p.add_argument("--anchors-kind", default=ANCHORS_KIND)
    p.add_argument("--country", action="append", default=None, metavar="ISO2",
                   help="Cadre le plan à ce(s) pays (répétable). Un pays inconnu "
                        "rend un plan vide, jamais le plan complet.")
    p.add_argument("--target", type=int, default=DEFAULT_TARGET_EXEMPLARS,
                   help=f"Exemplaires visés par classe (défaut {DEFAULT_TARGET_EXEMPLARS}, "
                        f"plafond banque {HARD_CAP}).")
    p.add_argument("--min-need", type=int, default=2,
                   help="Besoin résiduel minimal pour qu'une classe PILOTE une "
                        "décision (défaut 2 : on ne vise jamais 1).")
    p.add_argument("--spread-min", type=float, default=DEFAULT_SPREAD_MIN)
    p.add_argument("--regression-weight", type=float, default=DEFAULT_REGRESSION_WEIGHT,
                   help="Poids des classes à 1 exemplaire (mesurées pires que 0).")
    p.add_argument("--cooldown-days", type=int, default=DEFAULT_COOLDOWN_DAYS)
    p.add_argument("--budget", type=int, default=None,
                   help="Appels planifiables. Défaut : (5000 − appels du jour) / 1,3.")
    p.add_argument("--max-groups", type=int, default=None)
    p.add_argument("--groups-per-run", type=int, default=8,
                   help="Taille d'une vague (une invocation ml:src:ebay:run).")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--today", default=None, help="Date de référence (tests).")
    # Exclusifs, et pas décoratifs (défaut S2) : `--dry-run` n'était lu nulle
    # part, si bien que `--dry-run --execute --yes` brûlait le quota en
    # affichant qu'on ne le brûlait pas. argparse sort en 2 sur la paire.
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="Défaut. N'appelle pas eBay, imprime le plan.")
    mode.add_argument("--execute", dest="execute", action="store_true",
                      help="Mode réel : lance les runs eBay. Exige --yes. "
                           "Incompatible avec --dry-run.")
    p.add_argument("--yes", action="store_true",
                   help="Confirme --execute. Sans lui, --execute refuse de partir.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s"
    )

    db_path = args.db or default_db()
    if not db_path.exists():
        raise SystemExit(f"Base introuvable : {db_path}")

    if args.budget is not None:
        budget = args.budget
    else:
        remaining = remaining_quota_today()
        budget = safe_budget(remaining)
        logger.info(
            "[quota] restant aujourd'hui %d/%d → budget planifiable %d (marge ×%.1f)",
            remaining, EBAY_DAILY_QUOTA, budget, QUOTA_SAFETY_FACTOR,
        )

    conn = connect_ro(db_path)
    try:
        alloc = build_allocation(
            conn,
            target=args.target,
            spread_min=args.spread_min,
            regression_weight=args.regression_weight,
            min_need=args.min_need,
            budget=budget,
            today=args.today or date.today().isoformat(),
            cooldown_days=args.cooldown_days,
            max_groups=args.max_groups,
            anchors_kind=args.anchors_kind,
            countries=(
                frozenset(c.upper() for c in args.country) if args.country else None
            ),
        )
    finally:
        conn.close()

    rendered = (
        render_json(alloc, groups_per_run=args.groups_per_run)
        if args.format == "json"
        else render_text(alloc, groups_per_run=args.groups_per_run)
    )
    if args.out:
        args.out.write_text(rendered + "\n", encoding="utf-8")
        logger.info("plan écrit → %s", args.out)
    else:
        print(rendered)

    if not args.execute:
        return 0
    if not args.yes:
        raise SystemExit(
            "--execute consomme du quota eBay réel (argent). "
            "Ajoute --yes pour confirmer."
        )
    if not alloc.planned:
        logger.info("aucun groupe planifié — rien à exécuter.")
        return 0
    return execute(alloc, groups_per_run=args.groups_per_run)


if __name__ == "__main__":
    sys.exit(main())
