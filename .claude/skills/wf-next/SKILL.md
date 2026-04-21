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
   - Skill ツールで `/lyria <theme>` を実行（composition.json → セグメント生成 → raw master 自動生成）
   - `assets.raw_master` にファイル名を記録
   - ガイダンス: 「生成されたセグメントをミキシング+マスタリングし、最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」
   - **ここでフロー停止**

**マスター音源検出:**
2. `assets.raw_master != null` + `assets.master_audio = null`:
   - `01-master/` 内のファイルを走査し、raw_master と異なるファイル（ユーザーが作成した最終マスター）を検出
   - 検出できた場合: `assets.master_audio` にファイル名記録 → `phase: "mastered"` → 自動的に公開フローへ進む
   - 検出できない場合: ガイダンス「最終マスターを 01-master/ に配置後、`/wf-next` を再実行してください」

#### `mastered` → 全自動公開フロー（承認なし）

以下を全自動で一気通貫実行。各ステップ完了時に `workflow-state.json` を更新し、途中で中断しても同じ状態から再開できる。

1. **並列 A**（2 Agent 同時起動）:
   - Agent 1: Skill `/videoup` — generate_videos.sh で動画生成
   - Agent 2: Skill `/description` — 概要欄自動生成
2. 並列 A 完了後:
   - `assets.master_video`, `assets.description` を更新
3. **順次**: Skill `/upload` — YouTube アップロード + live 移行
   - `upload.video_id`, `upload.video_url` を記録
   - `stage: "live"`, `phase: "publishing"` に更新
   - `collections/planning/` → `collections/live/` に移動
4. **順次**: `uv run yt-post-upload community-draft <collection-path>` — コミュニティ投稿ドラフト
   - `community.drafted` を更新
   - `phase: "complete"` に更新

#### `publishing` → リカバリ（途中エラー再実行）

`assets` フラグで未完了ステップを特定し、そこから再実行。
- `assets.master_video = null` → 並列 A から
- `upload.video_id = null` → `/upload` から
- `community.drafted = false` → コミュニティドラフトから

#### `complete` → 完了案内

```
全工程完了済みです。
→ `/analyze` で初週パフォーマンスを確認してください（T+7日後推奨）
```

### 3. state ファイルの更新ルール

各操作で `updated_at` を現在時刻に更新。スキーマ詳細は `.claude/references/workflow/schema.md` を参照。

## Cross References

- 新規開始: `/wf-new`
- 進捗確認: `/wf-status`
