#!/usr/bin/env python3
"""競合チャンネルのベンチマークデータ収集・分析スクリプト

YouTube Data API で競合チャンネルの最新動画データを取得し、
派生指標の算出・サムネイル分析（Gemini）・Markdown レポート生成を行う。

Usage:
    # チャンネルディレクトリから実行
    cd channels/fantasy-celtic-music

    python3 ../../automation/benchmark_collector.py                      # 鮮度チェック → 古いもののみ更新
    python3 ../../automation/benchmark_collector.py --force               # 全チャンネル強制更新
    python3 ../../automation/benchmark_collector.py --json-only           # JSON のみ出力
    python3 ../../automation/benchmark_collector.py --no-thumbnails       # サムネイル分析スキップ
    python3 ../../automation/benchmark_collector.py --keep-thumbnails     # サムネイル画像を保持
    python3 ../../automation/benchmark_collector.py --competitor world-fantasia  # 単一競合
"""

import argparse
import json
import logging
import re
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from youtube_automation.commands._shared.arguments import CompetitorArgumentParser
from youtube_automation.configuration import channel_dir as _channel_dir
from youtube_automation.configuration import load_config
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError, YouTubeAPIError
from youtube_automation.domains.analytics.benchmark import (
    is_short_benchmark_duration,
    is_short_benchmark_video,
)
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.analytics.benchmark_analyzer import (
    compute_daily_views,
    compute_engagement_rate,
    compute_posting_intervals,
    extract_description_keywords,
    parse_iso_duration,
)
from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler
from youtube_automation.infrastructure.cost_tracker import log_quota
from youtube_automation.infrastructure.documents.publishing import read_published_json_document
from youtube_automation.infrastructure.filesystem import write_text_files_transactionally
from youtube_automation.infrastructure.google.youtube import YouTubeClients
from youtube_automation.infrastructure.observability.profile import section
from youtube_automation.infrastructure.retry import execute_with_retry

logger = logging.getLogger(__name__)

# channels.list バッチ単位（YouTube Data API 上限）
_CHANNELS_BATCH_SIZE = 50
_SCAN_PAGE_SIZE = 50
_DEFAULT_SCAN_RECENT = 150
# quota 記録（Issue #2056）: read 系 list operation は 1 request = 1 unit
_QUOTA_SERVICE = "youtube-data-api"
_READ_QUOTA_UNITS = 1
_VIDEO_DESCRIPTION_FIELD = "description"
_DESCRIPTION_TTP_SECTION_TITLE = "概要欄TTPサンプル"
_DESCRIPTION_TTP_SAMPLE_LIMIT = 3
_SHORT_THUMBNAIL_KEYS = ("high", "medium", "default")
_DEFAULT_THUMBNAIL_KEYS = ("maxres", "standard", "high", "medium", "default")
_GENERATED_START = "<!-- benchmark:generated:start -->"
_GENERATED_END = "<!-- benchmark:generated:end -->"
_USER_START = "<!-- benchmark:user:start -->"
_USER_END = "<!-- benchmark:user:end -->"
_REPORT_MARKERS = (_GENERATED_START, _GENERATED_END, _USER_START, _USER_END)
_LEGACY_USER_HEADING = "## サムネイル分析"


def _render_managed_report(generated: str, user: str = "") -> str:
    """Render a channel report with explicit generated/user ownership regions."""
    generated = generated.rstrip("\r\n")
    user = user.strip("\r\n")
    user_body = f"{user}\n" if user else ""
    return f"{_GENERATED_START}\n{generated}\n{_GENERATED_END}\n\n{_USER_START}\n{user_body}{_USER_END}\n"


def _extract_marker_region(content: str, start: str, end: str, path: Path) -> str:
    lines = content.splitlines()
    for marker in _REPORT_MARKERS:
        if content.count(marker) != 1 or lines.count(marker) != 1:
            raise ConfigError(
                f"{path}: benchmark report marker が欠損・重複・行内配置されています: {marker}. "
                "手書き分析を退避し、4 marker を各1行に復元して再実行してください。"
            )
    positions = [content.index(marker) for marker in _REPORT_MARKERS]
    if positions != sorted(positions):
        raise ConfigError(
            f"{path}: benchmark report marker の順序が不正です。generated start/end, "
            "user start/end の順に復元して再実行してください。"
        )
    start_at = content.index(start) + len(start)
    end_at = content.index(end, start_at)
    return content[start_at:end_at].strip("\r\n")


def _existing_user_content(path: Path) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    if any(marker in content for marker in _REPORT_MARKERS):
        return _extract_marker_region(content, _USER_START, _USER_END, path)

    lines = content.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == _LEGACY_USER_HEADING]
    if len(matches) > 1:
        raise ConfigError(
            f"{path}: legacy の '{_LEGACY_USER_HEADING}' が複数あります。"
            "手書き分析を1セクションへ統合して再実行してください。"
        )
    return "".join(lines[matches[0] :]).strip("\r\n") if matches else ""


