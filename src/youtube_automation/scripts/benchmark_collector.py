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
    python3 ../../automation/benchmark_collector.py --channel world-fantasia  # 単一チャンネル
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

from youtube_automation.utils.benchmark_analyzer import (  # noqa: E402
    compute_daily_views,
    compute_engagement_rate,
    compute_posting_intervals,
    extract_description_keywords,
    parse_iso_duration,
)
from youtube_automation.utils.channel_config import ChannelConfig  # noqa: E402
from youtube_automation.utils.exceptions import ConfigError  # noqa: E402
from youtube_automation.utils.secrets import get_gemini_api_key  # noqa: E402
from youtube_automation.utils.youtube_service import get_youtube  # noqa: E402

logger = logging.getLogger(__name__)

# サムネイル分析で使用する Gemini モデル（テキスト出力 + 画像入力）
THUMBNAIL_ANALYSIS_MODEL = "gemini-2.5-flash"
THUMBNAIL_ANALYSIS_DELAY = 5  # 秒（レート制限対策）

THUMBNAIL_ANALYSIS_PROMPT = """Analyze this YouTube thumbnail for a fantasy/celtic ambient music channel.
Return ONLY valid JSON (no markdown, no code fences):
{
  "composition": "brief description of layout, focal points, and character positioning",
  "color_palette": "dominant colors and overall mood/tone",
  "text_placement": "how title text is positioned and styled",
  "character_activity": "what the character is doing (or 'none' if no character)",
  "atmosphere": "overall mood, lighting, and environmental effects",
  "strengths": ["list", "of", "effective", "elements"]
}"""


