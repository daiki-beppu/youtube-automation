---
name: automation-run
description: "Use when 明示済み automation-run 呼び出しまたは target_workflow で active collection を状態駆動で継続・再開するとき。「automation-run」で発動。collection 不在からの正規一気通貫入口は /wf-auto、一段だけ進める場合は /wf-next、定期時刻の設定は /automation-schedule"
---

## 前後工程

- `前工程`: `/automation-schedule`, `/wf-new`
- `後工程`: `/post-publish`, `/analytics-run`

## Overview

`workflow-state.json` と実成果物を毎段再評価し、未完了の active collection 1 件を制作〜公開まで継続する統合 runner。判断・lease・履歴は `references/automation-run-state.py` を単一ソースとし、実作業は既存 `/wf-new`、`/lyria`、`/suno-helper`、`/masterup`、`/wf-next`、`/post-publish` に委譲する。子 skill の処理を本文へ複製しない。

## Hard Gates

1. **lease 必須**: 子 skill の実行前に reference script で lease を取得する。busy は成功扱いで終了し、別 collection へ切り替えない。全終了経路で自分の token を指定して release する。
2. **公開許可の正は config だけ**: `workflow.scheduled_automation.allow_external_publish` が `true` の場合だけ YouTube upload / publish を許可する。会話・prompt・環境変数で上書きしない。`false` ではローカル動画と metadata 生成まで進め、`external_publish_disabled` で停止する。
3. **一段ごとに再評価**: 子 skill 完了後に同じ collection を `plan` し直す。前の decision から次 action を推測しない。成果物・state が変化しない成功報告は `failed` として記録し停止する。
4. **不可逆操作を重複させない**: `upload.video_id` が非空なのに `phase != complete` または `stage != live` の場合、同じ video ID の completed `upload_tracking.json` があれば `/wf-next` の local reconciliation だけを実行し、なければ `upload_state_inconsistent` で停止する。どちらも upload は再実行しない。Suno は prompt entry 数 × 2、state の期待数、実音源数がすべて整合するまで `/masterup` へ進めない。
5. **手動介入を突破しない**: 子 skill が login / CAPTCHA / 課金確認 / UI 非互換 / 承認待ちを返したら `blocked` として停止理由・再開 action を履歴へ残す。無人実行中に AskUserQuestion が必要になった場合も同様に停止する。
6. **workflow-state の更新責務を維持**: 本 skill と state script は `workflow-state.json` を直接更新しない。更新は既存 `/wf-new` / `/wf-next` と各子 skill の既存契約に従い、成果物検証後だけ行う。

## 完了条件

- state script が同じ collection に対して `action: complete` を返す。
- `phase: complete`、`stage: live`、`upload.video_id` が揃う。
- `workflow.post_publish.configured == true` の場合、`post_publish_history.json` で同 video ID の 3 step が完了している。
- 最終 action を `.automation-run/history.json` に `success` として記録し、lease を release する。

## 状態判定契約

チャンネルルートで実行する。

```bash
STATE_SCRIPT=.claude/skills/automation-run/references/automation-run-state.py

uv run python "$STATE_SCRIPT" acquire --channel-dir .
uv run python "$STATE_SCRIPT" heartbeat --channel-dir . --token <token>
uv run python "$STATE_SCRIPT" plan --channel-dir . [--collection <name>]
uv run python "$STATE_SCRIPT" record --channel-dir . --token <token> \
  --collection <name> --action <action> --status success|blocked|failed \
  --reason <reason> [--resume-action <action>]
uv run python "$STATE_SCRIPT" release --channel-dir . --token <token>
```

`plan` の action は次の固定契約。

