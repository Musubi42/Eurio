"""Adapter LMDLP — discover + match (pas d'image, scope prix+qualité).

Porté de l'ancien ``referential/scrape_lmdlp.py`` (archi JSON morte) vers la
nouvelle archi source-adapter + SQLite. Ce qui est conservé du vieux script :
la découverte via l'API WooCommerce Store et l'extraction (pays/année/thème/
prix/qualité). Ce qui change : le matching passe par le ``SlugGroupMatcher``
partagé (one-to-one par country/year), et l'écriture cible ``coin_market_quotes``
(le pipeline s'en charge), plus le JSON ``eurio_referential.json``.

Un produit LMDLP = **une qualité** (``type='simple'``, pas de variations Woo).
Une pièce physique = N produits ; on les groupe par (country, year, theme_slug)
et chaque groupe est matché à au plus un eurio_id.
"""

from __future__ import annotations

import html
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

import httpx

from referential.eurio_referential import slugify
from sources._base.adapter import DiscoveredItem, SourceQuery
from sources._base.slug_match import RefCoin, SlugGroupMatcher
from sources.ebay.queries import ISO2_TO_NAME_FR

logger = logging.getLogger(__name__)

SOURCE_ID = "lmdlp"
API_BASE = "https://lamonnaiedelapiece.com/wp-json/wc/store/v1/products"
USER_AGENT = "Eurio/0.1 lmdlp-scraper (https://github.com/Musubi42/Eurio)"
# Filtre serveur sur l'attribut « valeur faciale = 2 € » (slug technique NL).
ATTR_DENOM_2EUR = ("pa_nominale-waarde", "2-euro-fr")
RATE_LIMIT_SEC = 0.3
PER_PAGE = 100

_SNAPSHOTS_DIR = Path(__file__).resolve().parents[2] / "datasets" / "sources"

# Nom de pays FR (catégorie LMDLP) → ISO2. On inverse la map maintenue du tree
# sources/ (ebay.queries) plutôt que d'importer le module legacy eurio_referential.
_FR_NAME_TO_ISO2: dict[str, str] = {
    name: iso for iso, name in ISO2_TO_NAME_FR.items() if iso != "eu"
}

YEAR_RX = re.compile(r"^(19|20)\d{2}$")
# Le nom LMDLP est « <préfixe identité> <SÉP> <thème> <qualité> ». Le préfixe
# identité varie : « 2 euros {Pays} {Année} » OU « {Pays} {Année} » (parfois
# suivi d'un « 2 euros » après le séparateur). Plutôt qu'un regex de préfixe
# rigide (qui ratait le format pays-d'abord), on coupe sur le 1er séparateur
# et on garde la partie thème, puis on retire un « 2 euros » résiduel en tête.
NAME_SEP_RX = re.compile(r"\s[–—:-]\s")
LEADING_2EUR_RX = re.compile(r"^\s*2\s*euros?\s+", re.IGNORECASE)
QUALITY_SUFFIX_RX = re.compile(
    r"\s+(UNC|BU(?:\s+FDC)?(?:\s+\w+)?|BE(?:\s+\w+)?|"
    r"FDC|Coincard|Blister|Rouleau)\b.*$",
    re.IGNORECASE,
)
MULTIPACK_PREFIX_RX = re.compile(r"^\s*\d+\s*x\s+2\s*euros?", re.IGNORECASE)
PLUS_SEPARATOR_RX = re.compile(r"\s\+\s")


@dataclass(frozen=True)
class LmdlpProduct:
    """Un produit LMDLP normalisé (= une qualité d'une pièce)."""

    sku: str
    name: str
    permalink: str | None
    country: str | None       # ISO2
    year: int | None
    theme_slug: str
    quality: str | None       # libellé attribut « Qualité » (UNC / BU FDC / …)
    price_eur: float | None
    in_stock: bool


# ── extraction helpers (portés, lisent un dict produit de l'API Store) ───────


def get_attr_terms(product: dict, attr_name: str) -> list[str]:
    """Termes d'un attribut par nom (insensible à la casse)."""
    target = attr_name.casefold()
    for a in product.get("attributes", []):
        if (a.get("name") or "").casefold() == target:
            return [t.get("name", "") for t in a.get("terms", [])]
    return []


def extract_country_iso2(product: dict) -> str | None:
    for cat in product.get("categories", []):
        iso = _FR_NAME_TO_ISO2.get((cat.get("name") or "").strip())
        if iso:
            return iso
    return None


