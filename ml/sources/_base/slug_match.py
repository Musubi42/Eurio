"""Matcher de slugs partagé — assignation one-to-one par (country, year).

Extrait de ``sources.bce.adapter`` (chunk 2 du rebuild LMDLP) pour être
réutilisé par toute source qui référence une pièce par un libellé textuel
(BCE par page HTML, LMDLP par nom de produit, …) sans identifiant fort.

Principe : une source liste N blocs ``(country, year, theme_slug)`` ; on les
apparie aux eurio_id candidats de ``eurio.db`` (commémo 2 €) par fuzzy slug,
**de façon injective par (country, year)** — un eurio_id ne peut être réclamé
que par un seul bloc, ce qui évite le sur-matching où la 2ᵉ pièce d'une année
vole l'eurio_id de la 1ʳᵉ uniquement parce qu'elle score un poil plus haut.

La partie *générique* vit ici ; les **overrides manuels** (translation
source↔Numista qui diverge trop pour matcher en fuzzy) restent propres à
chaque source et sont injectés via ``SlugGroupMatcher.overrides``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher


@dataclass(frozen=True)
class RefCoin:
    """Candidat référentiel : un eurio_id et son triplet d'identité."""

    eurio_id: str
    country: str
    year: int
    theme_slug: str


# Overrides : ``(country, year, source_slug) -> eurio_id``. Court-circuite le
# fuzzy quand le vocabulaire de la source diverge trop du slug Numista.
Overrides = dict[tuple[str, int, str], str]


def slug_score(a: str, b: str) -> float:
    """Score symétrique en couverture de tokens + ratio caractère.

    Les titres source sont souvent verbeux
    ("550th-anniversary-of-the-death-of-donatello") alors que les slugs
    référentiels sont compacts ("donatello"). On prend la couverture max sur
    les deux directions pour ne pas pénaliser la dissymétrie inhérente.
    """
    if not a or not b:
        return 0.0
    src_tokens = {t for t in a.split("-") if t}
    cand_tokens = {t for t in b.split("-") if t}
    inter = src_tokens & cand_tokens
    cov_a = (len(inter) / len(src_tokens)) if src_tokens else 0.0
    cov_b = (len(inter) / len(cand_tokens)) if cand_tokens else 0.0
    coverage = max(cov_a, cov_b)
    ratio = SequenceMatcher(None, a, b).ratio()
    return max(coverage, ratio * 0.7)


def max_assignment(scoremaps: list[dict[str, float]]) -> list[str | None]:
    """Appariement injectif maximisant le score total (force brute, petits groupes).

    ``scoremaps[i]`` = ``{eurio_id: score}`` des candidats acceptables (≥ plancher)
    pour le bloc ``i``. Retourne l'eurio_id retenu (ou None) par bloc, sans qu'un
    eurio_id soit utilisé deux fois. À égalité de total, le premier exploré gagne
    (déterministe).
    """
    n = len(scoremaps)
    best_total = -1.0
    best_assign: list[str | None] = [None] * n

    def rec(i: int, used: set[str], total: float, cur: list[str | None]) -> None:
        nonlocal best_total, best_assign
        if i == n:
            if total > best_total:
                best_total = total
                best_assign = cur.copy()
            return
        # Laisser le bloc i non assigné.
        cur.append(None)
        rec(i + 1, used, total, cur)
        cur.pop()
        # Ou l'assigner à chaque candidat libre.
        for eid, sc in scoremaps[i].items():
            if eid in used:
                continue
            used.add(eid)
            cur.append(eid)
            rec(i + 1, used, total + sc, cur)
            cur.pop()
            used.discard(eid)

    rec(0, set(), 0.0, [])
    return best_assign


