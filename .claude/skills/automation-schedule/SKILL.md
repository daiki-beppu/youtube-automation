---
name: automation-schedule
description: "Use when チャンネルの定期制作スケジュール（workflow.json の scheduled_automation）を設定し、Claude Code / Codex の定期実行ジョブを作成・更新・確認・停止するとき。「定期実行」「スケジュール設定」「自動で回して」「automation-schedule」で発動。automation のリリース追従は /automation-update、本体リリースは /automation-release、制作を手動で一段進めるのは /wf-next"
---

## 前後工程

- `前工程`: `/channel-new`, `/setup`
- `後工程`: `/wf-next`

## Overview

チャンネルごとの定期制作設定（`config/channel/workflow.json` の `scheduled_automation`）を単一入口で管理する。前提診断 → config 生成（dry-run 差分）→ スケジューラージョブの作成・更新 → 状態確認・停止までを一度の対話で行う。スケジュール実装は実行環境別アダプタ（macOS: launchd / その他: cron）に分離し、実行環境は Claude Code（`claude -p`）または Codex（`codex exec`）を使う。

## Hard Gates

1. **外部公開許可（`allow_external_publish: true`）の有効化は明示承認なしに絶対に行わない。** 有効化する前に、対象チャンネル名・頻度（run_time / cadence / timezone）・「定期実行が人手確認なしで YouTube へアップロード・公開する」影響を表示し、AskUserQuestion で「有効化する / しない（既定）」の 2 択を取る。承認が得られない・質問できない・ユーザーが言及していない、のいずれの場合も `false` のままにする。`schedule_config.py generate` へ `--allow-external-publish` を付けるのはこの承認を得た後だけ。
2. **config 書き込みとジョブ作成は差分提示 → 承認後。** `generate --dry-run` の差分と `install` で作成・更新されるジョブ内容（label / 時刻 / 曜日 / runtime）を表示し、AskUserQuestion で「適用する / 中止」の 2 択を取ってから実行する。dry-run のみの依頼なら書き込み・ジョブ作成を一切行わない。
3. **前提診断が fail のまま進まない。** Step 0 の `detect_runtime.sh` が exit 0 でなければ、fail 行の対処（`/setup` / `/channel-new` / CLI インストール）を案内して停止する。
4. **重複ジョブを作らない。** ジョブは `scheduler_job.sh` 経由でのみ作成・更新する（同一 label 上書きで冪等）。launchctl / crontab を直接叩いてジョブを追加しない。

## 完了条件

- `setup` / `update`: `scheduler_job.sh status` で config（enabled=true）とジョブ登録の両方が確認できる
- `status`: config とジョブの現在状態が表示されている
- `disable`: ジョブが削除され、（ユーザーが望む場合）config も `enabled: false` になっている

## When to Use

- 「このチャンネルを定期的に自動で進めたい」「毎朝 /wf-next を回して」→ setup
- 「定期実行の状態を見たい」→ `/automation-schedule status`
- 「定期実行を止めて」→ `/automation-schedule disable`
- 制作を今すぐ一段進めるだけなら /wf-next（本スキルは起動の定期化のみを担う）

## References

| ファイル | 役割 |
|---|---|
| `references/detect_runtime.sh` | 前提診断（config / uv / claude・codex CLI / launchd・cron / 認証 / 通知） |
| `references/schedule_config.py` | `scheduled_automation` の表示（show）・生成・差分更新（generate、loader と同一検証） |
| `references/scheduler_job.sh` | ジョブの install / status / disable（launchd or cron、同一 label で冪等） |
| `references/run_scheduled.sh` | ジョブから起動される実行ラッパー（enabled 確認・lock・retry・外部反映ガード・通知） |

設定スキーマの正は `src/youtube_automation/utils/config/workflow.py::ScheduledAutomation`（未設定チャンネルは `enabled: false` で挙動不変）。

## Task

すべてチャンネルリポジトリ直下で実行する。

### Step 0. 前提診断

```bash
bash .claude/skills/automation-schedule/references/detect_runtime.sh
```