def extract_year(product: dict) -> int | None:
    for cat in product.get("categories", []):
        name = (cat.get("name") or "").strip()
        if YEAR_RX.match(name):
            return int(name)
    sku = product.get("sku") or ""
    m = re.search(r"(20\d{2})", sku)
    return int(m.group(1)) if m else None


def extract_theme_slug(product: dict) -> str:
    """Slug du thème : nom unescapé, sans préfixe identité (pays/année/« 2 euros »)
    ni suffixe qualité. Coupe sur le 1er séparateur ; gère les deux ordres
    (« 2 euros {Pays} {Année} – {thème} » et « {Pays} {Année} – 2 euros {thème} »)."""
    raw = html.unescape(product.get("name") or "")
    parts = NAME_SEP_RX.split(raw, maxsplit=1)
    theme = parts[1] if len(parts) > 1 else raw
    theme = LEADING_2EUR_RX.sub("", theme)
    theme = QUALITY_SUFFIX_RX.sub("", theme)
    return slugify(theme)


def extract_price_eur(product: dict) -> float | None:
    p = product.get("prices") or {}
    raw = p.get("price")
    minor = p.get("currency_minor_unit")
    if raw is None or minor is None:
        return None
    try:
        return int(raw) / (10 ** int(minor))
    except (TypeError, ValueError):
        return None


def extract_quality(product: dict) -> str | None:
    qs = get_attr_terms(product, "Qualité")
    return qs[0] if qs else None


def is_single_commemo(product: dict) -> tuple[bool, str]:
    """``(keep, reason)``. Rejette sets, rouleaux, coffrets, bundles, multipacks.

    Eurio cible des pièces canoniques *individuelles* : un « 2 x 2 euros » ou un
    rouleau ne s'attache pas à un seul eurio_id sans perte/duplication. On les
    drop au scrape plutôt que de les empiler.
    """
    if not product.get("is_purchasable"):
        return False, "not_purchasable"
    raw_name = product.get("name") or ""
    name = raw_name.casefold()
    types = [t.casefold() for t in get_attr_terms(product, "Type")]
    cat_names = [(c.get("name") or "").casefold() for c in product.get("categories", [])]

    if MULTIPACK_PREFIX_RX.match(raw_name):
        return False, "multipack_prefix"
    if PLUS_SEPARATOR_RX.search(raw_name):
        return False, "plus_separator_bundle"

    blacklist_terms = ("coffret", "rouleau", "série", "serie", "set ", " set", "blister")
    if any(b in name for b in blacklist_terms):
        return False, "name_blacklist"
    if any(b in c for c in cat_names for b in ("coffret", "rouleau", "liste")):
        return False, "category_blacklist"

    if types and not any("commémorative" in t or "commemorative" in t for t in types):
        return False, f"type_not_commemo: {types}"
    return True, "ok"


def to_product(raw: dict) -> LmdlpProduct:
    """Convertit un dict produit API en ``LmdlpProduct`` normalisé."""
    return LmdlpProduct(
        sku=raw.get("sku") or "",
        name=html.unescape(raw.get("name") or ""),
        permalink=raw.get("permalink"),
        country=extract_country_iso2(raw),
        year=extract_year(raw),
        theme_slug=extract_theme_slug(raw),
        quality=extract_quality(raw),
        price_eur=extract_price_eur(raw),
        in_stock=bool(raw.get("is_in_stock")),
    )


