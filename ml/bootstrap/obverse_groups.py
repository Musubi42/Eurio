"""Dérivation des design_groups STANDARD par AVERS (monarque + Nème type).

Voir ``docs/design-groups-standards/KICKOFF.md``. Contrairement à
``bootstrap_design_groups.py`` (axe ``numista_id``, écrit dans Supabase), ce
module est **SQLite-first** (``eurio.db``) et groupe les standards par **avers** :
``be-1999`` et ``be-2007`` partagent l'effigie « Albert II (1er type) » — seul le
*revers* (carte commune) change, ce que Numista traite comme deux Types distincts.
On les réunit en **un seul design_group** → une seule classe ArcFace, et la classe
cesse de starve sur eBay (cf. KICKOFF §1).

Dérivation **déterministe** depuis ``design_description`` (fallback ``eurio_id``).
**Aucune vision LLM pour dériver** : la vision sert seulement à *valider* a
posteriori (cf. ``ml/foundation/obverse_group_review.py``).

Décisions (KICKOFF §3) :
- frontière = changement de monarque OU de « Nème type ». On IGNORE la carte
  (revers), le « Nème portrait » (micro-variante) et l'année.
- on crée un groupe **même pour un monarque mono-membre** (ex. Philippe) : le
  groupe porte designation / i18n / avers partagé et fournit un id de classe
  stable découplé du millésime. (Diffère de l'axe A legacy qui exige ≥2 membres.)
- les pièces non parsables → **flag ``unparsable``**, jamais un groupe deviné
  (doctrine « aucun fallback silencieux »).

Ce module n'écrit rien par lui-même hors de ``bootstrap(..., apply=True)`` ; le
parsing / la dérivation sont des fonctions pures (testées sans DB).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

# Slug de dénomination — copie locale (le legacy l'expose mais importe Supabase
# au top-level ; on garde ce module découplé). Source de vérité identique.
FACE_VALUE_SLUG: dict[float, str] = {
    0.01: "1cent",
    0.02: "2cent",
    0.05: "5cent",
    0.10: "10cent",
    0.20: "20cent",
    0.50: "50cent",
    1.00: "1euro",
    2.00: "2euro",
}


def face_value_slug(face_value: float) -> str:
    key = round(float(face_value), 2)
    return FACE_VALUE_SLUG.get(key, f"fv{int(round(key * 100))}c")


def face_value_display(face_value: float) -> str:
    key = round(float(face_value), 2)
    if key >= 1.0:
        return f"{int(key) if key == int(key) else key:g}€"
    return f"{int(round(key * 100))}c"


def _slugify(text: str) -> str:
    """kebab-case ASCII : « Albert II » → ``albert-ii``."""
    out = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())
    return out.strip("-")


def _ordinal_fr(n: int) -> str:
    return "1er" if n == 1 else f"{n}e"


def _ordinal_en(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# « 2nd type », « 1st type »… (dans la parenthèse de design_description).
_TYPE_RE = re.compile(r"(\d+)\s*(?:st|nd|rd|th)\s+type", re.IGNORECASE)
# Préfixe dénomination de design_description : « 2 Euros - … », « 50 Cents - … ».
_DENOM_PREFIX_RE = re.compile(r"^\s*[\d.,]+\s*(?:euros?|cents?)\s*[-–—]\s*", re.IGNORECASE)
# Tokens « -1st-map- », « -2nd-type- »… dans un eurio_id (pour le fallback).
_EURIO_ORDINAL_TOKEN_RE = re.compile(r"-\d+(?:st|nd|rd|th)-")


@dataclass(frozen=True)
class ObverseKey:
    """Identité d'avers déterministe : monarque + ordinal de type."""

    monarch: str
    type_ordinal: int


@dataclass(frozen=True)
class StandardCoin:
    """Ligne ``coins`` strictement nécessaire à la dérivation (testable sans DB)."""

    eurio_id: str
    country: str
    face_value: float
    year: int
    design_description: str | None
    design_group_id: str | None = None


