---
name: wf-next
purpose: 進める
description: "Use when 既存コレクション（collections/planning/）を一段進めるとき。「次どうする？」「続き進めて」で発動。進捗閲覧のみは /wf-status、新規は /wf-new"
---

## 前後工程

- `前工程`: `/wf-new`, `/wf-new`
- `後工程`: `/analytics`, `/analytics --flop`
- `委譲先`: `/music --master`, `/music --generate`, `/video --generate`, `/video --describe`, `/publish --playlist`, `/publish --upload`

## 成果物

- `書き込む`: `collections/<id>/workflow-state.json`, `collections/<id>/20-documentation/upload_tracking.json`

動画説明 JSON+HTML pair の書き込みは `/video --describe` owner へ委譲する。
- `読み込む`: `collections/<id>/workflow-state.json`, `collections/<id>/01-master/*`, `collections/<id>/10-assets/*`, `config/channel/workflow.json`

## Overview

既存コレクションを次工程へ進めるオーケストレーター。完了済みの素材を自動検出し、未完了のステップから再開する。
`/wf-new --auto` から固定 collection を委譲された場合も本スキルが state 更新の単一責務を持つ。統合 runner の `allow_external_publish = false` 制約ではローカル動画・metadata 生成まで進め、YouTube 書き込み直前で停止する。対話 gate の承認後は同じ run へ結果を返し、resolver が実成果物を再評価する。

## Hard Gates: subagent 委譲境界

1. メインエージェントだけが owner CLI 経由で `workflow-state.json` の `assets` と制御面の `phase` / `stage` / `upload` / `updated_at` を更新する。subagent は委譲先 skill の入力確認に必要な場合だけ state を読み、書き込まない。
2. AskUserQuestion、`skip_*_approval` の承認ゲート、候補選択、playlist 初期化などの承認はメインエージェントが完了させる。未承認の操作を subagent へ委譲しない。
3. 各フェーズの生成・変換処理は Agent ツールで一作業ずつ subagent へ委譲する。委譲プロンプトには入力パス、実行する skill / CLI、期待成果物、state 書き込み禁止、完了報告形式を明記する。
4. subagent 終了後、メインエージェントが期待成果物の存在と現在の `phase` / `assets` との整合を実ファイルで検証する。すべて PASS の場合だけ state を更新する。失敗、欠落、不整合時は state を変更せず、同じステップから再実行できる状態で停止する。

委譲プロンプトには上記 3 の要素を具体値で埋め、成果物は絶対パスで受け取る。subagent の `status: success` だけを更新根拠にせず、実ファイルで検証する。

### workflow-state 制御面の更新境界

対象 collection を確定したら、その絶対 path を `COLLECTION_DIR` として固定する。メインも制御面キー (`phase` / `stage` / `upload` / `updated_at`) を Edit / Write で直接変更しない。必要な更新は次の owner CLI だけを使い、各更新と同じ owner lock 内で `updated_at` も更新させる。CLI が非 0 の場合は state を再編集せず、同じ工程から再開できる状態で停止する。

```bash
uv run yt-workflow-state --collection "$COLLECTION_DIR" set-phase <planning|prepared|mastered|publishing|complete>
uv run yt-workflow-state --collection "$COLLECTION_DIR" set-stage <planning|live>
uv run yt-workflow-state --collection "$COLLECTION_DIR" set-upload --video-id <video-id> [--video-url <url>] [--publish-at <timestamp>]
uv run yt-workflow-state --collection "$COLLECTION_DIR" touch
```

資産系キー (`assets.*` / `planning.*`) も直接変更せず、`set-asset` / `set-planning` を使う。`yt-upload-collection` / `yt-upload-auto` や owner reference script が state を更新済みの場合は、同じ変更を CLI で重ねない。

> **このセッションで初めて `/wf-*` を呼ぶ場合は、先に [`docs/workflow-cheatsheet.md`](../../../docs/workflow-cheatsheet.md) の判定フローを 1 回だけユーザーに提示すること**。