@dataclass
class LmdlpAdapter:
    source_id: str = SOURCE_ID
    conn: sqlite3.Connection | None = None
    sleep: float = RATE_LIMIT_SEC
    # Seuils fuzzy alignés avec BCE (cf. SlugGroupMatcher).
    score_floor: float = 0.25
    gap_ratio: float = 1.4
    # Overrides manuels LMDLP (country, year, theme_slug) → eurio_id. Vide pour
    # l'instant ; à peupler si des libellés divergent trop du slug Numista.
    overrides: dict[tuple[str, int, str], str] = field(default_factory=dict)

    @property
    def _matcher(self) -> SlugGroupMatcher:
        return SlugGroupMatcher(
            overrides=self.overrides,
            score_floor=self.score_floor,
            gap_ratio=self.gap_ratio,
        )

    # ── fetch (avec cache snapshot journalier) ───────────────────────────────

    def fetch_all_2eur(self) -> list[dict]:
        """Pagine tous les produits « 2 € » de l'API Store.

        Idempotence inter-jour : si un snapshot daté d'aujourd'hui existe, on le
        réutilise sans appel réseau (politesse boutique communautaire + permet à
        un refresh par coin de ne pas re-paginer le shop)."""
        cache = _SNAPSHOTS_DIR / f"lmdlp_{date.today().isoformat()}.json"
        if cache.is_file():
            import json
            logger.info("[lmdlp] snapshot du jour réutilisé : %s", cache.name)
            return json.loads(cache.read_text(encoding="utf-8"))

        products: list[dict] = []
        page = 1
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
            while True:
                resp = client.get(API_BASE, params={
                    "per_page": PER_PAGE,
                    "page": page,
                    "attributes[0][attribute]": ATTR_DENOM_2EUR[0],
                    "attributes[0][slug]": ATTR_DENOM_2EUR[1],
                })
                resp.raise_for_status()
                chunk = resp.json()
                if not chunk:
                    break
                products.extend(chunk)
                total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
                logger.info("[lmdlp] page %d/%d : +%d (total %d)",
                            page, total_pages, len(chunk), len(products))
                if page >= total_pages:
                    break
                page += 1
                time.sleep(self.sleep)

        self._write_snapshot(cache, products)
        return products

    @staticmethod
    def _write_snapshot(cache: Path, products: list[dict]) -> None:
        import json
        _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(products, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    # ── référentiel (index (country, year) → candidats) ──────────────────────

    def _load_referential(self) -> dict[tuple[str, int], list[RefCoin]]:
        if self.conn is None:
            raise RuntimeError("LmdlpAdapter.conn requis (connexion eurio.db).")
        idx: dict[tuple[str, int], list[RefCoin]] = {}
        rows = self.conn.execute(
            "SELECT eurio_id, country, year FROM coins "
            "WHERE face_value = 2.0 AND is_commemorative = 1"
        ).fetchall()
        for r in rows:
            eid = r["eurio_id"]
            parts = eid.split("-", 3)  # {country}-{year}-{denom}-{slug}
            slug = parts[3] if len(parts) == 4 else ""
            idx.setdefault((r["country"], r["year"]), []).append(
                RefCoin(eurio_id=eid, country=r["country"], year=r["year"], theme_slug=slug)
            )
        return idx

    # ── discover : fetch → filtre → groupe → match → DiscoveredItem ──────────

    def discover(self, query: SourceQuery) -> Iterable[DiscoveredItem]:
        """Yield un ``DiscoveredItem`` par produit matché (target_eurio_id posé).

        Le matching one-to-one se fait au niveau **pièce** (clé distincte
        (country, year, theme_slug)) ; chaque produit hérite de l'eurio_id de sa
        pièce. Les produits non matchés / hors filtre ne sont pas émis."""
        raw_products = self.fetch_all_2eur()
        ref_index = self._load_referential()

        target_ids: set[str] | None = None
        if query.target_eurio_id:
            target_ids = {query.target_eurio_id}
        elif query.target_eurio_ids:
            target_ids = set(query.target_eurio_ids)

        # 1) filtre single-commemo + normalisation
        products: list[LmdlpProduct] = []
        for raw in raw_products:
            keep, _reason = is_single_commemo(raw)
            if not keep:
                continue
            p = to_product(raw)
            if p.country is None or p.year is None or not p.theme_slug:
                continue
            if query.country and query.country != p.country:
                continue
            products.append(p)

        # 2) clés-pièces distinctes (country, year, theme_slug) → match one-to-one
        keys: list[tuple[str, int, str]] = []
        seen: set[tuple[str, int, str]] = set()
        for p in products:
            k = (p.country, p.year, p.theme_slug)
            if k not in seen:
                seen.add(k)
                keys.append(k)
        assignments = self._matcher.match_group(ref_index, keys)
        key_to_eurio = {k: eid for k, eid in zip(keys, assignments)}

        # 3) émission : 1 DiscoveredItem par produit matché
        for p in products:
            eurio_id = key_to_eurio.get((p.country, p.year, p.theme_slug))
            if eurio_id is None:
                continue
            if target_ids is not None and eurio_id not in target_ids:
                continue
            yield DiscoveredItem(
                source_ref=f"lmdlp/{p.sku}",
                source_url=p.permalink,
                target_eurio_id=eurio_id,
                listing_title=p.name,
                listing_country=p.country,
                listing_year=p.year,
                listing_price=p.price_eur,
                listing_currency="EUR",
                condition_raw=p.quality,
                raw_payload={
                    "sku": p.sku,
                    "name": p.name,
                    "permalink": p.permalink,
                    "quality": p.quality,
                    "price_eur": p.price_eur,
                    "in_stock": p.in_stock,
                    "country": p.country,
                    "year": p.year,
                    "theme_slug": p.theme_slug,
                },
            )
