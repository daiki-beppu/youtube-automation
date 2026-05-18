---
name: wf-next
description: Use when 既存コレクション（collections/planning/ 配下）の次の工程を実行したいとき。「次どうする？」「次のステップやって」「続き進めて」など、制作中コレクションを一段進めるときに使用する。読むだけで進捗を見たい場合は /wf-status、新規コレクション開始は /wf-new
---

## Overview

既存コレクションを次工程へ進めるオーケストレーター。完了済みの素材を自動検出し、未完了のステップから再開する。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-import` を案内

## Instructions

### 1. アクティブなコレクションの特定

- `collections/planning/` の `workflow-state.json` を探索
- 複数ある場合はユーザーに選択を促す

### 2. フェーズ別処理

#### `prepared` → 段階的サポート

完了済みの素材と音楽エンジンを確認し、未完了の作業を案内・実行。

**Suno パス:**
1. `assets.music_prompts = true` + `assets.raw_master = null`:
   - ユーザーにプレイリスト URL を AskUserQuestion で取得
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
   - **走査対象**:
     - worktree 内 `01-master/` を必ず走査
     - **worktree 検知**: `git rev-parse --git-common-dir` がカレント `.git`（`git rev-parse --git-dir` の絶対パス）と異なる絶対パスを返したら worktree 内とみなす。
     - **main repo 側パス導出**: worktree 内のときは `git rev-parse --git-common-dir` の親ディレクトリ（= main repo ルート）配下の `collections/planning/<collection-name>/01-master/` も走査対象に追加（worktree は短命で、ユーザーが DAW 書き出しを main repo 側に置くケースに対応）。
   - **候補抽出**:
     - 拡張子: `.m4a` / `.wav` / `.flac` / `.aac` / `.mp3` のみ
     - `raw_master`（典型的には `master.mp3`）と同名のファイルは除外（raw を最終マスターと誤検出しない）
     - 拡張子が候補に含まれていても raw_master と同一ファイル名のものは候補にしない
   - 検出できた場合:
     - 複数候補があればユーザーに採用ファイルを確認（worktree 内と main repo 側で同名ファイルが両方ある場合は両方提示してどちらを採用するか聞く）
     - 採用ファイルが worktree 外（main repo 側）にあるときは worktree 側 `01-master/` にコピーしてから処理（state 更新後の動画化・後続 skill が worktree 内で完結するように）
     - `assets.master_audio` にはコピー後の **ファイル名のみ** 記録 → `phase: "mastered"` → 自動的に公開フローへ進む
   - 検出できない場合: ガイダンス「最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」（worktree 実行時は「worktree 側 `01-master/` か main repo 側 `01-master/` のいずれかに配置」と案内）

> Note: `/videoup` 側の `generate_videos.sh` も同様に worktree 実行時の main repo 側 master-mix 検出に未対応。別 issue で追従予定（本 skill のスコープ外）。

#### `mastered` → 全自動公開フロー（承認なし）

以下を全自動で一気通貫実行。各ステップ完了時に `workflow-state.json` を更新し、途中で中断しても同じ状態から再開できる。

1. **並列 A**（2 Agent 同時起動）:
   - Agent 1: Skill `/videoup` — generate_videos.sh で動画生成
   - Agent 2: Skill `/video-description` — 概要欄自動生成
2. 並列 A 完了後:
   - `assets.master_video`, `assets.description` を更新
3. **順次**: Skill `/video-upload` — YouTube アップロード + live 移行
   - `upload.video_id`, `upload.video_url` を記録
   - `stage: "live"`, `phase: "complete"` に更新
   - `collections/planning/` → `collections/live/` に移動

#### `publishing` → リカバリ（途中エラー再実行）

`assets` フラグで未完了ステップを特定し、そこから再実行。
- `assets.master_video = null` → 並列 A から
- `upload.video_id = null` → `/video-upload` から

#### `complete` → 完了案内

```
全工程完了済みです。
→ `/analytics-analyze` で初週パフォーマンスを確認してください（T+7日後推奨）
```

### 3. state ファイルの更新ルール

各操作で `updated_at` を現在時刻に更新。スキーマ詳細は `.claude/references/workflow/schema.md` を参照。

## Cross References

- 新規開始: `/wf-new`
- 進捗確認: `/wf-status`
