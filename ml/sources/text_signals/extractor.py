"""Extracteur de signaux texte — module pur, no I/O.

Depuis un titre eBay (et optionnellement quelques aspects déjà parsés),
produit un :class:`ListingTextSignals` avec ce que le texte dit
explicitement : pays, années, dénominations, tokens de thème,
markers de rejet, indicateurs de lot.

Pas de comparaison vs target_eurio_id ici (chunk 6). Pas de
persistance (chunk 5). Pas d'I/O.

Usage typique (chunk 5+) ::

    sig = extract_listing_text_signals(title)
    if "fr" in sig.countries and 2014 in sig.years:
        ...
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from .dictionaries import (
    ALL_COUNTRY_ISO2,
    COUNTRY_ADJECTIVES,
    COUNTRY_FLAGS,
    COUNTRY_NAMES,
    COUNT_PIECES_RE,
    COUNT_X_RE,
    DENOMINATION_RE,
    LOT_KEYWORDS_RE,
    REJECTION_MARKERS,
    STOP_WORDS,
    VALID_FACE_VALUES,
    YEAR_MAX,
    YEAR_MIN,
    YEAR_RE,
)

Coverage = Literal["rich", "sparse", "empty"]


@dataclass(frozen=True)
class ListingTextSignals:
    """Signaux extraits d'un titre + aspects (read-only).

    - ``countries``        : ISO2 détectés. Set car un titre peut nommer
                             plusieurs pays (lots transfrontaliers).
    - ``years``            : années 1999–2039 trouvées (toutes les
                             occurrences, pas seulement la première).
    - ``denominations``    : valeurs reconnues comme dénominations
                             (filtrées sur ``VALID_FACE_VALUES``).
    - ``theme_tokens``     : tokens significatifs (≥4 char, pas
                             stop-word, pas année, pas pays). Ordre
                             d'apparition. Utilisé au chunk 6 pour
                             croiser avec le slug du target.
    - ``rejected_markers`` : catégories de hors-scope détectées
                             (proof, metal, error_struck, ...). Vide
                             quand le listing est "propre".
    - ``is_lot``           : titre suggère un lot — ≥2 pays détectés,
                             keyword lot, ou compteur explicite ≥2.
    - ``coverage``         : ``rich`` (pays + année + denom),
                             ``sparse`` (1 ou 2 sur 3),
                             ``empty`` (rien d'exploitable).
    - ``matched``          : debug — pour chaque axe, les tokens
                             bruts qui ont matché. Utile au panel
                             review front (chunk 7).
    """

    countries: frozenset[str]
    years: frozenset[int]
    denominations: frozenset[float]
    theme_tokens: tuple[str, ...]
    rejected_markers: tuple[str, ...]
    is_lot: bool
    coverage: Coverage
    matched: dict[str, tuple[str, ...]] = field(default_factory=dict)


# ── Normalisation ───────────────────────────────────────────────────────────


def _strip_accents(s: str) -> str:
    """NFD → drop combining marks. "française" → "francaise"."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if not unicodedata.combining(c)
    )


def _normalize(title: str) -> str:
    """Lower + collapse whitespace. Garde les accents (le matcher
    pays a deux passes : avec et sans accents)."""
    s = title.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── Extraction par axe ──────────────────────────────────────────────────────


def _extract_years(text: str) -> tuple[frozenset[int], list[str]]:
    matches = YEAR_RE.findall(text)
    years: set[int] = set()
    raw: list[str] = []
    for m in matches:
        try:
            y = int(m)
        except ValueError:
            continue
        if YEAR_MIN <= y <= YEAR_MAX:
            years.add(y)
            raw.append(m)
    return frozenset(years), raw


