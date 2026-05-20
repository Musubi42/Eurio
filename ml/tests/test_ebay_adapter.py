"""Tests pour EbayAdapter (phase 3.B).

Tous les appels HTTP sont mockés via httpx.MockTransport — aucun call
réel n'est émis vers eBay (pas de token requis).

Couverture :
- queries.build_query depuis la table coins SQLite
- queries.title_matches_theme + STOP_WORDS
- filters.is_lot_suspected (D-26 niveau 1) sur titres FR
- filters.accept_listing : prix bornes, noise, devise
- adapter.discover : 1 listing → N DiscoveredItems (un par image)
- adapter.discover : titre lot → is_lot_suspected = True propagé
- adapter.discover : filtre anti-bruit rejette avant yield
- adapter.download_raw : écriture atomique, sha256 + dims (PIL)
- adapter rejette query sans target_eurio_id (orchestrator unfold required)
"""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
from PIL import Image

from market.ebay_client import EbayClient
from sources._base.adapter import SourceQuery
from sources.ebay.adapter import EbayAdapter
from sources.ebay.filters import accept_listing, is_lot_suspected, listing_row
from sources.ebay.queries import (
    _legacy_title_matches_theme,
    build_query,
    load_coin,
)
from state.store import Store


# ── helpers ──────────────────────────────────────────────────────────────────