@dataclass(frozen=True)
class ObverseGroup:
    """Un groupe avers dérivé, prêt à insérer."""

    group_id: str
    designation: str
    designation_i18n: dict[str, str]
    country: str
    face_value: float
    key: ObverseKey
    members: tuple[str, ...]
    year_min: int
    year_max: int

    @property
    def is_singleton(self) -> bool:
        return len(self.members) == 1


@dataclass
class DeriveResult:
    groups: list[ObverseGroup] = field(default_factory=list)
    unparsable: list[str] = field(default_factory=list)  # eurio_ids

    @property
    def singletons(self) -> list[ObverseGroup]:
        return [g for g in self.groups if g.is_singleton]


def parse_obverse_key(
    design_description: str | None, eurio_id: str | None = None
) -> ObverseKey | None:
    """Extrait ``(monarque, ordinal de type)`` de façon déterministe.

    Primaire : ``design_description`` (« 2 Euros - Albert II (1st map, 2nd type,
    1st portrait) » → ``ObverseKey('Albert II', 2)`` ; « 2 Euros - Philippe » →
    ``ObverseKey('Philippe', 1)``). Le « Nème type » absent vaut 1.
    Fallback léger : ``eurio_id`` (« …-standard-philippe » → ``Philippe`` t1).
    Renvoie ``None`` si rien d'exploitable (→ flag ``unparsable``).
    """
    monarch: str | None = None
    type_ordinal = 1

    if design_description:
        body = _DENOM_PREFIX_RE.sub("", design_description.strip())
        # Monarque = texte avant la 1ʳᵉ parenthèse (la parenthèse ne porte que
        # carte / type / portrait, qu'on ignore sauf le type).
        head = body.split("(", 1)[0].strip()
        if head:
            monarch = head
        m = _TYPE_RE.search(body)
        if m:
            type_ordinal = int(m.group(1))

    if monarch is None and eurio_id:
        # Fallback : « {country}-{year}-{denom}-standard-{reste} » → reste avant
        # le 1er token ordinal (« -1st-map- », « -2nd-type- »…).
        marker = "-standard-"
        idx = eurio_id.find(marker)
        if idx != -1:
            rest = eurio_id[idx + len(marker) :]
            cut = _EURIO_ORDINAL_TOKEN_RE.search(rest)
            slug_monarch = rest[: cut.start()] if cut else rest
            slug_monarch = slug_monarch.strip("-")
            if slug_monarch:
                monarch = slug_monarch.replace("-", " ").title()
            m = _TYPE_RE.search(rest.replace("-", " "))
            if m:
                type_ordinal = int(m.group(1))

    if not monarch:
        return None
    return ObverseKey(monarch=monarch, type_ordinal=type_ordinal)


def _build_group(
    country: str, face_value: float, key: ObverseKey, coins: list[StandardCoin]
) -> ObverseGroup:
    cc = country.upper()
    disp = face_value_display(face_value)
    monarch_slug = _slugify(key.monarch)
    group_id = f"{country.lower()}-{face_value_slug(face_value)}-{monarch_slug}-t{key.type_ordinal}"
    designation = f"{cc} {disp} {key.monarch} ({_ordinal_fr(key.type_ordinal)} type)"
    i18n = {
        "fr": designation,
        "en": f"{cc} {disp} {key.monarch} ({_ordinal_en(key.type_ordinal)} type)",
    }
    members = tuple(c.eurio_id for c in sorted(coins, key=lambda c: (c.year, c.eurio_id)))
    years = [c.year for c in coins]
    return ObverseGroup(
        group_id=group_id,
        designation=designation,
        designation_i18n=i18n,
        country=cc,
        face_value=face_value,
        key=key,
        members=members,
        year_min=min(years),
        year_max=max(years),
    )


