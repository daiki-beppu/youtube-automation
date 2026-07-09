#!/usr/bin/env python3
"""yt-discover-competitors CLI（Issue #114）。

ニッチキーワードから競合チャンネル候補を発掘し、ランキング付き Markdown + CSV を出力する。

Usage:
    yt-discover-competitors \
        --keywords "lo-fi study,chill beats,study music" \
        --min-subscribers 10000 --max-subscribers 1000000 \
        --posted-within-days 30 --top 20 \
        --output research/lo-fi-discovery.md

Design:
- 解釈フェーズ (`_build_parser` / `_build_params`): argparse → DiscoveryParams 正規化
- 実行フェーズ (`discover_competitors`): YouTube API + スコアリング
- 出力フェーズ (`_write_markdown` / `_write_csv`): ペア出力（.md + 同名 .csv）

CLI 境界で `ValidationError` を fail-fast で投げる（不整合な値のサイレントスキップ防止）。
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

from youtube_automation.utils.competitor_discovery import discover_competitors
from youtube_automation.utils.competitor_scoring import (
    CandidateChannel,
    DiscoveryParams,
    ScoredCandidate,
)
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.youtube_service import get_youtube

logger = logging.getLogger(__name__)


# Markdown / CSV の契約文字列は 1 箇所で定義する（テストとも共有）
_MARKDOWN_HEADER = "| rank | channel | subscribers | uploads/月 | 平均再生数 | スコア | 候補理由 |"
_MARKDOWN_SEPARATOR = "|------|---------|-------------|-----------|-----------|--------|---------|"

_CSV_COLUMNS: tuple[str, ...] = (
    "rank",
    "channel_id",
    "handle",
    "name",
    "subscribers",
    "monthly_uploads",
    "avg_views",
    "total_score",
    "score_keyword",
    "score_engagement",
    "score_posting",
    "score_subscriber",
    "reason",
    "channel_url",
)

# skill-config (.claude/skills/discover-competitors/config.default.yaml) が
# 読めない場合の最終フォールバック（plan §7.5 の値と同一）
_DEFAULT_MIN_SUBSCRIBERS = 0
_DEFAULT_MAX_SUBSCRIBERS = 10_000_000
_DEFAULT_POSTED_WITHIN_DAYS = 30
_DEFAULT_TOP = 20
_DEFAULT_PER_KEYWORD = 20


def _search_defaults() -> dict[str, int]:
    """CLI フラグ未指定時の既定値を skill-config から解決する。

    `.claude/skills/discover-competitors/config.default.yaml::search.*` が default、
    `config/skills/discover-competitors.yaml` のチャンネル上書きが優先される
    （優先順位: CLI フラグ明示指定 > チャンネル上書き > default）。
    """
    try:
        search = load_skill_config("discover-competitors").get("search") or {}
    except ConfigError:
        search = {}
    if not isinstance(search, dict):
        search = {}
    return {
        "min_subscribers": int(search.get("min_subscribers", _DEFAULT_MIN_SUBSCRIBERS)),
        "max_subscribers": int(search.get("max_subscribers", _DEFAULT_MAX_SUBSCRIBERS)),
        "posted_within_days": int(search.get("posted_within_days", _DEFAULT_POSTED_WITHIN_DAYS)),
        "top": int(search.get("top", _DEFAULT_TOP)),
        "per_keyword": int(search.get("per_keyword", _DEFAULT_PER_KEYWORD)),
    }


# ----------------------------------------------------------------------------
# 引数パース・境界変換
# ----------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-discover-competitors",
        description=("ニッチキーワードから競合チャンネル候補を発掘し、ランキング付き Markdown + CSV を出力する。"),
    )
    parser.add_argument(
        "--keywords",
        required=True,
        help="カンマ区切りのキーワード（例: 'lo-fi study,chill beats'）",
    )
    defaults = _search_defaults()
    parser.add_argument("--min-subscribers", type=int, default=defaults["min_subscribers"])
    parser.add_argument("--max-subscribers", type=int, default=defaults["max_subscribers"])
    parser.add_argument("--posted-within-days", type=int, default=defaults["posted_within_days"])
    parser.add_argument("--top", type=int, default=defaults["top"])
    parser.add_argument(
        "--per-keyword",
        type=int,
        default=defaults["per_keyword"],
        help="search.list の maxResults（キーワード毎の取得上限）",
    )
    parser.add_argument(
        "--require-music-topic",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "channels.list の topicCategories に音楽トピックを含むチャンネルのみ通すフィルタ。"
            "既定: ON（topic 不明チャンネルは fail-open で通す）。"
            "従来挙動に戻すには --no-require-music-topic"
        ),
    )
    parser.add_argument("--output", required=True, help="Markdown 出力先（同名 .csv も書き出す）")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _build_params(args: argparse.Namespace) -> DiscoveryParams:
    """argparse.Namespace → DiscoveryParams（不整合な値は即 fail）。"""
    keywords = tuple(k.strip() for k in (args.keywords or "").split(",") if k.strip())
    if not keywords:
        raise ValidationError("--keywords には少なくとも 1 つ非空のキーワードが必要です")
    if args.min_subscribers < 0:
        raise ValidationError(f"--min-subscribers は 0 以上が必要です: {args.min_subscribers}")
    if args.max_subscribers < args.min_subscribers:
        raise ValidationError(
            "--max-subscribers ({max_}) は --min-subscribers ({min_}) 以上が必要です".format(
                max_=args.max_subscribers, min_=args.min_subscribers
            )
        )
    if args.posted_within_days <= 0:
        raise ValidationError(f"--posted-within-days は 1 以上が必要です: {args.posted_within_days}")
    if args.top <= 0:
        raise ValidationError(f"--top は 1 以上が必要です: {args.top}")
    if args.per_keyword <= 0:
        raise ValidationError(f"--per-keyword は 1 以上が必要です: {args.per_keyword}")

    return DiscoveryParams(
        keywords=keywords,
        min_subscribers=args.min_subscribers,
        max_subscribers=args.max_subscribers,
        posted_within_days=args.posted_within_days,
        top=args.top,
        per_keyword_results=args.per_keyword,
        require_music_topic=args.require_music_topic,
    )


# ----------------------------------------------------------------------------
# レポート出力
# ----------------------------------------------------------------------------


def _format_count_compact(count: int) -> str:
    """整数を人間が読みやすい K/M 表記（コンパクト整数表記）に変換する。

    Markdown レポートの登録者数・平均再生数列を 480K / 1.2M 形式に統一するための
    presentation 層ヘルパー（CSV 側は生整数を使うので CSV は通さない）。
    """
    if count >= 1_000_000:
        millions = count / 1_000_000
        if millions == int(millions):
            return f"{int(millions)}M"
        return f"{millions:.1f}M"
    if count >= 1_000:
        return f"{count // 1_000}K"
    return str(count)


def _channel_url(channel: CandidateChannel) -> str:
    """handle 優先。handle が無ければ /channel/UC... にフォールバックする。"""
    handle = channel.handle
    if handle:
        if not handle.startswith("@"):
            handle = "@" + handle
        return f"https://www.youtube.com/{handle}"
    return f"https://www.youtube.com/channel/{channel.channel_id}"


def _channel_link(channel: CandidateChannel) -> str:
    label = channel.handle or channel.channel_id
    return f"[{label}]({_channel_url(channel)})"


def _write_markdown(scored: list[ScoredCandidate], output: Path, params: DiscoveryParams) -> None:
    """order.md の出力イメージに準拠した Markdown テーブルを書き出す。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 競合チャンネル発掘レポート",
        "",
        f"- keywords: {', '.join(params.keywords)}",
        f"- subscribers: {params.min_subscribers:,} 〜 {params.max_subscribers:,}",
        f"- posted_within_days: {params.posted_within_days}",
        f"- top: {params.top}",
        "",
        _MARKDOWN_HEADER,
        _MARKDOWN_SEPARATOR,
    ]
    for rank, s in enumerate(scored, start=1):
        ch = s.channel
        lines.append(
            "| {rank} | {channel} | {subs} | {uploads} | {avg} | {score} | {reason} |".format(
                rank=rank,
                channel=_channel_link(ch),
                subs=_format_count_compact(ch.subscribers),
                uploads=f"{s.monthly_uploads:.1f}",
                avg=_format_count_compact(s.avg_views),
                score=f"{s.score.total:.2f}",
                reason=s.reason,
            )
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csv(scored: list[ScoredCandidate], output: Path, params: DiscoveryParams) -> None:
    """plan §4.4 の 14 列ヘッダ仕様で CSV を書き出す。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_CSV_COLUMNS)
        for rank, s in enumerate(scored, start=1):
            ch = s.channel
            writer.writerow(
                [
                    rank,
                    ch.channel_id,
                    ch.handle,
                    ch.name,
                    ch.subscribers,
                    f"{s.monthly_uploads:.2f}",
                    s.avg_views,
                    f"{s.score.total:.4f}",
                    f"{s.score.keyword_match:.4f}",
                    f"{s.score.engagement:.4f}",
                    f"{s.score.posting_cadence:.4f}",
                    f"{s.score.subscriber_proximity:.4f}",
                    s.reason,
                    _channel_url(ch),
                ]
            )


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------


def main() -> None:
    args = _build_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    params = _build_params(args)

    youtube = get_youtube()
    scored = discover_competitors(youtube, params)

    output_md = Path(args.output)
    output_csv = output_md.with_suffix(".csv")

    _write_markdown(scored, output_md, params)
    _write_csv(scored, output_csv, params)

    if not scored:
        logger.warning("候補が見つかりませんでした。フィルタ条件を緩めるか、キーワードを変更してください。")
    logger.info("Markdown: %s", output_md)
    logger.info("CSV: %s", output_csv)


if __name__ == "__main__":
    main()