def estimate_collection_quota_units(*, channel_count: int, scan_recent: int) -> int:
    """通常収集の Data API read quota 上限を 50 件ページ単位で返す。"""
    if channel_count <= 0:
        return 0
    scan_pages = max(0, (scan_recent + _SCAN_PAGE_SIZE - 1) // _SCAN_PAGE_SIZE)
    channel_batches = (channel_count + _CHANNELS_BATCH_SIZE - 1) // _CHANNELS_BATCH_SIZE
    return channel_batches + channel_count * scan_pages * 2


def _markdown_code_fence(content: str) -> str:
    max_backticks = max((len(match.group(0)) for match in re.finditer(r"`+", content)), default=0)
    return "`" * max(3, max_backticks + 1)


def _execute_read_with_quota(request, context: str, bucket: str, *, metadata: dict | None = None):
    """read API request を実行し、成否に関わらず 1 request 分の quota を記録する。

    quota は失敗した request でも消費されるため `finally` で記録し、
    元例外はそのまま伝播させる。
    """
    try:
        return execute_with_retry(request, context)
    finally:
        log_quota(_QUOTA_SERVICE, bucket, _READ_QUOTA_UNITS, metadata=metadata)


class BenchmarkCollector:
    """競合チャンネルのベンチマークデータ収集（YouTube Data API）"""

    def __init__(self):
        self.config = load_config()
        self.youtube = None
        self.youtube_clients = YouTubeClients(
            full_handler=YouTubeOAuthHandler(),
            readonly_handler=YouTubeOAuthHandler.create_readonly(),
        )
        self.benchmark_config = load_skill_config("benchmark")
        self.channel_dir = _channel_dir()
        self.benchmarks_dir = self.channel_dir / "docs" / "benchmarks"
        self.data_dir = self.channel_dir / "data"
        self.today = date.today()

    def initialize(self):
        """YouTube API 認証を実行する。"""
        logger.info("YouTube API 認証中...")
        self.youtube = self.youtube_clients.youtube_readonly
        logger.info("認証完了")

    def check_freshness(self) -> list[dict]:
        """更新が必要なチャンネルを返す。

        Returns:
            freshness_days 以上未更新のチャンネル情報リスト
        """
        freshness_days = self.benchmark_config.get("freshness_days", 3)
        stale_channels = []
        report_path = self.benchmarks_dir / "benchmark-report.json"
        report_exists = report_path.exists() and report_path.with_suffix(".html").exists()
        if report_exists:
            report = read_published_json_document(report_path, RepositorySchema.CHANNEL_RESEARCH_REPORT)
            if not isinstance(report, dict) or report.get("report_type") != "benchmark":
                raise ConfigError(f"{report_path}: report_type は benchmark である必要があります")

        for ch in self.config.analytics.benchmark.channels:
            if not report_exists:
                logger.info("ファイル未作成: %s → 初回収集対象", ch["slug"])
                stale_channels.append(ch)
                continue

            mtime = datetime.fromtimestamp(
                min(report_path.stat().st_mtime, report_path.with_suffix(".html").stat().st_mtime)
            ).date()
            age = (self.today - mtime).days
            if age >= freshness_days:
                logger.info("%s: %d日前に更新 → 更新対象", ch["slug"], age)
                stale_channels.append(ch)
            else:
                logger.info("%s: %d日前に更新 → 最新", ch["slug"], age)

        return stale_channels

    def _fetch_channels_metadata(self, channel_infos: list[dict]) -> dict[str, dict]:
        """`channels.list` を `_CHANNELS_BATCH_SIZE` 件単位でバッチ呼び出しし、`{channel_id: item}` を返す。

        Args:
            channel_infos: `benchmark.channels` 相当のリスト（各要素に `id` を含む）

        Returns:
            channel_id をキーとした API レスポンス item の辞書。
            削除済み等で API レスポンスに含まれない channel_id はキーに現れない。
        """
        channel_ids = [ch["id"] for ch in channel_infos]
        items_by_id: dict[str, dict] = {}
        for i in range(0, len(channel_ids), _CHANNELS_BATCH_SIZE):
            batch = channel_ids[i : i + _CHANNELS_BATCH_SIZE]
            with section("benchmark.channels_list", batch_size=len(batch)):
                try:
                    request = self.youtube.channels().list(
                        part="snippet,statistics,contentDetails",
                        id=",".join(batch),
                    )
                    resp = _execute_read_with_quota(
                        request,
                        f"benchmark.channels_list (id={','.join(batch)})",
                        "channels.list",
                        metadata={"context": "benchmark.channels_list", "batch_size": len(batch)},
                    )
                except YouTubeAPIError:
                    raise
            for item in resp.get("items", []):
                items_by_id[item["id"]] = item
        return items_by_id

    def collect_channel(self, channel_info: dict, ch_item: dict) -> dict:
        """1チャンネル分のデータを YouTube Data API で収集する。

        Args:
            channel_info: benchmark.channels の1要素
            ch_item: `_fetch_channels_metadata` から渡される該当チャンネルの
                `channels.list` レスポンス item。チャンネルが見つからなければ空辞書

        Returns:
            チャンネルデータ辞書（概要 + 動画リスト + 派生指標）。

        Raises:
            YouTubeAPIError: `ch_item` が空（チャンネルが API レスポンスに存在しない）のとき。
                空辞書で握りつぶさず、欠落を呼び出し側へ伝播させる
        """
        channel_id = channel_info["id"]
        scan_recent = self.benchmark_config.get("scan_recent", _DEFAULT_SCAN_RECENT)
        min_views = self.benchmark_config.get("min_views", 10000)

        if not ch_item:
            raise YouTubeAPIError(
                f"ベンチマーク対象チャンネルが見つかりません: {channel_info.get('name', channel_id)} "
                f"(id={channel_id})。削除・非公開・ID 誤りの可能性があります。"
                "config/channel/analytics.json の benchmark.channels の id を確認してください。"
            )

        uploads_playlist_id = ch_item["contentDetails"]["relatedPlaylists"]["uploads"]

        channel_data = {
            "channel_id": channel_id,
            "name": channel_info["name"],
            "slug": channel_info["slug"],
            "relationship": channel_info.get("relationship", ""),
            "subscribers": int(ch_item["statistics"].get("subscriberCount", 0)),
            "total_videos": int(ch_item["statistics"].get("videoCount", 0)),
            "collected_at": self.today.isoformat(),
            "min_views_threshold": min_views,
        }

        # 最新動画ID取得（scan_recent 件を走査プールとする。50 件超は nextPageToken でページング）
        video_ids: list[str] = []
        page_token: str | None = None
        remaining = scan_recent
        upload_scan_complete = False
        while remaining > 0:
            with section("benchmark.playlist_items", page_size=min(50, remaining)):
                try:
                    request = self.youtube.playlistItems().list(
                        part="contentDetails",
                        playlistId=uploads_playlist_id,
                        maxResults=min(50, remaining),
                        pageToken=page_token,
                    )
                    playlist_resp = _execute_read_with_quota(
                        request,
                        "benchmark.playlist_items",
                        "playlistItems.list",
                        metadata={"context": "benchmark.playlist_items"},
                    )
                except YouTubeAPIError:
                    raise
            batch_ids = [item["contentDetails"]["videoId"] for item in playlist_resp.get("items", [])]
            video_ids.extend(batch_ids)
            page_token = playlist_resp.get("nextPageToken")
            remaining -= len(batch_ids)
            if not page_token or not batch_ids:
                upload_scan_complete = True
                break

        channel_data["scanned_count"] = len(video_ids)

        if not video_ids:
            logger.warning("動画が見つかりません: %s", channel_info["name"])
            channel_data["upload_scan"] = {
                "scanned_count": 0,
                "complete": upload_scan_complete,
                "latest_upload_at": None,
                "oldest_upload_at": None,
                "videos": [],
            }
            channel_data["videos"] = []
            channel_data["avg_views"] = 0
            channel_data["avg_daily_views"] = 0
            channel_data["avg_engagement_rate"] = 0
            channel_data["top_tags"] = []
            channel_data["posting_trend"] = {}
            return channel_data

        # 動画詳細取得（50件単位でバッチ）
        raw_videos: list[dict] = []
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            with section("benchmark.videos_list", batch_size=len(batch)):
                try:
                    request = self.youtube.videos().list(
                        part="snippet,statistics,contentDetails",
                        id=",".join(batch),
                    )
                    videos_resp = _execute_read_with_quota(
                        request,
                        "benchmark.videos_list",
                        "videos.list",
                        metadata={"context": "benchmark.videos_list", "batch_size": len(batch)},
                    )
                except YouTubeAPIError:
                    raise

            for video in videos_resp.get("items", []):
                snippet = video["snippet"]
                stats = video["statistics"]
                content = video["contentDetails"]

                # ライブ配信・非公開動画等で duration が欠落することがあるためスキップ
                duration_iso = content.get("duration")
                if not duration_iso:
                    logger.warning("duration 欠落のためスキップ: %s", video.get("id"))
                    continue

                is_short = is_short_benchmark_duration(duration_iso)
                thumbnail_keys = _SHORT_THUMBNAIL_KEYS if is_short else _DEFAULT_THUMBNAIL_KEYS
                v = {
                    "video_id": video["id"],
                    "title": snippet["title"],
                    "published_at": snippet["publishedAt"][:10],
                    "published_at_utc": snippet["publishedAt"],
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                    "duration_iso": duration_iso,
                    "duration_display": parse_iso_duration(duration_iso),
                    "tags": snippet.get("tags", []),
                    _VIDEO_DESCRIPTION_FIELD: snippet.get(_VIDEO_DESCRIPTION_FIELD, ""),
                    "description_keywords": extract_description_keywords(snippet.get(_VIDEO_DESCRIPTION_FIELD, "")),
                    "thumbnail_url": self._best_thumbnail_url(
                        snippet.get("thumbnails", {}),
                        keys=thumbnail_keys,
                    ),
                    "thumbnail_analysis": None,
                }
                v["daily_views"] = compute_daily_views(v, self.today)
                v["engagement_rate"] = compute_engagement_rate(v)
                raw_videos.append(v)

        upload_dates = [video["published_at"] for video in raw_videos]
        channel_data["upload_scan"] = {
            "scanned_count": len(raw_videos),
            "complete": upload_scan_complete,
            "latest_upload_at": max(upload_dates) if upload_dates else None,
            "oldest_upload_at": min(upload_dates) if upload_dates else None,
            "videos": [{"published_at": video["published_at"], "views": video["views"]} for video in raw_videos],
        }

        # 視聴数フィルタ（min_views 以上のみベンチマーク対象）
        videos = [v for v in raw_videos if v["views"] >= min_views]
        # 視聴数降順で並べ替え（レポートの可読性向上）
        videos.sort(key=lambda v: v["views"], reverse=True)

        logger.info(
            "%s: 走査 %d 本 → %d 本が %d 再生以上",
            channel_info["name"],
            len(raw_videos),
            len(videos),
            min_views,
        )

        channel_data["videos"] = videos
        channel_data["posting_trend"] = compute_posting_intervals(videos) if videos else {}

        # 集計（フィルタ後の Long 動画のみ対象）
        long_videos = [v for v in videos if not is_short_benchmark_video(v)]
        if long_videos:
            channel_data["avg_views"] = round(sum(v["views"] for v in long_videos) / len(long_videos))
            channel_data["avg_daily_views"] = round(sum(v["daily_views"] for v in long_videos) / len(long_videos), 1)
            channel_data["avg_engagement_rate"] = round(
                sum(v["engagement_rate"] for v in long_videos) / len(long_videos), 2
            )
        else:
            channel_data["avg_views"] = 0
            channel_data["avg_daily_views"] = 0
            channel_data["avg_engagement_rate"] = 0

        # タグ頻度分析（フィルタ後の動画のみ）
        all_tags = []
        for v in videos:
            all_tags.extend(t.lower() for t in v["tags"])
        tag_counts = Counter(all_tags)
        channel_data["top_tags"] = [{"tag": tag, "count": count} for tag, count in tag_counts.most_common(15)]

        return channel_data

    def collect_all(self, force: bool = False, competitor_slug: str | None = None) -> dict:
        """全チャンネル（または指定チャンネル）のデータを収集する。

        Args:
            force: True なら鮮度に関わらず全更新
            competitor_slug: 指定時はその競合のみ

        Returns:
            全チャンネルの収集結果

        Raises:
            ConfigError: 指定 `competitor_slug` が benchmark.channels に存在しないとき
            YouTubeAPIError: 収集対象の一部が API レスポンスに存在しない（欠落）とき
        """
        if competitor_slug:
            targets = [ch for ch in self.config.analytics.benchmark.channels if ch["slug"] == competitor_slug]
            if not targets:
                raise ConfigError(
                    f"指定された競合が見つかりません: {competitor_slug}。"
                    "config/channel/analytics.json の benchmark.channels に slug を登録してください。"
                )
        elif force:
            targets = list(self.config.analytics.benchmark.channels)
        else:
            targets = self.check_freshness()

        if not targets:
            logger.info("更新が必要なチャンネルはありません")
            return {"channels": [], "collected_at": self.today.isoformat(), "skipped": True}

        ch_items = self._fetch_channels_metadata(targets)

        # API レスポンスに含まれないチャンネル（削除・非公開・ID 誤り）を明示検知。
        # 空辞書を黙ってスキップせず、欠落があれば収集失敗として停止する。
        missing = [ch for ch in targets if ch["id"] not in ch_items]
        if missing:
            detail = ", ".join(f"{ch.get('name', ch['id'])} (id={ch['id']})" for ch in missing)
            raise YouTubeAPIError(
                f"ベンチマーク対象チャンネルが YouTube API レスポンスに見つかりません: {detail}。"
                "削除・非公開・ID 誤りの可能性があります。"
                "config/channel/analytics.json の benchmark.channels の id を確認してください。"
            )

        results = []
        for ch in targets:
            logger.info("収集中: %s (%s)", ch["name"], ch["id"])
            results.append(self.collect_channel(ch, ch_items[ch["id"]]))

        return {
            "channels": results,
            "collected_at": self.today.isoformat(),
        }

    def collect_playlists(self, channel_info: dict) -> dict:
        """1チャンネルの公開再生リスト構成を収集する。

        playlists.list → 各 playlistItems.list → videos.list の 3 段で
        再生リストごとの動画一覧と統計を取得する。

        Args:
            channel_info: benchmark.channels の1要素

        Returns:
            {channel_id, name, slug, playlists_collected_at, playlists: [...]}
        """
        channel_id = channel_info["id"]

        # 1. 全再生リストを取得（ページング）
        playlists_raw = []
        page_token = None
        while True:
            request = self.youtube.playlists().list(
                part="snippet,contentDetails",
                channelId=channel_id,
                maxResults=50,
                pageToken=page_token,
            )
            resp = _execute_read_with_quota(
                request,
                "benchmark.playlists_list",
                "playlists.list",
                metadata={"context": "benchmark.playlists_list"},
            )
            playlists_raw.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        logger.info("再生リスト取得: %d 件 (%s)", len(playlists_raw), channel_info["name"])

        # 2. 各再生リストの動画 ID を取得し、video_id → 所属情報をマップ化
        playlists_data = []
        all_video_ids: set[str] = set()
        for pl in playlists_raw:
            playlist_id = pl["id"]
            snippet = pl["snippet"]
            content = pl["contentDetails"]

            items = []
            item_page_token = None
            while True:
                request = self.youtube.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=item_page_token,
                )
                items_resp = _execute_read_with_quota(
                    request,
                    "benchmark.playlist_items",
                    "playlistItems.list",
                    metadata={"context": "benchmark.playlists_playlist_items"},
                )
                for item in items_resp.get("items", []):
                    item_snip = item["snippet"]
                    video_id = item["contentDetails"]["videoId"]
                    items.append(
                        {
                            "position": item_snip.get("position", 0),
                            "video_id": video_id,
                            "title": item_snip.get("title", ""),
                            "published_at": item["contentDetails"].get("videoPublishedAt", ""),
                        }
                    )
                    all_video_ids.add(video_id)
                item_page_token = items_resp.get("nextPageToken")
                if not item_page_token:
                    break

            playlists_data.append(
                {
                    "playlist_id": playlist_id,
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "item_count": int(content.get("itemCount", len(items))),
                    "items": items,
                }
            )

        # 3. 動画 ID をバッチ（50件ずつ）で statistics + duration を取得
        video_stats: dict[str, dict] = {}
        video_id_list = list(all_video_ids)
        for i in range(0, len(video_id_list), 50):
            batch = video_id_list[i : i + 50]
            request = self.youtube.videos().list(
                part="statistics,contentDetails",
                id=",".join(batch),
            )
            videos_resp = _execute_read_with_quota(
                request,
                "benchmark.videos_list",
                "videos.list",
                metadata={"context": "benchmark.playlists_videos_list", "batch_size": len(batch)},
            )
            for v in videos_resp.get("items", []):
                stats = v.get("statistics", {})
                content = v.get("contentDetails", {})
                duration_iso = content.get("duration", "")
                video_stats[v["id"]] = {
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                    "duration_iso": duration_iso,
                    "duration_display": parse_iso_duration(duration_iso) if duration_iso else "",
                }

        # 4. 各 playlist の items に統計をマージ
        for pl in playlists_data:
            for item in pl["items"]:
                stats = video_stats.get(item["video_id"], {})
                item.update(stats)

        return {
            "channel_id": channel_id,
            "name": channel_info["name"],
            "slug": channel_info["slug"],
            "playlists_collected_at": self.today.isoformat(),
            "playlists": playlists_data,
        }

    def save_json(self, data: dict, *, competitor_slug: str | None = None) -> Path:
        """中間 JSON を data/ に保存する。

        ``competitor_slug`` 指定時は同日ファイルの同一 slug だけを更新し、
        他チャンネルと playlist 収集済みフィールドを保持する。

        Returns:
            保存先パス
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        filename = f"benchmark_{self.today.strftime('%Y%m%d')}.json"
        path = self.data_dir / filename
        if competitor_slug is not None and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except json.JSONDecodeError:
                existing_data = None
            if existing_data is not None:
                incoming_by_slug = {channel.get("slug"): channel for channel in data.get("channels", [])}
                merged_channels = []
                for existing_channel in existing_data.get("channels", []):
                    incoming = incoming_by_slug.pop(existing_channel.get("slug"), None)
                    merged_channels.append(
                        {**existing_channel, **incoming} if incoming is not None else existing_channel
                    )
                merged_channels.extend(incoming_by_slug.values())
                data = {**existing_data, **data, "channels": merged_channels}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info("JSON 保存: %s", path)
        return path

    def merge_playlists_into_json(self, playlists_results: list[dict]) -> Path:
        """既存の同日付 benchmark JSON に playlists フィールドをマージする。

        既存ファイルがなければ playlists のみを含む新規ファイルを作成する。

        Args:
            playlists_results: collect_playlists() の結果リスト

        Returns:
            保存先パス
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        filename = f"benchmark_{self.today.strftime('%Y%m%d')}.json"
        path = self.data_dir / filename

        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"channels": [], "collected_at": self.today.isoformat()}

        # slug → channel オブジェクトを引けるようにする
        channels_by_slug = {ch.get("slug"): ch for ch in data.get("channels", [])}

        for pl_result in playlists_results:
            slug = pl_result["slug"]
            existing = channels_by_slug.get(slug)
            if existing is not None:
                existing["playlists_collected_at"] = pl_result["playlists_collected_at"]
                existing["playlists"] = pl_result["playlists"]
            else:
                # 同日に動画ベンチマークが未収集のチャンネルは新規エントリで挿入
                data.setdefault("channels", []).append(
                    {
                        "channel_id": pl_result["channel_id"],
                        "name": pl_result["name"],
                        "slug": slug,
                        "playlists_collected_at": pl_result["playlists_collected_at"],
                        "playlists": pl_result["playlists"],
                    }
                )

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info("JSON マージ保存: %s", path)
        return path

    # --- 内部メソッド ---

    @staticmethod
    def _best_thumbnail_url(thumbnails: dict, *, keys: tuple[str, ...]) -> str:
        for key in keys:
            if key in thumbnails:
                return thumbnails[key]["url"]
        return ""

    def download_thumbnails(self, data: dict, *, force: bool = False) -> None:
        """サムネイル画像を docs/benchmarks/thumbnails/ にダウンロードする。

        Args:
            data: collect_all() の結果
            force: True なら既存ファイルも再ダウンロード
        """
        thumbnails_dir = self.benchmarks_dir / "thumbnails"
        thumbnails_dir.mkdir(parents=True, exist_ok=True)

        downloaded = 0
        skipped = 0
        for channel in data.get("channels", []):
            slug = channel["slug"]
            for video in channel.get("videos", []):
                url = video.get("thumbnail_url")
                if not url:
                    continue

                dest = thumbnails_dir / f"{slug}_{video['video_id']}.jpg"
                if dest.exists() and not force:
                    skipped += 1
                    continue

                try:
                    urllib.request.urlretrieve(url, dest)
                    downloaded += 1
                except Exception as e:
                    logger.warning("サムネイルDL失敗 [%s]: %s", video["title"][:30], e)

        logger.info("サムネイルDL: %d 件（スキップ: %d 件）→ %s", downloaded, skipped, thumbnails_dir)