def derive_groups(coins: Iterable[StandardCoin]) -> DeriveResult:
    """Groupe les standards par ``(country, face_value, monarque, Nème type)``.

    Un groupe est créé pour chaque clé avers, **même mono-membre** (cf. en-tête).
    Les pièces dont l'avers n'est pas parsable sont listées dans ``unparsable``.
    Les groupes sont ordonnés par ``(country, face_value, year_min, group_id)``.
    """
    result = DeriveResult()
    buckets: dict[tuple[str, float, ObverseKey], list[StandardCoin]] = defaultdict(list)
    for coin in coins:
        key = parse_obverse_key(coin.design_description, coin.eurio_id)
        if key is None:
            result.unparsable.append(coin.eurio_id)
            continue
        buckets[(coin.country.upper(), round(float(coin.face_value), 2), key)].append(coin)

    for (country, fv, key), members in buckets.items():
        result.groups.append(_build_group(country, fv, key, members))

    result.groups.sort(key=lambda g: (g.country, g.face_value, g.year_min, g.group_id))
    result.unparsable.sort()
    return result


# ---------- DB I/O (lecture pour audit ; écriture via bootstrap) ----------


def load_standard_coins(
    conn: sqlite3.Connection, country: str, face_value: float | None = None
) -> list[StandardCoin]:
    """Charge les standards canoniques d'un pays (optionnellement d'une dénom)."""
    sql = (
        "SELECT eurio_id, country, face_value, year, design_description, design_group_id "
        "FROM coins WHERE country = ? AND is_commemorative = 0 "
        "AND canonical_eurio_id IS NULL"
    )
    params: list[object] = [country.upper()]
    if face_value is not None:
        sql += " AND face_value = ?"
        params.append(face_value)
    sql += " ORDER BY face_value, year, eurio_id"
    rows = conn.execute(sql, params).fetchall()
    return [
        StandardCoin(
            eurio_id=r["eurio_id"],
            country=r["country"],
            face_value=float(r["face_value"]),
            year=int(r["year"]),
            design_description=r["design_description"],
            design_group_id=r["design_group_id"],
        )
        for r in rows
    ]


# ---------- Bootstrap (plan read-only + apply transactionnel) ----------


@dataclass
class BootstrapPlan:
    """Plan d'attribution avers, calculé en lecture seule (aucune écriture)."""

    groups: list[ObverseGroup]
    to_attach: dict[str, list[str]] = field(default_factory=dict)  # group_id → eurio_ids NULL
    already_ok: dict[str, list[str]] = field(default_factory=dict)  # déjà == cible
    conflicts: list[tuple[str, str, str]] = field(default_factory=list)  # (eurio_id, courant, cible)
    unparsable: list[str] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    @property
    def n_to_attach(self) -> int:
        return sum(len(v) for v in self.to_attach.values())


def plan_bootstrap(
    conn: sqlite3.Connection, country: str, face_value: float | None = None
) -> BootstrapPlan:
    """Calcule le plan d'attribution avers sans rien écrire.

    Pour chaque pièce d'un groupe dérivé :
    - ``design_group_id IS NULL``        → ``to_attach`` (sera posé),
    - ``design_group_id == cible``       → ``already_ok`` (idempotent, sauté),
    - ``design_group_id`` autre & non-NULL → **conflit** (invariant §5.1 : ne
      jamais écraser un groupe numista_id / joint-issue existant).
    """
    coins = load_standard_coins(conn, country, face_value)
    derived = derive_groups(coins)
    by_eid = {c.eurio_id: c for c in coins}

    plan = BootstrapPlan(groups=derived.groups, unparsable=derived.unparsable)
    for g in derived.groups:
        for eid in g.members:
            current = by_eid[eid].design_group_id
            if current is None:
                plan.to_attach.setdefault(g.group_id, []).append(eid)
            elif current == g.group_id:
                plan.already_ok.setdefault(g.group_id, []).append(eid)
            else:
                plan.conflicts.append((eid, current, g.group_id))
    return plan


