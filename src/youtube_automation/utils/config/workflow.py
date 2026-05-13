"""ワークフロー設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PostUpload:
    """`post_upload` セクション（optional）.

    Shorts 公開時刻のみ管理する。Shorts スキルから
    CC（Complete Collection）公開の翌日 `short_publish_time` を
    publishAt として算出するために参照される。
    """

    short_publish_time: str = "08:00"


@dataclass(frozen=True)
class Workflow:
    """ワークフロー責務の合成（`workflow` / `post_upload` セクション）.

    新しいフィールドを追加するときは本 dataclass と loader の `_build_workflow`
    を更新する。必須キーは `_REQUIRED_KEYS_BY_SECTION` にも登録する。
    """

    post_upload: PostUpload = field(default_factory=PostUpload)
