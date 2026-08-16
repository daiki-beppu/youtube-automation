
## 前後工程

- `前工程`: `/wf-new`
- `後工程`: `/publish`, `/analytics`
- `委譲先`: `/wf-new`, `/music --generate`, `/music --generate`, `/music --master`, `/wf-next`, `/publish`

## 成果物

- `書き込む`: `.automation-run/history.json`
- `読み込む`: `collections/<id>/workflow-state.json`, `collections/<id>/20-documentation/community-post.txt`, `pinned_comment_history.json`

## Overview

`workflow-state.json` と実成果物を毎段再評価し、新規企画または active collection の未完了地点から公開後処理まで継続する正規入口。判断・lease・履歴は `references/wf-auto-state.py` を使い、実作業は同一 SKILL.md の通常入口、`/music --generate`、`/music --generate`、`/music --master`、`/wf-next`、`/publish` に委譲する。子 skill の処理は本文へ複製しない。`thumbnail::textless.enabled` も独自解釈せず、通常入口と `/wf-next` の契約をそのまま貫通させる。

## Hard Gates

1. **lease 必須**: 子 skill の実行前に lease を取得する。busy は別 run が進行中として終了し、別 collection へ切り替えない。全終了経路で自分の token を指定して release する。
2. **対象を固定**: `no_active_collection` では state を捏造せず `/wf-new` へ委譲する。collection 初期化後は返された名前を固定し、以後の `plan` に必ず `--collection` を渡す。
3. **公開許可の正は config だけ**: `workflow.scheduled_automation.allow_external_publish` が `true` の場合だけ YouTube upload / publish を許可する。会話、prompt、環境変数で上書きしない。`false` ではローカル成果物まで進め、`external_publish_disabled` で停止する。
4. **一段ごとに再評価**: 子 skill 完了後、同じ run 内で固定 collection を `plan` し直す。前 decision から次 action を推測しない。state と成果物が変化しない成功報告は `failed` として停止する。
5. **手動介入を突破しない**: 対話実行では子 skill の企画選択・承認へ回答後、同じ run 内で再評価する。`workflow.wf_new.skip_plan_selection` または子 skill-config の `skip_*_approval` / `skip_cost_confirm` が `true` の停止点はチャンネル設定による明示 opt-in なので突破には当たらず続行する。それ以外のユーザー入力、login、CAPTCHA、課金確認、承認待ちが無人実行で必要なら自動承認せず `blocked` と再開 action を履歴へ記録する。Suno の UI 非互換・拡張障害・生成失敗は人間操作の blocker に広げず、agent が診断・再試行するか根拠付き `failed` とする。
6. **不可逆操作を重複させない**: upload reconciliation、Suno 成果物数、publish idempotency は state resolver と委譲先の既存契約に従う。既存 video ID の remote upload や完了済み投稿を再発行しない。
7. **state 更新責務を維持**: 本 skill と state resolver は `workflow-state.json` を直接更新しない。成果物検証後の更新も `/wf-new`、`/wf-next` と各子 skill が owner CLI または state-owning CLI 経由で行う。
8. **長時間処理の待機主体を消さない**: 子 agent に Monitor を arm させて self-stop / completed にしてはならない。実行中 tool call を維持するか background session を30秒以下の間隔で poll させ、終了を自分で観測してから報告させる。

## 完了条件

- 固定 collection に対して resolver が `action: complete` を返す。
- `phase: complete`、`stage: live`、`upload.video_id` が揃う。
- publish 設定済みなら、community 投稿文と同 video ID の pinned comment 履歴が揃っている。
- 最終 action が `.automation-run/history.json` に記録され、lease が release される。

## 状態判定契約

チャンネルルートで実行する。

