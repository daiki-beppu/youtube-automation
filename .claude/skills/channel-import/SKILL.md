---
name: channel-import
description: Use when 既存の YouTube チャンネルを自動化システムに取り込みたいとき。「既存チャンネル」「チャンネル取り込み」「config 生成」「channel-import」など、既に YouTube で運営中のチャンネルの設定ファイル生成に関わる場面で使用すること。新規チャンネル開設は /channel-new を使うこと
---

## Overview

既に YouTube で運営中のチャンネルの情報をヒアリングし、`config/channel/*.json`（責務別分割、v2.0.0 以降）を生成してこの自動化システムに取り込む。

## Instructions

**実行場所**: チャンネルリポジトリのルート

### Step 0: リポジトリ準備（未作成の場合）

チャンネルリポジトリが存在しない場合は、以下の手順で準備:

1. **テンプレートからリポジトリ作成**:
   ```bash
   cd ~/02-yt
   gh repo create <short> --template daiki-beppu/youtube-channel-template --private --clone
   cd <short>
   ```
2. **automation パッケージのインストール**:
   ```bash
   uv add git+https://github.com/daiki-beppu/youtube-automation.git
   ```
3. **スキルの同期**:
   ```bash
   uv run yt-skills sync
   ```

既にリポジトリがある場合はこのステップをスキップ。

### Step 1: 基本情報のヒアリング

AskUserQuestion でユーザーに以下を質問:

1. **YouTube チャンネル URL またはハンドル**（例: `@channel-name`）
2. **チャンネル名**（表示名）
3. **短縮名**（3-4文字の略称、例: goa, rjn）

### Step 2: ジャンル・世界観のヒアリング

AskUserQuestion で以下を対話的に確認:

- **ジャンル** (`genre.primary`): 「どんなジャンルのチャンネルですか？」（例: Celtic, Lo-Fi, Jazz, Ambient）
- **スタイル** (`genre.style`): 「スタイルをもう少し具体的に」（例: Fantasy, Smooth, Chill）
- **コンテキスト** (`genre.context`): 「どんな世界観・文脈ですか？」（例: RPG Adventure, Rainy Night Cafe）
- **コアメッセージ** (`channel.core_message`): 「チャンネルが届けたい価値は？」

### Step 3: コンテンツ設定のヒアリング

AskUserQuestion で以下を確認:

1. **音楽エンジン**: Suno / Lyria / both
2. **タイトルテンプレート**: 既存動画のタイトルパターンを確認し、`{style} {theme} Music - {activity} BGM [{duration_display}]` 形式で提案
3. **タグ** (`tags.base`): ジャンルに適した YouTube 検索タグを 10 個程度提案
4. **テーマ別タグ** (`tags.themes`): 6-10 テーマのタグ群を提案
5. **説明文設定**:
   - `descriptions.opening`: `{style} {primary} music inspired by ...` 形式
   - `descriptions.perfect_for`: 4 項目（例: Study & Focus, Relaxation, Creative Work, Sleep）
   - `descriptions.hashtags`: 5 個程度
6. **Suno 設定**（音楽エンジンが Suno/both の場合）: `config/skills/suno.yaml` で `workspace_name` / `genre_line` / `exclude_styles` を上書き（ない場合は skill default を使用）

### Step 4: config 生成

`channel-setup/references/config-template/*.json` をベースに、ヒアリング結果で各ファイルの全フィールドを埋めて `config/channel/*.json` を生成（meta / content / youtube / analytics）。

含めるべきセクション（必須・skill-config 管理・オプション）は **`channel-setup/references/config-generation-rules.md`** を参照。

### Step 5: ディレクトリ構造の確認・補完

正準ディレクトリ構造は **`channel-setup/references/directory-structure.md`** を参照。
既存リポジトリに不足しているディレクトリがあれば作成する。

### Step 6: 検証

JSON 構文検証・config ロードテスト（`uv run yt-config-migrate verify`）は **`channel-setup/references/verification.md`** を参照。

### Step 7: OAuth 認証と channel_id 取得

`auth/token.json` がない場合、OAuth 認証と channel_id 自動取得を実行。
手順は **`channel-setup/references/verification.md`**（「OAuth 認証」「channel_id の自動取得」）を参照。

### Step 8: 次ステップ案内

config 生成・認証完了後、以下を案内:

1. **ブランディング素材**: 未作成の場合は `channel-setup/references/verification.md`（「ブランディング素材生成」）を参照
2. **ベンチマーク設定**: 競合チャンネルを追加したい場合は `config/channel/analytics.json` の `benchmark.channels` を追加し `/benchmark` で収集
3. **ペルソナ定義**: `/viewer-voice` → `/audience-persona` → `/viewing-scene` の順で実行
4. **データ収集・分析**: `/analytics-collect` → `/analytics-analyze` で現状のパフォーマンスを把握
5. **コレクション制作**: `/wf-new` で最初のコレクション制作を開始

## Cross References

- `/channel-new` → 新規チャンネル開設はこちら
- `/channel-setup` → 新規チャンネルのテクニカルセットアップ（/channel-direction 後）
- `channel-setup/references/config-template/*.json` → config テンプレート（責務別 4 ファイル）
- `/wf-new` → config 完成後の最初のアクション
