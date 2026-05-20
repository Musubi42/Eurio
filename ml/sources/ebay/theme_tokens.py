"""Tokenisation multilingue des titres de pièces Numista.

Spec : ``docs/sources-refacto/ebay-multi-marketplace/language-probe.md``
§"Étape 2bis", figée par le kickoff I2 ``i18n-theme-matcher-kickoff.md``.

Le matcher (``ml.sources.ebay.queries.title_matches_theme``) consomme ce
module pour produire, par eurio_id × langue active du marketplace, un
ensemble de tokens discriminants à comparer au titre seller eBay.

Toutes les comparaisons se font sur les versions **normalisées**
(lowercase + NFKD drop accents). Les sets ci-dessous sont donc déjà
écrits en clair, sans accents — ainsi ``"Année"`` côté input devient
``"annee"`` après ``normalize`` et matche ``"annee"`` dans le set.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata


# ── STOP_WORDS_BY_LANG ────────────────────────────────────────────────────
# Mots fonctionnels qui apparaissent partout dans les titres Numista
# localisés et n'aident pas à discriminer un thème de commémo. Jet initial
# repris de language-probe.md §"Étape 2bis" (verrouillé 2026-05-20).
#
# À tuner empiriquement via ``scripts/probe_i18n_tokens.py`` (chunk C de I2)
# si la médiane de tokens utiles sort de l'intervalle [2, 6].
STOP_WORDS_BY_LANG: dict[str, set[str]] = {
    "en": {
        "of", "the", "in", "and", "a", "an", "to", "for", "with", "on", "by",
        "anniversary", "years", "year", "since", "birth", "death", "founding",
        "th", "st", "nd", "rd",
        "euro", "euros",
    },
    "fr": {
        "de", "la", "le", "les", "du", "des", "et", "au", "aux", "a",
        "pour", "en", "sur", "par",
        "anniversaire", "ans", "an", "annee", "annees",
        "naissance", "mort", "deces",
        "euro", "euros",
        "ere", "eme",  # ordinaux (1re, 2e — après normalisation NFKD)
    },
    "de": {
        "der", "die", "das", "den", "dem", "des",
        "und", "von", "im", "in", "zu", "zur", "zum", "mit", "fur",
        "jahre", "jahr", "jahrestag", "geburtstag", "jahrhundert",
        "euro",
    },
    "it": {
        "di", "del", "della", "dei", "degli", "delle", "dello",
        "il", "lo", "la", "i", "gli", "le", "un", "una", "e", "ed",
        "in", "a", "al", "alla", "ai", "agli", "per", "con", "su",
        "anniversario", "anni", "anno",
        "nascita", "morte",
        "euro",
    },
    "es": {
        "de", "del", "la", "el", "los", "las", "y", "en", "para", "con", "por",
        "aniversario", "anos", "ano",  # "años" → "anos" après NFKD
        "nacimiento", "muerte",
        "euro", "euros",
    },
    "nl": {
        "van", "de", "het", "een", "en", "in", "op", "voor", "te", "met",
        "jaar", "jaren", "jubileum", "geboorte", "overlijden",
        "euro",
    },
}


# ── COUNTRY_TOKENS_BY_LANG ────────────────────────────────────────────────
# Tokens "pays" — équivalent multilingue de ``COUNTRY_SLUG_TOKENS`` de
# ``queries.py``. Les titres Numista localisés mentionnent souvent le pays
# émetteur ("2 Euro Deutschland — Kniefall…", "2 euros Andorre — Hymne…").
# Ces tokens décrivent OÙ et pas QUOI, donc on les sort pour ne pas matcher
# deux commémos du même pays par accident.
#
# Périmètre : 21 pays eurozone + Andorre, Monaco, Saint-Marin, Vatican.
# Forme : nom canonique + adjectif (sans accents post-NFKD).
COUNTRY_TOKENS_BY_LANG: dict[str, set[str]] = {
    "en": {
        "andorra", "andorran",
        "austria", "austrian",
        "belgium", "belgian",
        "bulgaria", "bulgarian",
        "croatia", "croatian",
        "cyprus", "cypriot",
        "estonia", "estonian",
        "finland", "finnish",
        "france", "french",
        "germany", "german",
        "greece", "greek",
        "ireland", "irish",
        "italy", "italian",
        "latvia", "latvian",
        "lithuania", "lithuanian",
        "luxembourg", "luxembourgish",
        "malta", "maltese",
        "monaco", "monegasque",
        "netherlands", "dutch",
        "portugal", "portuguese",
        "san", "marino", "sammarinese",
        "slovakia", "slovak",
        "slovenia", "slovenian",
        "spain", "spanish",
        "vatican",
    },
    "fr": {
        "andorre", "andorran", "andorrane",
        "autriche", "autrichien", "autrichienne",
        "belgique", "belge",
        "bulgarie", "bulgare",
        "croatie", "croate",
        "chypre", "chypriote",
        "estonie", "estonien", "estonienne",
        "finlande", "finlandais", "finlandaise",
        "france", "francais", "francaise",
        "allemagne", "allemand", "allemande",
        "grece", "grec", "grecque",
        "irlande", "irlandais", "irlandaise",
        "italie", "italien", "italienne",
        "lettonie", "letton", "lettone",
        "lituanie", "lituanien", "lituanienne",
        "luxembourg", "luxembourgeois", "luxembourgeoise",
        "malte", "maltais", "maltaise",
        "monaco", "monegasque",
        "pays", "bas", "neerlandais", "neerlandaise",
        "portugal", "portugais", "portugaise",
        "saint", "marin", "marinais",
        "slovaquie", "slovaque",
        "slovenie", "slovene",
        "espagne", "espagnol", "espagnole",
        "vatican",
    },
    "de": {
        "andorra", "andorranisch",
        "osterreich", "osterreichisch",
        "belgien", "belgisch",
        "bulgarien", "bulgarisch",
        "kroatien", "kroatisch",
        "zypern", "zypriotisch",
        "estland", "estnisch",
        "finnland", "finnisch",
        "frankreich", "franzosisch",
        "deutschland", "deutsch", "deutsche",
        "griechenland", "griechisch",
        "irland", "irisch",
        "italien", "italienisch",
        "lettland", "lettisch",
        "litauen", "litauisch",
        "luxemburg", "luxemburgisch",
        "malta", "maltesisch",
        "monaco", "monegassisch",
        "niederlande", "niederlandisch",
        "portugal", "portugiesisch",
        "san", "marino", "sanmarinesisch",
        "slowakei", "slowakisch",
        "slowenien", "slowenisch",
        "spanien", "spanisch",
        "vatikan", "vatikanisch",
    },
    "it": {
        "andorra", "andorrano",
        "austria", "austriaco",
        "belgio", "belga",
        "bulgaria", "bulgaro",
        "croazia", "croato",
        "cipro", "cipriota",
        "estonia", "estone",
        "finlandia", "finlandese",
        "francia", "francese",
        "germania", "tedesco", "tedesca",
        "grecia", "greco", "greca",
        "irlanda", "irlandese",
        "italia", "italiano", "italiana",
        "lettonia", "lettone",
        "lituania", "lituano",
        "lussemburgo", "lussemburghese",
        "malta", "maltese",
        "monaco", "monegasco",
        "paesi", "bassi", "olandese", "olandesi",
        "portogallo", "portoghese",
        "san", "marino", "sammarinese",
        "slovacchia", "slovacco",
        "slovenia", "sloveno",
        "spagna", "spagnolo", "spagnola",
        "vaticano",
    },
    "es": {
        "andorra", "andorrano", "andorrana",
        "austria", "austriaco", "austriaca",
        "belgica", "belga",
        "bulgaria", "bulgaro", "bulgara",
        "croacia", "croata",
        "chipre", "chipriota",
        "estonia", "estonio", "estonia",
        "finlandia", "finlandes", "finlandesa",
        "francia", "frances", "francesa",
        "alemania", "aleman", "alemana",
        "grecia", "griego", "griega",
        "irlanda", "irlandes", "irlandesa",
        "italia", "italiano", "italiana",
        "letonia", "leton", "letona",
        "lituania", "lituano", "lituana",
        "luxemburgo", "luxemburgues",
        "malta", "maltes", "maltesa",
        "monaco", "monegasco", "monegasca",
        "paises", "bajos", "holandes", "holandesa",
        "portugal", "portugues", "portuguesa",
        "san", "marino", "sanmarinense",
        "eslovaquia", "eslovaco",
        "eslovenia", "esloveno",
        "espana", "espanol", "espanola",  # "España" → "espana" après NFKD
        "vaticano",
    },
    "nl": {
        "andorra", "andorrees",
        "oostenrijk", "oostenrijks",
        "belgie", "belgisch",
        "bulgarije", "bulgaars",
        "kroatie", "kroatisch",
        "cyprus", "cypriotisch",
        "estland", "estisch",
        "finland", "fins",
        "frankrijk", "frans",
        "duitsland", "duits", "duitse",
        "griekenland", "grieks",
        "ierland", "iers",
        "italie", "italiaans",
        "letland", "lets",
        "litouwen", "litouws",
        "luxemburg", "luxemburgs",
        "malta", "maltees",
        "monaco", "monegaskisch",
        "nederland", "nederlandse", "nederlands",
        "portugal", "portugees",
        "san", "marino", "sammarinees",
        "slowakije", "slowaaks",
        "slovenie", "sloveens",
        "spanje", "spaans",
        "vaticaan", "vaticaans",
    },
}


# Tokens à drop systématiquement quel que soit la langue (digits, ordinaux).
_DIGITS_OR_ORDINAL = re.compile(
    r"^\d+(th|st|nd|rd|e|er|me|eme|ere|o|a|ª|º)?$",
    re.IGNORECASE,
)


def normalize(s: str) -> str:
    """Lowercase + NFKD drop combining marks (accents).

    Pure function — utilisée à la fois pour normaliser les titres
    Numista d'entrée et les titres seller eBay côté matcher.
    """
    decomposed = unicodedata.normalize("NFKD", s.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def extract_tokens(
    title: str,
    lang: str,
    *,
    max_words: int = 6,
    min_len: int = 4,
) -> list[str]:
    """Tokens discriminants d'un titre Numista localisé.

    Pipeline :

    1. ``normalize(title)`` — lowercase + drop accents
    2. split sur ``\\W+``
    3. drop si dans ``STOP_WORDS_BY_LANG[lang]`` ou
       ``COUNTRY_TOKENS_BY_LANG[lang]``
    4. drop si ``len < min_len``
    5. drop si pure-digits ou ordinal (``100th``, ``2e``, ``100º``)
    6. cap à ``max_words``

    Args:
        title: titre Numista localisé (ex: ``"2 Euros Bearded vulture"``)
        lang: ISO 639-1 (``fr``, ``en``, ``de``, ``it``, ``es``, ``nl``)
        max_words: nombre max de tokens retournés
        min_len: longueur min (en chars) — évite ``"war"`` qui matcherait
            ``"warm"``

    Returns:
        Liste de tokens normalisés, ordre d'apparition préservé.
    """
    if not title:
        return []
    stop = STOP_WORDS_BY_LANG.get(lang, set())
    countries = COUNTRY_TOKENS_BY_LANG.get(lang, set())
    norm = normalize(title)
    raw_tokens = re.split(r"\W+", norm)
    kept: list[str] = []
    for tok in raw_tokens:
        if not tok:
            continue
        if tok in stop or tok in countries:
            continue
        if len(tok) < min_len:
            continue
        if _DIGITS_OR_ORDINAL.match(tok):
            continue
        kept.append(tok)
        if len(kept) >= max_words:
            break
    return kept


def load_i18n_title(
    conn: sqlite3.Connection,
    eurio_id: str,
    lang: str,
) -> str | None:
    """Renvoie le titre Numista localisé ou ``None`` si absent.

    Lookup PK (``eurio_id``, ``lang``) sur ``coin_names_i18n`` — query
    triviale, pas de cache pour V1 (volumes négligeables, à mesurer si
    le matcher devient hot).
    """
    row = conn.execute(
        "SELECT title FROM coin_names_i18n WHERE eurio_id=? AND lang=?",
        (eurio_id, lang),
    ).fetchone()
    if row is None:
        return None
    # Support à la fois Row (sqlite3.Row) et tuple
    try:
        return row["title"]
    except (TypeError, IndexError):
        return row[0]
