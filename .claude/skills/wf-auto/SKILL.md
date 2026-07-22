---
name: wf-auto
description: "Use when 正規入口から collection の有無を問わず、企画開始または未完了地点から制作・公開・post-publish まで状態駆動で継続・再開するとき。「制作を最初から最後まで」「wf-auto」で発動。一段だけ進める場合は /wf-next、進捗確認だけなら /wf-status"
---

## 前後工程

- `前工程`: `/automation-schedule`, `/wf-new`
- `後工程`: `/post-publish`, `/analytics-run`

## Overview

`workflow-state.json` と実成果物を毎段再評価し、新規企画または active collection の未完了地点から公開後処理まで継続する統合入口。判断・lease・履歴は `references/wf-auto-state.py` を使い、実作業は既存 `/wf-new`、`/lyria`、`/suno-helper`、`/masterup`、`/wf-next`、`/post-publish` に委譲する。子 skill の処理は本文へ複製しない。

## Hard Gates

1. **lease 必須**: 子 skill の実行前に lease を取得する。busy は別 run が進行中として終了し、別 collection へ切り替えない。全終了経路で自分の token を指定して release する。
2. **対象を固定**: `no_active_collection` では state を捏造せず `/wf-new` へ委譲する。collection 初期化後は返された名前を固定し、以後の `plan` に必ず `--collection` を渡す。
3. **公開許可の正は config だけ**: `workflow.scheduled_automation.allow_external_publish` が `true` の場合だけ YouTube upload / publish を許可する。会話、prompt、環境変数で上書きしない。`false` ではローカル成果物まで進め、`external_publish_disabled` で停止する。
4. **一段ごとに再評価**: 子 skill 完了後、同じ run 内で固定 collection を `plan` し直す。前 decision から次 action を推測しない。state と成果物が変化しない成功報告は `failed` として停止する。
5. **手動介入を突破しない**: 対話実行では子 skill の企画選択・承認へ回答後、同じ run 内で再評価する。無人実行でユーザー入力、login、CAPTCHA、課金確認、UI 非互換、承認待ちが必要なら自動承認せず `blocked` と再開 action を履歴へ記録する。
6. **不可逆操作を重複させない**: upload reconciliation、Suno 成果物数、post-publish idempotency は state resolver と委譲先の既存契約に従う。既存 video ID の remote upload や完了済み投稿を再発行しない。
7. **state 更新責務を維持**: 本 skill と state resolver は `workflow-state.json` を直接更新しない。更新は `/wf-new`、`/wf-next` と各子 skill が成果物検証後に行う。

## 完了条件

- 固定 collection に対して resolver が `action: complete` を返す。
- `phase: complete`、`stage: live`、`upload.video_id` が揃う。
- post-publish 設定済みなら、同 video ID の必要 step が `post_publish_history.json` で完了している。
- 最終 action が `.automation-run/history.json` に記録され、lease が release される。

## 状態判定契約

チャンネルルートで実行する。

```bash
STATE_SCRIPT=.claude/skills/wf-auto/references/wf-auto-state.py

uv run python "$STATE_SCRIPT" acquire --channel-dir .
uv run python "$STATE_SCRIPT" heartbeat --channel-dir . --token <token>
uv run python "$STATE_SCRIPT" plan --channel-dir . [--collection <fixed-name>]
uv run python "$STATE_SCRIPT" record --channel-dir . --token <token> \
  --collection <fixed-name> --action <action> --status success|blocked|failed \
  --reason <reason> [--resume-action <action>]
uv run python "$STATE_SCRIPT" record-bootstrap --channel-dir . --token <token> \
  --status blocked|failed --reason <reason>
uv run python "$STATE_SCRIPT" release --channel-dir . --token <token>
```

初回 `plan` の固定契約:

| 状態 | action / 処理 |
|---|---|
| active collection なし | `wf-new` / `no_active_collection`。`/wf-new` を新規開始する |
| active collection あり | state と実成果物から未完了 action を返す |

`plan` の action と委譲先:

| action | 委譲先 / 処理 |
|---|---|
| `wf-new` | `/wf-new`。不在時は新規開始、固定済み planning では未完了工程から再開 |
| `lyria` | `/lyria` |
| `suno-helper` | `/suno-helper`。manual intervention は停止 |
| `masterup` | strict Suno 成果物を入力に `/masterup` |
| `wf-next-local` | `/wf-next` のローカル動画・metadata 生成まで。YouTube write は行わない |
| `wf-next` | `/wf-next`。config が許可した場合だけ upload を含める |
| `post-publish` | `/post-publish`。history により完了 step を skip |
| `blocked` | reason / resume_action を記録して停止 |
| `complete` | 完了を記録して停止 |

## 実行手順

1. `config/channel/` が無ければ `/channel-new` を案内して停止し、`load_config()` が失敗した場合も既存チャンネル取り込みモードの `/channel-new` を案内して停止する。state resolver または上記子 skill が無ければ `/automation-update`（本リポジトリ内では `yt-skills sync`）を案内して停止する。すべて満たすまで lease と子 skill を開始しない。
2. `acquire` で token を保持する。exit 20 / `busy` なら子 skill を開始せず終了する。
3. 初回 `plan` を実行する。
   - `reason: no_active_collection`: `/wf-new` の `SKILL.md` を読み、既存 gate を保って新規開始する。無人実行で collection 作成前に入力が必要なら `record-bootstrap --status blocked --reason user_input_required` で停止する。
   - collection が返る: その名前を固定する。
4. `/wf-new` が collection を初期化したら、出力 path と `workflow-state.json` の実在を検証して名前を固定する。`record --action wf-new --status success` 後、同じ run 内で `plan --collection <fixed-name>` を実行する。企画選択等で対話が一時停止しても lease を保持した実行文脈へ回答を戻し、完了後に同じ固定処理を行う。
5. 各 action の直前に `heartbeat` を実行する。owner なら対応する子 skill の `SKILL.md` を読み、固定 collection、期待成果物、外部公開許可を明示して委譲する。`not-owner` なら開始しない。
6. 子 skill の期待成果物と state を検証する。成功は `record --status success`、手動介入は `blocked`、その他は `failed` として reason / resume_action を残す。成功時だけ固定 collection を再度 `plan` する。
7. `post-publish` 後も再評価し、`phase: complete`、`stage: live`、`upload.video_id` と必要な post-publish history が揃って `action: complete` になったら完了記録を残す。
8. `finally` 相当で必ず自分の token を指定して `release` する。`not-owner` でも他 token の lease は削除しない。

## 再開と停止報告

- 再実行時は新しい lease を取り、state と成果物から action を再計算する。`.automation-run/history.json` は監査用であり工程判定の source of truth にしない。
- `blocked` / `failed` の報告には collection（未作成なら `null`）、action、reason、resume_action、history path を含める。
- 無人実行の blocker を成功完了として報告しない。人間が行う認証は login / 同意等のブラウザ操作だけとし、コマンド起動と再検証は AI または setup script が担う。

## 想定 API call 数

resolver、lease、履歴は API 0。実行前に選ばれた子 skill の見積もりを提示する。`allow_external_publish: false` では YouTube write API は 0。再開時は完了済み upload / post-publish step を再発行しない。

## References

- `references/wf-auto-state.py`: collection 選択、新規開始判定、次 action、成果物検証、lease、実行履歴の正規実装
- `/wf-new`: 企画・collection 初期化・素材準備
- `/wf-next`: 制作・公開と state 更新
- `/post-publish`: 公開後 chain と idempotency history
