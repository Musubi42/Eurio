"""Dictionnaires & patterns du text-signal extractor.

Source : observations sur ~50 titres réels eBay FR + DE + EN
échantillonnés depuis ``source_images.listing_title`` (cf.
``docs/sources-refacto/auto-validation/progress.md`` chunk 4).

On reste strict sur le périmètre :
- 21 pays Eurozone (incluant Bulgarie, entrée 2026-01-01) + 4
  micro-états (AD, MC, SM, VA) qui frappent leurs propres euros.
- Variantes linguistiques observées en pratique (FR principalement,
  EN/DE/IT/ES en second). Pas de transliteration ni de fuzzy match :
  on liste explicitement ce qu'on rencontre.
- Pas de codes ISO2 nus dans les dicos (ex. "FR", "DE") — trop de
  faux positifs (sigles, abréviations). Les flags emoji sont
  acceptés en revanche, ils sont sans ambiguïté.

Conventions :
- Tous les tokens sont en minuscules dans les dicos. Le matcher
  lowercase le titre avant lookup.
- ``COUNTRY_NAMES``     : noms canoniques (substantif), priorité haute.
- ``COUNTRY_ADJECTIVES``: adjectifs (féminin singulier suffit, on
  matche en suffixe-souple via mots-frontières).
- ``COUNTRY_FLAGS``     : flag emoji → ISO2.
"""

from __future__ import annotations

import re
from typing import Iterable

# ── Pays & micro-états ───────────────────────────────────────────────────────

# Noms substantifs. Une variante par token (mots multiples = "saint marin",
# "pays bas", l'extractor les normalise en gérant les espaces multiples).
COUNTRY_NAMES: dict[str, frozenset[str]] = {
    "AD": frozenset({"andorre", "andorra"}),
    "AT": frozenset({"autriche", "austria", "österreich", "osterreich"}),
    "BE": frozenset({"belgique", "belgium", "belgien", "belgio", "bélgica", "belgica"}),
    "BG": frozenset({"bulgarie", "bulgaria", "bulgarien"}),
    "CY": frozenset({"chypre", "cyprus", "zypern", "chipre"}),
    "DE": frozenset({"allemagne", "germany", "deutschland", "germania", "alemania"}),
    "EE": frozenset({"estonie", "estonia", "estland"}),
    "ES": frozenset({"espagne", "spain", "españa", "espana", "spanien"}),
    "FI": frozenset({"finlande", "finland", "finnland", "suomi", "finlandia"}),
    "FR": frozenset({"france", "frankreich", "francia"}),
    "GR": frozenset({"grèce", "grece", "greece", "griechenland", "ellada", "grecia"}),
    "HR": frozenset({"croatie", "croatia", "kroatien", "hrvatska", "croacia"}),
    "IE": frozenset({"irlande", "ireland", "irland", "eire", "irlanda"}),
    "IT": frozenset({"italie", "italy", "italia", "italien"}),
    "LT": frozenset({"lituanie", "lithuania", "litauen", "lietuva", "lituania"}),
    "LU": frozenset({"luxembourg", "luxemburg", "lussemburgo", "luxemburgo"}),
    "LV": frozenset({"lettonie", "latvia", "lettland", "latvija", "letonia"}),
    "MC": frozenset({"monaco", "mónaco"}),
    "MT": frozenset({"malte", "malta"}),
    "NL": frozenset({"pays-bas", "pays bas", "netherlands", "niederlande", "olanda", "holland", "países bajos", "paises bajos"}),
    "PT": frozenset({"portugal"}),
    "SI": frozenset({"slovénie", "slovenie", "slovenia", "slowenien", "slovenija", "eslovenia"}),
    "SK": frozenset({"slovaquie", "slovakia", "slowakei", "slovensko", "eslovaquia"}),
    "SM": frozenset({"saint-marin", "saint marin", "san marino"}),
    "VA": frozenset({"vatican", "vaticano", "vatikan"}),
}

