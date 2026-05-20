"""ローカライズ戦略の判定ユーティリティ.

YouTube Analytics の国別 views と公開された国別 CPM 参考値を組み合わせて、
``supported_languages`` 見直しのための言語別 ROI を推定する。

参考 CPM の出典 (2026 Q1):
- https://upgrowth.in/youtube-cpm-by-country-global-comparison-2026/ (2026-02-21)
- https://www.lenostube.com/en/youtube-cpm-rpm-rates/ (2026-04-02)
- https://fluxnote.io/guides/highest-paying-youtube-countries-2026 (2026-03-06)

このモジュールが出す値は **参考推定** であり、実 AdSense 値とは乖離する。
半年ごとに ``COUNTRY_CPM_USD`` を見直すこと。
"""

from __future__ import annotations

from typing import Mapping

# ISO 3166-1 alpha-2 → YouTube 公式言語コード (BCP-47 寄せ)
# 多言語国 (CH/CA/SG/IN 等) は最も視聴ボリュームの大きい主要言語に寄せる。
COUNTRY_TO_PRIMARY_LANGUAGE: dict[str, str] = {
    "US": "en",
    "GB": "en",
    "AU": "en",
    "CA": "en",
    "NZ": "en",
    "IE": "en",
    "DE": "de",
    "AT": "de",
    "CH": "de",
    "JP": "ja",
    "KR": "ko",
    "ES": "es",
    "MX": "es",
    "BR": "pt",
    "PT": "pt",
    "FR": "fr",
    "IN": "hi",
    "HK": "zh-HK",
    "TW": "zh-TW",
    "CN": "zh-CN",
    "SG": "zh-CN",
    "IL": "he",
    "NO": "no",
    "SE": "sv",
    "FI": "fi",
    "DK": "da",
    "IT": "it",
    "NL": "nl",
}

# 国別参考 CPM (USD). レンジ提示の国は中央値を採用 (FR/KR = 2-5 USD の中央値 3.5)。
COUNTRY_CPM_USD: dict[str, float] = {
    "AU": 36.21,
    "US": 32.75,
    "CA": 29.15,
    "NZ": 28.15,
    "GB": 24.00,
    "CH": 23.13,
    "DE": 22.00,
    "NO": 20.17,
    "IE": 19.50,
    "SG": 18.28,
    "DK": 17.49,
    "HK": 17.23,
    "AT": 16.86,
    "SE": 16.50,
    "FI": 15.80,
    "ES": 14.22,
    "IL": 14.08,
    "JP": 10.53,
    "PT": 10.32,
    "FR": 3.50,
    "KR": 3.50,
    "BR": 1.64,
    "MX": 1.41,
    "IN": 0.83,
}

# 未登録国フォールバック CPM (USD). lenostube 公開値の world median 相当。
DEFAULT_CPM_FALLBACK_USD: float = 5.0

# 未登録国を集約する仮想言語コード。
OTHER_LANGUAGE_BUCKET: str = "other"


def aggregate_by_language(countries: Mapping[str, Mapping[str, float]]) -> dict[str, dict]:
    """国別データを言語別に集約する.

    Args:
        countries: ``get_country_analytics()`` の ``"countries"`` セクション形式。
            キーが ISO 国コード、値が ``{"views": int, ...}`` の dict。

    Returns:
        ``{lang: {views, country_count, top_countries: [(country, views), ...]}}``。
        未マッピング国は ``OTHER_LANGUAGE_BUCKET`` バケットに集約される。
    """
    by_lang: dict[str, dict] = {}
    for country, data in countries.items():
        lang = COUNTRY_TO_PRIMARY_LANGUAGE.get(country, OTHER_LANGUAGE_BUCKET)
        views = int(data.get("views", 0) or 0)
        bucket = by_lang.setdefault(
            lang,
            {"views": 0, "country_count": 0, "top_countries": []},
        )
        bucket["views"] += views
        bucket["country_count"] += 1
        bucket["top_countries"].append((country, views))

    total_views = sum(b["views"] for b in by_lang.values())
    for bucket in by_lang.values():
        bucket["view_share_percent"] = (
            round(bucket["views"] / total_views * 100, 2) if total_views > 0 else 0.0
        )
        bucket["top_countries"].sort(key=lambda pair: pair[1], reverse=True)
    return by_lang


