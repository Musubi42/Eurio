"""Tests pour le bench audit live (P10-F, 2026-05-26).

Couvre les 2 endpoints `/bench/runs/{run_id}` (structure par discovery
group) et `/bench/runs/{run_id}/listings` (drill paginé), plus les
helpers d'image fallback (`_canonical_obverse_url`,
`_listing_image_url`).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from api.bench_routes import (  # noqa: E402
    _canonical_obverse_url,
    _coin_context,
    _listing_image_url,
    _run_groups,
    _run_listings,
)
from sources._base.run_logger import start_run  # noqa: E402
from store import Store  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────


def _seed_coin(
    conn, *, eurio_id: str, country: str, year: int,
    face_value: float = 2.0, theme: str | None = "Theme",
    is_commemorative: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO coins (eurio_id, country, year, face_value, currency,
                           is_commemorative, theme)
        VALUES (?, ?, ?, ?, 'EUR', ?, ?)
        """,
        (eurio_id, country, year, face_value, int(is_commemorative), theme),
    )


def _seed_source_image(
    conn, *, sid: str, run_id: str,
    country: str, year: int,
    target_eurio_id: str | None,
    route_decision: str | None = "pending",
    route_reason: str | None = "no_crops_yet",
    listing_title: str = "2 Euro Foo",
    listing_price: float | None = 5.0,
    image_url: str | None = "https://i.ebayimg.com/img.jpg",
    is_lot_suspected: bool = False,
) -> None:
    raw = json.dumps({"image_url": image_url}) if image_url else None
    conn.execute(
        """
        INSERT INTO source_images (
          id, source, source_ref, target_eurio_id, listing_title,
          listing_country, listing_year, listing_price, listing_currency,
          storage_path, license, is_lot_suspected, run_id,
          route_decision, route_reason, raw_payload_json
        ) VALUES (?, 'ebay', ?, ?, ?, ?, ?, ?, 'EUR',
                  '/tmp/x.jpg', 'fair_use_research', ?, ?, ?, ?, ?)
        """,
        (sid, f"ebay_{sid}", target_eurio_id, listing_title,
         country, year, listing_price,
         int(is_lot_suspected), run_id,
         route_decision, route_reason, raw),
    )


def _seed_canonical_image(
    conn, *, eurio_id: str, source: str, url: str | None,
    local_path: str | None, role: str = "obverse",
) -> None:
    conn.execute(
        """
        INSERT INTO coin_canonical_images
          (eurio_id, role, source, url, local_path)
        VALUES (?, ?, ?, ?, ?)
        """,
        (eurio_id, role, source, url, local_path),
    )


def _seed_quote(conn, *, eurio_id: str, run_id: str) -> None:
    conn.execute(
        """
        INSERT INTO coin_market_quotes (
          id, eurio_id, source, condition_normalized, currency,
          period_start, period_end, run_id
        ) VALUES (?, ?, 'ebay_browse', 'UNC', 'EUR',
                  '2026-05-01', '2026-05-31', ?)
        """,
        (uuid.uuid4().hex, eurio_id, run_id),
    )


@pytest.fixture()
def store_run(tmp_path):
    store = Store(tmp_path / "t.db")
    conn = store._connection()
    with start_run(conn, source="ebay", kind="run", filters={}, force=True) as run:
        yield store, conn, run.run_id


# ── Tests : _run_groups + summary ─────────────────────────────────────────


def test_run_groups_404_when_unknown(store_run):
    _, conn, _ = store_run
    with pytest.raises(HTTPException) as exc:
        _run_groups(conn, run_id="ghost")
    assert exc.value.status_code == 404


def test_run_groups_empty_run(store_run):
    _, conn, run_id = store_run
    groups, summary = _run_groups(conn, run_id=run_id)
    assert groups == []
    assert summary.n_groups == 0
    assert summary.total_listings == 0
    assert summary.total_unmatched == 0
    assert summary.total_quotes == 0


