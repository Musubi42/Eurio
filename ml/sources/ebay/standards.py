"""Découverte / attribution des pièces STANDARD (is_commemorative=0) sur eBay.

Contraste avec les commémoratives (``sources/ebay/queries.py``) : un standard
n'a PAS de thème par année. Sa face nationale est identique sur toute une
*ère de design* (carte 1ʳᵉ/2ᵉ, portrait, type), et une ère = une ligne
canonique ``coins`` dont ``year`` est l'année de *début*. Conséquences :

* **Groupe de découverte = ``(dénomination, pays)``** — PAS l'année : une
  seule recherche large « 2 euro {pays} » couvre toutes les ères du pays
  (cf. vue ``v_ebay_standard_groups``).
* **Attribution par appartenance de plage** : l'année du listing tombe dans
  ``[début_ère, début_ère_suivante − 1]`` → cette ère. Il n'y a pas de thème
  positif à matcher (sauf le nom de portrait, capté incidemment par le
  theme-matcher commémo, mais ce n'est pas le pivot ici).
* **Collision avec les commémos** : une recherche large ramène aussi les
  commémos du pays. On les EXCLUT par theme-match négatif — si le titre
  *hit* une commémo de ``(pays, année)``, c'est cette commémo (déjà captée
  par le run commémo) → ``commemo`` (discard).
* **Garde-fou de contradiction** : pays + dénomination uniquement. L'axe
  *année* est neutre pour un standard (il couvre toute sa durée de vie) — on
  le retire explicitement du verdict (``compare_to_group`` le calcule pour
  les commémos, où l'année EST un axe dur).

Doctrine « chemin neuf, tout en review d'abord » : ``target_eurio_id`` n'est
qu'un *prior* (year-résolu) qui pré-remplit la review queue ; ``candidates``
porte toujours les ères du pays pour que l'humain tranche / corrige. Le
routage review vs auto reste celui du pipeline générique (resolve → enqueue) ;
ce module ne décide rien d'irréversible.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from sources.ebay.queries import theme_match_state
from sources.text_signals import (
    GroupIdentity,
    compare_to_group,
    extract_listing_text_signals,
)

# Borne haute « ouverte » pour la plage de l'ère la plus récente d'un pays.
_ERA_OPEN_END = 9999

# Préfixe stable du motif de rejet « commémo détectée dans un run standard ».
# Importé par l'adapter pour parser l'eurio_id sans coupler sur une chaîne nue.
COMMEMO_IN_STANDARD_PREFIX = "commemo_in_standard_run:"

# Auto-déclaration commémo dans le titre seller (DE/ES/FR/IT/EN/NL, accents
# retirés, « ü→u »). Un standard dit « Kursmünze » ; une commémo dit
# « Gedenkmünze / conmemorativo / commémorative ». Signal négatif fort,
# complémentaire de l'exclusion par theme-match : attrape les lots commémo
# « alle Nationen / todos los paises » qui ne nomment aucun thème pays.
_COMMEMO_KW_RE = re.compile(
    r"\b("
    r"gedenkmunzen?|sondermunzen?|sonderpragung|"   # DE
    r"conmemorativ\w*|"                               # ES
    r"commemorati\w*|"                               # FR / IT / EN (accents ôtés)
    r"herdenkingsmunt\w*"                            # NL
    r")\b"
)
# Auto-déclaration standard — lève l'exclusion commémo si co-présente (évite
# le faux rejet d'un « Kursmünze … KEINE Gedenkmünze » → double négation).
_STANDARD_KW_RE = re.compile(
    r"\b("
    r"kursmunzen?|umlaufmunzen?|"                     # DE
    r"circulacion|circulation|circolazione|courante"  # ES / FR / EN / IT
    r")\b"
)


def _strip_accents(s: str) -> str:
    """NFD → drop combining marks ; « münze » → « munze », « commémorative »
    → « commemorative ». Aligne la casse des mots-clés multilingues."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c)
    ).lower()