def compute_estimated_revenue(
    countries: Mapping[str, Mapping[str, float]],
    by_language: Mapping[str, dict],
) -> dict[str, float]:
    """言語別の推定収益 (USD) を計算する.

    国別に ``views × CPM`` を積み上げ、その国の主要言語バケットに合算する。
    未登録国は ``DEFAULT_CPM_FALLBACK_USD`` を適用し ``OTHER_LANGUAGE_BUCKET`` に寄せる。

    Args:
        countries: ``get_country_analytics()`` の ``"countries"`` セクション。
        by_language: ``aggregate_by_language()`` の戻り値。集計対象言語の特定に使う。

    Returns:
        ``{lang: estimated_revenue_usd}``。``by_language`` の全キーを含む。
    """
    revenue: dict[str, float] = {lang: 0.0 for lang in by_language}
    for country, data in countries.items():
        lang = COUNTRY_TO_PRIMARY_LANGUAGE.get(country, OTHER_LANGUAGE_BUCKET)
        cpm = COUNTRY_CPM_USD.get(country, DEFAULT_CPM_FALLBACK_USD)
        views = int(data.get("views", 0) or 0)
        revenue[lang] = revenue.get(lang, 0.0) + views / 1000.0 * cpm
    return {lang: round(value, 2) for lang, value in revenue.items()}


def recommend_supported_languages(
    by_language: Mapping[str, dict],
    estimated_revenue: Mapping[str, float],
    current: list[str],
    keep_floor: float = 0.5,
    add_floor: float = 1.0,
) -> dict:
    """``supported_languages`` の追加・維持・削除候補を返す.

    Args:
        by_language: ``aggregate_by_language()`` の戻り値。
        estimated_revenue: ``compute_estimated_revenue()`` の戻り値。
        current: 現在の ``supported_languages``。
        keep_floor: 現状維持判定の view_share % 下限 (default 0.5)。
        add_floor: 新規追加判定の view_share % 下限 (default 1.0)。

    Returns:
        ``{"add": [...], "keep": [...], "remove": [...], "rationale": [...]}``。
        ``add`` / ``keep`` / ``remove`` はそれぞれ言語コード列、``rationale``
        は人間可読の説明文字列リスト。``OTHER_LANGUAGE_BUCKET`` は推奨対象外。
    """
    current_set = set(current)
    candidates: list[tuple[str, float, float]] = [
        (lang, bucket["view_share_percent"], estimated_revenue.get(lang, 0.0))
        for lang, bucket in by_language.items()
        if lang != OTHER_LANGUAGE_BUCKET
    ]
    candidates.sort(key=lambda triple: triple[2], reverse=True)

    add: list[str] = []
    keep: list[str] = []
    remove: list[str] = []
    rationale: list[str] = []

    for lang, share, revenue in candidates:
        if lang in current_set:
            if share >= keep_floor:
                keep.append(lang)
            else:
                remove.append(lang)
                rationale.append(
                    f"{lang}: view_share {share}% が keep_floor {keep_floor}% を下回るため削除候補"
                )
        else:
            if share >= add_floor:
                add.append(lang)
                rationale.append(
                    f"{lang}: view_share {share}% / est. revenue ${revenue} で add_floor {add_floor}% を超過、追加推奨"
                )

    # 現在 supported だが Analytics に出てこない言語は data なしで保持判定不能。
    # 「データなし」として rationale に明示し、remove ではなく keep に残す。
    seen_langs = {lang for lang, _, _ in candidates}
    for lang in current:
        if lang not in seen_langs and lang not in keep and lang not in remove:
            keep.append(lang)
            rationale.append(f"{lang}: 過去 90 日の views データなし。判定保留")

    return {
        "add": add,
        "keep": keep,
        "remove": remove,
        "rationale": rationale,
    }