_DEFAULT_THUMBNAIL_ANALYSIS_MODEL = "gemini-3.5-flash"


class BenchmarkThumbnailAnalyzer:
    """ベンチマークサムネイルの Gemini 分析"""

    def __init__(self, benchmarks_dir: Path):
        self.benchmarks_dir = benchmarks_dir
        cfg = load_skill_config("benchmark").get("thumbnail_analysis", {})
        self.model = cfg.get("model", _DEFAULT_THUMBNAIL_ANALYSIS_MODEL)
        self.delay_sec = float(cfg.get("delay_sec", 5))
        self.prompt = cfg.get("prompt", "").strip()

    def analyze_thumbnails(self, data: dict, keep: bool = False) -> dict:
        """サムネイル画像をダウンロードして Gemini で分析する。

        Args:
            data: collect_all() の結果
            keep: True ならサムネイル画像を docs/benchmarks/thumbnails/ に保存

        Returns:
            thumbnail_analysis が追加された data
        """
        try:
            from google.genai import types

            from youtube_automation.infrastructure.media.genai_client import create_global_genai_client
        except ImportError:
            logger.warning("google-genai 未インストール — サムネイル分析をスキップ")
            return data

        try:
            client = create_global_genai_client()
        except ConfigError as e:
            logger.warning("AI クライアント初期化失敗 — サムネイル分析をスキップ: %s", e)
            return data
        thumbnails_dir = self.benchmarks_dir / "thumbnails" if keep else None
        if thumbnails_dir:
            thumbnails_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp_dir:
            for channel in data.get("channels", []):
                slug = channel["slug"]
                for i, video in enumerate(channel.get("videos", [])):
                    url = video.get("thumbnail_url")
                    if not url:
                        continue

                    # ダウンロード
                    tmp_path = Path(tmp_dir) / f"{slug}_{i}.jpg"
                    try:
                        urllib.request.urlretrieve(url, tmp_path)
                    except Exception as e:
                        logger.warning("サムネイルDL失敗 [%s]: %s", video["title"][:30], e)
                        continue

                    # 保持する場合はコピー
                    if thumbnails_dir:
                        import shutil

                        keep_path = thumbnails_dir / f"{slug}_{video['video_id']}.jpg"
                        shutil.copy2(tmp_path, keep_path)

                    # Gemini 分析
                    try:
                        image_bytes = tmp_path.read_bytes()
                        response = client.models.generate_content(
                            model=self.model,
                            contents=[
                                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                                self.prompt,
                            ],
                        )
                        # JSON パース
                        text = response.text.strip()
                        # コードフェンスを除去
                        text = re.sub(r"^```(?:json)?\s*", "", text)
                        text = re.sub(r"\s*```$", "", text)
                        video["thumbnail_analysis"] = json.loads(text)
                        logger.info("サムネイル分析完了: %s", video["title"][:40])
                        from youtube_automation.infrastructure.cost_tracker import log_generation

                        log_generation(
                            "analysis",
                            self.model,
                            quantity=1,
                            unit="call",
                            metadata={"video_id": video["video_id"], "channel_slug": slug},
                        )
                    except json.JSONDecodeError as e:
                        logger.warning("サムネイル分析JSONパース失敗 [%s]: %s", video["title"][:30], e)
                    except Exception as e:
                        logger.warning("サムネイル分析失敗 [%s]: %s", video["title"][:30], e)

                    time.sleep(self.delay_sec)

        return data


