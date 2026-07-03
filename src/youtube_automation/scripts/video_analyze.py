#!/usr/bin/env python3
"""yt-video-analyze CLI

Issue #103: ベンチマーク競合・自チャンネル動画・任意 URL を Gemini で動画解析する。

Usage:
    yt-video-analyze --source benchmark --channel <slug> --top 5
    yt-video-analyze --source own --collection <name>
    yt-video-analyze --url <youtube_url>

Design:
- 解釈フェーズ (`main`): argparse → skill-config → channel_dir 解決 → target list 構築
- 実行フェーズ (`VideoAnalyzer.analyze_url` ループ): Gemini 呼出 + JSON 保存
- 出力フェーズ (`VideoAnalysisReport`): slug 単位で Markdown 集約

skill-config / Gemini Client / data_dir は **境界 (`main`) で 1 回だけ解決し**、
ループ内で再解決しない (フェーズ分離)。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google.genai import errors as genai_errors

from youtube_automation.scripts.benchmark_collector import load_benchmark_videos, select_top_vod_benchmark_videos
from youtube_automation.utils.config import channel_dir as _channel_dir
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.genai_client import create_genai_client
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.video_analyzer import (
    VideoAnalysisReport,
    VideoAnalyzer,
    VideoTarget,
)

logger = logging.getLogger(__name__)

SKILL_NAME = "video-analyze"
SOURCE_BENCHMARK = "benchmark"
SOURCE_OWN = "own"
SOURCE_CHOICES = (SOURCE_BENCHMARK, SOURCE_OWN)

# 任意 URL 経路では slug を一意に持てないため固定名で保存する
URL_SOURCE_SLUG = "url"
WATCH_URL_TEMPLATE = "https://www.youtube.com/watch?v={video_id}"

# upload_tracking.json の配置パターン (collections/live/<name>/20-documentation/)
_COLLECTION_DOC_DIR = "20-documentation"
_UPLOAD_TRACKING_NAME = "upload_tracking.json"

_SHORTS_PATH_RE = re.compile(r"^/shorts/([A-Za-z0-9_-]+)/?$")


# ---------------------------------------------------------------------------
# URL → video_id
# ---------------------------------------------------------------------------


def _extract_video_id_from_url(url: str) -> str:
    """YouTube URL から video_id を抽出する。

    対応形式:
    - https://www.youtube.com/watch?v=<id>
    - https://youtu.be/<id>
    - https://www.youtube.com/shorts/<id>

    Raises:
        ValidationError: URL が空 / YouTube ドメインでない / video_id が取れない
    """
    if not url:
        raise ValidationError("URL が空です")

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if host.endswith("youtu.be"):
        # 末尾スラッシュ付き ("https://youtu.be/<id>/") も受理する
        vid = parsed.path.strip("/")
        if not vid or "/" in vid:
            raise ValidationError(f"youtu.be URL から video_id を取得できません: {url}")
        return vid

    if host.endswith("youtube.com"):
        if parsed.path == "/watch":
            vid_list = parse_qs(parsed.query).get("v", [])
            if not vid_list or not vid_list[0]:
                raise ValidationError(f"watch URL に v パラメータがありません: {url}")
            return vid_list[0]
        m = _SHORTS_PATH_RE.match(parsed.path)
        if m:
            return m.group(1)

    raise ValidationError(f"YouTube URL ではありません: {url}")


# ---------------------------------------------------------------------------
# Target resolvers (3 経路)
# ---------------------------------------------------------------------------


def _resolve_url_target(url: str) -> VideoTarget:
    """任意 URL を VideoTarget に変換する (slug は固定 'url')。"""
    video_id = _extract_video_id_from_url(url)
    return VideoTarget(video_id=video_id, slug=URL_SOURCE_SLUG, url=url, title="")


def _resolve_own_targets(*, channel_dir: Path, collection_name: str) -> list[VideoTarget]:
    """自チャンネル live コレクションから VideoTarget リストを構築する。

    `complete_collection.video_id` を 1 件、`videos[]` があれば各エントリを追加。
    """
    tracking_path = channel_dir / "collections" / "live" / collection_name / _COLLECTION_DOC_DIR / _UPLOAD_TRACKING_NAME
    if not tracking_path.exists():
        raise ValidationError(
            f"upload_tracking.json が見つかりません: collection='{collection_name}' path={tracking_path}"
        )

    data = json.loads(tracking_path.read_text(encoding="utf-8"))

    targets: list[VideoTarget] = []
    cc = data.get("complete_collection") or {}
    cc_video_id = cc.get("video_id")
    if cc_video_id:
        targets.append(
            VideoTarget(
                video_id=cc_video_id,
                slug=collection_name,
                url=cc.get("video_url") or WATCH_URL_TEMPLATE.format(video_id=cc_video_id),
                title=cc.get("title", ""),
            )
        )

    for v in data.get("videos") or []:
        vid = v.get("video_id")
        if not vid:
            continue
        targets.append(
            VideoTarget(
                video_id=vid,
                slug=collection_name,
                url=v.get("video_url") or WATCH_URL_TEMPLATE.format(video_id=vid),
                title=v.get("title", ""),
            )
        )

    if not targets:
        raise ValidationError(f"コレクション '{collection_name}' に有効な video_id が含まれていません")
    return targets


def _resolve_benchmark_targets(*, data_dir: Path, channel_slug: str, top: int) -> list[VideoTarget]:
    """ベンチマーク JSON から slug でフィルタし、上位 `top` 件を VideoTarget に変換する。"""
    if top <= 0:
        raise ValidationError(f"--top は 1 以上を指定してください (received: {top})")

    videos = load_benchmark_videos(data_dir)
    matched = [v for v in videos if v.get("channel_slug") == channel_slug]
    if not matched:
        raise ValidationError(f"benchmark JSON に slug='{channel_slug}' の動画がありません")

    # live 配信（duration_iso == "P0D"）は Gemini が URL を取り込めず 403 になるため
    # スキップして次点の VOD を繰り上げる (#1462)。yt-doctor の readiness 判定と同じ選定。
    selected, skipped_live = select_top_vod_benchmark_videos(matched, top)
    if skipped_live:
        logger.info(
            "live 配信 %d 本を解析対象から除外し次点 VOD を繰り上げます"
            "（Gemini はライブ配信 URL を取り込めないため）: %s",
            len(skipped_live),
            ", ".join(str(v.get("video_id")) for v in skipped_live),
        )
    if not selected:
        raise ValidationError(f"slug='{channel_slug}' の benchmark 動画は live 配信のみで、解析可能な VOD がありません")

    return [
        VideoTarget(
            video_id=v["video_id"],
            slug=channel_slug,
            url=WATCH_URL_TEMPLATE.format(video_id=v["video_id"]),
            title=v.get("title", ""),
        )
        for v in selected
    ]


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


class _VideoAnalyzeParser(argparse.ArgumentParser):
    """`--source` の値ごとに必須引数の有無を post-parse で検証する parser。"""

    def parse_args(self, args=None, namespace=None):  # type: ignore[override]
        ns = super().parse_args(args=args, namespace=namespace)
        if ns.source == SOURCE_BENCHMARK and not ns.channel:
            self.error("--source benchmark には --channel が必須です")
        if ns.source == SOURCE_OWN and not ns.collection:
            self.error("--source own には --collection が必須です")
        return ns


def _build_parser() -> argparse.ArgumentParser:
    """yt-video-analyze の argparse を構築する。

    - `--source` と `--url` は相互排他 (どちらか必須)
    - `--source benchmark` は `--channel` 必須、`--source own` は `--collection` 必須
    """
    parser = _VideoAnalyzeParser(description="Gemini で YouTube 動画を解析 (benchmark / own / url の 3 経路)")
    entry = parser.add_mutually_exclusive_group(required=True)
    entry.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
        help="解析対象の入力経路 (benchmark|own)",
    )
    entry.add_argument("--url", help="単発動画の YouTube URL")

    parser.add_argument("--channel", help="--source benchmark 用: チャンネル slug")
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="--source benchmark 用: 上位何件を解析するか (default: 5)",
    )
    parser.add_argument("--collection", help="--source own 用: コレクション名")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログ")
    return parser


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _resolve_targets(args: argparse.Namespace, *, channel_dir: Path, data_dir: Path) -> tuple[str, list[VideoTarget]]:
    """args の入力経路に応じて (slug, targets) を返す。

    `--source` choices と `add_mutually_exclusive_group(required=True)` により、
    network 入口は url / benchmark / own の 3 値に網羅性が argparse 側で保証される。
    """
    if args.url:
        target = _resolve_url_target(args.url)
        return target.slug, [target]
    if args.source == SOURCE_BENCHMARK:
        return args.channel, _resolve_benchmark_targets(data_dir=data_dir, channel_slug=args.channel, top=args.top)
    # SOURCE_OWN: choices と排他制約で他値は到達不能
    return args.collection, _resolve_own_targets(channel_dir=channel_dir, collection_name=args.collection)


def _run_analysis(*, analyzer: VideoAnalyzer, targets: list[VideoTarget]) -> tuple[list[dict], list[dict]]:
    """targets を順に Gemini で解析し、(成功 results, 失敗 failures) を返す。

    plan「失敗動画はログ + JSON 保存せず次へ」の方針に従い、ValidationError
    （JSON パース失敗）と Gemini SDK の APIError（rate limit / private 動画 /
    network 等）を 1 件ずつ failures に積み、N 件ループ全停止を防ぐ。
    """
    results: list[dict] = []
    failures: list[dict] = []
    for target in targets:
        try:
            payload = analyzer.analyze_url(target)
        except (ValidationError, genai_errors.APIError) as err:
            logger.warning("動画分析失敗 [%s]: %s", target.video_id, err)
            failures.append({"video_id": target.video_id, "url": target.url, "error": str(err)})
            continue
        analyzer.save_json(target, payload)
        results.append(payload)
    return results, failures


def main():
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # 境界での解決: skill-config / channel_dir / data_dir / Gemini Client は一度だけ
    cfg = load_skill_config(SKILL_NAME)
    channel_dir = _channel_dir()
    data_dir = channel_dir / "data"
    reports_dir = channel_dir / "reports"

    slug, targets = _resolve_targets(args, channel_dir=channel_dir, data_dir=data_dir)
    logger.info("解析対象: slug='%s' 件数=%d", slug, len(targets))

    analyzer = VideoAnalyzer(
        client=create_genai_client(),
        model=cfg["model"],
        prompt=cfg["prompt"],
        delay_sec=cfg["delay_sec"],
        data_dir=data_dir,
        analysis_window_sec=cfg["analysis_window_sec"],
    )

    results, failures = _run_analysis(analyzer=analyzer, targets=targets)

    md = VideoAnalysisReport.render(slug=slug, results=results, failures=failures)
    VideoAnalysisReport.write(reports_dir=reports_dir, slug=slug, content=md)

    logger.info("動画分析完了: slug='%s' 成功=%d 失敗=%d", slug, len(results), len(failures))


if __name__ == "__main__":
    main()