# Adjectifs (utilisé séparément des noms : tons légèrement plus faibles
# pour Coverage, mais comptent comme "pays détecté"). Forme féminine
# singulier — on matche en mots-frontières donc "française" capture
# aussi "francaise" si le titre est sans accents (matcher normalisé).
COUNTRY_ADJECTIVES: dict[str, frozenset[str]] = {
    "AT": frozenset({"autrichienne", "autrichien"}),
    "BE": frozenset({"belge"}),
    "DE": frozenset({"allemande", "allemand"}),
    "ES": frozenset({"espagnole", "espagnol"}),
    "FI": frozenset({"finlandaise", "finlandais"}),
    "FR": frozenset({"française", "francaise", "français", "francais"}),
    "GR": frozenset({"grecque", "grec"}),
    "IT": frozenset({"italienne", "italien"}),
    "LU": frozenset({"luxembourgeoise", "luxembourgeois"}),
    "NL": frozenset({"néerlandaise", "neerlandaise", "néerlandais", "neerlandais", "hollandaise", "hollandais"}),
    "PT": frozenset({"portugaise", "portugais"}),
}

# Flag emojis → ISO2. Sans ambiguïté.
COUNTRY_FLAGS: dict[str, str] = {
    "🇦🇩": "AD",
    "🇦🇹": "AT",
    "🇧🇪": "BE",
    "🇧🇬": "BG",
    "🇨🇾": "CY",
    "🇩🇪": "DE",
    "🇪🇪": "EE",
    "🇪🇸": "ES",
    "🇫🇮": "FI",
    "🇫🇷": "FR",
    "🇬🇷": "GR",
    "🇭🇷": "HR",
    "🇮🇪": "IE",
    "🇮🇹": "IT",
    "🇱🇹": "LT",
    "🇱🇺": "LU",
    "🇱🇻": "LV",
    "🇲🇨": "MC",
    "🇲🇹": "MT",
    "🇳🇱": "NL",
    "🇵🇹": "PT",
    "🇸🇮": "SI",
    "🇸🇰": "SK",
    "🇸🇲": "SM",
    "🇻🇦": "VA",
}

ALL_COUNTRY_ISO2: frozenset[str] = frozenset(COUNTRY_NAMES.keys())


# ── Années ───────────────────────────────────────────────────────────────────

# Eurozone : 1999 = première frappe (lancement 2002), commémo depuis 2004.
# Borne haute large pour absorber les listings prospectifs et garder la
# regex simple.
# ⚠️ La borne DROITE n'est pas `\b` mais `(?![\d])`, et c'est délibéré.
# `\b` refusait « 2016R » — millésime collé à la lettre d'atelier, forme
# courante des annonces italiennes et allemandes (mesuré le 2026-08-27 :
# 37 crops de la file ouverte portaient un millésime au titre et rendaient
# `years_json = []`). La borne GAUCHE reste `\b` : sans elle, un numéro de
# catalogue « KM2016 » deviendrait un millésime. Un chiffre à droite reste
# refusé, donc « 20161 » ne rend rien.
YEAR_RE = re.compile(r"\b(199[9]|20[0-3]\d)(?![\d])")

# Plage de millésimes — « 2004 bis 2022 », « 2004 a 2024 », « 2004-2022 ».
# Une plage n'affirme RIEN sur l'année de la pièce photographiée : le
# vendeur annonce un choix. Le comparateur en fait un axe `absent`, jamais
# un `contradict` (cf. comparator._year_axis).
YEAR_RANGE_RE = re.compile(
    r"\b(?:199[9]|20[0-3]\d)\s*(?:-|–|—|/|bis|to|a|à|au|until|hasta|fino\s+al)"
    r"\s*(?:199[9]|20[0-3]\d)(?![\d])",
    re.IGNORECASE,
)
YEAR_MIN, YEAR_MAX = 1999, 2039


# ── Dénominations ────────────────────────────────────────────────────────────

