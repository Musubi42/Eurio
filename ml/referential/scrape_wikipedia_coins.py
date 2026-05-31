"""Scrape la liste par pièce des 2 € commémoratives de nl.wikipedia.

Source : `nl.wikipedia.org/wiki/Lijst_van_herdenkingsmunten_van_€_2` — un
`wikitable` par année (2004→2026), colonnes ``Land | Afbeelding | Thema``, une
ligne par pièce. C'est la couche **« attendu »** du référentiel : elle donne le
compteur ET l'identité (pays + thème NL) de chaque pièce. On matche chaque ligne
à un ``eurio_id`` (sinon ``matched_eurio_id = NULL`` = pièce manquante).

Matching : même langue des deux côtés. Les titres NL qu'on a déjà par coin
(``coin_names_i18n`` / ``coin_descriptions_i18n`` lang='nl') alimentent les
``aux_slugs`` du ``SlugGroupMatcher`` — exactement le pattern FR de LMDLP, en NL.

Émissions communes : la page liste chaque commune (Rome 2007, UEM 2009, € 2012,
drapeau 2015, Erasmus 2022) UNE fois sous « Europese Unie ». On la **déplie en
une ligne par pays émetteur** via le ``design_group`` eu-* de l'année (l'année
identifie le groupe de façon unique) → match direct exact, pas de fuzzy.

Doctrine official-only : on ne stocke ni n'affiche l'image Wikipédia, seulement
le thème (cf. memory ``project_eurlex_source``). Écrit dans ``wikipedia_nl_coins``.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

_ML_ROOT = Path(__file__).resolve().parents[1]
if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))

from referential.eurio_referential import slugify  # noqa: E402
from sources._base.slug_match import RefCoin, SlugGroupMatcher  # noqa: E402

logger = logging.getLogger(__name__)

WIKI_URL = "https://nl.wikipedia.org/wiki/Lijst_van_herdenkingsmunten_van_%E2%82%AC_2"
USER_AGENT = "Eurio/0.1 wikipedia-nl-coins (https://github.com/Musubi42/Eurio)"
SOURCE = "wikipedia_nl"

# Préfixe « 2 euro(s) » des titres Numista/BCE NL stockés (bruit dénomination).
LEADING_2EUR_RX = re.compile(r"^\s*2\s*euros?\s+", re.IGNORECASE)
# Note de renvoi en fin de thème (« (voor meer informatie, zie …) ») = bruit pur.
_NOTE_RX = re.compile(r"\(\s*voor meer informatie.*?\)", re.IGNORECASE | re.DOTALL)

# Sources de titres NL → slugs auxiliaires de matching (miroir LMDLP _FR_*).
_NL_SLUG_SOURCES = (
    ("coin_names_i18n", "title"),
    ("coin_descriptions_i18n", "title"),
)

# Substantif néerlandais (Wikipedia) → ISO2. Explicite (les exonymes NL ne sont
# pas tous dans text_signals). « Europese Unie » traité à part (émission commune).
DUTCH_COUNTRY_TO_ISO2: dict[str, str] = {
    "andorra": "AD", "belgië": "BE", "belgie": "BE", "bulgarije": "BG",
    "duitsland": "DE", "estland": "EE", "finland": "FI", "frankrijk": "FR",
    "griekenland": "GR", "ierland": "IE", "italië": "IT", "italie": "IT",
    "kroatië": "HR", "kroatie": "HR", "letland": "LV", "litouwen": "LT",
    "luxemburg": "LU", "malta": "MT", "monaco": "MC", "nederland": "NL",
    "oostenrijk": "AT", "portugal": "PT", "san marino": "SM",
    "slovenië": "SI", "slovenie": "SI", "slowakije": "SK", "spanje": "ES",
    "vaticaanstad": "VA", "vaticaan": "VA", "cyprus": "CY",
}

_EU_LAND = ("europese unie", "europa")

# Overrides manuels (country, year, theme_slug_wiki) → eurio_id. Cas où le thème
# nl.wikipedia emploie un EXONYME ou un descripteur différent de notre titre : la
# pièce EST en base mais aucun slug ne peut matcher (Koerland≠Kurzeme, etc.). Pas
# d'algo possible via nos traductions → mapping explicite, une ligne par cas.
# Documenté dans docs/sources-refacto/exonym-matching.md.
MANUAL_OVERRIDES: dict[tuple[str, int, str], str] = {
    ("DE", 2014, "de-michaeliskirche-in-hildesheim-nedersaksen-negende-uit-de-bundeslander-serie"):
        "de-2014-2eur-state-of-lower-saxony",            # Hildesheim/Michaeliskirche = Basse-Saxe
    ("NL", 2014, "koningsdubbelportret"):
        "nl-2014-2eur-accession-of-king",                # double portrait royal = accession (canonique, pas la variante coloured)
    ("LV", 2015, "30-jarig-bestaan-van-de-letse-ornithologische-vereniging"):
        "lv-2015-2eur-the-black-stork",                  # 30 ans société ornithologique = la cigogne noire
    ("LV", 2016, "midden-lijfland-eerste-uit-de-historische-en-culturele-regios-serie"):
        "lv-2016-2eur-vidzeme",                          # Midden-Lijfland (Moyenne-Livonie) = Vidzeme
    ("ES", 2017, "de-kerk-van-santa-maria-del-naranco-achtste-uit-de-serie-unesco-wereld-erfgoedlijst"):
        "es-2017-2eur-churches-of-the-kingdom-of-asturias",  # église précise = série « églises du royaume des Asturies »
    ("LV", 2017, "koerland-tweede-uit-de-historische-en-culturele-regios-serie"):
        "lv-2017-2eur-kurzeme",                          # Koerland (exonyme NL) = Kurzeme
    ("LV", 2017, "letgallen-derde-uit-de-historische-en-culturele-regios-serie"):
        "lv-2017-2eur-latgale",                          # Letgallen (exonyme NL) = Latgale
    ("LT", 2018, "100-verjaardag-van-de-oprichting-van-de-onafhankelijke-staat"):
        "lt-2018-2eur-centenary-of-independent-baltic-states",  # indépendance lituanienne = série commune États baltes
    ("LV", 2025, "selonie-vijfde-en-laatste-uit-de-historische-en-culturele-regios-serie"):
        "lv-2025-2eur-selija",                           # Selonië (NL) = Selija (Sélonie)
}


@dataclass
class NlCoinRow:
    country: str            # ISO2
    year: int
    theme: str
    theme_slug: str
    source_url: str
    matched_eurio_id: str | None = None
    match_score: float | None = None


# Thèmes NL souvent verbeux et partageant un long préfixe (« 200 verjaardag van
# de oprichting van de Universiteit van Gent / … Luik ») : on slugifie plus long
# que le défaut (60) pour garder le token distinctif de fin — sinon collision PK
# ET matching dégradé (le token discriminant tombe à la troncature).
_THEME_SLUG_MAXLEN = 120


def _theme_slug(text: str) -> str:
    return slugify(text, max_len=_THEME_SLUG_MAXLEN)


def _clean_theme(text: str) -> str:
    text = _NOTE_RX.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _country_iso2(text: str) -> str | None:
    """ISO2 du pays depuis le libellé de cellule (plus long nom NL contenu)."""
    low = re.sub(r"\s+", " ", text.lower())
    best: tuple[int, str] | None = None
    for name, iso2 in DUTCH_COUNTRY_TO_ISO2.items():
        if name in low and (best is None or len(name) > best[0]):
            best = (len(name), iso2)
    return best[1] if best else None


def _is_eu(text: str) -> bool:
    low = re.sub(r"\s+", " ", text.lower()).strip()
    return any(low == e or low.startswith(e) for e in _EU_LAND)


@dataclass
class _RawRow:
    land: str
    year: int
    theme: str


def parse_list(html: str) -> list[_RawRow]:
    """Extrait toutes les lignes pièce des tableaux par année (un par section)."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[_RawRow] = []
    for table in soup.find_all("table", class_="wikitable"):
        heading = table.find_previous(["h2", "h3", "h4"])
        year = _normalize_year(heading.get_text(strip=True)) if heading else None
        if year is None:
            continue
        rows = table.find_all("tr")
        # En-tête attendu : Land | Afbeelding | Thema. On saute la 1re ligne.
        for r in rows[1:]:
            cells = r.find_all(["th", "td"])
            if len(cells) < 3:
                continue
            for c in (cells[0], cells[2]):
                for sup in c.find_all("sup"):
                    sup.decompose()
            land = re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True)).strip()
            theme = _clean_theme(cells[2].get_text(" ", strip=True))
            if not land or not theme:
                continue
            out.append(_RawRow(land=land, year=year, theme=theme))
    return out


