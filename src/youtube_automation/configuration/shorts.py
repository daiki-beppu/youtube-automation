"""ショート設定の責務別 dataclass.

`config/channel/shorts.json` でチャンネル運用設定（Shorts 機能の有効化・公開時刻・
投稿本数・投稿間隔・モード）を集約する。生成側のパラメータ（尺・フェード・フォント）
は別途 `.claude/skills/short/config.default.yaml` などの skill-config に置く。

未配置の場合は `Shorts.enabled = False`（オプトイン）で `ShortUploader` が起動時に
拒否する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_PUBLISH_TIME = "08:00"
DEFAULT_MIN_HOURS_BETWEEN_SHORTS = 24


@dataclass(frozen=True)
class ShortsCollection:
    """collection 型（`/short`）固有の生成設定."""

    default_count: int = 3
    chapter_offset_sec: int = 30


@dataclass(frozen=True)
class ShortsRelease:
    """release 型（`/short-release`）固有の生成設定."""

    languages: tuple[str, ...] = ("jp", "en")
    start_sec: int = 30
    duration_sec: int = 40


@dataclass(frozen=True)
class Shorts:
    """`shorts` セクション.

    Fields:
        enabled: Shorts 機能をこのチャンネルで使うかどうか（オプトイン）.
            False のとき `ShortUploader.__init__` が `UploadError` を投げる.
        publish_time: 本編公開の翌日に Shorts を公開する時刻（HH:MM, チャンネルタイムゾーン）.
        min_hours_between_shorts_per_collection: 同一チャンネル内 Shorts 投稿の最低間隔.
        mode: Shorts モード判定. "auto" は `youtube.content_model.type` に従う.
            明示指定する場合は "collection" / "release" のいずれか.
        collection: collection 型用パラメータ.
        release: release 型用パラメータ.
    """

    enabled: bool = False
    publish_time: str = DEFAULT_PUBLISH_TIME
    min_hours_between_shorts_per_collection: int = DEFAULT_MIN_HOURS_BETWEEN_SHORTS
    mode: str = "auto"
    collection: ShortsCollection = field(default_factory=ShortsCollection)
    release: ShortsRelease = field(default_factory=ShortsRelease)
