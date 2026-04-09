---
name: channel-setup
description: >-
  Use when /channel-direction で方向性が確定し、チャンネルのテクニカルセットアップを行いたいとき。
  「セットアップ」「設定ファイル生成」「config 作成」「チャンネル構築」など、
  新チャンネルの設定ファイル+ディレクトリ構造の完成に関わる場面で使用すること。
  /channel-direction の後に実行する
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

`channel-research.md` の分析データも参照しながら、方向性に基づいて以下を Claude が生成し提案:

テンプレートは `references/config-template.json` を参照（同スキルディレクトリ内）。

1. **tags.base**（10個程度）: 競合のタグ分析を参考にジャンルに適した YouTube 検索タグ
2. **tags.themes**（6-10テーマ）: テーマ別タグ群（各3語程度）
3. **descriptions**: opening（{style} {primary} で始まる）、sub_opening、perfect_for（4項目）、hashtags（5個）
4. **title.template**: `"{style} {theme} ... Music - {activity} BGM [{duration_display}]"` 形式
5. **title.theme_activities**: テーマ→アクティビティのマッピング
6. **suno**: genre_line（音色キーワード）、exclude_styles（除外スタイル）

提案をユーザーに見せ、承認 or 修正指示を受ける。

### Step 3: channel_config.json の完成

Phase 1 で作成した最小 config を完全版に拡張。`config-template.json` の全フィールドを埋める。

**必須セクション**: channel, content_model, genre, youtube, tags, descriptions, gemini_image, analytics, title, audio, workflow, suno

**オプションセクション**（方向性に基づき追加）:

| オプション | セクション | 条件 |
|-----------|----------|------|
| Lyria 音楽生成 | `lyria` | 音楽エンジンで lyria/both 選択時。ジャンルから提案 |
| ループ動画 | `veo` | デフォルト有効 |
| プレイリスト | `playlists` | プレイリスト名を提案（ID は空欄） |
| ショート動画 | `short` | デフォルト有効 |
| 投稿後自動化 | `post_upload` | デフォルト有効 |

`benchmark` セクションは `/channel-new` で既に設定済み。

### Step 4: 残りディレクトリの作成

```bash
mkdir -p {collections/planning,collections/live,reports,branding,tools,tests,.claude}
```

### Step 5: 残りファイル生成

| ファイル | 生成方法 |
|---------|---------|
| `config/schedule_config.json` | `references/schedule-template.json` をコピー。投稿頻度を方向性に合わせて調整 |
| `config/upload_settings.json` | `references/upload-settings-template.json` をコピー |
| `config/localizations.json` | `references/localizations-template.json` をコピーし、ジャンル情報を反映した具体的な文言に調整 |
| `get_channel_status` | `references/get-channel-status-template.py` の `{{CHANNEL_NAME}}` を置換 |
| `.claude/CLAUDE.md` | `references/claude-md-template.md` の `{{CHANNEL_NAME}}` / `{{DIR_NAME}}` を置換 |

### Step 6: 実行権限付与

```bash
chmod +x get_channel_status
```

### Step 7: 検証

#### JSON 構文検証

```bash
python3 -c "import json; json.load(open('config/channel_config.json'))"
```

#### ChannelConfig ロードテスト

```bash
python3 -c "
import sys; sys.path.insert(0, 'automation')
from utils.channel_config import ChannelConfig
c = ChannelConfig.load()
print(f'Channel: {c.channel[\"name\"]} ({c.channel[\"short\"]})')
print(f'Genre: {c.genre[\"primary\"]} / {c.genre[\"style\"]}')
print(f'Benchmarks: {len(c.benchmark_config.get(\"channels\", []))} channels')
print('Config loaded successfully!')
"
```

#### 成果物の確認

生成された全ファイルを一覧で確認。

### Step 8: 次ステップ案内

1. **YouTube チャンネル作成**（まだの場合）→ `channel_config.json` の `youtube_handle`、`url`、`channel_id` を更新
2. **OAuth 認証**: 初回実行で新チャンネル固有の認証フロー起動（`automation/auth/client_secrets.json` は submodule 経由で共有済み）
   ```bash
   python3 get_channel_status  # 新規 OAuth フロー → auth/token.json 生成
   ```
3. **ブランディング素材**: `generate_image.py` で生成し `branding/` に配置
   - **バナー画像** (`branding/banner.png`): 2048 x 1152 px、6 MB 以下、アスペクト比 16:9
   - **プロフィール写真** (`branding/icon.png`): 800 x 800 px 程度、4 MB 以下、PNG 形式、アスペクト比 1:1
   - Gemini で生成後、Pillow でリサイズ・圧縮してサイズ上限内に収めること
   ```bash
   # アイコン生成
   python3 automation/generate_image.py --prompt "..." --output branding/icon.png --aspect-ratio 1:1 -y
   # バナー生成
   python3 automation/generate_image.py --prompt "..." --output branding/banner.png --aspect-ratio 16:9 -y
   # リサイズ（上限超過時）
   python3 -c "
   from PIL import Image
   icon = Image.open('branding/icon.png').resize((800, 800), Image.LANCZOS)
   icon.save('branding/icon.png', 'PNG', optimize=True)
   banner = Image.open('branding/banner.png').resize((2048, 1152), Image.LANCZOS)
   banner.save('branding/banner.png', 'PNG', optimize=True)
   "
   ```
4. **初回コレクション制作**: `/wf-new` を実行

## Cross References

- `/channel-direction` → 前フェーズ: 方向性決定
- `references/` → テンプレートファイル（同スキルディレクトリ内）
- `/wf-new` → チャンネル完成後の最初のアクション