class BenchmarkCollector:
    """競合チャンネルのベンチマークデータ収集（YouTube Data API）"""

    def __init__(self):
        self.config = ChannelConfig.load()
        self.youtube = None
        self.benchmark_config = self.config.benchmark_config
        self.channel_dir = ChannelConfig.channel_dir()
        self.benchmarks_dir = self.channel_dir / "docs" / "benchmarks"
        self.data_dir = self.channel_dir / "data"
        self.today = date.today()

    def initialize(self):
        """YouTube API 認証を実行する。"""
        logger.info("YouTube API 認証中...")
        self.youtube = get_youtube()
        logger.info("認証完了")

    def check_freshness(self) -> list[dict]:
        """更新が必要なチャンネルを返す。

        Returns:
            freshness_days 以上未更新のチャンネル情報リスト
        """
        freshness_days = self.benchmark_config.get("freshness_days", 3)
        stale_channels = []

        for ch in self.config.benchmark_channels:
            md_path = self.benchmarks_dir / f"{ch['slug']}.md"
            if not md_path.exists():
                logger.info("ファイル未作成: %s → 初回収集対象", ch["slug"])
                stale_channels.append(ch)
                continue

            mtime = datetime.fromtimestamp(md_path.stat().st_mtime).date()
            age = (self.today - mtime).days
            if age >= freshness_days:
                logger.info("%s: %d日前に更新 → 更新対象", ch["slug"], age)
                stale_channels.append(ch)
            else:
                logger.info("%s: %d日前に更新 → 最新", ch["slug"], age)

        return stale_channels

    def collect_channel(self, channel_info: dict) -> dict:
        """1チャンネル分のデータを YouTube Data API で収集する。

        Args:
            channel_info: benchmark.channels の1要素

        Returns:
            チャンネルデータ辞書（概要 + 動画リスト + 派生指標）
        """
        channel_id = channel_info["id"]
        scan_recent = self.benchmark_config.get("scan_recent", 50)
        min_views = self.benchmark_config.get("min_views", 10000)

        # チャンネル概要
        ch_resp = self.youtube.channels().list(
            part="snippet,statistics,contentDetails",
            id=channel_id,
        ).execute()

        if not ch_resp.get("items"):
            logger.error("チャンネルが見つかりません: %s", channel_id)
            return {}

        ch_item = ch_resp["items"][0]
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

        # 最新動画ID取得（scan_recent 件を走査プールとする）
        # TODO: scan_recent > 50 の場合は nextPageToken によるページング対応
        video_ids: list[str] = []
        page_token: str | None = None
        remaining = scan_recent
        while remaining > 0:
            playlist_resp = self.youtube.playlistItems().list(
                part="contentDetails",
                playlistId=uploads_playlist_id,
                maxResults=min(50, remaining),
                pageToken=page_token,
            ).execute()
            batch_ids = [item["contentDetails"]["videoId"] for item in playlist_resp.get("items", [])]
            video_ids.extend(batch_ids)
            page_token = playlist_resp.get("nextPageToken")
            remaining -= len(batch_ids)
            if not page_token or not batch_ids:
                break

        channel_data["scanned_count"] = len(video_ids)

        if not video_ids:
            logger.warning("動画が見つかりません: %s", channel_info["name"])
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
            videos_resp = self.youtube.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(video_ids[i:i + 50]),
            ).execute()

            for video in videos_resp.get("items", []):
                snippet = video["snippet"]
                stats = video["statistics"]
                content = video["contentDetails"]

                v = {
                    "video_id": video["id"],
                    "title": snippet["title"],
                    "published_at": snippet["publishedAt"][:10],
                    "published_at_utc": snippet["publishedAt"],
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                    "duration_iso": content["duration"],
                    "duration_display": parse_iso_duration(content["duration"]),
                    "tags": snippet.get("tags", []),
                    "description_keywords": extract_description_keywords(snippet.get("description", "")),
                    "thumbnail_url": self._best_thumbnail_url(snippet.get("thumbnails", {})),
                    "thumbnail_analysis": None,
                }
                v["daily_views"] = compute_daily_views(v, self.today)
                v["engagement_rate"] = compute_engagement_rate(v)
                raw_videos.append(v)

        # 視聴数フィルタ（min_views 以上のみベンチマーク対象）
        videos = [v for v in raw_videos if v["views"] >= min_views]
        # 視聴数降順で並べ替え（レポートの可読性向上）
        videos.sort(key=lambda v: v["views"], reverse=True)

        logger.info(
            "%s: 走査 %d 本 → %d 本が %d 再生以上",
            channel_info["name"], len(raw_videos), len(videos), min_views,
        )

        channel_data["videos"] = videos
        channel_data["posting_trend"] = compute_posting_intervals(videos) if videos else {}

        # 集計（フィルタ後の Long 動画のみ対象）
        long_videos = [v for v in videos if not self._is_short(v)]
        if long_videos:
            channel_data["avg_views"] = round(sum(v["views"] for v in long_videos) / len(long_videos))
            channel_data["avg_daily_views"] = round(
                sum(v["daily_views"] for v in long_videos) / len(long_videos), 1
            )
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
        channel_data["top_tags"] = [
            {"tag": tag, "count": count}
            for tag, count in tag_counts.most_common(15)
        ]

        return channel_data

    def collect_all(self, force: bool = False, channel_slug: str | None = None) -> dict:
        """全チャンネル（または指定チャンネル）のデータを収集する。

        Args:
            force: True なら鮮度に関わらず全更新
            channel_slug: 指定時はそのチャンネルのみ

        Returns:
            全チャンネルの収集結果
        """
        if channel_slug:
            targets = [ch for ch in self.config.benchmark_channels if ch["slug"] == channel_slug]
            if not targets:
                logger.error("チャンネルが見つかりません: %s", channel_slug)
                return {"channels": [], "collected_at": self.today.isoformat()}
        elif force:
            targets = list(self.config.benchmark_channels)
        else:
            targets = self.check_freshness()

        if not targets:
            logger.info("更新が必要なチャンネルはありません")
            return {"channels": [], "collected_at": self.today.isoformat(), "skipped": True}

        results = []
        for ch in targets:
            logger.info("収集中: %s (%s)", ch["name"], ch["id"])
            data = self.collect_channel(ch)
            if data:
                results.append(data)

        return {
            "channels": results,
            "collected_at": self.today.isoformat(),
        }

    def save_json(self, data: dict) -> Path:
        """中間 JSON を data/ に保存する。

        Returns:
            保存先パス
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        filename = f"benchmark_{self.today.strftime('%Y%m%d')}.json"
        path = self.data_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info("JSON 保存: %s", path)
        return path

    # --- 内部メソッド ---

    @staticmethod
    def _is_short(video: dict) -> bool:
        """Short 動画かどうかを判定する。"""
        duration = video.get("duration_iso", "")
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
        if not match:
            return False
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        return hours == 0 and minutes < 5

    @staticmethod
    def _best_thumbnail_url(thumbnails: dict) -> str:
        """最高解像度のサムネイルURLを返す。"""
        for key in ("maxres", "standard", "high", "medium", "default"):
            if key in thumbnails:
                return thumbnails[key]["url"]
        return ""


class BenchmarkThumbnailAnalyzer:
    """ベンチマークサムネイルの Gemini 分析"""

    def __init__(self, benchmarks_dir: Path):
        self.benchmarks_dir = benchmarks_dir

    def analyze_thumbnails(self, data: dict, keep: bool = False) -> dict:
        """サムネイル画像をダウンロードして Gemini で分析する。

        Args:
            data: collect_all() の結果
            keep: True ならサムネイル画像を docs/benchmarks/thumbnails/ に保存

        Returns:
            thumbnail_analysis が追加された data
        """
        try:
            get_gemini_api_key()
        except ConfigError:
            logger.warning("GEMINI_API_KEY 未設定 — サムネイル分析をスキップ")
            return data

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            logger.warning("google-genai 未インストール — サムネイル分析をスキップ")
            return data

        client = genai.Client()
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
                            model=THUMBNAIL_ANALYSIS_MODEL,
                            contents=[
                                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                                THUMBNAIL_ANALYSIS_PROMPT,
                            ],
                        )
                        # JSON パース
                        text = response.text.strip()
                        # コードフェンスを除去
                        text = re.sub(r'^```(?:json)?\s*', '', text)
                        text = re.sub(r'\s*```$', '', text)
                        video["thumbnail_analysis"] = json.loads(text)
                        logger.info("サムネイル分析完了: %s", video["title"][:40])
                    except json.JSONDecodeError as e:
                        logger.warning("サムネイル分析JSONパース失敗 [%s]: %s", video["title"][:30], e)
                        video["thumbnail_analysis"] = {
                            "raw": response.text[:500] if 'response' in dir() else str(e)
                        }
                    except Exception as e:
                        logger.warning("サムネイル分析失敗 [%s]: %s", video["title"][:30], e)

                    time.sleep(THUMBNAIL_ANALYSIS_DELAY)

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
            md_map[channel["slug"]] = self._generate_channel_md(channel)

        # common-patterns は全チャンネルのデータが必要
        if data.get("channels"):
            md_map["common-patterns"] = self._generate_common_patterns(data)
            md_map["README"] = self._generate_readme(data)

        return md_map

    def write_markdown(self, md_map: dict[str, str]):
        """Markdown ファイルを書き出す。"""
        self.benchmarks_dir.mkdir(parents=True, exist_ok=True)

        for key, content in md_map.items():
            path = self.benchmarks_dir / f"{key}.md"
            path.write_text(content, encoding="utf-8")
            logger.info("Markdown 更新: %s", path.name)

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

    @staticmethod
    def _is_short(video: dict) -> bool:
        """Short 動画かどうかを判定する（レポート生成時のフィルタ用）。"""
        duration = video.get("duration_iso", "")
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
        if not match:
            return False
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        return hours == 0 and minutes < 5

    def _generate_channel_md(self, channel: dict) -> str:
        """個別チャンネルの Markdown を生成する。"""
        videos = channel.get("videos", [])
        long_videos = [v for v in videos if not self._is_short(v)]
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
            lines.extend([
                f"## ベンチマーク対象（再生数 {min_views:,}+）",
                "",
                f"> **該当動画なし** — 直近 {scanned} 本のいずれも {min_views:,} 再生未満でした。",
                "",
            ])
            return "\n".join(lines)

        lines.extend([
            f"## ベンチマーク対象（再生数 {min_views:,}+ / 直近 {scanned} 本走査中 {len(videos)} 件該当）",
            "",
            "| # | 公開日 | 時刻(JST) | タイトル | 再生数 | 日次再生 | 高評価 | コメント | ER% | 尺 |",
            "|---|--------|-----------|---------|-------|---------|-------|---------|-----|-----|",
        ])

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
            lines.extend([
                f"**Long動画平均再生数**: {channel['avg_views']:,} / 本",
                f"**平均日次再生数**: {channel['avg_daily_views']:.0f}",
                f"**平均エンゲージメント率**: {channel['avg_engagement_rate']:.1f}%",
            ])
        if posting.get("average_interval"):
            trend_label = {"accelerating": "加速傾向", "decelerating": "減速傾向", "stable": "安定"}.get(
                posting["trend"], "不明"
            )
            lines.append(f"**投稿頻度**: 平均{posting['average_interval']:.1f}日おき（{trend_label}）")
        lines.append("")

        # 投稿間隔トレンド
        if posting.get("intervals_days"):
            lines.extend([
                "## 投稿間隔トレンド",
                "",
                f"平均間隔: {posting['average_interval']:.1f}日（{trend_label}）",
                f"直近{len(posting['intervals_days'])}本: "
                + " → ".join(f"{d}d" for d in posting["intervals_days"]),
                "",
            ])

        # タグ分析
        top_tags = channel.get("top_tags", [])
        if top_tags:
            lines.extend([
                "## タグ分析",
                "",
                "頻出タグ: "
                + ", ".join(f"{t['tag']} ({t['count']}/{len(videos)}本)" for t in top_tags[:10]),
                "",
            ])

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

        # サムネイル分析
        analyzed = [
            v for v in videos
            if v.get("thumbnail_analysis") and isinstance(v["thumbnail_analysis"], dict)
            and "composition" in v.get("thumbnail_analysis", {})
        ]
        if analyzed:
            lines.extend(["## サムネイル分析（Gemini API）", ""])
            for i, v in enumerate(analyzed[:5], 1):
                a = v["thumbnail_analysis"]
                lines.extend([
                    f"### {i}. \"{self._escape_md_table(v['title'])}\" ({v['views']:,}再生)",
                    f"- **構図**: {a.get('composition', 'N/A')}",
                    f"- **配色**: {a.get('color_palette', 'N/A')}",
                    f"- **テキスト**: {a.get('text_placement', 'N/A')}",
                    f"- **キャラ活動**: {a.get('character_activity', 'N/A')}",
                    f"- **雰囲気**: {a.get('atmosphere', 'N/A')}",
                    f"- **強み**: {', '.join(a.get('strengths', []))}",
                    "",
                ])

        return "\n".join(lines)

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
                prefix = existing[:existing.index(marker)]
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
        lines.extend([
            f"## 投稿時間帯（JST）（{self.today.isoformat()} データ実証）",
            "",
        ])
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

このファイルは `/benchmark` スキルで自動更新される。
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
        bench_channels = self.config.benchmark_channels
        for i, ch in enumerate(bench_channels):
            prefix = "└──" if i == len(bench_channels) - 1 else "├──"
            padding = max(1, 25 - len(ch['slug']))
            lines.append(f"{prefix} {ch['slug']}.md{' ' * padding}# {ch['name']} 分析")
        lines.extend(["```", "", "## チャンネル一覧", ""])

        # テーブル
        lines.extend([
            "| チャンネル | 登録者 | 動画数 | ポジション | 平均再生 | 平均ER% |",
            "|---|---|---|---|---|---|",
        ])
        for ch in channels:
            lines.append(
                f"| [{ch['name']}]({ch['slug']}.md) "
                f"| {ch['subscribers']:,} | {ch['total_videos']} "
                f"| {ch.get('relationship', '')} "
                f"| {ch.get('avg_views', 0):,} | {ch.get('avg_engagement_rate', 0):.1f}% |"
            )
        lines.append("")

        # 更新履歴
        lines.extend([
            "## 更新履歴",
            "",
            f"- {self.today.isoformat()}: benchmark_collector.py で最新データ取得"
            "（拡充版: ER%, 日次再生, タグ, サムネイル分析）",
        ])

        # 既存の更新履歴を保持
        readme_path = self.benchmarks_dir / "README.md"
        if readme_path.exists():
            existing = readme_path.read_text(encoding="utf-8")
            history_match = re.search(r'## 更新履歴\n\n(- .+)', existing, re.DOTALL)
            if history_match:
                old_entries = history_match.group(1).strip().split("\n")
                # 今日のエントリを除外して追記
                for entry in old_entries:
                    if not entry.startswith(f"- {self.today.isoformat()}"):
                        lines.append(entry)

        lines.append("")
        return "\n".join(lines)


def find_latest_benchmark_json(data_dir: Path) -> Path | None:
    """最新のベンチマーク JSON を返す。"""
    files = sorted(data_dir.glob("benchmark_*.json"), reverse=True)
    return files[0] if files else None


def load_benchmark_videos(data_dir: Path, min_views: int = 10000, require_thumbnail: bool = False) -> list[dict]:
    """最新ベンチマーク JSON から min_views 以上の動画を抽出する。

    Returns:
        動画情報リスト（再生数降順）
    """
    benchmark_path = find_latest_benchmark_json(data_dir)
    if not benchmark_path:
        return []

    with open(benchmark_path) as f:
        data = json.load(f)

    targets = []
    seen_ids: set[str] = set()
    for ch in data.get("channels", []):
        channel_name = ch.get("name", "Unknown")
        channel_slug = ch.get("slug", "unknown")
        for v in ch.get("videos", []):
            vid = v.get("video_id", "")
            if vid in seen_ids:
                continue
            seen_ids.add(vid)
            views = int(v.get("views", 0))
            thumb_url = v.get("thumbnail_url", "")
            if views < min_views:
                continue
            if require_thumbnail and not thumb_url:
                continue
            targets.append({
                "video_id": vid,
                "title": v.get("title", ""),
                "views": views,
                "channel_name": channel_name,
                "channel_slug": channel_slug,
                "published_at": v.get("published_at", ""),
                "thumbnail_url": thumb_url,
            })

    targets.sort(key=lambda x: x["views"], reverse=True)
    return targets


def ensure_benchmark_fresh(data_dir: Path | None = None):
    """ベンチマークデータの鮮度を確認し、全チャンネルが1つの JSON に揃った状態を保証する。

    1つでも古い or 欠けているチャンネルがあれば --force で全チャンネル一括更新。
    """
    collector = BenchmarkCollector()
    if data_dir is None:
        data_dir = collector.data_dir

    # 最新 JSON に全チャンネルが含まれているか検証
    need_update = False
    expected_slugs = {ch["slug"] for ch in collector.config.benchmark_channels}

    latest = find_latest_benchmark_json(data_dir)
    if latest:
        with open(latest) as f:
            latest_data = json.load(f)
        found_slugs = {ch.get("slug") for ch in latest_data.get("channels", [])}
        missing = expected_slugs - found_slugs
        if missing:
            logger.info("ベンチマーク: 最新 JSON に %s が欠けている → 全チャンネル更新", missing)
            need_update = True
    else:
        logger.info("ベンチマーク: JSON が存在しない → 全チャンネル更新")
        need_update = True

    if not need_update:
        stale = collector.check_freshness()
        if stale:
            logger.info("ベンチマーク: %d チャンネルが古い → 全チャンネル更新", len(stale))
            need_update = True

    if not need_update:
        logger.info("ベンチマーク: 全チャンネル最新（%d チャンネル）", len(expected_slugs))
        return

    collector.initialize()
    data = collector.collect_all(force=True)

    if data.get("skipped") or not data.get("channels"):
        return

    if collector.benchmark_config.get("analyze_thumbnails", True):
        analyzer = BenchmarkThumbnailAnalyzer(collector.benchmarks_dir)
        data = analyzer.analyze_thumbnails(data, keep=False)

    collector.save_json(data)
    reporter = BenchmarkReportGenerator(collector.config, collector.benchmarks_dir, collector.today)
    md_map = reporter.generate_markdown(data)
    reporter.write_markdown(md_map)
    logger.info("ベンチマーク更新完了")


def main():
    parser = argparse.ArgumentParser(description="競合チャンネルのベンチマークデータ収集・分析")
    parser.add_argument("--force", action="store_true", help="鮮度に関わらず全チャンネル更新")
    parser.add_argument("--json-only", action="store_true", help="JSON のみ出力（Markdown 生成スキップ）")
    parser.add_argument("--no-thumbnails", action="store_true", help="サムネイル分析をスキップ")
    parser.add_argument("--keep-thumbnails", action="store_true", help="サムネイル画像を保持")
    parser.add_argument("--channel", type=str, default=None, help="単一チャンネルの slug を指定")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログ出力")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    collector = BenchmarkCollector()

    if not collector.config.benchmark_channels:
        print("[ERROR] channel_config.json に benchmark.channels が設定されていません")
        sys.exit(1)

    print("\n=== Benchmark Collector ===")
    print(f"対象チャンネル: {len(collector.config.benchmark_channels)}件")
    print(f"鮮度基準: {collector.benchmark_config.get('freshness_days', 3)}日")
    print()

    # 認証
    collector.initialize()

    # 収集
    data = collector.collect_all(force=args.force, channel_slug=args.channel)

    if data.get("skipped"):
        print("すべてのベンチマークは最新です。--force で強制更新できます。")
        sys.exit(0)

    if not data.get("channels"):
        print("[ERROR] データ収集に失敗しました")
        sys.exit(1)

    # サムネイル分析
    analyze_thumbnails = collector.benchmark_config.get("analyze_thumbnails", True)
    if analyze_thumbnails and not args.no_thumbnails:
        print("サムネイル分析中（Gemini API）...")
        analyzer = BenchmarkThumbnailAnalyzer(collector.benchmarks_dir)
        data = analyzer.analyze_thumbnails(data, keep=args.keep_thumbnails)

    # JSON 保存
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
        print(f"  {ch['name']}: {videos_count}本取得, 平均{ch.get('avg_views', 0):,}再生, "
              f"ER {ch.get('avg_engagement_rate', 0):.1f}%, サムネイル分析 {analyzed}/{videos_count}")
    print()


if __name__ == "__main__":
    main()