class BenchmarkReportGenerator:
    """ベンチマーク Markdown レポート生成"""

    def __init__(self, config, benchmarks_dir: Path, today: date):
        self.config = config
        self.benchmarks_dir = benchmarks_dir
        self.today = today

    def generate_markdown(self, data: dict) -> dict[str, str]:
        """収集データから Markdown レポートを生成する。

        Returns:
            {slug: markdown_content, "common-patterns": ..., "README": ...}
        """
        md_map = {}

        for channel in data.get("channels", []):
            md_map[channel["slug"]] = _render_managed_report(self._generate_channel_md(channel))

        # common-patterns は全チャンネルのデータが必要
        if data.get("channels"):
            md_map["common-patterns"] = self._generate_common_patterns(data)
            md_map["README"] = self._generate_readme(data)

        return md_map

    def write_markdown(self, md_map: dict[str, str]):
        """Markdown ファイルを事前検証後に一括で原子的に書き出す。"""
        self.benchmarks_dir.mkdir(parents=True, exist_ok=True)
        contents = {}
        for key, content in md_map.items():
            path = self.benchmarks_dir / f"{key}.md"
            if _GENERATED_START in content:
                generated = _extract_marker_region(content, _GENERATED_START, _GENERATED_END, path)
                content = _render_managed_report(generated, _existing_user_content(path))
            contents[path] = content

        if not contents:
            return
        write_text_files_transactionally(contents)
        for path in contents:
            logger.info("Markdown 更新: %s", path.name)

    def generate_playlists_markdown(self, playlists_results: list[dict]) -> dict[str, str]:
        """再生リスト収集結果から {slug}-playlists.md コンテンツを生成する。

        Returns:
            {f"{slug}-playlists": markdown_content}
        """
        md_map = {}
        for pl_result in playlists_results:
            slug = pl_result["slug"]
            md_map[f"{slug}-playlists"] = self._generate_playlists_md(pl_result)
        return md_map

    def _generate_playlists_md(self, channel: dict) -> str:
        """1チャンネル分の再生リスト構成 Markdown を生成する。"""
        playlists = channel.get("playlists", [])
        collected_at = channel.get("playlists_collected_at", "")

        lines = [
            f"# {channel['name']} — 再生リスト構成",
            "",
            f"*取得日: {collected_at}*",
            "",
            f"再生リスト総数: **{len(playlists)}**",
            "",
            "## 再生リスト一覧",
            "",
            "| # | タイトル | 動画数 | 合計再生 | 平均再生 |",
            "|---|---------|-------|---------|---------|",
        ]

        for i, pl in enumerate(playlists, 1):
            items = pl.get("items", [])
            total_views = sum(it.get("views", 0) for it in items)
            avg_views = round(total_views / len(items)) if items else 0
            title = self._escape_md_table(pl.get("title", ""))
            lines.append(f"| {i} | {title} | {pl.get('item_count', len(items))} | {total_views:,} | {avg_views:,} |")

        # 構成軸の観察メモ（手動追記用プレースホルダー）
        lines.extend(
            [
                "",
                "## 構成軸の観察メモ",
                "",
                "<!-- TODO: 分類軸候補（time / mood / activity / season）を上記一覧から考察して追記 -->",
                "",
                "## 再生リスト別詳細",
                "",
            ]
        )

        # 各再生リストの動画一覧
        for i, pl in enumerate(playlists, 1):
            title = pl.get("title", "")
            description = pl.get("description", "").strip()
            items = sorted(pl.get("items", []), key=lambda x: x.get("position", 0))

            lines.append(f"### {i}. {title}")
            lines.append("")
            lines.append(f"- playlist_id: `{pl.get('playlist_id', '')}`")
            lines.append(f"- 動画数: {pl.get('item_count', len(items))}")
            if description:
                # 長すぎる説明は最初の数行まで
                desc_short = "\n".join(description.splitlines()[:3])
                lines.append(f"- 説明: {desc_short}")
            lines.append("")

            if items:
                lines.append("| pos | タイトル | 再生数 | 高評価 | 尺 |")
                lines.append("|-----|---------|-------|-------|-----|")
                for item in items:
                    pos = item.get("position", 0)
                    item_title = self._escape_md_table(item.get("title", ""))
                    views = item.get("views", 0)
                    likes = item.get("likes", 0)
                    duration = item.get("duration_display", "—")
                    lines.append(f"| {pos} | {item_title} | {views:,} | {likes:,} | {duration} |")
                lines.append("")
            else:
                lines.append("*動画なし*")
                lines.append("")

        return "\n".join(lines)

    # --- 内部メソッド ---

    @staticmethod
    def _escape_md_table(text: str) -> str:
        """Markdown テーブル内のパイプ文字をエスケープする。"""
        return text.replace("|", "\\|")

    @staticmethod
    def _utc_to_jst_time(utc_str: str) -> str:
        """UTC ISO 8601 タイムスタンプから JST 時刻（HH:MM）を返す。"""
        if not utc_str or len(utc_str) < 16:
            return "—"
        try:
            from datetime import datetime, timedelta, timezone

            utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            jst_dt = utc_dt.astimezone(timezone(timedelta(hours=9)))
            return jst_dt.strftime("%H:%M")
        except (ValueError, TypeError):
            return "—"

    def _generate_channel_md(self, channel: dict) -> str:
        """個別チャンネルの Markdown を生成する。"""
        videos = channel.get("videos", [])
        long_videos = [v for v in videos if not is_short_benchmark_video(v)]
        posting = channel.get("posting_trend", {})

        # ヘッダー
        lines = [
            f"# {channel['name']}",
            "",
            f"*最終更新: {channel['collected_at']}*",
            "",
            "## チャンネル概要",
            "",
            "| 項目 | 値 |",
            "|------|-----|",
            f"| チャンネル名 | {channel['name']} |",
            f"| チャンネルID | {channel['channel_id']} |",
            f"| 登録者数 | {channel['subscribers']:,} |",
            f"| 動画数 | {channel['total_videos']} |",
            f"| CLM との関係 | {channel.get('relationship', '')} |",
            "",
        ]

        # 動画テーブル（ベンチマーク対象＝視聴数しきい値以上）
        min_views = channel.get("min_views_threshold", 10000)
        scanned = channel.get("scanned_count", len(videos))

        if not videos:
            lines.extend(
                [
                    f"## ベンチマーク対象（再生数 {min_views:,}+）",
                    "",
                    f"> **該当動画なし** — 直近 {scanned} 本のいずれも {min_views:,} 再生未満でした。",
                    "",
                ]
            )
            return "\n".join(lines)

        lines.extend(
            [
                f"## ベンチマーク対象（再生数 {min_views:,}+ / 直近 {scanned} 本走査中 {len(videos)} 件該当）",
                "",
                "| # | 公開日 | 時刻(JST) | タイトル | 再生数 | 日次再生 | 高評価 | コメント | ER% | 尺 |",
                "|---|--------|-----------|---------|-------|---------|-------|---------|-----|-----|",
            ]
        )

        max_views = max((lv["views"] for lv in long_videos), default=0)
        for i, v in enumerate(videos, 1):
            title = self._escape_md_table(v["title"])
            views_str = f"{v['views']:,}"
            if long_videos and v["views"] == max_views:
                title = f"**{title}**"
                views_str = f"**{views_str}**"
            jst_time = self._utc_to_jst_time(v.get("published_at_utc", ""))
            lines.append(
                f"| {i} | {v['published_at']} | {jst_time} | {title} | {views_str} "
                f"| {v['daily_views']:.0f} | {v['likes']:,} | {v['comments']:,} "
                f"| {v['engagement_rate']:.1f}% | {v['duration_display']} |"
            )

        lines.append("")

        # 集計
        if long_videos:
            lines.extend(
                [
                    f"**Long動画平均再生数**: {channel['avg_views']:,} / 本",
                    f"**平均日次再生数**: {channel['avg_daily_views']:.0f}",
                    f"**平均エンゲージメント率**: {channel['avg_engagement_rate']:.1f}%",
                ]
            )
        if posting.get("average_interval"):
            trend_label = {"accelerating": "加速傾向", "decelerating": "減速傾向", "stable": "安定"}.get(
                posting["trend"], "不明"
            )
            lines.append(f"**投稿頻度**: 平均{posting['average_interval']:.1f}日おき（{trend_label}）")
        lines.append("")

        # 投稿間隔トレンド
        if posting.get("intervals_days"):
            lines.extend(
                [
                    "## 投稿間隔トレンド",
                    "",
                    f"平均間隔: {posting['average_interval']:.1f}日（{trend_label}）",
                    f"直近{len(posting['intervals_days'])}本: "
                    + " → ".join(f"{d}d" for d in posting["intervals_days"]),
                    "",
                ]
            )

        # タグ分析
        top_tags = channel.get("top_tags", [])
        if top_tags:
            lines.extend(
                [
                    "## タグ分析",
                    "",
                    "頻出タグ: " + ", ".join(f"{t['tag']} ({t['count']}/{len(videos)}本)" for t in top_tags[:10]),
                    "",
                ]
            )

        # トレンド分析
        lines.extend(["## トレンド分析", ""])
        lines.append("### 高パフォーマンス動画（再生数上位）")
        sorted_videos = sorted(long_videos, key=lambda v: v["views"], reverse=True)
        for v in sorted_videos[:5]:
            lines.append(
                f"- **{v['views']:,}再生** (日次{v['daily_views']:.0f}, ER {v['engagement_rate']:.1f}%): "
                f"「{self._escape_md_table(v['title'])}」— {v['duration_display']}"
            )
        lines.append("")

        self._append_description_ttp_samples(lines, long_videos)

        # サムネイル分析
        analyzed = [
            v
            for v in videos
            if v.get("thumbnail_analysis")
            and isinstance(v["thumbnail_analysis"], dict)
            and "composition" in v.get("thumbnail_analysis", {})
        ]
        if analyzed:
            lines.extend(["## サムネイル分析（Gemini API）", ""])
            for i, v in enumerate(analyzed[:5], 1):
                a = v["thumbnail_analysis"]
                lines.extend(
                    [
                        f'### {i}. "{self._escape_md_table(v["title"])}" ({v["views"]:,}再生)',
                        f"- **構図**: {a.get('composition', 'N/A')}",
                        f"- **配色**: {a.get('color_palette', 'N/A')}",
                        f"- **テキスト**: {a.get('text_placement', 'N/A')}",
                        f"- **キャラ活動**: {a.get('character_activity', 'N/A')}",
                        f"- **雰囲気**: {a.get('atmosphere', 'N/A')}",
                        f"- **強み**: {', '.join(a.get('strengths', []))}",
                        "",
                    ]
                )

        return "\n".join(lines)

    def _append_description_ttp_samples(self, lines: list[str], videos: list[dict]) -> None:
        description_videos = [
            v
            for v in videos
            if isinstance(v.get(_VIDEO_DESCRIPTION_FIELD), str) and v[_VIDEO_DESCRIPTION_FIELD].strip()
        ]
        if not description_videos:
            return

        lines.extend([f"## {_DESCRIPTION_TTP_SECTION_TITLE}", ""])
        for i, video in enumerate(description_videos[:_DESCRIPTION_TTP_SAMPLE_LIMIT], 1):
            description = video[_VIDEO_DESCRIPTION_FIELD].strip()
            fence = _markdown_code_fence(description)
            lines.extend(
                [
                    f'### {i}. "{self._escape_md_table(video["title"])}" ({video["views"]:,}再生)',
                    "",
                    f"{fence}text",
                    description,
                    fence,
                    "",
                ]
            )

    def _generate_common_patterns(self, data: dict) -> str:
        """common-patterns.md を生成する。

        既存の手書きパターンは保持しつつ、運用ベンチマークの数値を更新する。
        """
        channels = data.get("channels", [])

        # 既存ファイルを読み込み（手書き部分を保持）
        common_path = self.benchmarks_dir / "common-patterns.md"
        if common_path.exists():
            existing = common_path.read_text(encoding="utf-8")
            # 「運用ベンチマーク」セクション以降を差し替え
            marker = "## 運用ベンチマーク"
            if marker in existing:
                prefix = existing[: existing.index(marker)]
            else:
                prefix = existing.rstrip() + "\n\n"
        else:
            prefix = self._generate_common_patterns_prefix()

        # 運用ベンチマーク テーブル生成
        lines = [
            f"## 運用ベンチマーク（{self.today.isoformat()} データ実証）",
            "",
            "| 指標 | " + " | ".join(ch["name"] for ch in channels) + " | CLM 目標 |",
            "|------|" + "|".join("---" for _ in channels) + "|----------|",
        ]

        # 各指標行
        metrics = [
            ("平均再生数", lambda ch: f"{ch.get('avg_views', 0):,}"),
            ("平均日次再生", lambda ch: f"{ch.get('avg_daily_views', 0):.0f}"),
            ("平均ER%", lambda ch: f"{ch.get('avg_engagement_rate', 0):.1f}%"),
            ("投稿頻度", lambda ch: f"{ch.get('posting_trend', {}).get('average_interval', 0):.1f}日おき"),
        ]
        for label, fn in metrics:
            row = f"| {label} | " + " | ".join(fn(ch) for ch in channels) + " | — |"
            lines.append(row)

        lines.append("")

        # 投稿時間帯分析
        lines.extend(
            [
                f"## 投稿時間帯（JST）（{self.today.isoformat()} データ実証）",
                "",
            ]
        )
        for ch in channels:
            videos = ch.get("videos", [])
            jst_times = []
            for v in videos:
                utc_str = v.get("published_at_utc", "")
                if utc_str and len(utc_str) >= 16:
                    t = self._utc_to_jst_time(utc_str)
                    if t != "—":
                        jst_times.append(t)
            if jst_times:
                lines.append(f"### {ch['name']}")
                lines.append("")
                lines.append("| 動画 | 投稿時刻(JST) | 再生数 |")
                lines.append("|------|---------------|--------|")
                for v in videos:
                    t = self._utc_to_jst_time(v.get("published_at_utc", ""))
                    if t != "—":
                        title_short = self._escape_md_table(v["title"][:40])
                        lines.append(f"| {title_short} | {t} | {v['views']:,} |")
                lines.append("")

        lines.append("")

        return prefix + "\n".join(lines) + "\n"

    def _generate_common_patterns_prefix(self) -> str:
        """common-patterns.md の初期テンプレート"""
        return f"""# 共通成功パターン

*最終更新: {self.today.isoformat()}*

## 分析対象

このファイルは `/channel-research --benchmark` スキルで自動更新される。
手書きのパターン分析は「運用ベンチマーク」セクションより上に記載すること。

"""

    def _generate_readme(self, data: dict) -> str:
        """README.md を生成する。"""
        channels = data.get("channels", [])

        lines = [
            "# Benchmarks - 競合チャンネル分析",
            "",
            "CLM のコンテンツ戦略・サムネイル設計・タイトル最適化の参考となる"
            "ベンチマークチャンネル情報を一元管理する。",
            "",
            "## ディレクトリ構成",
            "",
            "```",
            "benchmarks/",
            "├── README.md                      # このファイル（インデックス）",
            "├── common-patterns.md             # 全チャンネル共通の成功パターン",
        ]
        bench_channels = self.config.analytics.benchmark.channels
        for i, ch in enumerate(bench_channels):
            prefix = "└──" if i == len(bench_channels) - 1 else "├──"
            padding = max(1, 25 - len(ch["slug"]))
            lines.append(f"{prefix} {ch['slug']}.md{' ' * padding}# {ch['name']} 分析")
        lines.extend(["```", "", "## チャンネル一覧", ""])

        # テーブル
        lines.extend(
            [
                "| チャンネル | 登録者 | 動画数 | ポジション | 平均再生 | 平均ER% |",
                "|---|---|---|---|---|---|",
            ]
        )
        for ch in channels:
            lines.append(
                f"| [{ch['name']}]({ch['slug']}.md) "
                f"| {ch['subscribers']:,} | {ch['total_videos']} "
                f"| {ch.get('relationship', '')} "
                f"| {ch.get('avg_views', 0):,} | {ch.get('avg_engagement_rate', 0):.1f}% |"
            )
        lines.append("")

        # 更新履歴
        lines.extend(
            [
                "## 更新履歴",
                "",
                f"- {self.today.isoformat()}: benchmark_collector.py で最新データ取得"
                "（拡充版: ER%, 日次再生, タグ, サムネイル分析）",
            ]
        )

        # 既存の更新履歴を保持
        readme_path = self.benchmarks_dir / "README.md"
        if readme_path.exists():
            existing = readme_path.read_text(encoding="utf-8")
            history_match = re.search(r"## 更新履歴\n\n(- .+)", existing, re.DOTALL)
            if history_match:
                old_entries = history_match.group(1).strip().split("\n")
                # 今日のエントリを除外して追記
                for entry in old_entries:
                    if not entry.startswith(f"- {self.today.isoformat()}"):
                        lines.append(entry)

        lines.append("")
        return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = CompetitorArgumentParser(description="競合チャンネルのベンチマークデータ収集・分析")
    parser.add_argument("--force", action="store_true", help="鮮度に関わらず全チャンネル更新")
    parser.add_argument("--json-only", action="store_true", help="JSON のみ出力（Markdown 生成スキップ）")
    parser.add_argument("--no-thumbnails", action="store_true", help="サムネイルDL・分析をスキップ")
    parser.add_argument("--keep-thumbnails", action="store_true", help="（非推奨: サムネイルは常に保持されます）")
    parser.add_argument("-y", "--yes", action="store_true", help="確認プロンプトをスキップ")
    parser.add_argument("--competitor", type=str, default=None, help="単一競合の slug を指定")
    parser.add_argument(
        "--playlists",
        action="store_true",
        help="再生リスト構成のみ収集（既存動画ベンチマークはスキップ）。--competitor 必須",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログ出力")
    return parser


def main():
    args = _build_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    collector = BenchmarkCollector()

    if not collector.config.analytics.benchmark.channels:
        print("[ERROR] config/channel/analytics.json に benchmark.channels が設定されていません")
        sys.exit(1)

    # --- 再生リスト収集モード ---
    if args.playlists:
        if not args.competitor:
            print("[ERROR] --playlists には --competitor <slug> の指定が必須です")
            print("        （誤って全チャンネル分の API クォータを消費しないため）")
            sys.exit(1)

        targets = [ch for ch in collector.config.analytics.benchmark.channels if ch["slug"] == args.competitor]
        if not targets:
            print(f"[ERROR] 競合が見つかりません: {args.competitor}")
            sys.exit(1)

        print("\n=== Benchmark Playlists Collector ===")
        print(f"対象: {targets[0]['name']} ({args.competitor})")
        print()

        collector.initialize()

        playlists_results = []
        for ch in targets:
            logger.info("再生リスト収集中: %s (%s)", ch["name"], ch["id"])
            result = collector.collect_playlists(ch)
            playlists_results.append(result)

        json_path = collector.merge_playlists_into_json(playlists_results)
        print(f"JSON 保存: {json_path}")

        if not args.json_only:
            reporter = BenchmarkReportGenerator(collector.config, collector.benchmarks_dir, collector.today)
            md_map = reporter.generate_playlists_markdown(playlists_results)
            reporter.write_markdown(md_map)
            for key in md_map:
                print(f"Markdown 更新: {key}.md")

        # サマリー
        print()
        print("=== 結果サマリー ===")
        for r in playlists_results:
            playlists = r.get("playlists", [])
            total_videos = sum(len(p.get("items", [])) for p in playlists)
            total_views = sum(it.get("views", 0) for p in playlists for it in p.get("items", []))
            print(f"  {r['name']}: 再生リスト {len(playlists)}件, 総動画 {total_videos}本, 合計再生 {total_views:,}")
        print()
        return

    if args.keep_thumbnails:
        logger.info("--keep-thumbnails: サムネイルは常に保持されるようになりました（このフラグは不要）")

    analyze_thumbnails = collector.benchmark_config.get("gemini_thumbnail_analysis", False)
    scan_recent = collector.benchmark_config.get("scan_recent", _DEFAULT_SCAN_RECENT)
    num_channels = len(collector.config.analytics.benchmark.channels)

    print("\n=== Benchmark Collector ===")
    print(f"  対象チャンネル: {num_channels} 件")
    print(f"  走査プール: {scan_recent} 本/ch")
    print(
        "  Data API quota 上限目安: "
        f"{estimate_collection_quota_units(channel_count=num_channels, scan_recent=scan_recent)} units"
        "（全対象を更新する場合）"
    )
    print(f"  鮮度基準: {collector.benchmark_config.get('freshness_days', 3)} 日")
    if args.no_thumbnails:
        print("  サムネイル分析: OFF（--no-thumbnails）")
    elif analyze_thumbnails:
        model = collector.benchmark_config.get("thumbnail_analysis", {}).get("model", _DEFAULT_THUMBNAIL_ANALYSIS_MODEL)
        print(f"  サムネイル分析: Gemini ({model}) — Vertex AI 課金が発生します")
    else:
        print("  サムネイル分析: ON（エージェント — 追加課金なし）")
    print()

    if not args.yes and not args.force:
        try:
            answer = input("続行しますか？ [Y/n] ").strip().lower()
            if answer and answer != "y":
                print("キャンセルしました")
                sys.exit(0)
        except (EOFError, KeyboardInterrupt):
            print("\nキャンセルしました")
            sys.exit(0)

    # 認証
    collector.initialize()

    # 収集
    try:
        data = collector.collect_all(force=args.force, competitor_slug=args.competitor)
    except (ConfigError, YouTubeAPIError) as e:
        print(f"[ERROR] ベンチマーク収集に失敗しました: {e}")
        sys.exit(1)

    if data.get("skipped"):
        print("すべてのベンチマークは最新です。--force で強制更新できます。")
        sys.exit(0)

    if not data.get("channels"):
        print("[ERROR] データ収集に失敗しました")
        sys.exit(1)

    # サムネイルDL（常時、--no-thumbnails でスキップ）
    if not args.no_thumbnails:
        collector.download_thumbnails(data, force=args.force)

    # Gemini 分析（明示的に ON にした場合のみ）
    if analyze_thumbnails and not args.no_thumbnails:
        print("サムネイル分析中（Gemini API）...")
        analyzer = BenchmarkThumbnailAnalyzer(collector.benchmarks_dir)
        data = analyzer.analyze_thumbnails(data, keep=True)

    # JSON 保存
    if args.competitor:
        json_path = collector.save_json(data, competitor_slug=args.competitor)
    else:
        json_path = collector.save_json(data)
    print(f"JSON 保存: {json_path}")

    # Markdown 生成
    if not args.json_only:
        reporter = BenchmarkReportGenerator(collector.config, collector.benchmarks_dir, collector.today)
        md_map = reporter.generate_markdown(data)
        reporter.write_markdown(md_map)
        print(f"Markdown 更新: {len(md_map)} ファイル")

    # サマリー
    print()
    print("=== 結果サマリー ===")
    for ch in data["channels"]:
        videos_count = len(ch.get("videos", []))
        analyzed = sum(1 for v in ch.get("videos", []) if v.get("thumbnail_analysis"))
        print(
            f"  {ch['name']}: {videos_count}本取得, 平均{ch.get('avg_views', 0):,}再生, "
            f"ER {ch.get('avg_engagement_rate', 0):.1f}%, サムネイル分析 {analyzed}/{videos_count}"
        )
    print()


if __name__ == "__main__":
    main()
