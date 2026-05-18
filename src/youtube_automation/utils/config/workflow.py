"""ワークフロー設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field

# Shorts 公開時刻のデフォルト（CC 公開の翌日 08:00 JST）。
# `_build_workflow` の loader と `ShortUploader._calculate_short_publish_at`
# の双方が同じ default を使えるよう、定数として 1 箇所で定義する。
DEFAULT_SHORT_PUBLISH_TIME = "08:00"


@dataclass(frozen=True)
class PostUpload:
    """`workflow.post_upload` セクション（Shorts スケジュール公開時刻）.

    v4.0.0 で撤去したが、v5 で Shorts 投稿スケジュール用に復活。
    現状は `short_publish_time` のみ。CC の公開日 + 1day の何時に Shorts を
    公開するか（HH:MM）を保持する。
    """

    short_publish_time: str = DEFAULT_SHORT_PUBLISH_TIME


@dataclass(frozen=True)
class Workflow:
    """ワークフロー責務の合成（`workflow` セクション）.

    v5 で `post_upload` を再導入。将来 community / pinned_comment 等を追加する場合も
    必ず本 dataclass にネストし、loader (`_build_workflow`) で組み立てる。
    """

    post_upload: PostUpload = field(default_factory=PostUpload)