```bash
STATE_SCRIPT=.claude/skills/wf-new/references/wf-auto-state.py

uv run python "$STATE_SCRIPT" acquire --channel-dir .
uv run python "$STATE_SCRIPT" heartbeat --channel-dir . --token <token>
uv run python "$STATE_SCRIPT" plan --channel-dir . [--collection <fixed-name>]
uv run python "$STATE_SCRIPT" record --channel-dir . --token <token> \
  --collection <fixed-name> --action <action> --status success|blocked|failed \
  --reason <reason> [--resume-action <action>] \
  --ai-started-at <current-attempt-ai-started-at> \
  [--human-interval <human-start> <human-end>]...
uv run python "$STATE_SCRIPT" record-bootstrap --channel-dir . --token <token> \
  --status blocked|failed --reason <reason> \
  --ai-started-at <current-attempt-ai-started-at>
uv run python "$STATE_SCRIPT" release --channel-dir . --token <token>
```

初回 `plan` の固定契約:

| 状態 | action / 処理 |
|---|---|
| active collection なし | `wf-new` / `no_active_collection`。同一 SKILL.md の通常入口を新規開始する |
| active collection あり | state と実成果物から未完了 action を返す |

`plan` の action と委譲先:

| action | 委譲先 / 処理 |
|---|---|
| `wf-new` | 同一 SKILL.md の通常入口。不在時は新規開始、固定済み planning では未完了工程から再開 |
| `lyria` | `/music --generate` |
| `minimax` | `/music --generate` |
| `suno-helper` | `/music --generate` の browser use 主導フロー。人間への handoff は login / CAPTCHA の該当操作だけ |
| `masterup` | strict Suno 成果物を入力に `/music --master` |
| `wf-next-local` | `/wf-next` のローカル動画・metadata 生成まで。YouTube write は行わない |
| `wf-next` | `/wf-next`。config が許可した場合だけ upload を含める |
| `publish` | `/publish`。各成果物の状態判定により完了 step を skip |
| `blocked` | reason / resume_action を記録して停止 |
| `complete` | 完了を記録して停止 |

### canonical action の AI timing 契約

各 canonical action は、`heartbeat` が `owner` を確認した直後かつ子 skill への委譲または terminal action の処理を始める直前に、次のコマンドを実行する。stdout の値をその attempt 専用の `<current-attempt-ai-started-at>` として保持する。

```bash
uv run python -c 'from datetime import UTC, datetime; print(datetime.now(UTC).isoformat())'
```

子 skill の終了報告だけで成功とせず、期待成果物と state を検証してから終了 status を決める。検証に成功した場合だけ `success`、手動介入が必要なら `blocked`、検証失敗を含むその他の失敗は `failed` とする。すべての `record --status success|blocked|failed` と collection 作成前の `record-bootstrap --status blocked|failed` に、同じ attempt で保持した `--ai-started-at <current-attempt-ai-started-at>` を渡して AI 区間を必ず閉じる。`blocked` / `complete` の terminal action も、同じ順序で開始時刻を取得して記録する。

retry・再開時は action を実行するたびに新しい開始時刻を取得し、新しい attempt として追記する。前回の開始時刻を再利用せず、前回の `failed` / `blocked` attempt と実行時間を履歴に残す。

### 同一 run の人間介入 gate timing 契約

canonical action の開始時に、空の `<current-attempt-human-intervals>` を同じ attempt の一時情報として用意する。対話実行で AskUserQuestion または本人操作の依頼を提示する直前に、メインエージェントが human 開始時刻を取得する。承認取得と本人操作の依頼は subagent へ委譲しない。回答または本人操作の完了を受け取った直後、成果物検証や次のコマンドへ進む前に、メインエージェントが human 終了時刻を取得し、閉じた組を `<current-attempt-human-intervals>` へ追加する。

時刻の取得には AI 開始時刻と同じ UTC コマンドを使う。同一 action に複数の gate がある場合も、前の組を上書き・統合せず、各 gate の閉区間を発生順に保持する。action の status と成果物検証が確定して `record` を実行するとき、同じ attempt の AI 開始時刻に加え、保持した区間を発生順を保ったまま全件 `--human-interval START END` として渡す。gate が 0 件ならこの option は渡さない。