def apply_plan(conn: sqlite3.Connection, plan: BootstrapPlan) -> dict[str, int]:
    """Écrit le plan en base, dans une transaction unique (idempotent, additif).

    ``INSERT … ON CONFLICT(id) DO NOTHING`` sur ``design_groups`` ; ``UPDATE
    coins SET design_group_id`` borné par ``WHERE … AND design_group_id IS
    NULL`` (double garde anti-écrasement, en plus du contrôle de ``plan``).
    Lève ``RuntimeError`` si le plan porte des conflits (aucune écriture).
    """
    if plan.has_conflicts:
        details = "; ".join(f"{e} déjà dans {cur} (cible {tgt})" for e, cur, tgt in plan.conflicts)
        raise RuntimeError(
            f"Bootstrap avorté — {len(plan.conflicts)} conflit(s) d'écrasement : {details}"
        )

    summary = {"groups_inserted": 0, "coins_attached": 0, "already_ok": 0, "unparsable": len(plan.unparsable)}
    summary["already_ok"] = sum(len(v) for v in plan.already_ok.values())

    conn.execute("BEGIN IMMEDIATE")
    try:
        for g in plan.groups:
            cur = conn.execute(
                """
                INSERT INTO design_groups (id, designation, designation_i18n_json)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (g.group_id, g.designation, json.dumps(g.designation_i18n, ensure_ascii=False)),
            )
            summary["groups_inserted"] += cur.rowcount if cur.rowcount > 0 else 0
            for eid in plan.to_attach.get(g.group_id, []):
                cur = conn.execute(
                    "UPDATE coins SET design_group_id = ? "
                    "WHERE eurio_id = ? AND design_group_id IS NULL",
                    (g.group_id, eid),
                )
                summary["coins_attached"] += cur.rowcount
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return summary


# ---------- CLI ----------


def _main() -> int:
    import argparse
    import sys
    from pathlib import Path

    ml_dir = Path(__file__).resolve().parents[1]
    if str(ml_dir) not in sys.path:
        sys.path.insert(0, str(ml_dir))
    from state.store import Store  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Bootstrap design_groups STANDARD par avers (eurio.db).")
    parser.add_argument("--country", required=True, help="ISO2 (ex. BE)")
    parser.add_argument("--face-value", type=float, default=None, help="optionnel, ex. 2.0")
    parser.add_argument("--db", default=str(ml_dir / "state" / "eurio.db"))
    parser.add_argument("--apply", action="store_true", help="écrit en base (défaut = dry-run)")
    args = parser.parse_args()

    store = Store(Path(args.db))
    plan = plan_bootstrap(store._connection(), args.country, args.face_value)

    print(f"Pays {args.country.upper()} — {len(plan.groups)} groupe(s) avers dérivé(s).")
    for g in plan.groups:
        attach = plan.to_attach.get(g.group_id, [])
        ok = plan.already_ok.get(g.group_id, [])
        print(f"  {g.group_id:34} {g.designation}")
        for eid in g.members:
            mark = "→ attach" if eid in attach else ("✓ déjà" if eid in ok else "?")
            print(f"      {mark:9} {eid}")
    if plan.unparsable:
        print(f"\n⚠ Non parsables (ignorés) : {plan.unparsable}")
    if plan.has_conflicts:
        print(f"\n✗ CONFLITS d'écrasement ({len(plan.conflicts)}) — bootstrap refusé :")
        for eid, cur, tgt in plan.conflicts:
            print(f"      ✗ {eid} déjà dans '{cur}' (cible '{tgt}')")
        return 1

    if not args.apply:
        print(f"\n[DRY-RUN] {plan.n_to_attach} pièce(s) seraient attachées. Relancer avec --apply.")
        return 0

    summary = apply_plan(store._connection(), plan)
    print(
        f"\n✓ APPLIQUÉ — groupes insérés: {summary['groups_inserted']}, "
        f"pièces attachées: {summary['coins_attached']}, "
        f"déjà OK: {summary['already_ok']}, non parsables: {summary['unparsable']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
