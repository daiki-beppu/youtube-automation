"""ワークフロー設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ApprovalGates:
    """`/wf-next` の承認ゲート設定（`wf_next.approval_gates`）.

    既定値は両方 `False` で従来通り全自動進行する。`True` にすると
    skill 側 (`/wf-next`) が該当フェーズ進行前にユーザー承認を取りに行く。

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

    - `skip_manual_mastering`: `True` のとき、`prepared` フェーズ 2-B（マスター音源検出）で
      `01-master/` に raw master と別の最終マスター候補が見つからなくても、
      `assets.raw_master` をそのまま `assets.master_audio` として採用し
      `phase: "mastered"` へ進む（raw=final 運用）。既定 `False` は従来通り
      ユーザーによる最終マスター配置を待って停止する。
    """

    approval_gates: ApprovalGates = field(default_factory=ApprovalGates)
    skip_manual_mastering: bool = False


@dataclass(frozen=True)
class Workflow:
    """ワークフロー責務の合成（`workflow` セクション）.

    Shorts スケジュール公開時刻は `Shorts.publish_time`（`config/channel/shorts.json`）に
    移動した — `workflow.post_upload.short_publish_time` は使わない。
    """

    wf_next: WfNext = field(default_factory=WfNext)
