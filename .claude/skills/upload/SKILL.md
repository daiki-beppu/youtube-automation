---
name: upload
description: Use when コレクションの動画が完成し、YouTubeへのアップロード自動化が必要なとき。Complete Collection のアップロードと live 移行を実行
---

## Overview

Complete Collection を YouTube にアップロードし、`planning/` → `live/` へ自動移行します。`/description` スキルで事前生成した概要欄・タイトル・タグを使用します。

## When to Use

- コレクションの動画ファイルが揃い、YouTube へのアップロードが必要なとき
- アップロード設定の確認や OAuth 認証のセットアップが必要なとき

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| `$ARGUMENTS` | コレクションディレクトリパス（省略可） | `/upload collections/planning/20260304-clm-fairy-forest-collection` |
| 未指定 | `collections/planning/` から自動検出 | `/upload` |

## Channel Adaptation

実行前に `channel_config.json` の `content_model` を読み取り、チャンネルに適応する:

| content_model.type | 動作 |
|-------------------|------|
| `collection` | Complete Collection アップロード → live 移動（単一動画） |
| `single_release` | `content_model.languages` に基づくアップロード |

### collection 型
- 下記フローのとおり Complete Collection を1本アップロード
- `collection_uploader.py` を使用

### single_release + languages: ["jp","en"]（COT）
- **同日2本アップロード**: JP + EN を同日投稿（API クォータ: 2 × 1,600 = 3,200 ユニット）
- **プレイリスト管理**: `channel_config.json` の `playlists.jp` / `playlists.en` に自動追加
- **相互リンク**: アップロード後に概要欄を更新し、JP↔EN 動画 URL を相互記載
- `video_uploader.py` を直接使用

## Instructions

あなたは YouTube アップロード自動化スペシャリストです。YouTube Data API v3、OAuth 2.0 認証、Collection Uploader の運用に精通しています。

### 対象コレクション

```
$ARGUMENTS
```

引数が指定されている場合はそのディレクトリを、未指定の場合は `collections/planning/` 配下のコレクションを自動検出します。

### 前提条件チェック

アップロード前に以下を確認する（詳細は `references/posting-checklist.md` 参照）:

1. **マスター動画**: `01-master/*.mp4` または `03-Individual-movie/*master*.mp4` — 存在しなければエラー終了
2. **サムネイル**: `10-assets/thumbnail.jpg` — 存在しなければエラー終了
3. **概要欄**: `20-documentation/descriptions.md` — **存在しない場合は `/description` スキルを実行して自動生成する**（対象コレクションパスを引き継ぐ）。生成完了後にアップロードフローへ進む

### アップロードフロー

以下を自動実行:

1. **Complete Collection アップロード** — マスター動画、メタデータ（descriptions.md から読み込み）、サムネイル設定
2. **live 移動** — `collections/planning/` → `collections/live/`

メタデータは `descriptions.md` から title / description / tags を優先使用。存在しない場合は `BAHMetadataGenerator` で自動生成にフォールバック。

### コマンドリファレンス

```bash
# Complete Collection アップロード（デフォルト動作）
uv run yt-upload-collection [-c NAME]

# 進捗確認
uv run yt-upload-collection --status [-c NAME]

# スケジュール計算（ドライラン）
uv run yt-upload-collection --plan [-c NAME]
```

### エラーハンドリング

- トラッキングによるリジューム（中断後の再実行で未完了分のみ処理）
- 指数バックオフによるリトライ（5xx エラー時、最大5回）
- `20-documentation/upload_tracking.json` (v3 スキーマ) へのログ保存

### リファレンス

アップロード前の詳細チェックリストは `references/posting-checklist.md` を参照。

### API ステータス設定（自動適用）

アップローダーが以下を自動設定する（手動指定不要）:

- `selfDeclaredMadeForKids: false` — 子ども向けコンテンツではない
- `containsSyntheticMedia: true` — AI 生成コンテンツの申告

### メタデータ基準

- YouTube タイトル長制限準拠（100文字）
- 誇張表現回避（Epic, Ultimate 等の禁止）
- SEO 最適化タグ（`channel_config.json` の `tags.base` 参照）
- AI 透明性・Usage & Attribution の記載
