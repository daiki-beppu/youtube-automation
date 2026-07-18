"""ワークフロー設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ApprovalGates:
    """`/wf-next` の承認ゲート設定（後方互換ビュー）.

    正キーは `WfNext.skip_audio_approval` / `WfNext.skip_upload_approval`（#1744）。
    本 dataclass は旧 `wf_next.approval_gates.{audio,upload}` を参照し続ける既存
    consumer 向けの derived view で、loader が常に `audio = not skip_audio_approval` /
    `upload = not skip_upload_approval` として整合させる。

    - `audio`: `prepared` フェーズの音源承認ゲート（2-B）。最終マスター候補検出後、
      `assets.master_audio` を確定して `mastered` フェーズへ進める前に承認。
    - `upload`: `mastered` フェーズのアップロード承認ゲート（3-B）。
      `/video-upload` で YouTube アップロード + live 移行を実行する直前に承認。
    """

    audio: bool = False
    upload: bool = False


@dataclass(frozen=True)
class WfNext:
    """`/wf-next` 関連の設定（`wf_next` セクション）.

    boolean は全て「`True` = 手動工程を省いて自動進行」の向きに統一している（#1744）。

    - `skip_audio_approval`: `True`（既定）のとき、`prepared` フェーズ 2-B の
      音源承認ゲートを設けず自動進行する。`False` にすると `assets.master_audio`
      確定前に skill 側 (`/wf-next`) がユーザー承認を取りに行く。
      旧キー `approval_gates.audio`（true=承認する）の後方互換 alias を loader が解決する。
    - `skip_upload_approval`: `True`（既定）のとき、`mastered` フェーズ 3-B の
      アップロード承認ゲートを設けず自動進行する。`False` にすると `/video-upload`
      実行直前にユーザー承認を取りに行く。旧キー `approval_gates.upload` も同様に alias。
    - `skip_manual_mastering`: `True` のとき、`prepared` フェーズ 2-B（マスター音源検出）で
      `01-master/` に raw master と別の最終マスター候補が見つからなくても、
      `assets.raw_master` をそのまま `assets.master_audio` として採用し
      `phase: "mastered"` へ進む（raw=final 運用）。既定 `False` は従来通り
      ユーザーによる最終マスター配置を待って停止する。
    - `approval_gates`: 後方互換の derived view（`ApprovalGates` docstring 参照）。
    """

    approval_gates: ApprovalGates = field(default_factory=ApprovalGates)
    skip_audio_approval: bool = True
    skip_upload_approval: bool = True
    skip_manual_mastering: bool = False


@dataclass(frozen=True)
class PostPublishApprovalGates:
    """`/post-publish` の各 step 直前に置く承認ゲート."""

    community_post: bool = False
    pinned_comment: bool = False
    metadata_audit: bool = False


@dataclass(frozen=True)
class PostPublish:
    """公開後チェーン設定.

    `configured` は `workflow.json` に `workflow.post-publish` が明示されたかを示す。
    未設定時は従来の `/community-post` 案内だけを維持する。
    """

    configured: bool = False
    approval_gates: PostPublishApprovalGates = field(default_factory=PostPublishApprovalGates)


@dataclass(frozen=True)
class Workflow:
    """ワークフロー責務の合成（`workflow` セクション）.

    Shorts スケジュール公開時刻は `Shorts.publish_time`（`config/channel/shorts.json`）に
    移動した — `workflow.post_upload.short_publish_time` は使わない。
    """

    wf_next: WfNext = field(default_factory=WfNext)
    post_publish: PostPublish = field(default_factory=PostPublish)
