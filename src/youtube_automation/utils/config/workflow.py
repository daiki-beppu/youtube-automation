"""ワークフロー設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Workflow:
    """ワークフロー責務の合成（`workflow` セクション）.

    v4.0.0 で short 関連フィールド（`post_upload` / `short`）を撤去した。
    将来フィールドが増えたら本 dataclass に追加し、`_REQUIRED_KEYS_BY_SECTION` に
    必須キーを登録すること。
    """