@dataclass
class SlugGroupMatcher:
    """Apparie des blocs ``(country, year, theme_slug)`` à des eurio_id.

    Paramétré par les ``overrides`` de la source et les seuils fuzzy
    (``score_floor`` / ``gap_ratio``, alignés avec l'ancien ``eval.matching``).
    """

    overrides: Overrides = field(default_factory=dict)
    score_floor: float = 0.25
    gap_ratio: float = 1.4

    def assign_one(
        self,
        country: str,
        year: int,
        theme_slug: str,
        candidates: list[RefCoin],
        claimed: set[str],
    ) -> str | None:
        """Matche un bloc à un eurio_id parmi les candidats **non réclamés**.

        ``claimed`` = eurio_id déjà attribués à un autre bloc de la même
        (country, year) → exclus pour garantir le 1-pièce ↔ 1-eurio_id. Avec un
        ``claimed`` vide, comportement = override → floor → gap.
        """
        # Override manuel — court-circuit le fuzzy. On vérifie que l'eurio_id
        # existe encore parmi les candidats ET n'est pas déjà réclamé, pour
        # éviter une FK error / un double-match.
        override = self.overrides.get((country, year, theme_slug))
        if (
            override is not None
            and override not in claimed
            and any(c.eurio_id == override for c in candidates)
        ):
            claimed.add(override)
            return override

        avail = [c for c in candidates if c.eurio_id not in claimed]
        if not avail:
            return None
        scored = sorted(
            ((slug_score(theme_slug, c.theme_slug), c) for c in avail),
            key=lambda x: x[0],
            reverse=True,
        )
        best_score, best = scored[0]
        runner_score = scored[1][0] if len(scored) > 1 else 0.0
        has_gap = runner_score == 0 or best_score >= runner_score * self.gap_ratio
        if best_score >= self.score_floor and has_gap:
            claimed.add(best.eurio_id)
            return best.eurio_id
        return None

    def match_entry(
        self,
        ref_index: dict[tuple[str, int], list[RefCoin]],
        country: str,
        year: int,
        theme_slug: str,
    ) -> str | None:
        """Match d'un bloc isolé (sans contrainte d'unicité). Conservé pour les
        appels unitaires ; ``match_group`` est le chemin batch one-to-one."""
        return self.assign_one(
            country, year, theme_slug, ref_index.get((country, year), []), set()
        )

    def match_group(
        self,
        ref_index: dict[tuple[str, int], list[RefCoin]],
        items: list[tuple[str, int, str]],
    ) -> list[str | None]:
        """Assignation **1-to-1** par (country, year) sur N blocs.

        ``items`` = liste de ``(country, year, theme_slug)``. Retourne l'eurio_id
        (ou None) par item, **dans le même ordre**. Aucun eurio_id n'est attribué
        à deux blocs de la même (country, year).

        - Groupe à **1 bloc** → ``assign_one`` (override → floor → gap), comportement
          historique inchangé (cas ultra-majoritaire).
        - Groupe à **≥2 blocs** → overrides forcés d'abord, puis assignation
          **optimale** (maximise le score total) sur les candidats restants, par
          force brute (groupes minuscules). Un appariement sous le plancher est
          rejeté (→ None). Évite le sur-matching où la 2ᵉ pièce vole l'eurio_id
          de la 1ʳᵉ uniquement parce qu'elle score un poil plus haut dessus.
        """
        results: list[str | None] = [None] * len(items)
        groups: dict[tuple[str, int], list[int]] = {}
        for i, (country, year, _slug) in enumerate(items):
            groups.setdefault((country, year), []).append(i)

        for (country, year), idxs in groups.items():
            candidates = list(ref_index.get((country, year), []))
            if len(idxs) == 1:
                i = idxs[0]
                results[i] = self.assign_one(
                    country, year, items[i][2], candidates, set()
                )
                continue

            claimed: set[str] = set()
            free_idxs: list[int] = []
            # 1) overrides forcés (claiment leur eurio_id en priorité).
            for i in idxs:
                slug = items[i][2]
                override = self.overrides.get((country, year, slug))
                if (
                    override is not None
                    and override not in claimed
                    and any(c.eurio_id == override for c in candidates)
                ):
                    claimed.add(override)
                    results[i] = override
                else:
                    free_idxs.append(i)

            # 2) assignation optimale des blocs restants sur candidats libres.
            avail = [c.eurio_id for c in candidates if c.eurio_id not in claimed]
            slug_of = {c.eurio_id: c.theme_slug for c in candidates}
            scoremaps: list[dict[str, float]] = []
            for i in free_idxs:
                slug = items[i][2]
                sm = {eid: slug_score(slug, slug_of[eid]) for eid in avail}
                scoremaps.append(
                    {eid: sc for eid, sc in sm.items() if sc >= self.score_floor}
                )
            for local, eid in enumerate(max_assignment(scoremaps)):
                results[free_idxs[local]] = eid
        return results