# Capture "2 €", "2 EUR", "2 euros", "2EUR", "2,50 euros", "0.50 €", etc.
# Le groupe 1 = montant (avec virgule ou point décimal).
# Note : pas de `\b` final — `€` n'est pas un word-char donc le boundary
# casse les matches "2€" / "0,50 €". On ferme proprement le mot "euro"
# avec `\b` interne, pas de boundary après le symbole monétaire.
DENOMINATION_RE = re.compile(
    r"\b(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur(?:os?)?\b)",
    re.IGNORECASE,
)

# Subset face-values reconnues comme valides (autres = dropped, ex. "10 euros"
# = un montant prix, pas une dénomination de pièce).
#
# 2.5 inclus : la Belgique frappe des **2½ euro** (format collector hors
# circulation). Ce n'est PAS une pièce de notre scope 2 € — mais il faut
# la *reconnaître* comme dénomination pour que le garde-fou de
# contradiction (`compare_to_group`) la rejette d'un groupe 2 €. La
# capturer = pouvoir la contredire ; la dropper = la laisser passer.
VALID_FACE_VALUES: frozenset[float] = frozenset({
    0.01, 0.02, 0.05, 0.10, 0.20, 0.50,
    1.0, 2.0, 2.5,
})


# ── Markers de rejet (cohérents avec NOISE_PATTERNS de filters.py) ───────────

# Liste typée par catégorie. Chaque marker capture une raison potentielle
# de hors-scope. Le filtre amont accept_listing rejette en bloc sur
# ``noise_title`` ; ici on garde la granularité par catégorie pour
# auditer.
REJECTION_MARKERS: dict[str, re.Pattern[str]] = {
    "proof": re.compile(r"\b(proof|épreuve|epreuve|belle\s*épreuve|belle\s*epreuve|bu\b)\b", re.IGNORECASE),
    "metal": re.compile(r"\b(argent|silver|or\s|gold|plaqu[eé]e?|silbermünze)\b", re.IGNORECASE),
    "colored": re.compile(r"\b(coloris[eé]e?|colored|farbig)\b", re.IGNORECASE),
    "error_struck": re.compile(r"\b(faut[eé]e?|erreur\s*de\s*frappe|mint\s*error|d[eé]sax[eé]e?|mal\s*frapp[eé]e?)\b", re.IGNORECASE),
    "replica": re.compile(r"\b(replica|copy|reproduction|fake|copie|nachbildung)\b", re.IGNORECASE),
    "fantasy": re.compile(r"\b(souvenir|fantasy|fantaisie|jeton|token)\b", re.IGNORECASE),
    # L'objet vendu EST le rangement, pas une pièce. Volontairement
    # étroit : « album », « étui », « capsule » et « blister » sont exclus
    # car ils accompagnent presque toujours une vraie pièce (mesuré le
    # 2026-08-27 : 1 213 crops de la file ouverte portent blister/coincard/
    # capsule, contre 1 seul les marqueurs ci-dessous).
    "accessory": re.compile(
        r"(sammlerbox|m[üu]nzbox|sortierbox|aufbewahrungsbox|m[üu]nzalbum|"
        r"3d[-\s]?druck|3d[-\s]?print|coin\s*holder|presentoir|pr[ée]sentoir)",
        re.IGNORECASE,
    ),
}


# ── Lot detection (mots-clefs et compteurs explicites) ───────────────────────

# Cohérent avec LOT_PATTERNS de filters.py mais retournant la liste des
# matches plutôt qu'un boolean.
LOT_KEYWORDS_RE = re.compile(
    r"\b("
    r"lot|coffret|s[eé]rie|collection\s*compl[eè]te|"
    r"rouleau|roll|set\s+of|sets?\b|"
    r"bundle|konvolut|sammlung|"
    # Sets multilingues (cf. coin-census-bench) : KMS/Kursmünzensatz/Münzset/
    # (Euro-)Satz/Komplettsatz (DE), cofre/cartera/juego (ES), divisionale (IT),
    # jaarset/muntset (NL).
    r"kms|kursm[üu]nzensatz|m[üu]nzset|satz|komplettsatz|"
    r"cofre|cartera|juego|divisionale|jaarset|muntset"
    r")\b",
    re.IGNORECASE,
)