@dataclass(frozen=True)
class StandardEra:
    """Une ère de design standard d'un pays = une ligne canonique ``coins``.

    ``year_from`` = année de début (colonne ``coins.year``). ``year_to`` =
    année de début de l'ère *strictement* suivante − 1, ou ``_ERA_OPEN_END``
    pour la plus récente. La plage ``[year_from, year_to]`` est l'intervalle
    de millésimes couverts par l'ère.
    """

    eurio_id: str
    year_from: int
    year_to: int


@dataclass(frozen=True)
class StandardMatch:
    """Attribution d'un listing eBay aux ères standard d'un pays.

    - ``verdict`` :
        - ``"single"``    : millésime résolu à une ère unique, pas une commémo
          → ``target_eurio_id`` posé (prior porté en review).
        - ``"ambiguous"`` : millésime absent / multi-année / collision même-
          année (ex. MT 2026) → ``target_eurio_id`` None, review avec toutes
          les ères du pays en candidates.
        - ``"commemo"``   : le titre *hit* une commémo de ``(pays, année)`` →
          discard (déjà captée par le run commémo).
        - ``"no_match"``  : contradiction franche pays / dénomination →
          discard (``contradictions`` porte l'axe fautif).
        - ``"no_eras"``   : pays sans ère standard catalogue (défensif) →
          discard.
    - ``candidates`` : ères du pays (ordre catalogue) — portées en review.
    - ``reason`` : motif (debug / ``discarded_listings``).
    """

    verdict: str
    target_eurio_id: str | None
    candidates: tuple[str, ...]
    reason: str


def load_standard_eras(
    conn: sqlite3.Connection,
    denomination: float,
    country: str,
) -> list[StandardEra]:
    """Ères de design standard d'un ``(dénomination, pays)``, plages calculées.

    Canoniques seules (``canonical_eurio_id IS NULL``) — les variantes
    pattern / mule / coloured ne sont pas la pièce de circulation, on ne les
    scrape pas. Ordonnées par année de début ; ``year_to`` de chaque ère =
    (année de l'ère *strictement* suivante − 1), ouverte pour la dernière.
    Le calcul sur l'année strictement suivante (et non l'élément suivant)
    rend les collisions même-année (ex. MT 2026 ×2) toutes deux ouvertes
    plutôt que de créer une plage vide.
    """
    rows = conn.execute(
        """
        SELECT eurio_id, year
          FROM coins
         WHERE face_value = ? AND country = ? AND is_commemorative = 0
           AND canonical_eurio_id IS NULL
         ORDER BY year, eurio_id
        """,
        (denomination, country),
    ).fetchall()
    distinct_years = sorted({int(r["year"]) for r in rows})
    eras: list[StandardEra] = []
    for r in rows:
        year_from = int(r["year"])
        later = [y for y in distinct_years if y > year_from]
        year_to = (later[0] - 1) if later else _ERA_OPEN_END
        eras.append(
            StandardEra(eurio_id=r["eurio_id"], year_from=year_from, year_to=year_to)
        )
    return eras


def eras_for_year(eras: list[StandardEra], year: int) -> list[StandardEra]:
    """Ères dont la plage contient ``year`` (ère = plus grand début ≤ year).

    Renvoie ``[]`` si ``year`` précède la 1ʳᵉ ère (millésime hors-référentiel).
    Renvoie >1 seulement sur une collision même-année (deux ères débutant la
    même année — ex. MT 2026 Valletta / Il-Kelb-tal-Fenek).
    """
    eligible = [e for e in eras if e.year_from <= year]
    if not eligible:
        return []
    top = max(e.year_from for e in eligible)
    return [e for e in eras if e.year_from == top]


