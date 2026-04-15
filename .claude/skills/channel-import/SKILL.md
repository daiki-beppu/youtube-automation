---
name: channel-import
description: >-
  Use when 既存の YouTube チャンネルを自動化システムに取り込みたいとき。
  「既存チャンネル」「チャンネル取り込み」「config 生成」「channel-import」など、
  既に YouTube で運営中のチャンネルの設定ファイル生成に関わる場面で使用すること。
  新規チャンネル開設は /channel-new を使うこと
---

## Overview

既に YouTube で運営中のチャンネルの情報をヒアリングし、`config/channel_config.json` を生成してこの自動化システムに取り込む。

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
   uv add git+https://github.com/daiki-beppu/youtube-channels-automation.git
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

`channel-setup/references/config-template.json` をベースに、ヒアリング結果で全フィールドを埋めて `config/channel_config.json` を生成。

**必須セクション**: channel, content_model, genre, youtube, tags, descriptions, analytics, title, workflow

**skill-config で管理されるセクション**（channel_config.json には置かない）: thumbnail / suno / lyria / ideate / benchmark / short / description / masterup。チャンネル固有の上書きがある場合は `config/skills/<skill>.yaml` を作成。

**オプションセクション**（ヒアリング結果に基づき channel_config.json に追加）:

| オプション | セクション | 条件 |
|-----------|----------|------|
| ループ動画 | `veo` | デフォルト有効 |
| プレイリスト | `playlists` | プレイリスト名を提案（ID は空欄） |
| 投稿後自動化 | `post_upload` | デフォルト有効 |

### Step 5: ディレクトリ構造の確認・補完

既存リポジトリに不足しているディレクトリがあれば作成:

```bash
mkdir -p {collections/planning,collections/live,reports,branding,docs/benchmarks,docs/plans,data,config}
```

### Step 6: 検証

#### JSON 構文検証

```bash
python3 -c "import json; json.load(open('config/channel_config.json'))"
```

#### ChannelConfig ロードテスト

```bash
uv run python3 -c "
from youtube_automation.utils.channel_config import ChannelConfig
c = ChannelConfig.load()
print(f'Channel: {c.channel_name} ({c.channel_short})')
print(f'Genre: {c.genre_primary} / {c.genre_style}')
print('Config loaded successfully!')
"
```

### Step 7: OAuth 認証と channel_id 取得

`auth/token.json` がない場合:

1. **OAuth 認証を実行**:
   ```bash
   uv run yt-status
   ```
   初回実行時にブラウザが開き Google アカウントで認証 → `auth/token.json` が生成される。

2. **channel_id の自動取得**: 認証完了後、`channel.channel_id` が未設定なら API で自動取得し config に追記:
   ```bash
   uv run python3 -c "
   from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler
   handler = YouTubeOAuthHandler()
   service = handler.get_youtube_service()
   resp = service.channels().list(part='id', mine=True).execute()
   print(resp['items'][0]['id'])
   "
   ```
   取得した ID を `config/channel_config.json` の `channel.channel_id` に設定。

### Step 8: 次ステップ案内

config 生成・認証完了後、以下を案内:

1. **ベンチマーク設定**: 競合チャンネルを追加したい場合は `benchmark.channels` セクションを追加し `/benchmark` で収集
2. **ペルソナ定義**: `/viewer-voice` → `/persona` → `/viewing-scene` の順で実行
3. **データ収集・分析**: `/collect` → `/analyze` で現状のパフォーマンスを把握
4. **コレクション制作**: `/wf-new` で最初のコレクション制作を開始

## Cross References

- `/channel-new` → 新規チャンネル開設はこちら
- `/channel-setup` → 新規チャンネルのテクニカルセットアップ（/channel-direction 後）
- `channel-setup/references/config-template.json` → config テンプレート
- `/wf-new` → config 完成後の最初のアクション