## When to Use

| 状況 | 使う？ |
|---|---|
| 制作中コレクションがあり、次工程へ進める意思がある | ✅ 使う |
| 制作中コレクションがそもそも無い | ❌ `/wf-new` を使う（企画候補が未確定でも同じ入口） |
| 「進んでる？」と読み取りだけ求められた | ❌ `/wf-status` を使う |
| 公開済み動画の振り返り | ❌ `/analytics --analyze` または `/analytics --flop` |

`/wf-next` は `workflow-state.json::phase` を読み取り、対応する次工程を 1 段だけ実行して `assets` / `phase` を更新する。**冪等性あり**：途中エラーで停止しても、再実行で未完了ステップから再開する。ユーザーが `workflow-state.json` を手で編集すると冪等性の前提が崩れる（[扱い基準](../../../docs/workflow-cheatsheet.md#workflow-statejson-の扱い)）。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/setup --channel` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内

## 承認ゲート（config 駆動）

`config/channel/workflow.json` の `workflow.wf_next` で、フェーズ進行前に承認を取るかをチャンネルごとに宣言できる。boolean は `skip_manual_mastering` と同じく **`true` = 手動工程（承認）を省いて自動進行** の向きに統一されている（#1744）。SKILL.md 本体を書き換える運用は不要（`yt-skills sync` の衝突を避けるためにも本ファイルは編集しない）。

```json
{
  "workflow": {
    "wf_next": {
      "skip_audio_approval": true,
      "skip_upload_approval": true,
      "skip_manual_mastering": false
    }
  }
}
```

- `skip_audio_approval` (default `true`): `false` にすると `prepared` フェーズ 2-B（音源承認ゲート）で、最終マスター候補を検出した時点で承認を取る
- `skip_upload_approval` (default `true`): `false` にすると `mastered` フェーズ 3-B（アップロード承認ゲート）で、`/publish --upload` 実行直前に承認を取る
- 既定値は両方 `true` で、`workflow.json` に何も書かれていない既存チャンネルは従来通り全自動進行（後方互換）
- 旧キー `approval_gates.audio` / `approval_gates.upload` は廃止済みで、設定に残っている場合は `ConfigError` で停止する。`skip_audio_approval` / `skip_upload_approval` へ移行する
- 値の解決は `youtube_automation.configuration.load_config().workflow.wf_next` 経由（`skip_audio_approval` / `skip_upload_approval` / `skip_manual_mastering`。コード側で参照可能）

`skip_*_approval = false` のゲートに到達したら、本 skill は AskUserQuestion で承認を取り、却下されたらフロー停止 + ガイダンスのみで終了する。

## raw master 直採用（`skip_manual_mastering`）

`workflow.wf_next.skip_manual_mastering`（default `false`）は、`prepared` フェーズ 2-B（マスター音源検出）で raw master と別の最終マスター候補が `01-master/` に見つからないときの挙動を切り替える。

- `true`: `assets.raw_master` のファイル名をそのまま `assets.master_audio` として採用し、`phase: "mastered"` へ進む。「raw（自動クロスフェード結合出力）を外部 DAW でマスタリングせずそのまま公開する」運用（raw=final）をチャンネル単位で宣言するためのオプション
- `false`（未設定含む）: 従来通り、ユーザーが最終マスターを `01-master/` に配置するまで停止する

`skip_audio_approval` とは独立した設定であることに注意。`skip_audio_approval` は「候補を採用する前に確認プロンプトを出すかどうか」だけを制御し、候補そのものの自動採用／スキップ判断には関与しない。`skip_manual_mastering: true` かつ `skip_audio_approval: false` の場合は、raw master を採用する前に承認を取る。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| videos.insert（1,600 units / 本、mastered フェーズの yt-upload-collection / yt-upload-auto） | アップロード本数 | collection / release 型・進行フェーズ |
| playlists.insert / playlistItems.insert（各 50 units、yt-playlist-manager --init） | 新規プレイリスト数 + 割当本数 | プレイリスト構成 |
| Vertex AI Lyria / MiniMax Music（subagent `/music --generate` 委譲時） | `/music --generate` の「想定 API call 数」を参照 | API engine パス採否 |

- 上限 / 承認: upload 前に `--plan` で事前確認し、playlist 系は `--dry-run` を使う。/video --generate /music --master /video --describe はローカル処理で API 0。委譲先 skill の見積もりは各 skill の「想定 API call 数」を参照。

## Instructions

### 直接実行の canonical timing 契約

`/wf-next` を直接呼んだ場合も、state 判定・lease・history/timing の正は `/wf-new --auto` と同じ state script とする。下記「1. アクティブなコレクションの特定」の既存手順で対象名を `<fixed-name>` として固定した後、フェーズ処理や子 skill を開始する前に、チャンネルルートで次の順序を守る。

```bash
STATE_SCRIPT=.claude/skills/wf-new/references/wf-auto-state.py
uv run python "$STATE_SCRIPT" acquire --channel-dir .
uv run python "$STATE_SCRIPT" plan --channel-dir . --collection <fixed-name> --token <token>
uv run python "$STATE_SCRIPT" heartbeat --channel-dir . --token <token>
uv run python -c 'from datetime import UTC, datetime; print(datetime.now(UTC).isoformat())'
```

`acquire` の `busy` / exit 20 では作業を開始しない。`plan` には必ず同じ `<token>` を渡す。`plan` 後は `heartbeat` の JSON 応答が `status: refreshed` の場合だけ lease owner の確認成功として AI 開始時刻を取得し、stdout を同じ attempt 専用の `<current-attempt-ai-started-at>` として保持する。`status: not-owner` も exit 0 で返るため、exit 0 だけでは owner と判定しない。`status: not-owner` では開始時刻を取得せず停止する。resolver が返した固定 collection と action を `<resolver-action>` としてそのまま使い、公開許可や実成果物から action を独自再判定せず、別 action へ読み替えない。別 collection ID や timing 保存処理も作らない。

resolver が `blocked / external_publish_disabled` を返した対話実行では、公開範囲と API write を明示してユーザー承認を取る。承認時は record / release せず、owner token で `approve --approval external-publish` を実行し、同じ token・collection で `plan` を再実行する。これにより durable な `workflow.scheduled_automation.allow_external_publish` は変更せず、同じ canonical attempt が `publish_ready` へ進む。却下時だけ blocked を記録して release する。

```bash
uv run python "$STATE_SCRIPT" approve --channel-dir . --token <token> --approval external-publish
uv run python "$STATE_SCRIPT" plan --channel-dir . --collection <fixed-name> --token <token>
```

resolver action と直接入口の既存責務は次の対応を正とする。

| resolver action | 直接 `/wf-next` の処理 |
|---|---|
| `wf-new` | planning が未完了であることを報告し、`/wf-new` を再開 action として blocked で閉じる |
| `lyria` / `minimax` / `suno-helper` / `masterup` | prepared の既存のフェーズ別処理をそのまま実行し、同じ action ID で記録する |
| `wf-next-local` / `wf-next` | mastered / publishing の既存のフェーズ別処理を実行する。`wf-next-local` は resolver が許可したローカル成果物までに限定し、YouTube write を行わない |
| `publish` | production 完了を検証して `/publish` を再開 action として blocked で閉じ、公開後処理を本 skill へ複製しない |
| `blocked` | resolver の reason / resume action を変更せず blocked で閉じる |
| `complete` | 下記 complete の既存検証を通過した場合だけ success で閉じる |

既存の成果物検証、承認 gate、state 更新責務を変更せず、子 skill の終了報告だけで成功にしない。期待成果物と state を検証した後、成功だけを success、手動介入または責務外 action への handoff を blocked、検証失敗を含むその他を failed とし、すべて同じ固定 collection、resolver action、同じ attempt の AI 開始時刻で閉じる。対話 gate の時間分類と `--human-interval` は `/wf-new --auto` の canonical timing 契約をそのまま使う。

```bash
uv run python "$STATE_SCRIPT" record --channel-dir . --token <token> --collection <fixed-name> --action <resolver-action> --status success|blocked|failed --reason <reason> [--resume-action <resolver-resume-action>] --ai-started-at <current-attempt-ai-started-at> [--human-interval <human-start> <human-end>]...
```

status を記録した後は、成功時だけでなく blocked / failed の停止報告前にも同じ固定 collection を `plan --channel-dir . --collection <fixed-name> --token <token>` で再評価し、次回の再開 action を推測しない。全終了経路の `finally` 相当で `release --channel-dir . --token <token>` を実行し、他 token の lease は変更しない。ただし上記の対話承認待ちはまだ終了経路ではなく、承認を attempt context に保存して再 plan するまで record / release しない。

`/wf-new --auto` が token、resolver の action / collection、attempt の開始時刻を固定して本 skill へ委譲した場合は、その実行文脈を再利用する。nested `acquire` や独自 attempt の作成・記録・release は行わず、成果物と state の検証結果を呼び出し元へ返し、canonical history の記録と lease 解放は `/wf-new --auto` に一度だけ行わせる。

### 1. アクティブなコレクションの特定

- `collections/planning/` の `workflow-state.json` を探索
- 複数ある場合はユーザーに選択を促す
- 対象確定後、フェーズ処理へ進む前に骨格プリフライトを実行する（fail-loud、#1494）:

  ```bash
  uv run yt-collection-preflight <collection-dir-name>
  ```

  `[NG]`（`01-master/` 等の欠落）が報告されたら `uv run yt-collection-preflight <collection-dir-name> --fix` で補完してから続行する。欠落したまま後工程へ進むと `/music --master` / `/video --generate` がマスター音源の置き場を見失う

### 2. フェーズ別処理

#### `prepared` → 段階的サポート

完了済みの素材と音楽エンジンを確認し、未完了の作業を案内・実行。

**Suno パス:**
1. `assets.music_prompts = true` + `assets.raw_master = null`:
   - `workflow-state.json::planning.music.suno_playlist_url` の記録有無と `02-Individual-music/` の音声ファイル（mp3 / m4a / wav）実在を確認する
   - **`02-Individual-music/` に音声ファイルが 1 件以上存在（URL 記録の有無は問わない）**:
     - AskUserQuestion による URL 入力はスキップする。title list は `/music --master` Step 1.6 がローカルファイル名から自動復元するため playlist URL は不要。メインが `/music --master` の dry-run / Step 5.1 以外の検証ゲートを実行し、選曲・混入許容・over-max 例外などの承認分岐をすべて解決する。ラウドネス全曲走査は subagent 内の Step 5.1 で1回だけ行う
     - Agent ツールで subagent を起動し、対象 collection、（記録があれば）playlist URL、承認済み選択条件を入力として `/music --master` の Subagent Contract を実行させる。`workflow-state.json` 更新と雨レイヤー後処理は実行させない
     - 期待成果物 `01-master/master.*`、`01-master/.selection.log`、`01-master/.loudness-receipt.json` の存在をメインが確認する。`yt-raw-master-check --apply --loudness-receipt <receipt>` で receipt と現在の collection / 入力 SHA-256 / 閾値 / PASS 判定を検証する。この CLI が `assets.raw_master` と `updated_at` を owner 経由で更新するため、`yt-workflow-state` で重ねて更新しない。検証時に FFmpeg の全曲走査を再実行しない。雨レイヤーが有効なら、その後にメインが `/music --master` Step 5.6 を実行し、出力と state を再検証する
     - ガイダンス: 「raw master をミキシング+マスタリングし、最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」
     - **ここでフロー停止**
   - **URL 記録済みだが `02-Individual-music/` に音声ファイルが無い**:
     - URL 再入力は要求せず、「ダウンロードが完了していない可能性があります。`/music --generate` を再開するか手動でダウンロードしてから `/wf-next` を再実行してください」を表示
     - **ここでフロー停止**（`/music --master` は自動実行しない）
   - **URL 未記録（キー自体が無い、または `null`）かつ `02-Individual-music/` に音声ファイルも無い**:
     - 従来通りユーザーにプレイリスト URL を AskUserQuestion で取得
     - URL 取得後、上記と同じくメインが `/music --master` の承認分岐を解決し、Agent ツールで Subagent Contract を委譲する
     - メインが `01-master/master.*`、`01-master/.selection.log`、`01-master/.loudness-receipt.json` を検証し、上記と同じ receipt 付き `yt-raw-master-check --apply` を実行する。この CLI が owner 経由で state を更新するため重ねて変更しない
     - ガイダンス: 「raw master をミキシング+マスタリングし、最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」
     - **ここでフロー停止**

**Lyria パス:**
1. `assets.music_prompts = true` + `assets.raw_master = null`:
   - Agent ツールで subagent を起動し、対象 collection と theme を入力に `/music --generate <theme>` の Lyria 3 API セグメント生成だけを実行させる（最大 ~184 秒/リクエスト）。state 書き込みと承認取得は禁止する
   - 委譲前に期待する `02-Individual-music/` の音声ファイルと `01-master/` の raw master パスを列挙する。メインが実在を確認し、成功時だけ生成ファイル名を JSON string として `yt-workflow-state --collection "$COLLECTION_DIR" set-asset raw_master <json-value>` へ渡す
   - ガイダンス: 「生成されたセグメントをミキシング+マスタリングし、最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」
   - **ここでフロー停止**

**MiniMax パス:**
1. `assets.music_prompts = true` + `assets.raw_master = null`:
   - 対象 collection と theme を入力に `/music --generate <theme>` の MiniMax Music segment生成だけを実行する。state 書き込みは行わず、生成条件・call上限の承認は `/music --generate` の契約を維持する
   - `02-Individual-music/` のsegmentと `01-master/master.mp3` の実在を確認し、成功時だけ `assets.raw_master` と `updated_at` を更新する
   - ガイダンス: 「生成されたマスターを確認し、最終マスターとして採用または差し替え後、`/wf-next` を再実行してください」
   - **ここでフロー停止**

**マスター音源検出（音源承認ゲート 2-B）:**
2. `assets.raw_master != null` + `assets.master_audio = null`:
   - **判定・state 更新は共通 review lifecycle の `yt-master-audio-review` を使う**。このCLIは worktree/main の候補へ `source:filename` IDを付け、固定名 `tmp/reviews/master-audio.html` に標準audio playerと検査情報をatomic生成する。HTMLは表示専用で、任意path・command・state patchを受け付けない。

     ```bash
     SKIP_MANUAL_MASTERING="$(python3 -c 'from youtube_automation.configuration import load_config; print(str(load_config().workflow.wf_next.skip_manual_mastering).lower())')"
     SKIP_AUDIO_APPROVAL="$(python3 -c 'from youtube_automation.configuration import load_config; print(str(load_config().workflow.wf_next.skip_audio_approval).lower())')"
     uv run yt-master-audio-review \
       --collection "$COLLECTION_DIR" \
       --skip-manual-mastering "$SKIP_MANUAL_MASTERING" \
       --skip-audio-approval "$SKIP_AUDIO_APPROVAL"
     ```

     web reviewを利用できないときは黙って自動承認せず、Codex / Claude の同じsessionで `--transport terminal` を付け、返された候補から `--candidate-id <source:filename>` を明示して再実行する。terminal fallbackも同じdigest再検証とstate確定ownerを通る。`skip_audio_approval = true` はHTMLとbrokerを起動せず、一意な候補だけ自動確定する。
   - **走査対象**:
     - worktree 内 `01-master/` を必ず走査
     - **worktree 検知**: `git rev-parse --git-common-dir` がカレント `.git` と異なる絶対パスを返したら worktree 内とみなし、メインリポルート（`git-common-dir` の親ディレクトリ）の `collections/planning/<collection-name>/01-master/` も確認する。採用するファイルが main repo 側にある場合は、state 更新前に worktree 側 `01-master/` へコピーする（state 更新後の動画化が worktree 内で完結するように）
   - **候補抽出**: raw_master と異なるファイルのうち `.m4a` / `.wav` / `.flac` / `.aac` / `.mp3` を最終マスター候補として列挙
   - 検出できた場合:
     - 複数候補があればユーザーに採用ファイルを確認（worktree 内と main repo 側で同名ファイルが両方ある場合も含む）
     - 採用ファイルが worktree 外（main repo 側）にあるときは worktree 側 `01-master/` にコピーしてから処理（state 更新後の動画化が worktree 内で完結するように）
     - **承認ゲート（`skip_audio_approval = false` のとき）**: 採用ファイル名を提示して AskUserQuestion で「この音源で `mastered` に進めてよいか」を確認する。承認されたら下記の state 更新へ進む。却下されたら `assets.master_audio` を更新せず、ガイダンス「最終マスターを差し替えて `/wf-next` を再実行してください」を表示して停止
     - `assets.master_audio` にファイル名のみ記録 → `phase: "mastered"` → 自動的に公開フローへ進む（`skip_audio_approval = true` のときは確認なし）
   - 検出できない場合:
     - `workflow.wf_next.skip_manual_mastering = true` のとき（raw=final 運用）: `assets.raw_master` のファイル名をそのまま最終マスターとして採用する。**承認ゲート（`skip_audio_approval = false`）が有効なら**、raw master 直採用であることを明示して AskUserQuestion で確認してから進む。`assets.master_audio` に `assets.raw_master` と同じファイル名を記録 → `phase: "mastered"` → 自動的に公開フローへ進む
     - `skip_manual_mastering = false`（未設定含む、デフォルト）: ガイダンス「最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」を表示して停止（従来動作）

#### `mastered` → 公開フロー（アップロード承認ゲートあり）

以下を一気通貫実行する。実作業は subagent、成果物検証と各ステップ完了時の `workflow-state.json` 更新はメインが担当し、途中で中断しても同じ状態から再開できる。

0. `01-master/<assets.master_audio>` を ffprobe し、`config.audio.target_duration_min` / `target_duration_max` と比較する。この確認は全尺動画を生成する Agent 1 の起動前に行う。目標外なら実尺と目標尺を提示して AskUserQuestion で例外承認を取り、承認時は owner token に保存して再 plan する。却下時は動画を生成せず blocked で終了する。

   ```bash
   uv run python "$STATE_SCRIPT" approve --channel-dir . --token <token> --approval duration-outside-target
   uv run python "$STATE_SCRIPT" plan --channel-dir . --collection <fixed-name> --token <token>
   ```

1. **並列 A**（2 Agent 同時起動）:
   - Agent 1: 対象 collection、`01-master/<assets.master_audio>`、`10-assets/main.png/jpg` または `loop.mp4` を入力に Skill `/video --generate` の Subagent Contract を実行。thumbnail skill-config も渡し、`textless.enabled: false` の共有 `main.jpg` を textless 再生成へ戻さない。期待成果物は `01-master/*.mp4`。返却には同じ生成実行で解決した背景経路、effect、overlay、Full output outlookを含める
   - Agent 2 の起動前に、メインが `/video --describe` の重複トラック名を検出し、必要な表示名 mapping を確定するが、まだ `apply_track_display_names()` は呼ばない。その mapping、planning / localization、skill-config、benchmark 入力を列挙し、Agent 2 には `/video --describe` の Step 1 から品質チェック、`yt-title-duplicate-check`、検証済み `20-documentation/descriptions.json` + 同 basename HTML 保存までを実行させる。`apply_track_display_names()` と `workflow-state.json` の `assets.description` 更新は実行させない
   - 両 Agent とも state は入力確認に必要な範囲だけ読み、書き込まず、AskUserQuestion を実行しない。片方でも失敗または成果物欠落なら state を更新せず停止する
2. 並列 A 完了後:
   - メインが両成果物の存在と `phase: "mastered"` との整合を確認する
   - メインは `descriptions.html` の絶対pathをユーザーが開けるMarkdown linkで提示し、title、概要欄、tag、localizationを確認対象として要約する。自動進行でもこのlinkと要約を完了報告へ残す。`skip_upload_approval = false` では、この概要欄確認を後述のアップロード承認ゲート 3-B に含め、確認完了まで `assets.description` と phase を更新しない
   - PASS 後だけ、メインが Agent 1 の解決済み表示値を `/video --generate` の `master-video-review.md` に従ってfull reviewへ渡す。probe・digest・承認成功時に同CLIが `assets.master_video` を確定する。`skip_upload_approval = false` なら、ここでアップロード承認ゲート 3-B を先に実行し、承認後だけこの項目の残りへ進む。次に確定済み表示名 mapping を `apply_track_display_names()` で永続化し、概要欄完了を正準キー `assets.description` へ保存する `set-description-generated true` owner CLI を実行してから、次の owner CLI で phase と `updated_at` を一体更新する

     ```bash
     uv run yt-workflow-state --collection "$COLLECTION_DIR" set-phase publishing
     ```
3. **アップロード承認ゲート 3-B（`skip_upload_approval = false` のとき）**:
   - Step 2 から呼ぶゲートであり、承認されるまで `assets.description` と phase は `mastered` のまま保持する
   - 並列 A 完了直後、ユーザーに公開方法を提示する前に必ず `uv run yt-upload-collection --plan [-c <collection-name>] [--allow-duration-outside-target]` を実行し、`config/schedule_config.json` / `config/channel/youtube.json` を反映した実際の公開タイミングを確定する
   - resolver の `allow_duration_outside_target` が true の場合は、アップロード承認ゲートの plan に `--allow-duration-outside-target` を渡す。false の場合は渡さない。会話上の承認だけからフラグを組み立てず、owner 管理の attempt context を正とする
   - plan 結果が `📅 公開設定: 非公開でアップロード（即時公開は行いません）` の場合は、予約設定または YouTube Studio での手動公開を案内する。`📅 公開設定: 限定公開 (unlisted)` / `📅 公開設定: 非公開 (private)` が出た場合は、その公開範囲でアップロードされることを AskUserQuestion の文面に含める。`📅 公開予定: <日時>` が出た場合は「今アップロード → `<日時>` に自動で一般公開」と、実際の予約時刻を AskUserQuestion の文面に含める
   - `/publish --upload` を呼ぶ前に AskUserQuestion で「YouTube にアップロード + live 移行してよいか」を確認する。このとき、plan 結果に基づく公開タイミングまたは公開範囲（非公開アップロード / 限定公開 / 非公開 / 予約公開日時）を必ず明示する
   - 承認されたら次ステップへ進む。却下されたら `phase` を `mastered` のままにして停止し、ガイダンス「準備が整ったら `/wf-next` を再実行してください」を表示
   - `skip_upload_approval = true` のときは確認なしでそのまま進む（従来の全自動挙動）
4. **初投稿プレイリスト初期化**:
   - `config/channel/playlists.json` が存在する場合、Skill `/publish --playlist` で `uv run yt-playlist-status` を実行する
   - `playlist_id` 未設定の `(未作成)` がある場合は、`uv run yt-playlist-manager --init --dry-run` を表示し、ユーザー確認後に `uv run yt-playlist-manager --init` を実行してから `/publish --upload` へ進む
   - この確認は `skip_upload_approval` とは別の playlist 作成ゲート。`skip_upload_approval = true` でも、YouTube 上の playlist 作成と `config/channel/playlists.json` 書き戻しを伴うため未作成 playlist がある場合は確認を省略しない
   - ユーザーが playlist 初期化を却下した場合は `/publish --upload` を実行せず停止し、`/publish --playlist` で初期化してから `/wf-next` を再実行するよう案内する
   - これは YouTube 上の playlist 作成と `playlist_id` 書き戻しが目的。初回動画の追加は次の `/publish --upload` 内部の自動 assign (`assign_video()`) に任せる
   - `config/channel/playlists.json` が無い、または全 playlist に `playlist_id` がある場合はスキップ
5. **順次**: Agent ツールで subagent を起動し、対象 collection、動画、thumbnail、description を明示して Skill `/publish --upload` の Subagent Contract の `plan` / preflight だけを実行させる。state / tracking 更新と実アップロードは実行させない
   - resolver の `allow_duration_outside_target` が true の場合は、subagent の plan / preflight とメインの実 CLI の両方へ `--allow-duration-outside-target` を渡す。false の場合は渡さない。会話上の承認だけからフラグを組み立てず、owner 管理の attempt context を正とする
   - メインが完了報告の動画・メタデータパスと plan 結果を実ファイルおよび Step 3 の承認済み公開条件と突合する。不整合なら state を更新せず停止する
   - PASS 後、メインが `uv run yt-upload-collection [-c <collection-name>] [--allow-duration-outside-target]`（release 型は `uv run yt-upload-auto`）を実行する。実 CLI が upload tracking、state 更新、collection 型の planning → live 移行を一体で行うため、メインは同じ変更を手作業で重ねない
   - 実行後、メインが `20-documentation/upload_tracking.json`、対象動画、移動先 collection の state に記録された `upload.video_id` / `upload.video_url`、`stage: "live"`、`phase: "complete"` を検証する。いずれかが欠落・不整合なら完了扱いにしない

#### `publishing` → リカバリ（途中エラー再実行）

メインが `assets` フラグと実ファイルを突合して未完了ステップを特定し、同じ subagent 委譲から再実行する。
- `assets.master_video = null` → 並列 A から
- `upload.video_id = null` → 初投稿プレイリスト初期化ゲート（`uv run yt-playlist-status` → 必要なら `--init --dry-run` → 確認後 `--init`）を通してから `/publish --upload` へ進む
- `upload.video_id != null` かつ phase / stage / live 移動が未完了 → `20-documentation/upload_tracking.json` が schema v3、全体と Complete Collection の status が `completed`、video ID が state と完全一致する場合だけ、remote upload と playlist assign を skip する。planning 側 collection を同名の `collections/live/` へ移動（同名 live が既にあれば停止）し、移動後の絶対 path で `COLLECTION_DIR` を固定し直して次の owner CLI を順に実行する。tracking 欠落・不一致なら `upload_state_inconsistent` で停止し、upload を再実行しない

  ```bash
  uv run yt-workflow-state --collection "$COLLECTION_DIR" set-stage live
  uv run yt-workflow-state --collection "$COLLECTION_DIR" set-phase complete
  ```

#### `complete` → 完了案内

```
全工程完了済みです。
- `/analytics --analyze` で初週パフォーマンスを確認してください（T+7日後推奨）
```

### 3. state ファイルの更新ルール

state を更新するのはメインエージェントだけとし、検証 PASS 後の制御面操作は owner CLI で `updated_at` と一体更新する。資産系だけを更新した場合は `touch` を使う。subagent が state を変更した場合は失敗として扱い、変更内容を確認してから同じステップを再実行する。スキーマ詳細は `.claude/skills/wf-new/references/schema.md` を参照。

## 障害時ガイダンス

各ステップは子スキルへ委譲する orchestration。失敗時は委譲先の障害が表面化する。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 委譲先 skill の失敗 | 子 skill がエラー終了 | 各子 skill の「障害時ガイダンス」を参照して個別に対処 |

## Cross References

- 新規開始: `/wf-new`
- 進捗確認: `/wf-status`