def _commemo_theme_hit(
    conn: sqlite3.Connection,
    denomination: float,
    country: str,
    year: int,
    title: str,
) -> str | None:
    """eurio_id de la 1ʳᵉ commémo de ``(pays, année)`` dont le thème *hit* le
    titre, ou None. Sert à exclure du run standard les listings qui sont en
    fait des commémos (déjà captées par le run commémo)."""
    rows = conn.execute(
        """
        SELECT eurio_id
          FROM coins
         WHERE face_value = ? AND country = ? AND year = ?
           AND is_commemorative = 1 AND canonical_eurio_id IS NULL
         ORDER BY eurio_id
        """,
        (denomination, country, year),
    ).fetchall()
    for r in rows:
        if theme_match_state(title, r["eurio_id"], conn=conn) == "hit":
            return r["eurio_id"]
    return None


def attribute_standard_listing(
    title: str,
    denomination: float,
    country: str,
    *,
    conn: sqlite3.Connection,
) -> StandardMatch:
    """Route un listing eBay (recherche large par pays) vers une ère standard.

    Funnel (cf. en-tête du module) :
    1. garde-fou contradiction pays + dénom (axe année retiré) → ``no_match`` ;
    2. garde négatif mot-clé commémo (« Gedenkmünze / conmemorativo / … » sans
       mot-clé standard co-présent) → ``commemo`` ;
    3. millésime unique requis pour pinner l'ère ; sinon → ``ambiguous`` ;
    4. exclusion commémo (theme-match positif sur ``(pays, année)``) → ``commemo`` ;
    5. appartenance de plage → ``single`` (1 ère) / ``ambiguous`` (collision
       même-année ou millésime hors-référentiel).
    """
    eras = load_standard_eras(conn, denomination, country)
    candidates = tuple(e.eurio_id for e in eras)
    if not eras:
        return StandardMatch("no_eras", None, (), "no_standard_eras")

    signals = extract_listing_text_signals(title)

    # Garde-fou de contradiction — pays + dénomination seulement. L'axe
    # ANNÉE est neutre pour un standard (couvre toute sa durée de vie) : on le
    # retire du verdict. La GroupIdentity reçoit une année sentinelle (0) qui
    # ne sert qu'à l'axe filtré — l'axe pays/dénom ne la lit pas.
    contradictions = tuple(
        a
        for a in compare_to_group(
            signals, GroupIdentity(country.lower(), 0, denomination)
        )
        if a != "year"
    )
    if contradictions:
        return StandardMatch(
            "no_match", None, candidates, f"group_contradict_{contradictions[0]}"
        )

    # Garde négatif par mot-clé : un titre qui s'auto-déclare commémo
    # (Gedenkmünze / conmemorativo / commémorative) et ne s'auto-déclare PAS
    # standard (Kursmünze / circulation) est une commémo — discard. Attrape
    # les lots « alle Nationen / todos los paises » que l'exclusion par
    # theme-match (étape 4) rate faute de thème pays nommé.
    norm = _strip_accents(title or "")
    if _COMMEMO_KW_RE.search(norm) and not _STANDARD_KW_RE.search(norm):
        return StandardMatch("commemo", None, candidates, "commemo_keyword")

    # Sans millésime unique on ne peut pas pinner l'ère → review (candidats =
    # ères du pays). Couvre yearless (« Jahr nach Wahl ») et lots multi-années.
    if len(signals.years) != 1:
        reason = "year_absent" if not signals.years else "year_multi"
        return StandardMatch("ambiguous", None, candidates, reason)
    year = next(iter(signals.years))

    commemo = _commemo_theme_hit(conn, denomination, country, year, title)
    if commemo is not None:
        return StandardMatch(
            "commemo", None, candidates, f"commemo_in_standard_run:{commemo}"
        )

    hits = eras_for_year(eras, year)
    if not hits:
        return StandardMatch(
            "ambiguous", None, candidates, f"year_before_first_era:{year}"
        )
    if len(hits) > 1:
        return StandardMatch(
            "ambiguous", None, candidates, f"era_year_collision:{year}"
        )
    return StandardMatch("single", hits[0].eurio_id, candidates, f"year_resolved:{year}")