def test_run_groups_single_group_single_eurio(store_run):
    _, conn, run_id = store_run
    _seed_coin(conn, eurio_id="at-2005-foo", country="AT", year=2005)
    _seed_source_image(conn, sid="s1", run_id=run_id,
                       country="AT", year=2005, target_eurio_id="at-2005-foo",
                       route_decision="review_single",
                       route_reason="single_unmatched")
    _seed_source_image(conn, sid="s2", run_id=run_id,
                       country="AT", year=2005, target_eurio_id="at-2005-foo",
                       route_decision="review_lot",
                       route_reason="is_lot_suspected",
                       is_lot_suspected=True)
    _seed_source_image(conn, sid="s3", run_id=run_id,
                       country="AT", year=2005, target_eurio_id="at-2005-foo",
                       route_decision="pending",
                       route_reason="no_crops_yet")
    _seed_quote(conn, eurio_id="at-2005-foo", run_id=run_id)

    groups, summary = _run_groups(conn, run_id=run_id)
    assert len(groups) == 1
    g = groups[0]
    assert g.country == "AT"
    assert g.year == 2005
    assert g.denomination == 2.0
    assert g.target_eurio_ids == ["at-2005-foo"]
    assert g.total_listings == 3
    assert g.n_unmatched == 0
    assert g.n_pending == 1
    assert g.n_review_single == 1
    assert g.n_review_lot == 1
    assert g.n_quotes == 1

    # drops triés par (decision, reason) ; pas de bucket "matcher/unmatched"
    # vu que n_unmatched == 0.
    drop_ids = {d.node_id for d in g.drops}
    assert drop_ids == {
        "pending/no_crops_yet",
        "review_lot/is_lot_suspected",
        "review_single/single_unmatched",
    }
    counts = {d.node_id: d.count for d in g.drops}
    assert counts["pending/no_crops_yet"] == 1
    assert counts["review_lot/is_lot_suspected"] == 1
    assert counts["review_single/single_unmatched"] == 1

    # summary agrège correctement
    assert summary.n_groups == 1
    assert summary.total_listings == 3
    assert summary.total_unmatched == 0
    assert summary.total_pending == 1
    assert summary.total_quotes == 1


def test_run_groups_unmatched_bucket(store_run):
    """Listings avec target_eurio_id NULL → bucket 'matcher/unmatched'
    en tête des drops, et per-group n_unmatched > 0."""
    _, conn, run_id = store_run
    _seed_coin(conn, eurio_id="fr-2018-foo", country="FR", year=2018)
    _seed_source_image(conn, sid="m1", run_id=run_id,
                       country="FR", year=2018, target_eurio_id="fr-2018-foo",
                       route_decision="review_single",
                       route_reason="single_unmatched")
    _seed_source_image(conn, sid="u1", run_id=run_id,
                       country="FR", year=2018, target_eurio_id=None,
                       route_decision=None, route_reason=None)
    _seed_source_image(conn, sid="u2", run_id=run_id,
                       country="FR", year=2018, target_eurio_id=None,
                       route_decision=None, route_reason=None)

    groups, summary = _run_groups(conn, run_id=run_id)
    assert len(groups) == 1
    g = groups[0]
    assert g.n_unmatched == 2
    assert g.total_listings == 3
    assert g.drops[0].node_id == "matcher/unmatched"
    assert g.drops[0].count == 2
    assert g.drops[0].stage == "matcher"
    assert summary.total_unmatched == 2


def test_run_groups_multi_eurio_joint_issue(store_run):
    """(DE, 2007) avec 2 eurio_ids (joint-issue Treaty of Rome +
    Mecklenburg) doit retourner les 2 dans target_eurio_ids."""
    _, conn, run_id = store_run
    _seed_coin(conn, eurio_id="de-2007-rome", country="DE", year=2007)
    _seed_coin(conn, eurio_id="de-2007-mv", country="DE", year=2007)
    _seed_source_image(conn, sid="d1", run_id=run_id,
                       country="DE", year=2007, target_eurio_id="de-2007-rome")
    _seed_source_image(conn, sid="d2", run_id=run_id,
                       country="DE", year=2007, target_eurio_id="de-2007-mv")
    _seed_quote(conn, eurio_id="de-2007-rome", run_id=run_id)
    _seed_quote(conn, eurio_id="de-2007-mv", run_id=run_id)

    groups, _ = _run_groups(conn, run_id=run_id)
    assert len(groups) == 1
    g = groups[0]
    assert sorted(g.target_eurio_ids) == ["de-2007-mv", "de-2007-rome"]
    assert g.n_quotes == 2