# Compteurs numériques explicites — deux patterns complémentaires :
# 1. "2 x 2 EURO", "3x pièce" — "N x QQchose" indique multiplication.
# 2. "Lot de 3 pièces", "5 coins" — quantité explicite avec mot tête.
COUNT_X_RE = re.compile(r"\b(\d+)\s*x\s+\S", re.IGNORECASE)
COUNT_PIECES_RE = re.compile(
    r"\b(?:lot\s*de\s+)?(\d+)\s*(?:"
    r"pi[eè]ces?|coins?|m[oü]nzen?|st[uü]ck|stuks?|"        # FR/EN/DE/NL
    r"valori|valores|valeurs|werte|"                         # « valeurs »
    r"piezas|pezzi|monedas|monete|munten|"                   # « pièces » ES/IT/NL
    r"exemplaires|ejemplares|esemplari"                      # « exemplaires »
    r")\b",
    re.IGNORECASE,
)

# Plage de dénominations « 1 cent … 2 euro » = jeu complet (KMS/Satz/cofre/cartera).
# Un vendeur ne décrit jamais UNE pièce comme couvrant 1 cent à 2 euro.
DENOM_RANGE_RE = re.compile(
    r"\b1\s*c(?:ent|ents|t|ts|entime?s?|entavos?|entesimi?)?\b"
    r".{0,15}?"
    r"\b2\s*(?:€|eur)",
    re.IGNORECASE,
)


# ── Taxonomie listing : listing_kind (chunk C2 — pipeline prix) ──────────────
#
# listing_kind ∈ single | lot | coffret | graded_slab. Détermine la règle
# de prix en aval : seul `single` (pièce nue vendue seule) entre dans le
# prix de référence. Précédence de détection :
#   graded_slab > lot > coffret > single.
# Patterns appliqués sur le titre normalisé SANS accents.

# Slab gradé (PCGS/NGC/…) ou note de grade encapsulée : on paie le grade,
# pas la pièce → exclu du prix nu.
GRADED_SLAB_RE = re.compile(
    r"\b("
    r"pcgs|ngc|anacs|icg|"                    # services de gradation
    r"(?:ms|pf|pr|sp)[\s-]?\d{2}|"             # MS67, PF-69, SP 70…
    r"grad(?:ed|ing|ee?)|slab(?:bed)?|"
    r"encapsul(?:ated|ee?)"
    r")\b",
    re.IGNORECASE,
)

# Emballage d'origine d'UNE pièce (coincard, blister, folder) — premium
# d'emballage → exclu du prix nu. Distinct du lot multi-pièces.
COFFRET_RE = re.compile(
    r"\b("
    r"coincard|coin\s*card|coffret|blister|folder|infocard|munzkarte"
    r")\b",
    re.IGNORECASE,
)

# Lot multi-pièces (mots-clefs). 'coffret' est volontairement absent —
# traité par COFFRET_RE. Les compteurs explicites (COUNT_X_RE,
# COUNT_PIECES_RE) et le seuil ≥2 pays comptent aussi comme lot.
LOT_KIND_RE = re.compile(
    r"\b("
    r"lot|serie|collection\s*complete|rouleau|roll|set\s+of|sets?|"
    r"bundle|konvolut|sammlung|"
    # Sets multilingues (cf. coin-census-bench) — 'coffret' reste géré par
    # COFFRET_RE (= 1 pièce emballée). Appliqué sur le titre SANS accents.
    r"kms|kursmunzensatz|munzset|satz|komplettsatz|"
    r"cofre|cartera|juego|divisionale|jaarset|muntset"
    r")\b",
    re.IGNORECASE,
)


