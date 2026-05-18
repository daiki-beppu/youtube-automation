"""ワークフロー設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Workflow:
    """ワークフロー責務の合成（`workflow` セクション）.

    現状は空。将来 workflow.json で扱うフィールドが増えたら本 dataclass に追加し、
    `_REQUIRED_KEYS_BY_SECTION` に必須キーを登録する。

    Shorts スケジュール公開時刻は `Shorts.publish_time`（`config/channel/shorts.json`）に
    移動した — `workflow.post_upload.short_publish_time` は使わない。
    """