def _seed_coin(conn, *, eurio_id="fr-2015-2eur-paix", country="FR", year=2015,
               face_value=2.0, is_commemorative=True, theme="paix") -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO coins (
          eurio_id, country, country_name, year, face_value,
          is_commemorative, theme, numista_id, raw_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}')
        """,
        (eurio_id, country, "France", year, face_value, int(is_commemorative), theme, None),
    )


def _png_bytes(size=(120, 120), color=(40, 80, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _summary(item_id: str, title: str, price: float = 5.0, *, group_id: str | None = None,
             additional: list[str] | None = None) -> dict:
    out = {
        "itemId": item_id,
        "title": title,
        "price": {"value": str(price), "currency": "EUR"},
        "estimatedAvailabilities": [{"estimatedSoldQuantity": 0}],
        "seller": {"username": "vendeur42", "feedbackPercentage": "99.5", "feedbackScore": 1234},
        "itemOriginDate": "2026-04-01T00:00:00Z",
        "itemWebUrl": f"https://ebay.fr/itm/{item_id}",
        "image": {"imageUrl": f"https://i.ebayimg.com/images/g/{item_id}/s-l500.jpg"},
        "additionalImages": [{"imageUrl": u} for u in (additional or [])],
        "localizedAspects": [
            {"name": "Année", "value": "2015"},
            {"name": "État", "value": "Excellent état"},
        ],
    }
    if group_id:
        out["primaryItemGroup"] = {"itemGroupId": group_id}
    return out


def _detail(item_id: str, *, additional: list[str], condition: str = "Used") -> dict:
    return {
        "itemId": item_id,
        "title": "ignored at detail level",
        "image": {"imageUrl": f"https://i.ebayimg.com/images/g/{item_id}/HD-primary.jpg"},
        "additionalImages": [{"imageUrl": u} for u in additional],
        "condition": condition,
        "seller": {"username": "vendeur42"},
    }


class _MockEbayClient:
    """Drop-in for EbayClient that returns scripted responses.

    Counts calls so tests can assert quota-conscious behavior.
    """

    def __init__(self, *, search_responses: list[dict], item_responses: dict[str, dict],
                 group_responses: dict[str, dict] | None = None) -> None:
        self.search_responses = list(search_responses)
        self.item_responses = item_responses
        self.group_responses = group_responses or {}
        self.calls: list[tuple[str, dict]] = []

    def search(self, query, **kwargs):
        self.calls.append(("search", {"query": query, **kwargs}))
        # L'adapter fait 2 search calls par eurio_id (EBAY_DE + EBAY_ES).
        # Pour ne pas casser les tests legacy qui ne fournissaient qu'1
        # response, on garde la dernière "sticky" : 1 response → les
        # 2 mkts voient les mêmes items → merge dedup → résultat unique.
        if not self.search_responses:
            return {"itemSummaries": []}
        if len(self.search_responses) == 1:
            return self.search_responses[0]
        return self.search_responses.pop(0)

    def get_item(self, item_id, fieldgroups="PRODUCT"):
        self.calls.append(("get_item", {"item_id": item_id, "fieldgroups": fieldgroups}))
        return self.item_responses[item_id]

    def get_items_by_group(self, group_id):
        self.calls.append(("get_items_by_group", {"group_id": group_id}))
        return self.group_responses.get(group_id, {"items": []})


# ── queries ──────────────────────────────────────────────────────────────────


def test_load_coin_raises_if_missing(tmp_path):
    store = Store(tmp_path / "t.db")
    from sources.ebay.queries import CoinNotFound
    with pytest.raises(CoinNotFound):
        load_coin(store._connection(), "does-not-exist")


def test_build_query_uses_french_country_name_and_year(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_coin(conn, eurio_id="fr-2015-2eur-paix", country="FR", year=2015, theme="paix")
    coin = load_coin(conn, "fr-2015-2eur-paix")
    q = build_query(coin)
    assert q.q == "2 euro France 2015"
    assert "categoryId:32650" in q.aspect_filter
    # Bloc 1 (2026-05-05) : on a drop l'aspect Année:{...} pour ne plus
    # crasher le recall sur les vendeurs qui ne remplissent pas l'aspect.
    assert "{2015}" not in q.aspect_filter
    assert q.theme_tokens == ["paix"]


def test_theme_tokens_drop_stop_words_and_short_tokens(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_coin(
        conn,
        eurio_id="fr-2008-2eur-french-presidency-of-the-council-of-the-european-union",
        country="FR", year=2008,
    )
    coin = load_coin(conn, "fr-2008-2eur-french-presidency-of-the-council-of-the-european-union")
    q = build_query(coin)
    # 'of', 'the' dropped; 'french', 'presidency', 'council', 'european' kept
    assert "french" in q.theme_tokens
    assert "presidency" in q.theme_tokens
    assert "the" not in q.theme_tokens
    assert "of" not in q.theme_tokens


def test_legacy_title_matches_theme_permissive_if_no_tokens():
    # Legacy matcher : kept for fallback path, retiré en V2.
    assert _legacy_title_matches_theme("Anything goes", []) is True


def test_legacy_title_matches_theme_case_insensitive():
    assert _legacy_title_matches_theme("2 EURO Paix Allemagne 2015", ["paix"]) is True
    assert _legacy_title_matches_theme("2 euro Allemagne 2015", ["paix"]) is False


# ── matcher I2 multilingue ──────────────────────────────────────────────────


@pytest.fixture
def conn_i18n():
    """Connection SQLite avec quelques rows coin_names_i18n + coins."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE coins (
          eurio_id TEXT PRIMARY KEY,
          country TEXT NOT NULL, country_name TEXT, year INTEGER NOT NULL,
          face_value REAL NOT NULL, is_commemorative INTEGER NOT NULL DEFAULT 0,
          theme TEXT, numista_id INTEGER, raw_payload_json TEXT,
          imported_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE coin_names_i18n (
          eurio_id TEXT NOT NULL, lang TEXT NOT NULL, title TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'numista',
          confidence TEXT NOT NULL DEFAULT 'canon',
          model TEXT, fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (eurio_id, lang)
        );
        INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative, theme, numista_id) VALUES
          ('ad-2025-2eur-bearded-vulture', 'AD', 2025, 2.0, 1, 'Bearded vulture', 482937),
          ('de-2020-2eur-50-years-since-the-kniefall-von-warschau', 'DE', 2020, 2.0, 1, '50 years Kniefall', 226447),
          ('fr-1999-2eur-standard', 'FR', 1999, 2.0, 0, NULL, 104),
          ('xx-2030-2eur-no-i18n-data', 'XX', 2030, 2.0, 1, 'helmut schmidt', NULL),
          ('zz-2000-2eur-bare', 'ZZ', 2000, 2.0, 0, NULL, 999);
        INSERT INTO coin_names_i18n (eurio_id, lang, title) VALUES
          ('ad-2025-2eur-bearded-vulture', 'fr', '2 euros Gypaète barbu'),
          ('ad-2025-2eur-bearded-vulture', 'en', '2 Euros Bearded vulture'),
          ('de-2020-2eur-50-years-since-the-kniefall-von-warschau', 'fr', '2 euros Génuflexion de Varsovie'),
          ('de-2020-2eur-50-years-since-the-kniefall-von-warschau', 'en', '2 Euros Kneeling to Warsaw'),
          ('fr-1999-2eur-standard', 'fr', '2 euros 1re carte'),
          ('fr-1999-2eur-standard', 'en', '2 Euros 1st map'),
          ('zz-2000-2eur-bare', 'fr', '2 Euro'),
          ('zz-2000-2eur-bare', 'en', '2 Euro');
        """
    )
    yield conn
    conn.close()


def test_title_matches_theme_via_fr_title(conn_i18n):
    from sources.ebay.queries import title_matches_theme

    # Listing FR avec "gypaète" → match via titre FR Numista
    assert title_matches_theme(
        "Pièce 2€ Andorre 2025 Gypaète barbu", "ad-2025-2eur-bearded-vulture",
        marketplace="EBAY_FR", conn=conn_i18n,
    ) is True


def test_title_matches_theme_via_en_title_on_fr_mkt(conn_i18n):
    from sources.ebay.queries import title_matches_theme

    # Listing EN sur EBAY_FR (langues actives = fr + en) → match via titre EN
    assert title_matches_theme(
        "Andorra 2 Euros 2025 Bearded vulture coin", "ad-2025-2eur-bearded-vulture",
        marketplace="EBAY_FR", conn=conn_i18n,
    ) is True


def test_title_matches_theme_accent_insensitive(conn_i18n):
    from sources.ebay.queries import title_matches_theme

    # "Genuflexion" (sans accent) doit matcher le titre FR "Génuflexion"
    assert title_matches_theme(
        "2 Euros Allemagne 2020 - Genuflexion Varsovie", "de-2020-2eur-50-years-since-the-kniefall-von-warschau",
        marketplace="EBAY_FR", conn=conn_i18n,
    ) is True


def test_title_matches_theme_no_match_returns_false(conn_i18n):
    from sources.ebay.queries import title_matches_theme

    # Titre seller sans aucun token discriminant
    assert title_matches_theme(
        "2 euros Andorre 2025 pièce de monnaie", "ad-2025-2eur-bearded-vulture",
        marketplace="EBAY_FR", conn=conn_i18n,
    ) is False


def test_title_matches_theme_permissive_when_tokens_empty(conn_i18n):
    from sources.ebay.queries import title_matches_theme

    # zz-2000-2eur-bare a "2 Euro" en FR et EN → 0 tokens partout.
    # i18n trouvé mais aucun token discriminant → return True (permissif
    # comme legacy quand theme_tokens=[]).
    assert title_matches_theme(
        "Random title here", "zz-2000-2eur-bare",
        marketplace="EBAY_FR", conn=conn_i18n,
    ) is True


def test_title_matches_theme_fallback_legacy_when_no_i18n(conn_i18n):
    from sources.ebay.queries import title_matches_theme

    # Coin sans aucune row i18n → fallback _theme_keywords + legacy matcher.
    # Le slug contient "no-i18n-data" → tokens kept = ['data'] (len≥4, pas stop).
    # Listing contient "data" → match via legacy.
    assert title_matches_theme(
        "2 euros 2030 some data here", "xx-2030-2eur-no-i18n-data",
        marketplace="EBAY_GB", conn=conn_i18n,
    ) is True
    # Listing sans "data" → no match via legacy.
    assert title_matches_theme(
        "2 euros 2030 nothing relevant", "xx-2030-2eur-no-i18n-data",
        marketplace="EBAY_GB", conn=conn_i18n,
    ) is False


def test_title_matches_theme_unknown_mkt_falls_back_to_en(conn_i18n):
    from sources.ebay.queries import title_matches_theme

    # Marketplace inconnu → default lang = ["en"]. Match si EN i18n présent.
    assert title_matches_theme(
        "Bearded vulture coin", "ad-2025-2eur-bearded-vulture",
        marketplace="EBAY_UNKNOWN", conn=conn_i18n,
    ) is True


# ── filters ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("title,expected", [
    ("2 euro France 2015 Paix", False),
    ("LOT de 5 pièces 2 euro", True),
    ("Coffret Belgique 2002", True),
    ("Série complète 2 euro Allemagne", True),
    ("Rouleau de 2 euros France", True),
    ("Set of 25 coins 2 euro Europe", True),
    ("set 2 euro Allemagne 2015", True),
    ("2 euro Espagne 2015 BU", False),  # BU = noise but not a lot
])
def test_is_lot_suspected(title, expected):
    assert is_lot_suspected(title) is expected


def test_accept_listing_rejects_proof_and_silver():
    row = listing_row(_summary("123", "2 euro France 2015 PROOF", price=12.0))
    ok, reason = accept_listing(row, face_value=2.0)
    assert not ok and reason == "noise_title"

    row = listing_row(_summary("124", "2 euro France 2015 argent", price=80.0))
    ok, reason = accept_listing(row, face_value=2.0)
    assert not ok and reason == "noise_title"


def test_accept_listing_rejects_below_face_and_above_extreme():
    row = listing_row(_summary("125", "2 euro France 2015 Paix", price=0.5))
    ok, reason = accept_listing(row, face_value=2.0)
    assert not ok and reason == "below_face"

    row = listing_row(_summary("126", "2 euro France 2015 Paix", price=2000))
    ok, reason = accept_listing(row, face_value=2.0)
    assert not ok and reason == "above_extreme"


def test_accept_listing_rejects_non_eur():
    item = _summary("127", "2 euro France 2015", price=5.0)
    item["price"]["currency"] = "USD"
    row = listing_row(item)
    ok, reason = accept_listing(row, face_value=2.0)
    assert not ok and reason == "non_eur"


def test_accept_listing_keeps_lot_titles():
    """Important — lots are kept (only flagged), not rejected. Cf. D-26."""
    row = listing_row(_summary("128", "Lot de 5 pièces 2 euro France 2015", price=15.0))
    ok, reason = accept_listing(row, face_value=2.0)
    assert ok and reason == "ok"


def test_accept_listing_rejects_year_mismatch_for_commemoratives():
    """Bloc 1 (2026-05-05) — post-filter year-in-title pour les commémos."""
    row = listing_row(_summary("129", "2 euro France 2014 commémorative", price=5.0))
    ok, reason = accept_listing(
        row, face_value=2.0, expected_year=2015, is_commemorative=True,
    )
    assert not ok and reason == "year_mismatch"


def test_accept_listing_accepts_year_match():
    row = listing_row(_summary("130", "2 euro France 2015 commémorative", price=5.0))
    ok, reason = accept_listing(
        row, face_value=2.0, expected_year=2015, is_commemorative=True,
    )
    assert ok and reason == "ok"


def test_accept_listing_accepts_when_year_missing_in_title():
    """Policy accept-on-missing : pas d'année dans le titre → on accepte."""
    row = listing_row(_summary("131", "2 euro France commémorative", price=5.0))
    ok, reason = accept_listing(
        row, face_value=2.0, expected_year=2015, is_commemorative=True,
    )
    assert ok and reason == "ok"