# ── État numismatique : condition_normalized (chunk C2) ──────────────────────
#
# Tiers Eurio : UNC (neuve / non-circulée) > TTB (bien conservée) >
# TB (circulée / usée). Patterns sur titre normalisé SANS accents,
# multilingues (fr/en/de/es/it — langues observées sur EBAY_DE + EBAY_ES).
# Le grade réel vit dans le titre : le champ `condition` d'eBay est
# inexploitable (les vendeurs mettent « Neuf » partout).

# UNC — non-circulée / fleur de coin / brilliant uncirculated.
CONDITION_UNC_RE = re.compile(
    r"\b("
    r"unc|uncirculated|fdc|fleur de coin|bu|brilliant uncirculated|"
    r"stempelglanz|stgl|bankfrisch|pragefrisch|mint state|"
    r"fior di conio|fds|sin circular|neuf|neuve|neuwertig"
    r")\b",
    re.IGNORECASE,
)
# TTB — bien conservée (≈ VF/XF, superbe).
CONDITION_TTB_RE = re.compile(
    r"\b("
    r"ttb|superbe|sup|sehr schon|ss|vorzuglich|vz|"
    r"extremely fine|very fine|xf|ef|vf|"
    r"ebc|muy bien conservada|mbc|bellissimo|bb"
    r")\b",
    re.IGNORECASE,
)
# TB — circulée / usée (bas de gamme).
CONDITION_TB_RE = re.compile(
    r"\b("
    r"tb|tres beau|gebraucht|worn|used|abgegriffen|"
    r"bien conservada|circulata|molto bello"
    r")\b",
    re.IGNORECASE,
)
# Famille 'circulé/circulada/circulated' → TB, MAIS exclue quand préfixée
# 'un' (uncirculated) ou 'non ' (non circulée).
CONDITION_CIRCULATED_RE = re.compile(r"(?<!un)(?<!non )circul", re.IGNORECASE)


# ── Stop-words pour les theme tokens ─────────────────────────────────────────

# Multilingue volontairement minimal — on garde tout token ≥ 4 chars
# qui n'est pas dans la liste, après avoir retiré les années et
# dénominations. Le but est de produire des tokens qui pourront servir
# de signal positif/négatif quand on les croisera avec le slug du
# target_eurio_id (chunk 6).
STOP_WORDS: frozenset[str] = frozenset({
    # FR
    "avec", "sans", "pour", "dans", "vers", "chez", "entre",
    "tous", "toute", "toutes", "tout", "très", "tres", "plus", "moins",
    "neuf", "neuve", "occasion", "circulé", "circulee", "rare",
    "envoi", "rapide", "livrée", "livré", "voir", "photos", "photo",
    "choix", "choisissez", "choisir", "disponible", "disponibles", "dispo",
    "année", "annee", "années", "annees", "millésime", "millesime",
    "pièce", "piece", "pièces", "pieces", "coin", "coins",
    "edition", "édition", "tranche", "atelier", "frappe",
    # EN
    "with", "without", "from", "this", "that", "these", "those",
    "available", "please", "choose", "between",
    "mint", "uncirculated", "used", "year", "years",
    # Quality grades — on les capture en rejection_markers ou on
    # les ignore comme tokens.
    "fdc", "unc", "spl", "ttb", "sup",
    # Identifiants Numista (KM#xxx, KM:xxx) — dropés au tokenize.
    # Stop courts (≥4 chars exigé) ne s'applique pas ici, mais on
    # garde par sécurité.
    "euro", "euros",
})


# ── Helpers ──────────────────────────────────────────────────────────────────


def all_country_tokens() -> Iterable[tuple[str, str]]:
    """Yield (token, ISO2) pour chaque alias pays/adjectif/flag.

    Ordre stable utile au tie-breaking (substantif > adjectif > flag).
    """
    for iso2, names in COUNTRY_NAMES.items():
        for n in names:
            yield (n, iso2)
    for iso2, adjs in COUNTRY_ADJECTIVES.items():
        for a in adjs:
            yield (a, iso2)
    for flag, iso2 in COUNTRY_FLAGS.items():
        yield (flag, iso2)
