"""Lightweight stdlib tests for the referential helpers and parsers.

Run with: python ml/test_eurio_referential.py
Exits non-zero on first failure. No pytest, no fixtures.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bootstrap_circulation import parse_volume_cell
from bootstrap_circulation_de import parse_de_value
from eurio_referential import (
    compute_eurio_id,
    format_face_value,
    parse_volume,
    slugify,
)
from matching import best_slug_match, candidates_for, index_referential, slug_score
from scrape_lmdlp import (
    extract_country_iso2,
    extract_mintage,
    extract_price_eur,
    extract_theme_slug,
    extract_year,
    is_single_commemo,
)
from scrape_monnaiedeparis import (
    extract_availability,
    extract_product_jsonld,
    extract_sku_from_image,
    extract_theme_slug as mdp_extract_theme_slug,
    filter_coin_urls,
)
from scrape_monnaiedeparis import extract_price_eur as mdp_extract_price_eur
from scrape_ebay import (
    _theme_keywords,
    accept_listing,
    build_search_query,
    listing_weight,
    title_matches_theme,
    weighted_quantile,
)
from review_core import ReviewGroup, build_groups, candidate_preview, enrich_lmdlp, mark_group_resolved


class TestSlugify(unittest.TestCase):
    def test_basic_latin(self):
        self.assertEqual(slugify("Treaty of Rome"), "treaty-of-rome")

    def test_diacritics(self):
        self.assertEqual(slugify("Élysée Treaty"), "elysee-treaty")
        self.assertEqual(slugify("Università di Liège"), "universita-di-liege")

    def test_greek(self):
        self.assertEqual(
            slugify("Ολυμπιακοί Αγώνες Αθήνα 2004"),
            "olympiakoi-agones-athina-2004",
        )

    def test_cyrillic(self):
        self.assertEqual(
            slugify("Кирилица и глаголица"),
            "kirilitsa-i-glagolitsa",
        )

    def test_maltese_h_with_dot(self):
        # Ħal must transliterate to Hal, not be stripped.
        self.assertEqual(
            slugify("Hypogée de Ħal-Saflieni"),
            "hypogee-de-hal-saflieni",
        )
        self.assertEqual(slugify("Ħaġar Qim"), "hagar-qim")
        self.assertEqual(slugify("Ta' Ħaġrat Temples"), "ta-hagrat-temples")

    def test_apostrophes(self):
        self.assertEqual(slugify("Children's games"), "childrens-games")
        self.assertEqual(slugify("Children\u2019s games"), "childrens-games")

    def test_dashes(self):
        # en/em dashes become spaces, not collapsed.
        self.assertEqual(slugify("Andorra\u2013EU relations"), "andorra-eu-relations")
        self.assertEqual(slugify("foo \u2014 bar"), "foo-bar")

    def test_truncation_word_boundary(self):
        long = "200 years since the start of regular stagecoaches Vienna Bratislava"
        result = slugify(long, max_len=60)
        self.assertLessEqual(len(result), 60)
        # Must end on a word boundary (not mid-word).
        self.assertFalse(result.endswith("-"))
        self.assertTrue(all(c.isalnum() or c == "-" for c in result))

    def test_empty(self):
        self.assertEqual(slugify(""), "")
        self.assertEqual(slugify(None), "")


class TestComputeEurioId(unittest.TestCase):
    def test_2eur_commemorative(self):
        self.assertEqual(
            compute_eurio_id("HR", 2025, 2.0, "amphitheatre-pula"),
            "hr-2025-2eur-amphitheatre-pula",
        )

    def test_circulation_50c(self):
        self.assertEqual(
            compute_eurio_id("FR", 2020, 0.50, "standard"),
            "fr-2020-50c-standard",
        )

    def test_lowercase_country(self):
        self.assertEqual(
            compute_eurio_id("de", 2022, 2.0, "erasmus"),
            "de-2022-2eur-erasmus",
        )

    def test_eu_pseudo_country(self):
        self.assertEqual(
            compute_eurio_id("eu", 2022, 2.0, "erasmus"),
            "eu-2022-2eur-erasmus",
        )

    def test_invalid_face_value(self):
        with self.assertRaises(ValueError):
            compute_eurio_id("FR", 2020, 3.0, "standard")


class TestFormatFaceValue(unittest.TestCase):
    def test_all_denoms(self):
        cases = {
            0.01: "1c",
            0.02: "2c",
            0.05: "5c",
            0.10: "10c",
            0.20: "20c",
            0.50: "50c",
            1.00: "1eur",
            2.00: "2eur",
        }
        for face, code in cases.items():
            self.assertEqual(format_face_value(face), code)


class TestParseVolume(unittest.TestCase):
    def test_european_with_commas(self):
        self.assertEqual(parse_volume("510,000 coins"), 510000)

    def test_european_with_thin_space(self):
        self.assertEqual(parse_volume("36\u202f771\u202f000 coins"), 36771000)

    def test_european_with_nbsp(self):
        self.assertEqual(parse_volume("794\u00a0066\u00a0000"), 794066000)

    def test_empty(self):
        self.assertIsNone(parse_volume(""))
        self.assertIsNone(parse_volume("unknown"))


class TestParseVolumeCell(unittest.TestCase):
    def test_european_commas(self):
        self.assertEqual(parse_volume_cell("235,250,387"), 235250387)

    def test_european_spaces(self):
        self.assertEqual(parse_volume_cell("794 066 000"), 794066000)

    def test_us_compact_millions(self):
        self.assertEqual(parse_volume_cell("800.0"), 800_000_000)
        self.assertEqual(parse_volume_cell("50.7"), 50_700_000)

    def test_de_compact_millions(self):
        self.assertEqual(parse_volume_cell("60,00"), 60_000_000)
        self.assertEqual(parse_volume_cell("124,3"), 124_300_000)

    def test_specimen_tokens(self):
        for tok in ("s", "—", "-", "N/a", "n/a", ""):
            self.assertIsNone(parse_volume_cell(tok))

    def test_footnote_strip(self):
        self.assertEqual(parse_volume_cell("60,00[5]"), 60_000_000)

    def test_compact_millions_guard(self):
        # 99999.9 would silently become 99G coins — implausible, must reject.
        self.assertIsNone(parse_volume_cell("99999.9"))


class TestParseDeValue(unittest.TestCase):
    def test_german_thousands(self):
        self.assertEqual(parse_de_value("800.000.000"), 800_000_000)
        self.assertEqual(parse_de_value("1.234"), 1234)

    def test_dashes(self):
        self.assertIsNone(parse_de_value("–"))
        self.assertIsNone(parse_de_value("—"))
        self.assertIsNone(parse_de_value("-"))

    def test_with_nbsp(self):
        self.assertEqual(parse_de_value("800\u00a0000\u00a0000"), 800_000_000)


class TestLmdlpExtractors(unittest.TestCase):
    def _product(self, **overrides):
        base = {
            "id": 1,
            "name": "2 euros France 2022 \u2013 Erasmus UNC",
            "sku": "fr2022eraunc",
            "permalink": "https://lamonnaiedelapiece.com/fr/product/foo/",
            "is_purchasable": True,
            "is_in_stock": True,
            "categories": [
                {"name": "2022"},
                {"name": "France"},
            ],
            "attributes": [
                {"name": "Qualit\u00e9", "terms": [{"name": "UNC"}]},
                {"name": "Type", "terms": [{"name": "Pi\u00e8ce 2 euros comm\u00e9morative"}]},
                {"name": "Tirage", "terms": [{"name": "10.000.000"}]},
            ],
            "prices": {"price": "300", "currency_minor_unit": 2},
            "images": [{"src": "https://example.com/x.jpg"}],
        }
        base.update(overrides)
        return base

    def test_extract_country_french(self):
        self.assertEqual(extract_country_iso2(self._product()), "FR")

    def test_extract_country_micro_state(self):
        p = self._product(categories=[{"name": "2025"}, {"name": "Saint Marin"}])
        self.assertEqual(extract_country_iso2(p), "SM")

    def test_extract_year_from_category(self):
        self.assertEqual(extract_year(self._product()), 2022)

    def test_extract_year_fallback_sku(self):
        p = self._product(categories=[{"name": "France"}], sku="fr2024piunc")
        self.assertEqual(extract_year(p), 2024)

    def test_extract_price_eur(self):
        self.assertEqual(extract_price_eur(self._product()), 3.0)

    def test_extract_mintage_thousand_dots(self):
        self.assertEqual(extract_mintage(self._product()), 10_000_000)

    def test_extract_theme_slug_strips_quality(self):
        slug = extract_theme_slug(self._product())
        self.assertEqual(slug, "erasmus")

    def test_extract_theme_slug_handles_dash(self):
        p = self._product(name="2 euros Italie 2026 \u2013 Carlo Collodi Pinocchio BU FDC Coincard")
        self.assertEqual(extract_theme_slug(p), "carlo-collodi-pinocchio")

    def test_is_single_commemo_keeps_normal(self):
        keep, reason = is_single_commemo(self._product())
        self.assertTrue(keep, reason)

    def test_is_single_commemo_rejects_set(self):
        p = self._product(name="Coffret BU 2022")
        keep, reason = is_single_commemo(p)
        self.assertFalse(keep)

    def test_is_single_commemo_rejects_not_purchasable(self):
        p = self._product(is_purchasable=False)
        keep, _ = is_single_commemo(p)
        self.assertFalse(keep)

    def test_is_single_commemo_rejects_multipack_2x(self):
        p = self._product(name="2 x 2 euros Andorre 2023 \u2013 Solstice + Adhesion BU FDC Coincard")
        keep, reason = is_single_commemo(p)
        self.assertFalse(keep)
        self.assertEqual(reason, "multipack_prefix")

    def test_is_single_commemo_rejects_multipack_5x(self):
        p = self._product(name="5 x 2 euros France 2023 \u2013 Rugby BU FDC")
        keep, reason = is_single_commemo(p)
        self.assertFalse(keep)
        self.assertEqual(reason, "multipack_prefix")

    def test_is_single_commemo_rejects_plus_separator(self):
        p = self._product(name="2 euros Andorre 2023 \u2013 Solstice d'\u00e9t\u00e9 + Adh\u00e9sion ONU UNC")
        keep, reason = is_single_commemo(p)
        self.assertFalse(keep)
        self.assertEqual(reason, "plus_separator_bundle")

    def test_is_single_commemo_keeps_plus_without_surrounding_spaces(self):
        # '+' used as a Unicode bullet adjacent to text, e.g. "A+B", should still pass.
        # Real lmdlp products always use " + " with spaces when it's a bundle.
        p = self._product(name="2 euros France 2018 \u2013 C++ anniversary UNC")
        keep, _ = is_single_commemo(p)
        self.assertTrue(keep)


class TestSlugScore(unittest.TestCase):
    def test_token_coverage_dominates(self):
        # Source tokens fully present in candidate -> score >= coverage = 1.0
        s = slug_score("carlo-collodi-pinocchio", "pinocchio-200th-birthday-of-carlo-collodi")
        self.assertEqual(s, 1.0)

    def test_disjoint_low_score(self):
        s = slug_score("carlo-collodi-pinocchio", "800th-anniversary-of-the-death-of-francis-of-assisi")
        self.assertLess(s, 0.3)

    def test_french_to_english_partial(self):
        # 'francois-dassise' vs 'francis-of-assisi' shares chars but not tokens
        s = slug_score("francois-dassise", "francis-of-assisi")
        self.assertGreater(s, 0.3)

    def test_empty_inputs(self):
        self.assertEqual(slug_score("", "foo"), 0.0)
        self.assertEqual(slug_score("foo", ""), 0.0)


class TestCandidatesAndMatch(unittest.TestCase):
    def setUp(self):
        # Synthetic 3-entry referential
        self.ref = {
            "it-2026-2eur-pinocchio-200th-birthday-of-carlo-collodi": {
                "eurio_id": "it-2026-2eur-pinocchio-200th-birthday-of-carlo-collodi",
                "identity": {
                    "country": "IT", "year": 2026, "face_value": 2.0,
                    "is_commemorative": True, "national_variants": None,
                    "theme": "Pinocchio",
                },
            },
            "it-2026-2eur-800th-anniversary-of-the-death-of-francis-of-assisi": {
                "eurio_id": "it-2026-2eur-800th-anniversary-of-the-death-of-francis-of-assisi",
                "identity": {
                    "country": "IT", "year": 2026, "face_value": 2.0,
                    "is_commemorative": True, "national_variants": None,
                    "theme": "Francis of Assisi",
                },
            },
            "eu-2022-2eur-35-years-of-the-erasmus-programme": {
                "eurio_id": "eu-2022-2eur-35-years-of-the-erasmus-programme",
                "identity": {
                    "country": "eu", "year": 2022, "face_value": 2.0,
                    "is_commemorative": True,
                    "national_variants": ["FR", "DE", "IT"],
                    "theme": "Erasmus",
                },
            },
        }
        self.idx = index_referential(self.ref)

    def test_candidates_country_year(self):
        cands = candidates_for(self.idx, "IT", 2026)
        self.assertEqual(len(cands), 2)

    def test_candidates_include_joint_for_member_country(self):
        cands = candidates_for(self.idx, "FR", 2022)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["eurio_id"], "eu-2022-2eur-35-years-of-the-erasmus-programme")

    def test_candidates_exclude_joint_for_non_member(self):
        cands = candidates_for(self.idx, "BG", 2022)
        self.assertEqual(len(cands), 0)

    def test_best_slug_match_picks_pinocchio(self):
        cands = candidates_for(self.idx, "IT", 2026)
        best, score, runner, runner_score = best_slug_match("carlo-collodi-pinocchio", cands)
        self.assertEqual(best["eurio_id"], "it-2026-2eur-pinocchio-200th-birthday-of-carlo-collodi")
        self.assertEqual(score, 1.0)
        self.assertLess(runner_score, score)


class TestMdpExtractors(unittest.TestCase):
    def test_filter_coin_urls_accepts_commemo(self):
        urls = [
            "https://www.monnaiedeparis.fr/fr/erasmus-monnaie-de-2eur-commemorative-qualite-bu-millesime-2022",
            "https://www.monnaiedeparis.fr/fr/notre-dame-de-paris-monnaie-de-2eur-commemorative-qualite-bu-millesime-2025",
        ]
        out = filter_coin_urls(urls)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["year"], 2022)
        self.assertEqual(out[0]["quality_raw"], "bu")
        self.assertEqual(out[0]["theme_url_slug"], "erasmus")

    def test_filter_coin_urls_rejects_roll(self):
        urls = [
            "https://www.monnaiedeparis.fr/fr/notre-dame-de-paris-rouleau-de-25-monnaies-de-2eur-commemorative-qualite-fleur-de-coins-millesime"
        ]
        self.assertEqual(filter_coin_urls(urls), [])

    def test_filter_coin_urls_rejects_accessory(self):
        urls = [
            "https://www.monnaiedeparis.fr/fr/porte-cles-pour-piece-de-5eur-ou-2eur-courante-finition-argent-peut-accueillir-une-monnaie-de-29mm"
        ]
        self.assertEqual(filter_coin_urls(urls), [])

    def test_filter_coin_urls_rejects_missing_year(self):
        # URLs that were truncated in the sitemap
        urls = [
            "https://www.monnaiedeparis.fr/fr/musee-du-louvre-l-amour-et-psyche-a-demi-couchee-monnaie-de-2eur-commemorative-qualite-bu-millesime"
        ]
        self.assertEqual(filter_coin_urls(urls), [])

    def test_extract_product_jsonld_picks_product(self):
        html_text = (
            '<script type="application/ld+json">'
            '{"@context": "https://schema.org", "@type": "WebSite", "name": "x"}'
            '</script>'
            '<script type="application/ld+json">'
            '{"@context": "https://schema.org", "@type": "Product", "name": "Erasmus", '
            '"offers": {"price": 11, "priceCurrency": "EUR", '
            '"availability": "https://schema.org/OutOfStock"}}'
            '</script>'
        )
        ld = extract_product_jsonld(html_text)
        self.assertIsNotNone(ld)
        self.assertEqual(ld["name"], "Erasmus")

    def test_mdp_extract_price_eur(self):
        ld = {"offers": {"price": 24, "priceCurrency": "EUR"}}
        self.assertEqual(mdp_extract_price_eur(ld), 24.0)

    def test_extract_availability(self):
        ld = {"offers": {"availability": "https://schema.org/InStock"}}
        self.assertEqual(extract_availability(ld), "InStock")

    def test_extract_sku_from_image(self):
        ld = {"image": "https://www.monnaiedeparis.fr/media/catalog/product/C/o/Coincard_Erasmus_face_00af.png?suffix=1"}
        self.assertEqual(extract_sku_from_image(ld), "Coincard_Erasmus_face_00af")

    def test_extract_sku_from_image_none(self):
        self.assertIsNone(extract_sku_from_image({}))
        self.assertIsNone(extract_sku_from_image({"image": "https://example.com/random.jpg"}))

    def test_mdp_theme_slug_collapses_louvre_sub(self):
        meta = {"theme_url_slug": "musee-du-louvre-la-joconde"}
        ld = {"name": "Mus\u00e9e du Louvre - La Joconde"}
        slug = mdp_extract_theme_slug(meta, ld)
        self.assertEqual(slug, "musee-du-louvre")

    def test_mdp_theme_slug_prefers_short_name(self):
        # "Erasmus" (single token) should beat the longer url slug
        meta = {"theme_url_slug": "erasmus"}
        ld = {"name": "Erasmus"}
        self.assertEqual(mdp_extract_theme_slug(meta, ld), "erasmus")


class TestEbayScraper(unittest.TestCase):
    def _entry(self, eurio_id="de-2018-2eur-helmut-schmidt", iso2="DE", name_en="Germany", year=2018):
        return {
            "eurio_id": eurio_id,
            "identity": {
                "country": iso2,
                "country_name": name_en,
                "year": year,
                "face_value": 2.0,
                "is_commemorative": True,
            },
        }

    def test_theme_keywords_drops_stop_words(self):
        # 'of', 'the', 'years', 'since', 'birth' should be dropped
        kw = _theme_keywords("de-2018-2eur-100-years-since-the-birth-of-helmut-schmidt")
        self.assertIn("helmut", kw)
        self.assertIn("schmidt", kw)
        self.assertNotIn("years", kw)
        self.assertNotIn("birth", kw)

    def test_theme_keywords_drops_ordinals(self):
        kw = _theme_keywords("de-2006-2eur-holstentor-in-lubeck")
        self.assertIn("holstentor", kw)
        self.assertNotIn("in", kw)  # stop word

    def test_build_search_query_uses_french_country(self):
        entry = self._entry(iso2="DE", name_en="Germany", year=2018)
        q, aspect, tokens = build_search_query(entry)
        self.assertIn("Allemagne", q)
        self.assertIn("2018", q)
        self.assertIn("Année:{2018}", aspect)
        self.assertNotIn("Germany", q)

    def test_title_matches_theme(self):
        self.assertTrue(title_matches_theme("2 euros Allemagne Schmidt 2018", ["helmut", "schmidt"]))
        self.assertFalse(title_matches_theme("2 euros Allemagne Charlottenburg", ["helmut", "schmidt"]))
        # Empty theme tokens means we can't filter -> accept
        self.assertTrue(title_matches_theme("anything", []))

    def test_accept_listing_noise_title(self):
        row = {"title": "2 euros France 2022 BU FDC", "price": 15.0, "currency": "EUR"}
        ok, reason = accept_listing(row, 2.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "noise_title")

    def test_accept_listing_rejects_non_eur(self):
        row = {"title": "2 euro", "price": 5.0, "currency": "USD"}
        ok, reason = accept_listing(row, 2.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "non_eur")

    def test_accept_listing_rejects_below_face(self):
        row = {"title": "2 euro", "price": 0.5, "currency": "EUR"}
        ok, reason = accept_listing(row, 2.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "below_face")

    def test_accept_listing_rejects_extreme(self):
        row = {"title": "2 euro rare", "price": 2000.0, "currency": "EUR"}
        ok, reason = accept_listing(row, 2.0)
        self.assertFalse(ok)
        self.assertEqual(reason, "above_extreme")

    def test_accept_listing_ok(self):
        row = {"title": "2 euros Allemagne 2006 Holstentor", "price": 7.5, "currency": "EUR"}
        ok, reason = accept_listing(row, 2.0)
        self.assertTrue(ok)

    def test_weighted_quantile_uniform_weights(self):
        # With equal weights, behaves like a plain quantile
        values = [1, 2, 3, 4, 5]
        weights = [1, 1, 1, 1, 1]
        self.assertAlmostEqual(weighted_quantile(values, weights, 0.5), 3)
        self.assertAlmostEqual(weighted_quantile(values, weights, 0.25), 2)
        self.assertAlmostEqual(weighted_quantile(values, weights, 0.75), 4)

    def test_weighted_quantile_skewed(self):
        # Heavier weights near the low end -> median should shift down
        values = [1, 2, 3, 4, 5]
        weights = [10, 10, 1, 1, 1]
        self.assertEqual(weighted_quantile(values, weights, 0.5), 2)

    def test_weighted_quantile_empty(self):
        self.assertIsNone(weighted_quantile([], [], 0.5))

    def test_listing_weight_non_zero_for_new_seller(self):
        # A listing with 0 sold and no seller feedback should still get a
        # non-zero weight (0.05 floor) so it's not silently dropped.
        row = {"sold": 0, "origin_date": None, "seller_fb_pct": None}
        self.assertGreater(listing_weight(row), 0)

    def test_listing_weight_higher_for_seller_with_sales(self):
        hot = {"sold": 10, "origin_date": "2025-10-01T00:00:00Z", "seller_fb_pct": 99.5}
        cold = {"sold": 0, "origin_date": "2025-10-01T00:00:00Z", "seller_fb_pct": 99.5}
        self.assertGreater(listing_weight(hot), listing_weight(cold))


class TestReviewQueue(unittest.TestCase):
    def _queue_item(self, source="lmdlp", country="FR", year=2022, theme="erasmus", sku="fr2022eraunc", candidates=None):
        return {
            "source": source,
            "source_native_id": sku,
            "reason": "ambiguous_fuzzy",
            "candidates": candidates or [],
            "raw_payload": {
                "sku": sku,
                "name": "test",
                "country": country,
                "year": year,
                "theme_slug": theme,
                "permalink": f"https://example.com/{sku}",
            },
            "queued_at": "2026-04-13T00:00:00+00:00",
        }

    def test_build_groups_groups_by_theme(self):
        queue = [
            self._queue_item(sku="fr2022eraunc"),
            self._queue_item(sku="fr2022erabu"),
            self._queue_item(sku="fr2022erabe"),
            self._queue_item(country="DE", sku="de2022eraunc"),
        ]
        groups = build_groups(queue)
        self.assertEqual(len(groups), 2)
        fr_group = next(g for g in groups if g.country == "FR")
        self.assertEqual(len(fr_group.items), 3)
        self.assertEqual(fr_group.key, "lmdlp:FR:2022:erasmus")

    def test_build_groups_skips_resolved(self):
        items = [
            self._queue_item(sku="a"),
            self._queue_item(sku="b"),
        ]
        items[0]["resolved"] = True
        groups = build_groups(items)
        # The resolved item is filtered out; a new group is built around 'b' only
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].items), 1)
        self.assertEqual(groups[0].items[0]["source_native_id"], "b")

    def test_build_groups_source_filter(self):
        queue = [
            self._queue_item(source="lmdlp", sku="a"),
            self._queue_item(source="ebay", sku="b"),
        ]
        groups = build_groups(queue, source_filter="lmdlp")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].source, "lmdlp")

    def test_mark_group_resolved_stamps_all_items(self):
        items = [self._queue_item(sku="a"), self._queue_item(sku="b")]
        group = ReviewGroup(
            source="lmdlp", country="FR", year=2022, theme_slug="erasmus",
            items=items, candidates=["eu-2022-2eur-erasmus"],
        )
        mark_group_resolved(group, "pick", "eu-2022-2eur-erasmus")
        for it in items:
            self.assertTrue(it["resolved"])
            self.assertEqual(it["resolution"]["action"], "pick")
            self.assertEqual(it["resolution"]["eurio_id"], "eu-2022-2eur-erasmus")

    def test_enrich_lmdlp_appends_variants_and_dedupes(self):
        # Synthetic referential entry
        ref = {
            "fr-2022-2eur-test": {
                "eurio_id": "fr-2022-2eur-test",
                "identity": {"country": "FR", "year": 2022, "face_value": 2.0, "is_commemorative": True},
                "cross_refs": {"lmdlp_skus": ["existing_sku"]},
                "observations": {"lmdlp_variants": [{"sku": "existing_sku", "quality": "UNC"}]},
                "provenance": {"sources_used": ["wikipedia_commemo", "lmdlp"], "first_seen": "2026-01-01"},
            }
        }
        snapshot = [
            {
                "sku": "new_sku",
                "name": "Test new",
                "permalink": "https://example.com/new",
                "is_purchasable": True,
                "is_in_stock": True,
                "categories": [{"name": "2022"}, {"name": "France"}],
                "attributes": [{"name": "Qualit\u00e9", "terms": [{"name": "BU"}]}],
                "prices": {"price": "500", "currency_minor_unit": 2},
                "images": [{"src": "https://example.com/x.jpg"}],
            },
            {
                "sku": "existing_sku",
                "name": "Test existing",
                "permalink": "https://example.com/existing",
                "is_purchasable": True,
                "is_in_stock": True,
                "categories": [{"name": "2022"}, {"name": "France"}],
                "attributes": [{"name": "Qualit\u00e9", "terms": [{"name": "UNC"}]}],
                "prices": {"price": "300", "currency_minor_unit": 2},
                "images": [],
            },
        ]
        items = [{"source_native_id": "new_sku"}, {"source_native_id": "existing_sku"}]
        added = enrich_lmdlp(ref, "fr-2022-2eur-test", items, snapshot)
        self.assertEqual(added, 1)  # only the new sku, existing was deduped
        variants = ref["fr-2022-2eur-test"]["observations"]["lmdlp_variants"]
        self.assertEqual(len(variants), 2)
        skus = {v["sku"] for v in variants}
        self.assertEqual(skus, {"existing_sku", "new_sku"})

    def test_enrich_lmdlp_skips_missing_target(self):
        added = enrich_lmdlp({}, "nonexistent-id", [], [])
        self.assertEqual(added, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
