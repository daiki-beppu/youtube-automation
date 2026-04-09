---
name: wf-next
description: Use when コレクション制作の次のステップを知りたい・実行したいとき。「次のステップ」「次にやること」「next」「続き」「次は？」など、制作の次工程への進行に関わる場面で必ず使用すること
---

## Overview

制作サポート + 全自動公開オーケストレーター。`assets` フラグベースの冪等処理。

## Instructions

### 1. アクティブなコレクションの特定

- `collections/planning/` の `workflow-state.json` を探索
- 複数ある場合はユーザーに選択を促す

### 2. フェーズ別処理

#### `prepared` → 段階的サポート

`assets` フラグと `music_engine` を確認し、未完了の作業を案内・実行。

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

以下を全自動で一気通貫実行。各ステップ完了時に `assets` フラグを更新（冪等性確保）。

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

各操作で `updated_at` を現在時刻に更新。スキーマ詳細は `workflow-references/schema.md` を参照。

## Cross References

- 新規開始: `/wf-new`
- 進捗確認: `/wf-status`
