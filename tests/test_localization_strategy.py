"""utils/localization_strategy.py のユニットテスト."""

from __future__ import annotations

import pytest

from youtube_automation.utils.localization_strategy import (
    COUNTRY_CPM_USD,
    COUNTRY_TO_PRIMARY_LANGUAGE,
    DEFAULT_CPM_FALLBACK_USD,
    OTHER_LANGUAGE_BUCKET,
    aggregate_by_language,
    compute_estimated_revenue,
    recommend_supported_languages,
)


class TestTablesCompleteness:
    def test_country_keys_are_iso2_uppercase(self):
        for code in COUNTRY_TO_PRIMARY_LANGUAGE:
            assert len(code) == 2 and code.isupper(), code
        for code in COUNTRY_CPM_USD:
            assert len(code) == 2 and code.isupper(), code

    def test_cpm_keys_subset_of_language_map(self):
        cpm_only = set(COUNTRY_CPM_USD) - set(COUNTRY_TO_PRIMARY_LANGUAGE)
        assert cpm_only == set(), f"CPM 表のキーは言語マップにも登録すること: {cpm_only}"

    def test_cpm_values_positive(self):
        for code, cpm in COUNTRY_CPM_USD.items():
            assert cpm > 0, f"{code} CPM は正の値であること: {cpm}"

    def test_fallback_cpm_is_positive(self):
        assert DEFAULT_CPM_FALLBACK_USD > 0


class TestAggregateByLanguage:
    def test_groups_countries_into_language_buckets(self):
        countries = {
            "US": {"views": 100},
            "GB": {"views": 50},
            "JP": {"views": 30},
        }
        by_lang = aggregate_by_language(countries)
        assert by_lang["en"]["views"] == 150
        assert by_lang["en"]["country_count"] == 2
        assert by_lang["ja"]["views"] == 30

    def test_unmapped_country_goes_to_other(self):
        countries = {"ZW": {"views": 100}, "US": {"views": 50}}
        by_lang = aggregate_by_language(countries)
        assert OTHER_LANGUAGE_BUCKET in by_lang
        assert by_lang[OTHER_LANGUAGE_BUCKET]["views"] == 100

    def test_view_share_percent_sums_close_to_100(self):
        countries = {"US": {"views": 60}, "JP": {"views": 40}}
        by_lang = aggregate_by_language(countries)
        total = sum(b["view_share_percent"] for b in by_lang.values())
        assert total == pytest.approx(100.0, abs=0.01)

    def test_top_countries_sorted_descending(self):
        countries = {
            "US": {"views": 100},
            "GB": {"views": 200},
            "CA": {"views": 50},
        }
        by_lang = aggregate_by_language(countries)
        en_top = by_lang["en"]["top_countries"]
        assert [c for c, _ in en_top] == ["GB", "US", "CA"]

    def test_empty_input(self):
        assert aggregate_by_language({}) == {}


class TestComputeEstimatedRevenue:
    def test_uses_country_cpm_for_known_countries(self):
        countries = {"US": {"views": 1000}}
        by_lang = aggregate_by_language(countries)
        revenue = compute_estimated_revenue(countries, by_lang)
        expected = 1000 / 1000 * COUNTRY_CPM_USD["US"]
        assert revenue["en"] == pytest.approx(expected, abs=0.01)

    def test_uses_fallback_for_unmapped_countries(self):
        countries = {"ZW": {"views": 1000}}
        by_lang = aggregate_by_language(countries)
        revenue = compute_estimated_revenue(countries, by_lang)
        expected = 1000 / 1000 * DEFAULT_CPM_FALLBACK_USD
        assert revenue[OTHER_LANGUAGE_BUCKET] == pytest.approx(expected, abs=0.01)

    def test_aggregates_multi_country_languages(self):
        countries = {"US": {"views": 1000}, "GB": {"views": 1000}}
        by_lang = aggregate_by_language(countries)
        revenue = compute_estimated_revenue(countries, by_lang)
        expected = COUNTRY_CPM_USD["US"] + COUNTRY_CPM_USD["GB"]
        assert revenue["en"] == pytest.approx(expected, abs=0.01)


class TestRecommendSupportedLanguages:
    def test_adds_high_share_unsupported(self):
        countries = {"US": {"views": 5000}, "DE": {"views": 4000}, "JP": {"views": 1000}}
        by_lang = aggregate_by_language(countries)
        revenue = compute_estimated_revenue(countries, by_lang)
        rec = recommend_supported_languages(
            by_lang, revenue, current=["ja"], add_floor=1.0, keep_floor=0.5
        )
        assert "en" in rec["add"]
        assert "de" in rec["add"]
        assert "ja" in rec["keep"]

    def test_removes_low_share_supported(self):
        countries = {"US": {"views": 9990}, "KR": {"views": 10}}
        by_lang = aggregate_by_language(countries)
        revenue = compute_estimated_revenue(countries, by_lang)
        rec = recommend_supported_languages(
            by_lang, revenue, current=["ja", "ko"], add_floor=1.0, keep_floor=0.5
        )
        assert "ko" in rec["remove"]

    def test_other_bucket_excluded_from_add(self):
        countries = {"ZW": {"views": 5000}, "US": {"views": 5000}}
        by_lang = aggregate_by_language(countries)
        revenue = compute_estimated_revenue(countries, by_lang)
        rec = recommend_supported_languages(
            by_lang, revenue, current=["ja"], add_floor=1.0, keep_floor=0.5
        )
        assert OTHER_LANGUAGE_BUCKET not in rec["add"]
        assert OTHER_LANGUAGE_BUCKET not in rec["keep"]

    def test_current_lang_without_data_kept_with_rationale(self):
        countries = {"US": {"views": 1000}}
        by_lang = aggregate_by_language(countries)
        revenue = compute_estimated_revenue(countries, by_lang)
        rec = recommend_supported_languages(
            by_lang, revenue, current=["ja"], add_floor=1.0, keep_floor=0.5
        )
        assert "ja" in rec["keep"]
        assert any("ja" in note and "判定保留" in note for note in rec["rationale"])