def _extract_denominations(text: str) -> tuple[frozenset[float], list[str]]:
    """Capture les nombres + 'euro|€|EUR'. Filtre sur les face values
    connues pour éviter d'absorber des prix ("12 euros", "5 €"
    seuls = pas une dénomination de pièce eurozone)."""
    denoms: set[float] = set()
    raw: list[str] = []
    for m in DENOMINATION_RE.finditer(text):
        amount_str = m.group(1).replace(",", ".")
        try:
            amount = float(amount_str)
        except ValueError:
            continue
        # Tolère "0.5" → 0.50.
        if amount == 0.5:
            amount = 0.50
        if amount in VALID_FACE_VALUES:
            denoms.add(amount)
            raw.append(m.group(0))
    return frozenset(denoms), raw


def _extract_countries(
    title_lower: str, title_lower_noaccents: str,
) -> tuple[frozenset[str], list[str]]:
    """Cherche les noms substantifs, adjectifs, flags. Mots-frontières
    sur les noms textuels ; match direct pour les flags emoji.

    Retourne le set ISO2 + la liste des tokens bruts qui ont matché.
    """
    found: set[str] = set()
    matched_raw: list[str] = []

    # Flags emoji (sans ambiguïté, no boundary needed).
    for flag, iso2 in COUNTRY_FLAGS.items():
        if flag in title_lower:
            found.add(iso2)
            matched_raw.append(flag)

    # Noms substantifs.
    for iso2, names in COUNTRY_NAMES.items():
        for n in names:
            n_norm = _strip_accents(n)
            # Matche soit dans le titre original, soit la version sans accents.
            pattern = rf"\b{re.escape(n)}\b"
            pattern_na = rf"\b{re.escape(n_norm)}\b"
            if re.search(pattern, title_lower) or re.search(pattern_na, title_lower_noaccents):
                found.add(iso2)
                matched_raw.append(n)
                break  # un alias suffit pour ce pays

    # Adjectifs.
    for iso2, adjs in COUNTRY_ADJECTIVES.items():
        for a in adjs:
            a_norm = _strip_accents(a)
            pattern = rf"\b{re.escape(a)}\b"
            pattern_na = rf"\b{re.escape(a_norm)}\b"
            if re.search(pattern, title_lower) or re.search(pattern_na, title_lower_noaccents):
                found.add(iso2)
                matched_raw.append(a)
                break

    return frozenset(found), matched_raw


def _extract_rejection_markers(text: str) -> tuple[tuple[str, ...], list[str]]:
    found: list[str] = []
    raw: list[str] = []
    for label, pat in REJECTION_MARKERS.items():
        m = pat.search(text)
        if m:
            found.append(label)
            raw.append(m.group(0).strip())
    return tuple(found), raw


def _extract_lot(
    text: str, *, n_countries: int,
) -> tuple[bool, list[str]]:
    """Détection lot : keyword lot, compteur explicite ≥2, ou ≥2 pays.

    Le seuil ≥2 pays est intentionnel : un titre comme "2 Euro Andorre &
    France" est un lot transfrontalier, pas une ambiguïté à résoudre.
    """
    raw: list[str] = []
    is_lot = False

    for m in LOT_KEYWORDS_RE.finditer(text):
        is_lot = True
        raw.append(m.group(0))

    # "N x QQchose" — multiplicateur (N≥2 → lot).
    for m in COUNT_X_RE.finditer(text):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if n >= 2:
            is_lot = True
            raw.append(m.group(0).strip())

    # "Lot de N pièces", "N coins"
    for m in COUNT_PIECES_RE.finditer(text):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if n >= 2:
            is_lot = True
            raw.append(m.group(0).strip())

    if n_countries >= 2:
        is_lot = True
        raw.append(f"{n_countries}-countries")

    return is_lot, raw


