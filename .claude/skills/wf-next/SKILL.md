---
name: wf-next
description: "Use when 既存コレクション（collections/planning/）を一段進めるとき。「次どうする？」「続き進めて」で発動。進捗閲覧のみは /wf-status、新規は /wf-new"
---

## Overview

既存コレクションを次工程へ進めるオーケストレーター。完了済みの素材を自動検出し、未完了のステップから再開する。

> **このセッションで初めて `/wf-*` を呼ぶ場合は、先に [`docs/workflow-cheatsheet.md`](../../../docs/workflow-cheatsheet.md) の判定フローを 1 回だけユーザーに提示すること**（CLAUDE.md §6 参照）。

## When to Use

| 状況 | 使う？ |
|---|---|
| 制作中コレクションがあり、次工程へ進める意思がある | ✅ 使う |
| 制作中コレクションがそもそも無い | ❌ `/wf-new` を使う（または `/collection-ideate` で候補から） |
| 「進んでる？」と読み取りだけ求められた | ❌ `/wf-status` を使う |
| 公開済み動画の振り返り | ❌ `/analytics-analyze` または `/postmortem` |

`/wf-next` は `workflow-state.json::phase` を読み取り、対応する次工程を 1 段だけ実行して `assets` / `phase` を更新する。**冪等性あり**：途中エラーで停止しても、再実行で未完了ステップから再開する。ユーザーが `workflow-state.json` を手で編集すると冪等性の前提が崩れる（[扱い基準](../../../docs/workflow-cheatsheet.md#workflow-statejson-の扱い)）。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

## 承認ゲート（config 駆動）

`config/channel/workflow.json` の `workflow.wf_next.approval_gates` で、フェーズ進行前に承認を取るかをチャンネルごとに宣言できる。SKILL.md 本体を書き換える運用は不要（`yt-skills sync` の衝突を避けるためにも本ファイルは編集しない）。

```json
{
  "workflow": {
    "wf_next": {
      "approval_gates": {
        "audio": false,
        "upload": false
      },
      "skip_manual_mastering": false
    }
  }
}
```

- `approval_gates.audio` (default `false`): `prepared` フェーズ 2-B（音源承認ゲート）。最終マスター候補を検出した時点で承認を取る
- `approval_gates.upload` (default `false`): `mastered` フェーズ 3-B（アップロード承認ゲート）。`/video-upload` 実行直前に承認を取る
- 既定値は両方 `false` で、`workflow.json` に何も書かれていない既存チャンネルは従来通り全自動進行（後方互換）
- 値の解決は `youtube_automation.utils.config.load_config().workflow.wf_next` 経由（`approval_gates.{audio,upload}` / `skip_manual_mastering`。コード側で参照可能）

ゲートが `true` のフェーズに到達したら、本 skill は AskUserQuestion で承認を取り、却下されたらフロー停止 + ガイダンスのみで終了する。

## raw master 直採用（`skip_manual_mastering`）

`workflow.wf_next.skip_manual_mastering`（default `false`）は、`prepared` フェーズ 2-B（マスター音源検出）で raw master と別の最終マスター候補が `01-master/` に見つからないときの挙動を切り替える。

- `true`: `assets.raw_master` のファイル名をそのまま `assets.master_audio` として採用し、`phase: "mastered"` へ進む。「raw（自動クロスフェード結合出力）を外部 DAW でマスタリングせずそのまま公開する」運用（raw=final）をチャンネル単位で宣言するためのオプション
- `false`（未設定含む）: 従来通り、ユーザーが最終マスターを `01-master/` に配置するまで停止する

`approval_gates.audio` とは独立した設定であることに注意。`approval_gates.audio` は「候補を採用する前に確認プロンプトを出すかどうか」だけを制御し、候補そのものの自動採用／スキップ判断には関与しない。`skip_manual_mastering: true` かつ `approval_gates.audio: true` の場合は、raw master を採用する前に承認を取る。

## Instructions

### 1. アクティブなコレクションの特定

- `collections/planning/` の `workflow-state.json` を探索
- 複数ある場合はユーザーに選択を促す
- 対象確定後、フェーズ処理へ進む前に骨格プリフライトを実行する（fail-loud、#1494）:

  ```bash
  bunx tayk collection-preflight <collection-dir-name>
  ```

  `[NG]`（`01-master/` 等の欠落）が報告されたら `bunx tayk collection-preflight <collection-dir-name> --fix` で補完してから続行する。欠落したまま後工程へ進むと `/masterup` / `/videoup` がマスター音源の置き場を見失う

### 2. フェーズ別処理

#### `prepared` → 段階的サポート

完了済みの素材と音楽エンジンを確認し、未完了の作業を案内・実行。

**Suno パス:**
1. `assets.music_prompts = true` + `assets.raw_master = null`:
   - `workflow-state.json::planning.music.suno_playlist_url` の記録有無と `02-Individual-music/` の音声ファイル（mp3 / m4a / wav）実在を確認する
   - **URL 記録済み + `02-Individual-music/` に音声ファイルが 1 件以上存在**:
     - AskUserQuestion による URL 入力はスキップし、記録済み URL で Skill ツール `/masterup <URL>` を自動実行 → raw master 生成
     - `assets.raw_master` にファイル名を記録
     - ガイダンス: 「raw master をミキシング+マスタリングし、最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」
     - **ここでフロー停止**
   - **URL 記録済みだが `02-Individual-music/` に音声ファイルが無い**:
     - URL 再入力は要求せず、「ダウンロードが完了していない可能性があります。`/suno-helper` を再開するか手動でダウンロードしてから `/wf-next` を再実行してください」を表示
     - **ここでフロー停止**（`/masterup` は自動実行しない）
   - **URL 未記録（キー自体が無い、または `null`）**:
     - 従来通りユーザーにプレイリスト URL を AskUserQuestion で取得
     - Skill ツールで `/masterup <URL>` 自動実行 → DL + raw master 生成
     - `assets.raw_master` にファイル名を記録
     - ガイダンス: 「raw master をミキシング+マスタリングし、最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」
     - **ここでフロー停止**

**Lyria パス:**
1. `assets.music_prompts = true` + `assets.raw_master = null`:
   - Skill ツールで `/lyria <theme>` を実行（Lyria 3 API を 1 回以上呼んでセグメント生成、最大 ~184 秒/リクエスト）
   - `assets.raw_master` にファイル名を記録
   - ガイダンス: 「生成されたセグメントをミキシング+マスタリングし、最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」
   - **ここでフロー停止**

**マスター音源検出（音源承認ゲート 2-B）:**
2. `assets.raw_master != null` + `assets.master_audio = null`:
   - **判定・state 更新は reference script を使う**。worktree 外（main repo 側）で採用する最終マスター候補を見つけた場合は、先に worktree 側 `01-master/` へコピーしてから script を実行する。script は worktree 側 `01-master/` と `workflow-state.json` を唯一の書き込み対象にする。

     ```bash
     SKIP_MANUAL_MASTERING="$(python3 -c 'from youtube_automation.utils.config import load_config; print(str(load_config().workflow.wf_next.skip_manual_mastering).lower())')"
     APPROVAL_GATE_AUDIO="$(python3 -c 'from youtube_automation.utils.config import load_config; print(str(load_config().workflow.wf_next.approval_gates.audio).lower())')"
     python3 "$(git rev-parse --show-toplevel)/.claude/skills/wf-next/references/master_audio_transition.py" \
       "$COLLECTION_DIR" \
       --skip-manual-mastering "$SKIP_MANUAL_MASTERING" \
       --approval-gate-audio "$APPROVAL_GATE_AUDIO"
     ```

     `action: "needs_selection"` が返った場合は、`candidate_sources[].id`（例: `main:final.wav` / `worktree:final.wav`）から採用候補を AskUserQuestion で確認し、`--selected-master-audio <id>` を付けて同じコマンドを再実行する。候補ファイル名が一意なら従来通り `<filename>` でもよいが、worktree と main repo 側で同名候補がある場合は `<id>` が必須。`action: "needs_approval"` が返った場合だけ AskUserQuestion で承認を取り、承認なら `--approved yes --approved-master-audio <master_audio>`、却下なら `--approved no --approved-master-audio <master_audio>` を付けて同じコマンドを再実行する。複数候補かつ承認ゲートありの場合は、選択後の再実行で `needs_approval` が返るため、承認時も `--selected-master-audio <id> --approved yes --approved-master-audio <filename>` を付ける。承認対象と再実行時の採用予定ファイルが一致しない場合、script は state を更新せず再承認を要求する。この script の出力と `workflow-state.json` 更新結果を 2-B の実行契約とする。
   - **走査対象**:
     - worktree 内 `01-master/` を必ず走査
     - **worktree 検知**: `git rev-parse --git-common-dir` がカレント `.git` と異なる絶対パスを返したら worktree 内とみなし、メインリポルート（`git-common-dir` の親ディレクトリ）の `collections/planning/<collection-name>/01-master/` も確認する。採用するファイルが main repo 側にある場合は、state 更新前に worktree 側 `01-master/` へコピーする（state 更新後の動画化が worktree 内で完結するように）
   - **候補抽出**: raw_master と異なるファイルのうち `.m4a` / `.wav` / `.flac` / `.aac` / `.mp3` を最終マスター候補として列挙
   - 検出できた場合:
     - 複数候補があればユーザーに採用ファイルを確認（worktree 内と main repo 側で同名ファイルが両方ある場合も含む）
     - 採用ファイルが worktree 外（main repo 側）にあるときは worktree 側 `01-master/` にコピーしてから処理（state 更新後の動画化が worktree 内で完結するように）
     - **承認ゲート（`approval_gates.audio = true` のとき）**: 採用ファイル名を提示して AskUserQuestion で「この音源で `mastered` に進めてよいか」を確認する。承認されたら下記の state 更新へ進む。却下されたら `assets.master_audio` を更新せず、ガイダンス「最終マスターを差し替えて `/wf-next` を再実行してください」を表示して停止
     - `assets.master_audio` にファイル名のみ記録 → `phase: "mastered"` → 自動的に公開フローへ進む（`approval_gates.audio = false` のときは確認なし）
   - 検出できない場合:
     - `workflow.wf_next.skip_manual_mastering = true` のとき（raw=final 運用）: `assets.raw_master` のファイル名をそのまま最終マスターとして採用する。**承認ゲート（`approval_gates.audio = true`）が有効なら**、raw master 直採用であることを明示して AskUserQuestion で確認してから進む。`assets.master_audio` に `assets.raw_master` と同じファイル名を記録 → `phase: "mastered"` → 自動的に公開フローへ進む
     - `skip_manual_mastering = false`（未設定含む、デフォルト）: ガイダンス「最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」を表示して停止（従来動作）

#### `mastered` → 公開フロー（アップロード承認ゲートあり）

以下を一気通貫実行。各ステップ完了時に `workflow-state.json` を更新し、途中で中断しても同じ状態から再開できる。

1. **並列 A**（2 Agent 同時起動）:
   - Agent 1: Skill `/videoup` — generate_videos.sh で動画生成
   - Agent 2: Skill `/video-description` — 概要欄自動生成
2. 並列 A 完了後:
   - `assets.master_video`, `assets.description` を更新
3. **アップロード承認ゲート 3-B（`approval_gates.upload = true` のとき）**:
   - 並列 A 完了直後、ユーザーに公開方法を提示する前に必ず `bunx tayk upload-collection --plan [-c <collection-name>]` を実行し、`config/schedule_config.json` / `config/channel/youtube.json` を反映した実際の公開タイミングを確定する
   - plan 結果が `📅 公開設定: 即時公開 (public)` の場合だけ「即時公開」と表現する。`📅 公開設定: 限定公開 (unlisted)` / `📅 公開設定: 非公開 (private)` が出た場合は、その公開範囲でアップロードされることを AskUserQuestion の文面に含める。`📅 公開予定: <日時>` が出た場合は「今アップロード → `<日時>` に自動で一般公開」と、実際の予約時刻を AskUserQuestion の文面に含める
   - `/video-upload` を呼ぶ前に AskUserQuestion で「YouTube にアップロード + live 移行してよいか」を確認する。このとき、plan 結果に基づく公開タイミングまたは公開範囲（即時公開 / 限定公開 / 非公開 / 予約公開日時）を必ず明示する
   - 承認されたら次ステップへ進む。却下されたら `phase` を `mastered` のままにして停止し、ガイダンス「準備が整ったら `/wf-next` を再実行してください」を表示
   - `approval_gates.upload = false` のときは確認なしでそのまま進む（従来の全自動挙動）
4. **初投稿プレイリスト初期化**:
   - `config/channel/playlists.json` が存在する場合、Skill `/playlist` で `bunx tayk playlist-status` を実行する
   - `playlist_id` 未設定の `(未作成)` がある場合は、`bunx tayk playlist-manager --init --dry-run` を表示し、ユーザー確認後に `bunx tayk playlist-manager --init` を実行してから `/video-upload` へ進む
   - この確認は `approval_gates.upload` とは別の playlist 作成ゲート。`approval_gates.upload = false` でも、YouTube 上の playlist 作成と `config/channel/playlists.json` 書き戻しを伴うため未作成 playlist がある場合は確認を省略しない
   - ユーザーが playlist 初期化を却下した場合は `/video-upload` を実行せず停止し、`/playlist` で初期化してから `/wf-next` を再実行するよう案内する
   - これは YouTube 上の playlist 作成と `playlist_id` 書き戻しが目的。初回動画の追加は次の `/video-upload` 内部の自動 assign (`assign_video()`) に任せる
   - `config/channel/playlists.json` が無い、または全 playlist に `playlist_id` がある場合はスキップ
5. **順次**: Skill `/video-upload` — YouTube アップロード + live 移行
   - `upload.video_id`, `upload.video_url` を記録
   - `stage: "live"`, `phase: "complete"` に更新
   - `collections/planning/` → `collections/live/` に移動

#### `publishing` → リカバリ（途中エラー再実行）

`assets` フラグで未完了ステップを特定し、そこから再実行。
- `assets.master_video = null` → 並列 A から
- `upload.video_id = null` → 初投稿プレイリスト初期化ゲート（`bunx tayk playlist-status` → 必要なら `--init --dry-run` → 確認後 `--init`）を通してから `/video-upload` へ進む

#### `complete` → 完了案内

```
全工程完了済みです。
→ `/analytics-analyze` で初週パフォーマンスを確認してください（T+7日後推奨）
```

### 3. state ファイルの更新ルール

各操作で `updated_at` を現在時刻に更新。スキーマ詳細は `.claude/skills/wf-new/references/schema.md` を参照。

## 障害時ガイダンス

次工程は子スキルへ委譲する orchestration。失敗時は委譲先の障害が表面化する。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 委譲先 skill の失敗 | 子 skill がエラー終了 | 各子 skill の「障害時ガイダンス」を参照して個別に対処 |

## Cross References

- 新規開始: `/wf-new`
- 進捗確認: `/wf-status`