def test_run_groups_standard_year_null(store_run):
    """Régression : un run 100 % standard (``listing_year`` NULL) doit remonter
    son groupe `(pays, NULL)`. L'ancien filtre `listing_year IS NOT NULL`
    masquait tout → bench vide sur les deep-links standard."""
    _, conn, run_id = store_run
    _seed_coin(conn, eurio_id="ad-2014-std", country="AD", year=2014,
               is_commemorative=False)
    _seed_source_image(conn, sid="s1", run_id=run_id, country="AD", year=None,
                       target_eurio_id="ad-2014-std", route_decision="pending",
                       route_reason="no_crops_yet")
    _seed_source_image(conn, sid="s2", run_id=run_id, country="AD", year=None,
                       target_eurio_id="ad-2014-std",
                       route_decision="review_single", route_reason="single_unmatched")

    groups, summary = _run_groups(conn, run_id=run_id)
    assert summary.n_groups == 1
    assert summary.total_listings == 2
    g = groups[0]
    assert g.year is None
    assert g.country == "AD"
    assert g.group_id == "AD-std-2.0"
    assert g.target_eurio_ids == ["ad-2014-std"]
    # Drops calculés malgré le year NULL (sous-requêtes en IS NULL).
    assert {d.node_id for d in g.drops} == {
        "pending/no_crops_yet", "review_single/single_unmatched",
    }


# ── Tests : _run_listings (drill) ─────────────────────────────────────────


def test_listings_filter_by_route_decision(store_run):
    _, conn, run_id = store_run
    _seed_coin(conn, eurio_id="at-2005-foo", country="AT", year=2005)
    _seed_source_image(conn, sid="a", run_id=run_id,
                       country="AT", year=2005, target_eurio_id="at-2005-foo",
                       route_decision="review_single",
                       route_reason="single_unmatched")
    _seed_source_image(conn, sid="b", run_id=run_id,
                       country="AT", year=2005, target_eurio_id="at-2005-foo",
                       route_decision="pending",
                       route_reason="no_crops_yet")

    ls, total = _run_listings(
        conn, run_id, country="AT", year=2005,
        eurio_id=None, route_decision="review_single", route_reason=None,
        unmatched_only=False, limit=100, offset=0,
    )
    assert total == 1
    assert ls[0].source_image_id == "a"
    assert ls[0].route_decision == "review_single"


def test_listings_filter_by_eurio_id(store_run):
    """Deep-link funnel (§C3b) : deux commémos-sœurs partagent la maille
    (pays, année) du bench ; `eurio_id` doit discriminer une seule pièce."""
    _, conn, run_id = store_run
    _seed_coin(conn, eurio_id="it-2016-plautus", country="IT", year=2016)
    _seed_coin(conn, eurio_id="it-2016-donatello", country="IT", year=2016)
    _seed_source_image(conn, sid="p1", run_id=run_id, country="IT", year=2016,
                       target_eurio_id="it-2016-plautus")
    _seed_source_image(conn, sid="p2", run_id=run_id, country="IT", year=2016,
                       target_eurio_id="it-2016-plautus")
    _seed_source_image(conn, sid="d1", run_id=run_id, country="IT", year=2016,
                       target_eurio_id="it-2016-donatello")

    ls, total = _run_listings(
        conn, run_id, country="IT", year=2016,
        eurio_id="it-2016-plautus", route_decision=None, route_reason=None,
        unmatched_only=False, limit=100, offset=0,
    )
    assert total == 2
    assert {l.source_image_id for l in ls} == {"p1", "p2"}
    assert all(l.target_eurio_id == "it-2016-plautus" for l in ls)


def test_listings_unmatched_only(store_run):
    _, conn, run_id = store_run
    _seed_source_image(conn, sid="m", run_id=run_id,
                       country="FR", year=2018, target_eurio_id="fr-2018-x",
                       route_decision="review_single")
    _seed_source_image(conn, sid="u", run_id=run_id,
                       country="FR", year=2018, target_eurio_id=None,
                       route_decision=None, route_reason=None)

    ls, total = _run_listings(
        conn, run_id, country="FR", year=2018,
        eurio_id=None, route_decision=None, route_reason=None,
        unmatched_only=True, limit=100, offset=0,
    )
    assert total == 1
    assert ls[0].source_image_id == "u"
    assert ls[0].target_eurio_id is None


