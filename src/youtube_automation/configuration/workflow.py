"""ワークフロー設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WfNew:
    """`/wf-new` 関連の設定（`wf_new` セクション）.

    - `skip_plan_selection`: `True` のとき、analytics mode / benchmark fallback
      mode では推奨順 1 位を自動採用する。minimal mode の直接入力確認には
      適用せず、既定 `False` では従来どおりユーザー選択を待つ。
    """

    skip_plan_selection: bool = False


@dataclass(frozen=True)
class WfNext:
    """`/wf-next` 関連の設定（`wf_next` セクション）.

    boolean は全て「`True` = 手動工程を省いて自動進行」の向きに統一している（#1744）。

    - `skip_audio_approval`: `True`（既定）のとき、`prepared` フェーズ 2-B の
      音源承認ゲートを設けず自動進行する。`False` にすると `assets.master_audio`
      確定前に skill 側 (`/wf-next`) がユーザー承認を取りに行く。
      旧キー `approval_gates.audio`（true=承認する）は廃止されており、loader が拒否する。
    - `skip_upload_approval`: `True`（既定）のとき、`mastered` フェーズ 3-B の
      アップロード承認ゲートを設けず自動進行する。`False` にすると `/video-upload`
      実行直前にユーザー承認を取りに行う。旧キー `approval_gates.upload` も廃止されており、loader が拒否する。
    - `skip_manual_mastering`: `True` のとき、`prepared` フェーズ 2-B（マスター音源検出）で
      `01-master/` に raw master と別の最終マスター候補が見つからなくても、
      `assets.raw_master` をそのまま `assets.master_audio` として採用し
      `phase: "mastered"` へ進む（raw=final 運用）。既定 `False` は従来通り
      ユーザーによる最終マスター配置を待って停止する。
    """

    skip_audio_approval: bool = True
    skip_upload_approval: bool = True
    skip_manual_mastering: bool = False


#: `scheduled_automation.cadence` に指定できる曜日キー（月曜起点）。
SCHEDULED_AUTOMATION_CADENCE_DAYS: tuple[str, ...] = (
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
    "sun",
)

#: `scheduled_automation.notification` に指定できる通知先。
SCHEDULED_AUTOMATION_NOTIFICATIONS: tuple[str, ...] = ("terminal", "none")


@dataclass(frozen=True)
class ScheduledAutomation:
    """定期制作の宣言設定（`workflow.scheduled_automation` セクション、optional）（#1892）.

    Claude Code / Codex の定期実行アダプタ（`/automation-schedule`）が参照する
    実行環境非依存の宣言。未設定チャンネルは全 default（`enabled = False`）で
    ロードされ、手動制作・公開フローの挙動を一切変えない。

    - `enabled`: 定期実行の有効化。`False`（既定）ではスケジューラー設定を作成しない。
    - `timezone`: IANA タイムゾーン名（例 `Asia/Tokyo`）。スケジュール時刻の解釈に使う。
    - `run_time`: 定期起動時刻（`HH:MM`、24 時間表記）。
    - `cadence`: 起動する曜日の配列。`SCHEDULED_AUTOMATION_CADENCE_DAYS` の部分集合。
    - `target_workflow`: 起動する skill 名（既定 `wf-auto`。先頭 `/` なし）。
    - `max_retries`: 実行失敗時の再試行回数（0 = 再試行なし）。
    - `retry_delay_seconds`: 再試行までの待機秒数。
    - `prevent_concurrent_runs`: `True`（既定）のとき、前回実行が生存中なら
      次回スケジュールをスキップする（ロックによる実行排他）。
    - `notification`: 実行結果の通知先。`terminal`（既定） / `none`。
    - `allow_external_publish`: `True` のときのみ、定期実行内で YouTube への
      書き込み（アップロード・公開）を許可する。`False`（既定）では外部反映
      直前で停止する。有効化には `/automation-schedule` の明示確認が必要。
    """

    enabled: bool = False
    timezone: str = "Asia/Tokyo"
    run_time: str = "09:00"
    cadence: tuple[str, ...] = SCHEDULED_AUTOMATION_CADENCE_DAYS
    target_workflow: str = "wf-auto"
    max_retries: int = 0
    retry_delay_seconds: int = 300
    prevent_concurrent_runs: bool = True
    notification: str = "terminal"
    allow_external_publish: bool = False


@dataclass(frozen=True)
class PostPublishApprovalGates:
    """`/post-publish` の旧 `approval_gates` consumer 向け derived view."""

    community_post: bool = False
    pinned_comment: bool = False
    metadata_audit: bool = False


@dataclass(frozen=True)
class PostPublishSkipApprovals:
    """`/post-publish` の承認省略設定（`True` = 承認なし）."""

    community_post: bool = True
    pinned_comment: bool = True
    metadata_audit: bool = True


@dataclass(frozen=True)
class PostPublish:
    """公開後チェーン設定.

    `configured` は `workflow.json` に `workflow.post-publish` が明示されたかを示す。
    未設定時は従来の `/community-post` 案内だけを維持する。
    """

    configured: bool = False
    skip_approvals: PostPublishSkipApprovals = field(default_factory=PostPublishSkipApprovals)
    approval_gates: PostPublishApprovalGates = field(default_factory=PostPublishApprovalGates)


@dataclass(frozen=True)
class Workflow:
    """ワークフロー責務の合成（`workflow` セクション）.

    Shorts スケジュール公開時刻は `Shorts.publish_time`（`config/channel/shorts.json`）に
    移動した — `workflow.post_upload.short_publish_time` は使わない。
    """

    wf_new: WfNew = field(default_factory=WfNew)
    wf_next: WfNext = field(default_factory=WfNext)
    post_publish: PostPublish = field(default_factory=PostPublish)
    scheduled_automation: ScheduledAutomation = field(default_factory=ScheduledAutomation)