```bash
HUMAN_START_1="$(uv run python -c 'from datetime import UTC, datetime; print(datetime.now(UTC).isoformat())')"
# メインエージェントが gate を提示し、回答または必要な本人操作の完了を受け取る
HUMAN_END_1="$(uv run python -c 'from datetime import UTC, datetime; print(datetime.now(UTC).isoformat())')"

uv run python "$STATE_SCRIPT" record --channel-dir . --token <token> \
  --collection <fixed-name> --action <action> --status <status> --reason <reason> \
  --ai-started-at <current-attempt-ai-started-at> \
  --human-interval <human-start-1> <human-end-1> \
  --human-interval <human-start-2> <human-end-2>
```

この契約は同じ run の実行文脈へ回答または操作完了が戻る gate にだけ適用する。login / CAPTCHA は既存 Hard Gate の範囲を広げず、本人に必要な1操作だけを依頼し、認証コマンドの実行や CAPTCHA 回避を行わない。

### blocked 停止と agent wait の timing 分類

人間の回答や操作完了を同じ run で待たず `blocked` として停止すると決めた場合は、その停止決定時点で、すでに閉じている同一 run の human interval だけを渡して `record --status blocked` を実行する。未完了の human interval を開始・保存せず、その場で現在の attempt を閉じて lease を release し、run を停止する。停止後から次回起動までの放置時間を timing segment に含めない。

次回の再開では新しい lease を取得し、resolver で action を再評価する。owner 確認後に新しい attempt と新しい AI 開始時刻を作り、前回の AI 開始時刻を再利用しない。前回の `blocked` attempt は閉じた履歴として保持し、再開後の timing を追記する。login / CAPTCHA も本人に必要な1操作だけを依頼してこの blocked 停止契約に従い、自動突破しない。

通常の API polling、実行中 tool call の待機、agent が保持する background session の30 秒以下の間隔での poll は、agent が処理の完了・失敗を観測する canonical action 内の作業である。これらは AI 実行時間として扱い、human interval を開始しない。human interval に切り替えるのは、前節どおり同じ run へ回答が戻る明示的な AskUserQuestion または本人操作 gate だけとする。

### `suno-helper` action の自律実行契約

resolver が `action: suno-helper` を返したら、agent 自身が `/music --generate` の **Agent primary flow: browser use** を実行する。Codex は browser use、Claude Code は browser use または Claude in Chrome を使い、固定 collection について次を完走する。

1. collection server を AI または setup script が起動し、agent が Suno Create を開く
2. suno-helper overlay / popup で server と固定 collection を選択する
3. 既定の連続生成を開始し、全 pattern の生成完了を監視する
4. 生成曲を対象 playlist へ追加し、複数曲の ZIP download を実行する
5. `/music --generate` の strict 成果物数・manifest・音源ファイル検証を実行する

ユーザーへ `/music --generate` の実行、overlay 選択、曲生成、playlist 追加、ZIP download、成果物検証を一括して依頼してはならない。Suno が login または CAPTCHA を表示し本人操作が不可欠な場合だけ、現在の画面と必要な1操作を限定して依頼し、`record --action suno-helper --status blocked --reason suno_login_required|suno_captcha_required --resume-action suno-helper --ai-started-at <current-attempt-ai-started-at>` を残す。認証のコマンド実行や CAPTCHA 回避は行わない。

本人操作の完了後は agent が同じ固定 collection の `suno-helper` action から再開する。UI 非互換、拡張未ロード、server 接続、生成、playlist、download の失敗を login / CAPTCHA と束ねず、`/music --generate` の診断・再試行契約に従う。strict 完了条件が揃ったら成功を記録して同一 collection を再度 `plan` し、返された `masterup` 以降へ同じ run 内で継続する。