def _normalize_year(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    if len(digits) == 4:
        return int(digits)
    return None


def _load_nl_aux_slugs(conn) -> dict[str, set[str]]:
    """eurio_id → ensemble de slugs NL (titres i18n Numista + descriptions BCE)."""
    aux: dict[str, set[str]] = {}
    for table, col in _NL_SLUG_SOURCES:
        rows = conn.execute(
            f"SELECT eurio_id, {col} AS v FROM {table} "
            f"WHERE lang = 'nl' AND {col} IS NOT NULL AND {col} != ''"
        ).fetchall()
        for r in rows:
            slug = slugify(LEADING_2EUR_RX.sub("", r["v"]))
            if slug:
                aux.setdefault(r["eurio_id"], set()).add(slug)
    return aux


def _load_referential(conn) -> dict[tuple[str, int], list[RefCoin]]:
    nl_aux = _load_nl_aux_slugs(conn)
    idx: dict[tuple[str, int], list[RefCoin]] = {}
    rows = conn.execute(
        "SELECT eurio_id, country, year FROM coins "
        "WHERE face_value = 2.0 AND is_commemorative = 1"
    ).fetchall()
    for r in rows:
        eid = r["eurio_id"]
        parts = eid.split("-", 3)  # {country}-{year}-{denom}-{slug}
        slug = parts[3] if len(parts) == 4 else ""
        idx.setdefault((r["country"], r["year"]), []).append(
            RefCoin(
                eurio_id=eid, country=r["country"], year=r["year"],
                theme_slug=slug, aux_slugs=frozenset(nl_aux.get(eid, set())),
            )
        )
    return idx


def _expand_joint(conn, year: int, theme: str, src_url: str) -> list[NlCoinRow]:
    """Déplie une ligne « Europese Unie » en une ligne par pays émetteur via le
    design_group eu-* de l'année (match direct exact)."""
    grp = conn.execute(
        "SELECT country, eurio_id FROM coins "
        "WHERE design_group_id LIKE 'eu-%' AND year = ? "
        "AND face_value = 2.0 AND is_commemorative = 1",
        (year,),
    ).fetchall()
    if not grp:
        logger.warning("[wiki-nl] commune %d sans design_group eu-* en base", year)
    slug = _theme_slug(theme)
    # Un pays peut avoir plusieurs lignes dans le groupe (variantes couleur) :
    # on ne garde qu'un marqueur par pays (1er = canonique attendu).
    by_country: dict[str, str] = {}
    for r in grp:
        by_country.setdefault(r["country"], r["eurio_id"])
    return [
        NlCoinRow(country=country, year=year, theme=theme, theme_slug=slug,
                  source_url=src_url, matched_eurio_id=eid, match_score=1.0)
        for country, eid in by_country.items()
    ]


def harvest(store, *, html: str | None = None, dry_run: bool = False) -> dict:
    """Parse la liste nl, matche, et upsert dans ``wikipedia_nl_coins``.

    Retourne un récap ``{total, matched, joint, rate}``."""
    html = html or _fetch_html()
    raw = parse_list(html)
    conn = store._connection()  # noqa: SLF001

    joint_rows: list[NlCoinRow] = []
    joint_eids: set[str] = set()
    national: list[tuple[str, _RawRow]] = []  # (iso2, raw)
    for rr in raw:
        src_url = f"{WIKI_URL}#{rr.year}"
        if _is_eu(rr.land):
            for nr in _expand_joint(conn, rr.year, rr.theme, src_url):
                joint_rows.append(nr)
                joint_eids.add(nr.matched_eurio_id)
            continue
        iso2 = _country_iso2(rr.land)
        if iso2 is None:
            logger.warning("[wiki-nl] pays NL inconnu: %r (%d)", rr.land, rr.year)
            continue
        national.append((iso2, rr))

    # Fuzzy match des nationales — en excluant les eurio_id déjà pris par une
    # commune (sinon une nationale pourrait voler l'eurio_id du joint).
    ref_index = _load_referential(conn)
    for key, lst in ref_index.items():
        ref_index[key] = [c for c in lst if c.eurio_id not in joint_eids]
    matcher = SlugGroupMatcher(overrides=MANUAL_OVERRIDES)
    items = [(iso2, rr.year, _theme_slug(rr.theme)) for iso2, rr in national]
    matched = matcher.match_group(ref_index, items)

    national_rows: list[NlCoinRow] = []
    for (iso2, rr), eid in zip(national, matched):
        national_rows.append(NlCoinRow(
            country=iso2, year=rr.year, theme=rr.theme,
            theme_slug=_theme_slug(rr.theme), source_url=f"{WIKI_URL}#{rr.year}",
            matched_eurio_id=eid, match_score=None,
        ))

    # Dédup sur la PK (country, year, theme_slug). En cas de collision, on garde
    # la ligne MATCHÉE (ex. commune dépliée vs doublon national au même slug —
    # cf. SM 2012 « 10 jaar euro ») : une ligne non matchée ne doit pas écraser
    # une ligne matchée.
    by_pk: dict[tuple[str, int, str], NlCoinRow] = {}
    for row in (*joint_rows, *national_rows):
        pk = (row.country, row.year, row.theme_slug)
        existing = by_pk.get(pk)
        if existing is not None and existing.matched_eurio_id and not row.matched_eurio_id:
            continue
        by_pk[pk] = row
    rows = list(by_pk.values())

    n_matched = sum(1 for r in rows if r.matched_eurio_id is not None)
    recap = {
        "total": len(rows), "matched": n_matched, "joint": len(joint_rows),
        "rate": round(n_matched / len(rows), 3) if rows else 0.0,
    }
    logger.info("[wiki-nl] %d pièces (%d communes) — %d matchées (%.0f%%)",
                recap["total"], recap["joint"], recap["matched"],
                recap["rate"] * 100)
    if dry_run:
        return recap

    for r in rows:
        conn.execute(
            """
            INSERT INTO wikipedia_nl_coins
              (country, year, theme, theme_slug, source_url,
               matched_eurio_id, match_score, planned)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT (country, year, theme_slug) DO UPDATE SET
              theme = excluded.theme, source_url = excluded.source_url,
              matched_eurio_id = excluded.matched_eurio_id,
              match_score = excluded.match_score,
              fetched_at = datetime('now')
            """,
            (r.country, r.year, r.theme, r.theme_slug, r.source_url,
             r.matched_eurio_id, r.match_score),
        )
    conn.commit()
    return recap


def rematch_cell(conn, country: str, year: int) -> int:
    """Re-relie les lignes wiki non matchées d'une cellule après ajout d'un coin
    (accept de découverte). Réutilise le matcher fuzzy, en respectant l'unicité
    (les eurio_id déjà liés dans la cellule sont exclus). Retourne le nb de
    nouveaux liens écrits."""
    ref_index = _load_referential(conn)
    candidates = list(ref_index.get((country, year), []))
    claimed = {
        r[0] for r in conn.execute(
            "SELECT matched_eurio_id FROM wikipedia_nl_coins "
            "WHERE country = ? AND year = ? AND matched_eurio_id IS NOT NULL",
            (country, year),
        )
    }
    rows = conn.execute(
        "SELECT theme_slug FROM wikipedia_nl_coins "
        "WHERE country = ? AND year = ? AND matched_eurio_id IS NULL",
        (country, year),
    ).fetchall()
    matcher = SlugGroupMatcher(overrides=MANUAL_OVERRIDES)
    n = 0
    for r in rows:
        eid = matcher.assign_one(country, year, r["theme_slug"], candidates, claimed)
        if eid:
            conn.execute(
                "UPDATE wikipedia_nl_coins SET matched_eurio_id = ?, "
                "fetched_at = datetime('now') "
                "WHERE country = ? AND year = ? AND theme_slug = ?",
                (eid, country, year, r["theme_slug"]),
            )
            n += 1
    conn.commit()
    return n


def _fetch_html() -> str:
    resp = httpx.get(WIKI_URL, headers={"User-Agent": USER_AGENT},
                     follow_redirects=True, timeout=40)
    resp.raise_for_status()
    return resp.text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + matche + affiche le récap, n'écrit pas en DB.")
    parser.add_argument("--unmatched", action="store_true",
                        help="Liste les pièces non matchées (audit du matching).")
    parser.add_argument("--log", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    from state import Store

    store = Store(_ML_ROOT / "state" / "eurio.db")
    if args.unmatched:
        _print_unmatched(store)
        return 0
    recap = harvest(store, dry_run=args.dry_run)
    print(f"{recap['total']} pièces ({recap['joint']} communes) · "
          f"{recap['matched']} matchées ({recap['rate'] * 100:.0f}%) "
          f"{'(dry-run)' if args.dry_run else 'écrites'}")
    return 0


def _print_unmatched(store) -> None:
    conn = store._connection()  # noqa: SLF001
    rows = conn.execute(
        "SELECT country, year, theme FROM wikipedia_nl_coins "
        "WHERE matched_eurio_id IS NULL ORDER BY year, country"
    ).fetchall()
    print(f"{len(rows)} pièces non matchées :")
    for r in rows:
        print(f"  {r['country']} {r['year']}  {r['theme']}")


if __name__ == "__main__":
    raise SystemExit(main())
