---
name: automation-schedule
description: "Use when チャンネルの定期制作スケジュール（workflow.json の scheduled_automation）を設定し、Codex / Claude のネイティブ Scheduled Task を作成・更新・確認・停止するとき。「定期実行」「スケジュール設定」「自動で回して」「automation-schedule」で発動。automation のリリース追従は /automation-update、本体リリースは /automation-release、制作を手動で一段進めるのは /wf-next"
---

## 前後工程

- `前工程`: `/channel-new`, `/setup`
- `後工程`: `/wf-auto`, `/wf-next`

## Overview

`config/channel/workflow.json::workflow.scheduled_automation` を製品非依存の単一ソースとして、実行中製品のネイティブ scheduler に登録する。Codex は Scheduled Task、Claude は依存性に応じて `/schedule` Cloud Job または Cowork local Scheduled Task を使う。launchd / cron は明示承認された fallback に限る。

## Hard Gates

1. **`allow_external_publish: true` は明示承認なしに有効化しない。** 対象・頻度・YouTube 書き込みの影響を表示し、「有効化する / しない（既定）」を確認する。
2. **config と外部 scheduler は dry-run 提示・承認後だけ変更する。** config diff と `schedule_backend.py plan` の全項目を先に表示する。
3. **ローカル依存を Cloud Job へ登録しない。** ローカルファイル、OAuth、Chrome、Suno Helper、ffmpeg、ローカル media のいずれかが必要なら `local`。対応する local Scheduled Task が利用不能なら停止する。
4. **OS fallback は自動選択しない。** 理由・常時起動要件・製品側の履歴/停止UIを使えない制約を示し、明示承認後だけ `--confirm-os-fallback` を使う。
5. **同一チャンネルに複数 backend を作らない。** `schedule_backend.py show/guard` で active backend を確認し、切替時は旧 backend を先に disable する。外部登録成功後だけ ID を `record` する。
6. Step 0 の `fail` が残る場合は停止する。認証操作だけは人間に依頼し、コマンド実行・設定作成は AI が行う。

## Backend selection

| 実行製品 / 依存 | backend | 登録・管理 |
|---|---|---|
| Codex（cloud / local） | `codex-automation` | ChatGPT desktop/web の Scheduled。local は desktop の local project を必須にする |
| Claude + cloud 完結 | `claude-code-cloud` | Claude Code `/schedule` Cloud Job |
| Claude + local 依存 | `claude-cowork-local` | Cowork Scheduled で対象 folder を選ぶ。local 実行可否を登録前に確認する |
| ネイティブ利用不能 + 明示承認 | `os-fallback` | `scheduler_job.sh` の launchd / cron |

Claude Code `/loop` は最長 3 日の一時反復専用で、永続スケジュールには使わない。

## References

| ファイル | 役割 |
|---|---|
| `references/detect_runtime.sh` | config / uv / 実行中製品 / native 管理面 / OS fallback 可否の診断 |
| `references/schedule_config.py` | `scheduled_automation` の show / generate / dry-run |
| `references/schedule_backend.py` | 4 backend の plan、重複防止、外部 ID のローカル記録 |
| `references/scheduler_job.sh` | 明示選択された OS fallback 専用の install / status / disable |
| `references/run_scheduled.sh` | OS fallback 専用ラッパー。外部公開ゲート・lock・retry・通知を維持 |

設定スキーマの正は `src/youtube_automation/configuration/workflow.py::ScheduledAutomation`。

## Task: setup / update

すべてチャンネルリポジトリ直下で実行する。

### Step 0. 診断と backend 決定

```bash
bash .claude/skills/automation-schedule/references/detect_runtime.sh
uv run python .claude/skills/automation-schedule/references/schedule_backend.py show
```

1. `product-codex` / `product-claude` を既定候補にする。判定不能時だけユーザーに製品を確認する。
2. 対象 workflow の依存を `cloud` / `local` に分類し、分類根拠を表示する。既定 `wf-auto` は local（Chrome / OAuth / media / ffmpeg を利用）として扱う。
3. active な別 backend があれば、旧 backend の disable が承認・成功するまで停止する。

### Step 1. config と native task の dry-run