- exit 0 以外（fail 行あり）→ 各 fail 行の detail に書かれた対処を案内して**停止**（Hard Gate 3）
- warn 行は続行可。ただし `runtime-claude` / `runtime-codex` の ok が付いた方を Step 3 の `--runtime` に使う（両方 ok ならユーザーに選択を聞く）

### Step 1. 現状確認と設定案の提示（dry-run）

```bash
uv run python .claude/skills/automation-schedule/references/schedule_config.py show
uv run python .claude/skills/automation-schedule/references/schedule_config.py generate --dry-run --enable \
  --run-time <HH:MM> --cadence <mon,wed,fri> [--timezone <IANA>] [--target-workflow wf-next] \
  [--max-retries <N>] [--retry-delay-seconds <N>] [--notification terminal|none]
```

- 時刻・曜日はユーザーの依頼から決める。指定がなければ聞く（勝手に決めない）
- 差分（unified diff）をそのまま表示する
- `--allow-external-publish` はここでは**付けない**（既定 false。付けるのは Step 2 の承認後だけ）

### Step 2. 承認と config 書き込み

1. Step 1 の差分を提示し、AskUserQuestion で「適用する / 中止」を確認する（Hard Gate 2）
2. ユーザーが外部公開（自動アップロード）も望む場合のみ: 対象チャンネル・頻度・「定期実行が人手確認なしで YouTube に書き込む（公開は取消不可）」を表示し、AskUserQuestion で有効化の明示 2 択を取る（Hard Gate 1）
3. 承認された内容で書き込む（`--dry-run` を外し、承認された場合のみ `--allow-external-publish` を付与）

### Step 3. ジョブ作成・更新

```bash
bash .claude/skills/automation-schedule/references/scheduler_job.sh install --runtime <claude|codex>
```

- 同一チャンネルの再実行は同一 label の上書き = 既存ジョブの更新。重複作成されない
- timezone とシステム TZ が異なる場合は warn が出る。その場合はシステム TZ の壁時計で動くことをユーザーに伝える

### Step 4. 検証

```bash
bash .claude/skills/automation-schedule/references/scheduler_job.sh status
```

config（enabled=true）とジョブ登録の両方が表示されることを確認して完了報告する。

## サブコマンド

### `/automation-schedule status`

Step 0 の診断は省略してよい。`scheduler_job.sh status` の結果（effective config / ジョブ登録 / 直近ログ）を要約して報告する。

### `/automation-schedule disable`

1. `scheduler_job.sh status` で現状を表示し、AskUserQuestion で「停止する / 中止」を確認する
2. 承認後: `bash .claude/skills/automation-schedule/references/scheduler_job.sh disable`
3. config 側も無効化するか聞き、望まれたら `schedule_config.py generate --disable` を実行する（ジョブ削除だけでも、`run_scheduled.sh` は `enabled: false` を見て何もしないため安全側に倒れる）

## Gotchas

- 未設定チャンネル（`scheduled_automation` なし）は定期実行も外部反映も一切有効にならない。本スキルを実行するまで挙動は変わらない
- `run_scheduled.sh` は `prevent_concurrent_runs: true` のとき lock（`.automation-schedule/lock/`）で並行起動を抑止する。前回実行が異常終了で lock が残っても、pid 死活確認で stale lock は自動回収される
- `allow_external_publish: false` の定期実行は、実行プロンプトに「YouTube への書き込みを実行せず直前で停止する」制約を必ず注入する。ゲートは config 値が単一ソースであり、プロンプト側だけの書き換えで外さない
- 実行ログは `.automation-schedule/logs/` に残る。失敗調査はここから読む（全文を会話に貼らない）
- Suno 工程に到達した定期 `/wf-next` は `/suno-helper` の定期実行 flow と `yt-suno-unattended-request` を使う。既ログイン Chrome は前提とし、ログイン・CAPTCHA・課金確認・UI 非互換の `manual-intervention` は自動突破せず通知して停止する。制作〜公開の全工程統合は #1894 の責務