## 実行手順

1. `config/channel/` が無ければ `/setup --channel` を案内して停止する。
   `load_config()` が失敗した場合は`/setup --import` を案内して停止する。state resolver または上記子 skill が無ければ `/automation --update`（本リポジトリ内では `yt-skills sync`）を案内して停止する。すべて満たすまで lease と子 skill を開始しない。
2. `acquire` で token を保持する。exit 20 / `busy` なら子 skill を開始せず終了する。
3. 初回 `plan` を実行する。
   - `reason: no_active_collection`: resolver が `action: wf-new` を返したら別 skill を呼ばず、同一 SKILL.md の通常入口を canonical action として選ぶ。step 4 の heartbeat と AI 開始時刻取得後に通常入口を読み、企画選択、thumbnail 承認、preselected manifest、channel constraint verification を含む既存 gate と明示 opt-in の skip 分岐を保って新規開始する。`skip_plan_selection: true` の analytics / benchmark fallback mode は推奨順 1 位で続行し、minimal mode など設定で省略されていない入力が必要なら `record-bootstrap --status blocked --reason user_input_required --ai-started-at <current-attempt-ai-started-at>` で停止する。
   - collection が返る: その名前を固定する。
4. 選ばれた各 action の直前に `heartbeat` を実行する。owner なら直後に「canonical action の AI timing 契約」の開始時刻を取得して保持する。子 skill action は対応する `SKILL.md` を読み、固定 collection、期待成果物、外部公開許可を明示して委譲する。`blocked` / `complete` は同じ開始時刻取得後に terminal action として処理する。`not-owner` なら開始時刻を取得せず、action を開始しない。
5. `/wf-new` が collection を初期化したら、出力 path と `workflow-state.json` の実在を検証して名前を固定する。step 4 で保持した開始時刻を渡して `record --action wf-new --status success --ai-started-at <current-attempt-ai-started-at>` を実行した後、同じ run 内で `plan --collection <fixed-name>` を実行する。企画選択等で対話が一時停止しても lease を保持した実行文脈へ回答を戻し、完了後に同じ固定処理を行う。
6. 子 skill の期待成果物と state を検証する。検証成功だけを `record --status success`、手動介入は `blocked`、検証失敗を含むその他は `failed` として reason / resume_action を残し、すべてに同じ attempt の `--ai-started-at` を渡す。成功時だけ固定 collection を再度 `plan` する。
7. `publish` 後も再評価し、`phase: complete`、`stage: live`、`upload.video_id`、community 投稿文、pinned comment 履歴が揃って `action: complete` になったら、同じ timing 契約で完了記録を残す。
8. `finally` 相当で必ず自分の token を指定して `release` する。`not-owner` でも他 token の lease は削除しない。

## 再開と停止報告

- 再実行時は新しい lease を取り、state と成果物から action を再計算する。`.automation-run/history.json` は監査用であり工程判定の source of truth にしない。
- retry・再開で同じ action を再実行するときも、新しい AI 開始時刻と新しい attempt を使い、前回の失敗時間を上書きしない。
- `blocked` / `failed` の報告には collection（未作成なら `null`）、action、reason、resume_action、history path を含める。
- 無人実行の blocker を成功完了として報告しない。人間が行う認証は login / 同意等のブラウザ操作だけとし、コマンド起動と再検証は AI または setup script が担う。

## 想定 API call 数

resolver、lease、履歴は API 0。実行前に選ばれた子 skill の見積もりを提示する。`allow_external_publish: false` では YouTube write API は 0。再開時は完了済み upload / publish step を再発行しない。

## References

- `references/wf-auto-state.py`: collection 選択、新規開始判定、次 action、成果物検証、lease、実行履歴の正規実装
- `/wf-new`: 企画・collection 初期化・素材準備
- `/wf-next`: 制作・公開と state 更新
- `/publish`: 公開 chain と成果物ベースの idempotency 判定