```bash
uv run python .claude/skills/automation-schedule/references/schedule_config.py show
uv run python .claude/skills/automation-schedule/references/schedule_config.py generate --dry-run --enable \
  --run-time <HH:MM> --cadence <mon,wed,fri> [--timezone <IANA>] \
  [--target-workflow wf-auto] [--max-retries <N>] \
  [--retry-delay-seconds <N>] [--notification terminal|none]
uv run python .claude/skills/automation-schedule/references/schedule_backend.py plan \
  --product <codex|claude> --dependency-mode <cloud|local> \
  --run-time <HH:MM> --cadence <mon,wed,fri> [--timezone <IANA>] \
  [--target-workflow wf-auto] [--max-retries <N>] \
  [--retry-delay-seconds <N>] [--notification terminal|none]
```

時刻・曜日が未指定なら確認し、勝手に決めない。config dry-run と `plan` へ同じ候補値を渡す。`plan` は JSON を表示するだけで config / OS / 外部状態を変更しない。外部公開承認前は `--allow-external-publish` を付けない。

### Step 2. 承認後に config を書く

Step 1 の config diff、backend、title、prompt、cwd、timezone、RRULE、依存分類を表示して適用確認を取る。外部公開も明示承認された場合だけ `--allow-external-publish` を付け、`schedule_config.py generate` を実行する。

### Step 3. 選択 backend へ作成または更新

まず次を実行し、別 backend が active なら登録しない。

```bash
uv run python .claude/skills/automation-schedule/references/schedule_backend.py guard --backend <backend>
```

- `codex-automation`: Codex/ChatGPT の Scheduled Task 管理 capability を使う。CLI の `codex exec` や launchd / cron は使わない。local 依存では desktop local project と cwd を指定する。同じ external ID があれば更新する。
- `claude-code-cloud`: `plan` の prompt と schedule で `/schedule` Cloud Job を作成/更新する。local 依存が判明したら中止する。
- `claude-cowork-local`: Cowork Scheduled Task に local folder を指定して作成/更新する。製品側で local folder 実行を選べない場合は中止する。
- `os-fallback`: ネイティブが使えない理由と制約を提示して別途承認を取り、次だけを実行する。

```bash
bash .claude/skills/automation-schedule/references/scheduler_job.sh install \
  --backend os-fallback --confirm-os-fallback --runtime <claude|codex>
```

ネイティブ登録が成功した後だけ、返された不変 ID を記録する。

```bash
uv run python .claude/skills/automation-schedule/references/schedule_backend.py record \
  --backend <backend> --external-id <product-task-id>
```

### Step 4. 検証

`schedule_backend.py show` で backend / external ID を確認し、**同じ backend の製品管理面**で status・次回実行・cadence を確認する。config が `enabled=true` で、別 backend に同名 task がないことまで確認して完了。

## status

1. `schedule_backend.py show` と `schedule_config.py show` を実行する。
2. active backend と external ID を使い、その製品の Scheduled 管理面で状態・次回実行・直近結果を取得する。
3. state が `unconfigured` なら、製品側を job key `youtube-automation:<channel-dir>` で検索する。見つけても勝手に再作成せず、record の承認を取る。
4. `os-fallback` の場合だけ `scheduler_job.sh status --backend os-fallback` を使う。

## disable

1. status を提示して停止確認を取る。
2. active backend の external ID を指定し、製品の Scheduled 管理面で pause/delete する。別 backend は触らない。
3. 外部停止成功後に `schedule_backend.py disable --backend <backend>` を実行する。OS の場合だけ `scheduler_job.sh disable --backend os-fallback` が外部停止と state 更新を担う。
4. 希望された場合のみ `schedule_config.py generate --disable` で config も無効化する。

## Safety contract

- native task の prompt にも `allow_external_publish: false` の外部反映禁止を含める。`wf-auto` の `.automation-run/` lease、状態再評価、重複 upload 防止は変更しない。
- retry は backend の再実行機能が契約を満たす場合のみ native 側へ写像する。満たさない場合は prompt 内で `max_retries` / `retry_delay_seconds` を適用する。
- OS fallback のログは `.automation-schedule/logs/`。ネイティブの履歴は各製品の Scheduled 管理面を正とする。
