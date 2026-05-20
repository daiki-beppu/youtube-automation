#!/usr/bin/env python3
"""yt-localization-roi: 国別 views × 公開参考 CPM で言語別 ROI を推定する CLI.

過去 N 日の YouTube Analytics 国別データに公開参考 CPM テーブルを掛けて
言語別の推定収益を算出し、``supported_languages`` の見直し判断材料を
Markdown レポートとして出力する。

推定収益は公開参考 CPM の単純積算であり、実 AdSense 値とは乖離する。
判断補助の参考値として扱うこと。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from youtube_automation.utils.analytics_collector import YouTubeAnalyticsCollector
from youtube_automation.utils.config import channel_dir as _channel_dir
from youtube_automation.utils.config import load_config
from youtube_automation.utils.exceptions import ConfigError, YouTubeAPIError
from youtube_automation.utils.localization_strategy import (
    COUNTRY_CPM_USD,
    COUNTRY_TO_PRIMARY_LANGUAGE,
    DEFAULT_CPM_FALLBACK_USD,
    OTHER_LANGUAGE_BUCKET,
    aggregate_by_language,
    compute_estimated_revenue,
    recommend_supported_languages,
)

logger = logging.getLogger(__name__)


def build_analysis(
    countries: dict,
    current_supported: list[str],
    days: int,
    keep_floor: float,
    add_floor: float,
) -> dict:
    """国別 analytics dict から構造化分析結果を組み立てる."""
    by_language = aggregate_by_language(countries)
    estimated_revenue = compute_estimated_revenue(countries, by_language)
    recommended = recommend_supported_languages(
        by_language,
        estimated_revenue,
        current_supported,
        keep_floor=keep_floor,
        add_floor=add_floor,
    )

    country_rows = []
    for country, data in countries.items():
        lang = COUNTRY_TO_PRIMARY_LANGUAGE.get(country, OTHER_LANGUAGE_BUCKET)
        cpm = COUNTRY_CPM_USD.get(country, DEFAULT_CPM_FALLBACK_USD)
        views = int(data.get("views", 0) or 0)
        country_rows.append(
            {
                "country": country,
                "views": views,
                "view_share_percent": float(data.get("view_share_percent", 0.0) or 0.0),
                "language": lang,
                "cpm_usd": cpm,
                "estimated_revenue_usd": round(views / 1000.0 * cpm, 2),
                "cpm_is_fallback": country not in COUNTRY_CPM_USD,
            }
        )
    country_rows.sort(key=lambda r: r["views"], reverse=True)

    language_rows = [
        {
            "language": lang,
            "views": bucket["views"],
            "view_share_percent": bucket["view_share_percent"],
            "country_count": bucket["country_count"],
            "top_countries": [{"country": c, "views": v} for c, v in bucket["top_countries"][:5]],
            "estimated_revenue_usd": estimated_revenue.get(lang, 0.0),
        }
        for lang, bucket in by_language.items()
    ]
    language_rows.sort(key=lambda r: r["estimated_revenue_usd"], reverse=True)

    return {
        "generated_at": datetime.now().isoformat(),
        "window_days": days,
        "current_supported_languages": list(current_supported),
        "countries": country_rows,
        "languages": language_rows,
        "recommended": recommended,
        "thresholds": {"keep_floor": keep_floor, "add_floor": add_floor},
    }


def render_markdown(analysis: dict) -> str:
    """構造化分析結果から Markdown レポート文字列を生成する."""
    lines: list[str] = []
    lines.append("# Localization ROI Report")
    lines.append("")
    lines.append(f"- **Generated**: {analysis['generated_at']}")
    lines.append(f"- **Period**: {analysis['window_days']} days")
    lines.append(f"- **Current supported_languages**: {', '.join(analysis['current_supported_languages']) or '(none)'}")
    lines.append("")
    lines.append("## 国別 views (Top 30)")
    lines.append("")
    lines.append("| Country | Views | Share % | Lang | CPM (USD) | Est. Revenue (USD) |")
    lines.append("|---|---:|---:|---|---:|---:|")
    for row in analysis["countries"][:30]:
        cpm_label = f"{row['cpm_usd']:.2f}"
        if row["cpm_is_fallback"]:
            cpm_label += "*"
        lines.append(
            f"| {row['country']} | {row['views']:,} | {row['view_share_percent']:.2f} | "
            f"{row['language']} | {cpm_label} | {row['estimated_revenue_usd']:.2f} |"
        )
    lines.append("")
    lines.append("`*` は未登録国のフォールバック CPM 適用を示す。")
    lines.append("")

    lines.append("## 言語別集計 (estimated revenue 降順)")
    lines.append("")
    lines.append("| Lang | Views | Share % | Est. Revenue (USD) | Countries | Top Countries |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for row in analysis["languages"]:
        top = ", ".join(f"{c['country']}({c['views']:,})" for c in row["top_countries"])
        lines.append(
            f"| {row['language']} | {row['views']:,} | {row['view_share_percent']:.2f} | "
            f"{row['estimated_revenue_usd']:.2f} | {row['country_count']} | {top} |"
        )
    lines.append("")

    rec = analysis["recommended"]
    th = analysis["thresholds"]
    lines.append("## 推奨 supported_languages")
    lines.append("")
    lines.append(f"- **Add** (share ≥ {th['add_floor']}%): {', '.join(rec['add']) or '(なし)'}")
    lines.append(f"- **Keep** (share ≥ {th['keep_floor']}%): {', '.join(rec['keep']) or '(なし)'}")
    lines.append(f"- **Consider removing**: {', '.join(rec['remove']) or '(なし)'}")
    lines.append("")
    if rec["rationale"]:
        lines.append("### Rationale")
        lines.append("")
        for note in rec["rationale"]:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("## 注記")
    lines.append("")
    lines.append("- Est. Revenue は公開参考 CPM × views/1000 の単純積算であり、実 AdSense 値とは乖離する")
    lines.append("- 同言語でも国別 CPM 差が大きい (ES vs MX で 10x、PT vs BR で 6x)")
    lines.append("- CPM 出典: upgrowth.in (2026-02-21), lenostube.com (2026-04-02), fluxnote.io (2026-03-06)")
    return "\n".join(lines) + "\n"


def _default_output_path(channel_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    return channel_dir / "data" / "localization_roi" / f"{stamp}.md"


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="国別 views × 公開参考 CPM で言語別 ROI を推定し supported_languages の見直し材料を生成"
    )
    parser.add_argument("--days", type=int, default=90, help="過去日数 (default: 90)")
    parser.add_argument("--max-countries", type=int, default=30, help="取得する国数の上限 (default: 30)")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Markdown 出力先 (default: <channel_dir>/data/localization_roi/<YYYY-MM-DD>.md)",
    )
    parser.add_argument("--json", action="store_true", help="stdout に構造化 JSON のみ出力 (default)")
    parser.add_argument("--text", action="store_true", help="stdout に人間向け要約を出力")
    parser.add_argument(
        "--keep-floor",
        type=float,
        default=0.5,
        help="現状維持判定の view_share %% 下限 (default: 0.5)",
    )
    parser.add_argument(
        "--add-floor",
        type=float,
        default=1.0,
        help="新規追加判定の view_share %% 下限 (default: 1.0)",
    )

    args = parser.parse_args()

    try:
        config = load_config()
        current_supported = list(config.localizations.supported_languages)

        collector = YouTubeAnalyticsCollector()
        collector.initialize()

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

        result = collector.get_country_analytics(start_date, end_date, max_countries=args.max_countries)
        if "error" in result:
            raise YouTubeAPIError(f"get_country_analytics 失敗: {result['error']}")
        countries = result.get("countries", {}) or {}
        if not countries:
            raise YouTubeAPIError("国別 views が空でした。期間設定または API クォータを確認してください")

        analysis = build_analysis(
            countries,
            current_supported,
            days=args.days,
            keep_floor=args.keep_floor,
            add_floor=args.add_floor,
        )

        output_path = args.output or _default_output_path(_channel_dir())
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_markdown(analysis), encoding="utf-8")
        analysis["output_path"] = str(output_path)

        if args.text:
            print(f"📄 レポート: {output_path}")
            rec = analysis["recommended"]
            print(f"Add: {', '.join(rec['add']) or '(なし)'}")
            print(f"Keep: {', '.join(rec['keep']) or '(なし)'}")
            print(f"Remove: {', '.join(rec['remove']) or '(なし)'}")
        else:
            print(json.dumps(analysis, ensure_ascii=False, indent=2))

        return 0

    except ConfigError as e:
        logger.error(str(e))
        return 2
    except YouTubeAPIError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.exception(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
