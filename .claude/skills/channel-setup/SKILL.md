---
name: channel-setup
description: Use when /channel-direction で方向性が確定し、チャンネルのテクニカルセットアップを行いたいとき。「セットアップ」「設定ファイル生成」「config 作成」「チャンネル構築」など、新チャンネルの設定ファイル+ディレクトリ構造の完成に関わる場面で使用すること。/channel-direction の後に実行する
---

## Overview

`/channel-direction` で確定した方向性をもとに、`channel_config.json` を完成させ、全設定ファイル+ディレクトリ構造を一括生成する。

**前提**: `/channel-direction` が完了し、`docs/channel-direction.md` が存在すること。

## Instructions

**実行場所**: リポジトリルート（独立リポジトリ）

### Step 1: 方向性ドキュメントの読み込み

`docs/channel-direction.md` を読み、確定した方向性を把握:
- チャンネル名、短縮名、ジャンル、スタイル、コンテキスト
- コアメッセージ、差別化ポイント
- 動画の長さ、投稿頻度、音楽エンジン

### Step 2: 設定内容の提案と承認

`channel-research.md` の分析データも参照しながら、方向性に基づいて config 内容を Claude が生成し提案する。
生成ルールは **`references/config-generation-rules.md`** を参照（tags / descriptions / title / suno の書き方）。
雛形は `references/config-template.json`。

提案をユーザーに見せ、承認 or 修正指示を受ける。

### Step 3: channel_config.json の完成

Phase 1 で作成した最小 config を完全版に拡張。`config-template.json` の全フィールドを埋める。

含めるべきセクション（必須・skill-config 管理・オプション）は **`references/config-generation-rules.md`** を参照。
`benchmark` セクションは `/channel-new` で既に設定済み。

### Step 4: 残りディレクトリの作成

正準ディレクトリ構造は **`references/directory-structure.md`** を参照。

### Step 5: 残りファイル生成

| ファイル | 生成方法 |
|---------|---------|
| `config/schedule_config.json` | `references/schedule-template.json` をコピー。投稿頻度を方向性に合わせて調整 |
| `config/upload_settings.json` | `references/upload-settings-template.json` をコピー |
| `config/localizations.json` | `references/localizations-template.json` をコピーし、ジャンル情報を反映した具体的な文言に調整。多言語展開しないチャンネルは省略可（`ChannelConfig.supported_languages` は `youtube.language` のみへフォールバック） |
| `.claude/CLAUDE.md` | `references/claude-md-template.md` の `{{CHANNEL_NAME}}` / `{{DIR_NAME}}` を置換 |

### Step 6: 検証

JSON 構文検証・ChannelConfig ロードテスト・channel_id 自動取得コマンドは **`references/verification.md`** を参照。
検証後、生成された全ファイルを一覧で確認する。

### Step 7: 次ステップ案内

1. **YouTube チャンネル作成**（まだの場合）→ `channel_config.json` の `youtube_handle`、`url`、`channel_id` を更新
2. **OAuth 認証と channel_id 取得**: 手順は `references/verification.md`（「OAuth 認証」「channel_id の自動取得」）を参照
3. **ブランディング素材**: 生成手順は `references/verification.md`（「ブランディング素材生成」）を参照
4. **初回コレクション制作**: `/wf-new` を実行

## Cross References

- `/channel-direction` → 前フェーズ: 方向性決定
- `references/` → テンプレートファイル（同スキルディレクトリ内）
- `/wf-new` → チャンネル完成後の最初のアクション
