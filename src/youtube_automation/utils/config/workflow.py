"""ワークフロー設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PostUpload:
    """`post_upload` セクション（optional）."""

    short_publish_time: str = "08:00"


@dataclass(frozen=True)
class ShortSettings:
    """`short` セクション（optional）.

    S1 時点では未使用のスロット。S3 で実際の参照箇所から必要フィールドを追加する。
    """

    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Workflow:
    """ワークフロー責務の合成（`workflow` / `post_upload` / `short` セクション）."""

    post_upload: PostUpload = field(default_factory=PostUpload)
    short: ShortSettings = field(default_factory=ShortSettings)