| action | 委譲先 / 処理 |
|---|---|
| `wf-new` | 対象 collection 固定で `/wf-new` の未完了 planning 工程を実行 |
| `lyria` | `/lyria`。Suno 固有処理は呼ばない |
| `suno-helper` | `/suno-helper` の定期無人実行 flow。`manual-intervention` は停止 |
| `masterup` | strict Suno 成果物を入力に `/masterup` |
| `wf-next-local` | `/wf-next` の動画・metadata 生成だけを実行し、upload 直前で停止 |
| `wf-next` | `/wf-next`。config が許可した場合だけ upload を含める |
| `post-publish` | `/post-publish`。既存 history により完了 step を skip |
| `blocked` | reason / resume_action を記録して停止 |
| `complete` | 完了を記録して停止 |

初回 `--collection` 省略時は `collections/planning/*/workflow-state.json` の未完了 collection を `created_at`、名前の順で 1 件だけ選ぶ。以後は collection 名を固定する。upload 後に `planning/` から `live/` へ移動しても、同名を `plan --collection` で解決する。

## 実行手順

1. `config/channel/` を `load_config()` でロードできること、state script と子 skill が存在することを確認する。
2. `acquire` を実行し token を保持する。exit 20 / `busy` は「別 run が実行中」と報告して終了する。
3. `plan` を実行し、最初に返った collection 名を以後固定する。
4. 各 action の直前に `heartbeat` を実行し、`not-owner` なら子 skill を開始せず停止する。owner を確認後、action に対応する子 skill の `SKILL.md` を読み、対象 collection・期待成果物・外部公開許可を明示して既存手順を実行する。
   - `wf-next-local` は `/wf-next` のローカル動画・metadata 成果物まで。`yt-upload-*`、playlist 作成、comment、remote metadata 更新は実行しない。
   - `suno-helper` は `yt-suno-unattended-request` と extension state を使い、`assets.music_downloaded == true`、playlist URL、期待数以上の音源実在が揃うまで成功にしない。
   - `wf-next` の upload 後は live 移動先、tracking、video ID、phase/stage を既存契約どおり検証する。
   - `reason: upload_reconciliation_required` の `wf-next` は remote upload / playlist assign を一切呼ばない。同じ video ID の completed tracking を再検証し、`/wf-next` の publishing recovery 契約で planning → live 移動と `stage: live` / `phase: complete` の local state reconciliation だけを行う。
5. 子 skill の完了条件を満たしたら `record --status success` を実行し、同じ collection を再度 `plan` する。失敗は `failed`、手動介入・公開未許可は `blocked` として resume action 付きで記録し停止する。
6. `post-publish` 完了後も再評価し、`complete` を得たら完了記録を残す。
7. `finally` 相当で必ず自分の token を指定して `release` する。release が `not-owner` なら警告するが、他 token の lease は削除しない。

## 再開と通知

- 再実行時は新しい lease を取得し、workflow state・成果物・post-publish history から action を再計算する。`.automation-run/history.json` は監査・通知用であり、工程判定の source of truth にしない。
- `blocked` / `failed` の報告には collection、action、reason、resume_action、履歴 path を含める。
- `/automation-schedule` 経由では wrapper が exit status とログを `.automation-schedule/logs/` に残し、設定済み notification へ通知する。本 skill は blocker を成功完了と偽装しない。

## 想定 API call 数

state 判定・lease・履歴記録自体は API 0。実行時は選ばれた子 skill の見積もりを開始前に提示する。Lyria は `/lyria` の segment 数、Suno は `/suno-helper` の選択 entry 数、YouTube upload は `/video-upload` の対象動画 1 本、公開後処理は `/post-publish` の未完了 step 数に従う。`allow_external_publish: false` では YouTube write API は 0、失敗・再開時も完了済み upload / post-publish step を再発行しない。

## References

- `references/automation-run-state.py`: collection 選択、次 action、strict artifact check、lease、実行履歴
- `/wf-next`: state 更新と制作・公開の既存 orchestration
- `/suno-helper`: Suno 無人実行と安全停止
- `/post-publish`: 公開後 chain の idempotency history