def test_accept_listing_skips_year_check_for_standards():
    """Standards (non-commémoratifs) : pas de check year-in-title."""
    row = listing_row(_summary("132", "2 euro France 2010 standard", price=5.0))
    ok, reason = accept_listing(
        row, face_value=2.0, expected_year=2015, is_commemorative=False,
    )
    assert ok and reason == "ok"


# ── adapter.discover ─────────────────────────────────────────────────────────


@pytest.fixture()
def store_with_seeded_coin(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_coin(
        conn, eurio_id="fr-2015-2eur-paix", country="FR", year=2015,
        face_value=2.0, is_commemorative=True, theme="paix",
    )
    return store


def _make_adapter(store, *, search, items, groups=None) -> tuple[EbayAdapter, _MockEbayClient]:
    """Construit un adapter B4 avec une factory qui retourne TOUJOURS le
    même mock client, quel que soit le marketplace demandé.

    Routage uniforme : 2 mkts seront appelés (EBAY_DE + EBAY_ES). Le
    mock partage donc ses `search_responses` entre les 2 calls — tests
    qui ne fournissent qu'1 response retournent {itemSummaries:[]} pour
    le 2nd mkt (fallback du mock). Les tests qui veulent contrôler
    chaque mkt utilisent `_PerMktMockClient` plus bas.
    """
    client = _MockEbayClient(search_responses=search, item_responses=items, group_responses=groups)
    adapter = EbayAdapter(
        make_client=lambda mkt: client,  # noqa: ARG005
        conn=store._connection(),
    )
    return adapter, client


def test_discover_rejects_query_without_target_eurio_id(store_with_seeded_coin):
    adapter, _ = _make_adapter(
        store_with_seeded_coin,
        search=[{"itemSummaries": []}],
        items={},
    )
    with pytest.raises(ValueError, match="target_eurio_id"):
        list(adapter.discover(SourceQuery(source_id="ebay")))


def test_discover_yields_one_item_per_image(store_with_seeded_coin):
    """1 listing avec 3 images HD → 3 DiscoveredItems."""
    s1 = _summary("ITEM_1", "2 euro France 2015 Paix", price=5.0)
    detail = _detail("ITEM_1", additional=[
        "https://i.ebayimg.com/HD-1.jpg",
        "https://i.ebayimg.com/HD-2.jpg",
    ])
    adapter, client = _make_adapter(
        store_with_seeded_coin,
        search=[{"itemSummaries": [s1]}],
        items={"ITEM_1": detail},
    )

    items = list(adapter.discover(SourceQuery(
        source_id="ebay", target_eurio_id="fr-2015-2eur-paix",
    )))
    assert len(items) == 3, "1 primary + 2 additional = 3 images"
    refs = [it.source_ref for it in items]
    assert refs == ["ebay_ITEM_1_img0", "ebay_ITEM_1_img1", "ebay_ITEM_1_img2"]
    for it in items:
        assert it.target_eurio_id == "fr-2015-2eur-paix"
        assert it.listing_country == "FR"
        assert it.listing_year == 2015
        assert it.listing_price == 5.0
        assert it.is_lot_suspected is False
        assert it.raw_payload["ebay_item_id"] == "ITEM_1"
    # 2 search (EBAY_DE + EBAY_ES) + 1 item/{id} = 3 API calls. Le
    # même item_id revient sur les 2 mkts (mock sticky) → merge dedup
    # → 1 seul get_item.
    assert len(client.calls) == 3
    assert sum(1 for c in client.calls if c[0] == "search") == 2
    assert sum(1 for c in client.calls if c[0] == "get_item") == 1


def test_discover_propagates_lot_flag_to_all_images(store_with_seeded_coin):
    s1 = _summary("LOT_42", "Coffret 5 pièces 2 euro France 2015", price=20.0)
    detail = _detail("LOT_42", additional=["https://i.ebayimg.com/HD-2.jpg"])
    adapter, _ = _make_adapter(
        store_with_seeded_coin,
        search=[{"itemSummaries": [s1]}],
        items={"LOT_42": detail},
    )
    items = list(adapter.discover(SourceQuery(
        source_id="ebay", target_eurio_id="fr-2015-2eur-paix",
    )))
    assert len(items) == 2
    assert all(it.is_lot_suspected is True for it in items)


def test_discover_filters_proof_listings_before_yielding(store_with_seeded_coin):
    """Listing rejeté par accept_listing (proof) → pas de item/{id} call."""
    proof = _summary("PROOF_1", "2 euro France 2015 PROOF Paix", price=15.0)
    good = _summary("GOOD_1", "2 euro France 2015 Paix", price=5.0)
    adapter, client = _make_adapter(
        store_with_seeded_coin,
        search=[{"itemSummaries": [proof, good]}],
        items={"GOOD_1": _detail("GOOD_1", additional=[])},
    )
    items = list(adapter.discover(SourceQuery(
        source_id="ebay", target_eurio_id="fr-2015-2eur-paix",
    )))
    assert len(items) == 1
    # 1 search + 1 item/{id} (only for GOOD_1) — proof skipped.
    assert sum(1 for c in client.calls if c[0] == "get_item") == 1


def test_discover_ambiguous_country_year_filters_by_theme(tmp_path):
    """Quand 2 commemos partagent (country, year), filtre par theme tokens."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_coin(conn, eurio_id="be-2002-2eur-albert", country="BE", year=2002, theme="albert")
    _seed_coin(conn, eurio_id="be-2002-2eur-other-theme", country="BE", year=2002, theme="other")

    s_match = _summary("ALB_1", "2 euro Belgique 2002 Albert II", price=8.0)
    s_unrelated = _summary("UNR_1", "2 euro Belgique 2002 Other commemo theme", price=8.0)

    client = _MockEbayClient(
        search_responses=[{"itemSummaries": [s_match, s_unrelated]}],
        item_responses={"ALB_1": _detail("ALB_1", additional=[])},
    )
    adapter = EbayAdapter(
        make_client=lambda mkt: client, conn=conn,  # noqa: ARG005
    )

    items = list(adapter.discover(SourceQuery(
        source_id="ebay", target_eurio_id="be-2002-2eur-albert",
    )))
    refs = [it.source_ref for it in items]
    assert refs == ["ebay_ALB_1_img0"]
    # UNR_1 should NOT be probed — title didn't match theme tokens.
    assert all(c[1].get("item_id") != "UNR_1" for c in client.calls if c[0] == "get_item")


def test_discover_falls_back_to_summary_images_if_item_call_fails(store_with_seeded_coin):
    s1 = _summary("ITEM_X", "2 euro France 2015 Paix", price=5.0,
                  additional=["https://i.ebayimg.com/SUM-2.jpg"])

    class _FailingClient(_MockEbayClient):
        def get_item(self, item_id, fieldgroups="PRODUCT"):
            self.calls.append(("get_item", {"item_id": item_id, "fieldgroups": fieldgroups}))
            raise httpx.HTTPError("simulated")

    client = _FailingClient(search_responses=[{"itemSummaries": [s1]}], item_responses={})
    adapter = EbayAdapter(
        make_client=lambda mkt: client,  # noqa: ARG005
        conn=store_with_seeded_coin._connection(),
    )

    items = list(adapter.discover(SourceQuery(
        source_id="ebay", target_eurio_id="fr-2015-2eur-paix",
    )))
    # primary + 1 additional from summary fallback
    assert len(items) == 2
    urls = [it.raw_payload["image_url"] for it in items]
    assert "https://i.ebayimg.com/SUM-2.jpg" in urls


# ── B4 — adapter.discover multi-marketplace ─────────────────────────────────


class _PerMktMockClient(_MockEbayClient):
    """Variante du mock qui tag le marketplace courant sur chaque call.

    Permet aux tests B4 de vérifier quels mkts ont été appelés et avec
    quelle query (langue native).
    """

    def __init__(self, marketplace: str, **kwargs):
        super().__init__(**kwargs)
        self.marketplace = marketplace

    def search(self, query, **kwargs):
        self.calls.append(("search", {"marketplace": self.marketplace, "query": query, **kwargs}))
        if not self.search_responses:
            return {"itemSummaries": []}
        if len(self.search_responses) == 1:
            return self.search_responses[0]
        return self.search_responses.pop(0)

    def get_item(self, item_id, fieldgroups="PRODUCT"):
        self.calls.append((
            "get_item", {"marketplace": self.marketplace, "item_id": item_id, "fieldgroups": fieldgroups},
        ))
        return self.item_responses[item_id]


def _per_mkt_factory(mocks: dict[str, _PerMktMockClient]):
    def make(mkt: str) -> _PerMktMockClient:
        return mocks[mkt]
    return make


def test_discover_calls_de_and_es(tmp_path):
    """N'importe quel coin → 2 search calls : EBAY_DE + EBAY_ES (routage uniforme)."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_coin(conn, eurio_id="fr-2015-2eur-paix", country="FR", year=2015, theme="paix")

    s1 = _summary("DE_ONLY", "2 euro Frankreich 2015 Paix", price=5.0)
    s2 = _summary("ES_ONLY", "2 euros Francia 2015 paz", price=6.0)
    mocks = {
        "EBAY_DE": _PerMktMockClient(
            "EBAY_DE",
            search_responses=[{"itemSummaries": [s1]}],
            item_responses={"DE_ONLY": _detail("DE_ONLY", additional=[])},
        ),
        "EBAY_ES": _PerMktMockClient(
            "EBAY_ES",
            search_responses=[{"itemSummaries": [s2]}],
            item_responses={"ES_ONLY": _detail("ES_ONLY", additional=[])},
        ),
    }
    adapter = EbayAdapter(make_client=_per_mkt_factory(mocks), conn=conn)

    items = list(adapter.discover(SourceQuery(
        source_id="ebay", target_eurio_id="fr-2015-2eur-paix",
    )))

    # 2 mkts × 1 item unique chacun = 2 DiscoveredItems
    assert {it.raw_payload["ebay_item_id"] for it in items} == {"DE_ONLY", "ES_ONLY"}
    # Le first_mkt reflète l'ordre d'appel (EBAY_DE avant EBAY_ES).
    by_id = {it.raw_payload["ebay_item_id"]: it for it in items}
    assert by_id["DE_ONLY"].marketplace == "EBAY_DE"
    assert by_id["DE_ONLY"].marketplace_found == ("EBAY_DE",)
    assert by_id["ES_ONLY"].marketplace == "EBAY_ES"
    assert by_id["ES_ONLY"].marketplace_found == ("EBAY_ES",)


def test_discover_routing_is_uniform_across_countries(tmp_path):
    """Un coin d'origine sans marketplace natif (BG) → toujours EBAY_DE + EBAY_ES."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_coin(conn, eurio_id="bg-2026-2eur-membership", country="BG", year=2026, theme="membership")

    s1 = _summary("BG_1", "2 euro Bulgarien 2026 membership", price=8.0)
    mocks = {
        "EBAY_DE": _PerMktMockClient(
            "EBAY_DE",
            search_responses=[{"itemSummaries": [s1]}],
            item_responses={"BG_1": _detail("BG_1", additional=[])},
        ),
        "EBAY_ES": _PerMktMockClient(
            "EBAY_ES",
            search_responses=[{"itemSummaries": []}],
            item_responses={},
        ),
    }
    adapter = EbayAdapter(make_client=_per_mkt_factory(mocks), conn=conn)

    items = list(adapter.discover(SourceQuery(
        source_id="ebay", target_eurio_id="bg-2026-2eur-membership",
    )))

    assert len(items) == 1
    assert items[0].marketplace == "EBAY_DE"
    # Les 2 marketplaces ont bien été interrogés malgré l'origine BG.
    assert mocks["EBAY_DE"].calls and mocks["EBAY_ES"].calls


def test_discover_dedup_overlap_across_marketplaces(tmp_path):
    """Item_id partagé entre EBAY_DE et EBAY_ES → 1 DiscoveredItem dédupliqué.

    `marketplace` = first-seen (EBAY_DE, interrogé en premier).
    `marketplace_found` contient les 2.
    """
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_coin(conn, eurio_id="fr-2015-2eur-paix", country="FR", year=2015, theme="paix")

    s_shared = _summary("SHARED_42", "2 euro Frankreich 2015 Paix", price=5.0)
    mocks = {
        "EBAY_DE": _PerMktMockClient(
            "EBAY_DE",
            search_responses=[{"itemSummaries": [s_shared]}],
            item_responses={"SHARED_42": _detail("SHARED_42", additional=[])},
        ),
        "EBAY_ES": _PerMktMockClient(
            "EBAY_ES",
            search_responses=[{"itemSummaries": [s_shared]}],
            item_responses={"SHARED_42": _detail("SHARED_42", additional=[])},
        ),
    }
    adapter = EbayAdapter(make_client=_per_mkt_factory(mocks), conn=conn)

    items = list(adapter.discover(SourceQuery(
        source_id="ebay", target_eurio_id="fr-2015-2eur-paix",
    )))

    assert len(items) == 1, "dedup en RAM doit produire 1 seul DiscoveredItem"
    assert items[0].marketplace == "EBAY_DE"
    assert items[0].marketplace_found == ("EBAY_DE", "EBAY_ES")
    # 2 search (1 par mkt) mais 1 seul get_item (sur le first_mkt DE).
    de_calls = mocks["EBAY_DE"].calls
    es_calls = mocks["EBAY_ES"].calls
    assert sum(1 for c in de_calls if c[0] == "search") == 1
    assert sum(1 for c in es_calls if c[0] == "search") == 1
    assert sum(1 for c in de_calls if c[0] == "get_item") == 1
    assert sum(1 for c in es_calls if c[0] == "get_item") == 0


def test_discover_query_lang_per_marketplace(tmp_path):
    """DE coin → query allemande sur EBAY_DE, espagnole sur EBAY_ES."""
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    _seed_coin(
        conn, eurio_id="de-2024-2eur-paulskirche",
        country="DE", year=2024, theme="paulskirche",
    )

    mocks = {
        "EBAY_DE": _PerMktMockClient(
            "EBAY_DE",
            search_responses=[{"itemSummaries": []}],
            item_responses={},
        ),
        "EBAY_ES": _PerMktMockClient(
            "EBAY_ES",
            search_responses=[{"itemSummaries": []}],
            item_responses={},
        ),
    }
    adapter = EbayAdapter(make_client=_per_mkt_factory(mocks), conn=conn)

    list(adapter.discover(SourceQuery(
        source_id="ebay", target_eurio_id="de-2024-2eur-paulskirche",
    )))

    de_query = next(c[1]["query"] for c in mocks["EBAY_DE"].calls if c[0] == "search")
    es_query = next(c[1]["query"] for c in mocks["EBAY_ES"].calls if c[0] == "search")
    assert de_query == "2 euro Deutschland 2024"
    assert es_query == "2 euro Alemania 2024"


# ── adapter.download_raw ─────────────────────────────────────────────────────


def test_download_raw_writes_atomic_with_sha256_and_dims(tmp_path, monkeypatch):
    """download_raw fetches, writes atomically, returns size+sha+dims."""
    payload = _png_bytes(size=(150, 100))

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"Content-Type": "image/png"})

    transport = httpx.MockTransport(_handler)

    # Wrap httpx.Client to inject the mock transport. We monkeypatch the
    # Client class used inside the adapter module so the constructor
    # forces our transport regardless of args.
    import sources.ebay.adapter as adapter_mod
    real_client_cls = adapter_mod.httpx.Client

    def _patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(adapter_mod.httpx, "Client", _patched)

    store = Store(tmp_path / "t.db")
    adapter = EbayAdapter(
        make_client=lambda mkt: None,  # noqa: ARG005 — download_raw doesn't use client
        conn=store._connection(),
    )

    from sources._base.adapter import DiscoveredItem
    item = DiscoveredItem(
        source_ref="ebay_TEST_img0",
        raw_payload={"image_url": "https://example.com/x.png"},
    )
    dest = tmp_path / "out" / "ebay_TEST_img0.png"
    result = adapter.download_raw(item, dest)

    assert dest.is_file()
    assert dest.read_bytes() == payload
    assert result.bytes == len(payload)
    assert result.sha256 == __import__("hashlib").sha256(payload).hexdigest()
    assert result.width == 150 and result.height == 100