def _extract_theme_tokens(
    text: str,
    *,
    countries_found: frozenset[str],
    years_raw: set[str],
) -> tuple[str, ...]:
    """Tokens significatifs après suppression des stop-words, années,
    pays, dénominations. Ordre d'apparition préservé.

    Heuristique :
    - tokenize sur ``[a-z0-9]+`` (avec accents repliés)
    - drop si len < 4
    - drop si stop_word
    - drop si == année connue
    - drop si dans les noms de pays / adjectifs (qu'ils aient matché ou non)
    - drop si ressemble à une référence Numista (KM, km, etc.)
    """
    text_na = _strip_accents(text)
    tokens = re.findall(r"[a-z0-9]+", text_na)

    country_alias_tokens: set[str] = set()
    for names in COUNTRY_NAMES.values():
        for n in names:
            for part in re.findall(r"[a-z0-9]+", _strip_accents(n)):
                country_alias_tokens.add(part)
    for adjs in COUNTRY_ADJECTIVES.values():
        for a in adjs:
            for part in re.findall(r"[a-z0-9]+", _strip_accents(a)):
                country_alias_tokens.add(part)

    out: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        if len(tok) < 4:
            continue
        if tok in STOP_WORDS:
            continue
        if tok in years_raw:
            continue
        if tok in country_alias_tokens:
            continue
        if tok in {"euro", "euros", "cent", "cents"}:
            continue
        if re.fullmatch(r"\d+", tok):
            continue  # purement numérique (count, prix, …)
        if tok.startswith("km") and any(c.isdigit() for c in tok):
            continue  # référence Numista
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return tuple(out)


def _classify_coverage(
    *,
    countries: frozenset[str],
    years: frozenset[int],
    denominations: frozenset[float],
) -> Coverage:
    n = sum([
        bool(countries),
        bool(years),
        bool(denominations),
    ])
    if n >= 3:
        return "rich"
    if n >= 1:
        return "sparse"
    return "empty"


# ── API publique ────────────────────────────────────────────────────────────


def extract_listing_text_signals(
    title: str | None,
    *,
    aspects: dict[str, str] | None = None,
) -> ListingTextSignals:
    """Extrait les signaux textuels d'un titre + aspects optionnels.

    Les aspects (item specifics eBay) sont concaténés au titre comme un
    "second titre" virtuel — on tire sur le même pipeline d'extraction.
    En pratique les aspects Browse summaries sont quasi vides
    (cf. progress.md chunk 4 §"Aspects eBay quasi vides"), mais le
    paramètre est là pour les sources qui en peupleraient (numista
    legacy, autres marketplaces).
    """
    if not title:
        return ListingTextSignals(
            countries=frozenset(),
            years=frozenset(),
            denominations=frozenset(),
            theme_tokens=(),
            rejected_markers=(),
            is_lot=False,
            coverage="empty",
            matched={},
        )

    text = title
    if aspects:
        # Concatène pour passer le tout dans le même pipeline.
        text += " " + " ".join(f"{k}: {v}" for k, v in aspects.items() if v)

    title_lower = _normalize(text)
    title_lower_noaccents = _strip_accents(title_lower)

    years, years_raw = _extract_years(title_lower)
    denoms, denoms_raw = _extract_denominations(title_lower)
    countries, countries_raw = _extract_countries(title_lower, title_lower_noaccents)
    rej_markers, rej_raw = _extract_rejection_markers(title_lower)
    is_lot, lot_raw = _extract_lot(title_lower, n_countries=len(countries))

    # Pour theme tokens, on retire des candidats les años/years connus.
    theme_tokens = _extract_theme_tokens(
        title_lower,
        countries_found=countries,
        years_raw=set(years_raw),
    )

    coverage = _classify_coverage(
        countries=countries,
        years=years,
        denominations=denoms,
    )

    matched = {
        "countries": tuple(countries_raw),
        "years": tuple(years_raw),
        "denominations": tuple(denoms_raw),
        "rejected_markers": tuple(rej_raw),
        "lot": tuple(lot_raw),
    }

    # Vérification interne de cohérence : si tous les ISO2 trouvés ne
    # sont pas dans le set canonique, c'est un bug. On laisse passer
    # mais on logge en debug. Pas de side effect.
    assert all(c in ALL_COUNTRY_ISO2 for c in countries), (
        f"Unknown ISO2 in extracted countries: {countries - ALL_COUNTRY_ISO2}"
    )

    return ListingTextSignals(
        countries=countries,
        years=years,
        denominations=denoms,
        theme_tokens=theme_tokens,
        rejected_markers=rej_markers,
        is_lot=is_lot,
        coverage=coverage,
        matched=matched,
    )