def test_listings_pagination(store_run):
    _, conn, run_id = store_run
    for i in range(7):
        _seed_source_image(conn, sid=f"x{i}", run_id=run_id,
                           country="ES", year=2016,
                           target_eurio_id="es-2016-foo",
                           route_decision="pending",
                           route_reason="no_crops_yet")
    ls1, total = _run_listings(
        conn, run_id, country="ES", year=2016, eurio_id=None,
        route_decision=None, route_reason=None,
        unmatched_only=False, limit=3, offset=0,
    )
    ls2, _ = _run_listings(
        conn, run_id, country="ES", year=2016, eurio_id=None,
        route_decision=None, route_reason=None,
        unmatched_only=False, limit=3, offset=3,
    )
    assert total == 7
    assert len(ls1) == 3
    assert len(ls2) == 3
    # Pas de chevauchement
    assert not (set(l.source_image_id for l in ls1)
                & set(l.source_image_id for l in ls2))


def test_listings_image_url_extracted_from_payload(store_run):
    _, conn, run_id = store_run
    _seed_source_image(
        conn, sid="img", run_id=run_id,
        country="AT", year=2005, target_eurio_id="at-2005-foo",
        image_url="https://i.ebayimg.com/foo/s-l1600.jpg",
    )
    ls, _ = _run_listings(
        conn, run_id, country="AT", year=2005, eurio_id=None,
        route_decision=None, route_reason=None,
        unmatched_only=False, limit=10, offset=0,
    )
    assert ls[0].image_url == "https://i.ebayimg.com/foo/s-l1600.jpg"


# ── Tests : helpers d'image ───────────────────────────────────────────────


def test_canonical_obverse_url_prefers_numista(store_run):
    _, conn, _ = store_run
    _seed_coin(conn, eurio_id="fi-2017-foo", country="FI", year=2017)
    # 2 rows : BCE local + Numista URL → on doit avoir l'URL Numista
    _seed_canonical_image(conn, eurio_id="fi-2017-foo", source="bce_official",
                          url=None, local_path="ml/canonical/bce.webp")
    _seed_canonical_image(conn, eurio_id="fi-2017-foo", source="numista_api",
                          url="https://en.numista.com/coin.jpg",
                          local_path=None)
    assert (_canonical_obverse_url(conn, "fi-2017-foo")
            == "https://en.numista.com/coin.jpg")


def test_canonical_obverse_url_falls_back_to_local(store_run):
    _, conn, _ = store_run
    _seed_coin(conn, eurio_id="fi-2017-foo", country="FI", year=2017)
    _seed_canonical_image(conn, eurio_id="fi-2017-foo", source="bce_official",
                          url=None, local_path="ml/canonical/bce.webp")
    assert (_canonical_obverse_url(conn, "fi-2017-foo")
            == "/referential/canonical/fi-2017-foo/obverse?source=bce_official")


def test_canonical_obverse_url_none_when_missing(store_run):
    _, conn, _ = store_run
    _seed_coin(conn, eurio_id="orphan", country="AT", year=2005)
    assert _canonical_obverse_url(conn, "orphan") is None


def test_listing_image_url_extraction():
    assert _listing_image_url(None) is None
    assert _listing_image_url("not-json") is None
    assert _listing_image_url('{"image_url": null}') is None
    assert _listing_image_url('{"image_url": "https://x.jpg"}') == "https://x.jpg"


# ── Tests : _coin_context ─────────────────────────────────────────────────


def test_coin_context_returns_none_when_missing(store_run):
    _, conn, _ = store_run
    assert _coin_context(conn, "ghost") is None


def test_coin_context_includes_canonical_url(store_run):
    """Le contexte coin doit récupérer l'obverse_url via
    coin_canonical_images, pas via raw_payload_json."""
    _, conn, _ = store_run
    _seed_coin(conn, eurio_id="at-2005-foo", country="AT", year=2005,
               theme="Austrian Treaty")
    _seed_canonical_image(conn, eurio_id="at-2005-foo", source="numista_api",
                          url="https://numista.example/at.jpg",
                          local_path=None)
    ctx = _coin_context(conn, "at-2005-foo")
    assert ctx is not None
    assert ctx.obverse_url == "https://numista.example/at.jpg"
    assert ctx.country == "AT"
    assert ctx.year == 2005
    assert ctx.theme == "Austrian Treaty"
