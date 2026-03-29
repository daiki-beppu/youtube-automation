# youtube-channels-automation

YouTube チャンネル運営を自動化するツールキット。Analytics データ収集、AI コンテンツ生成、動画アップロード、メタデータ管理をまとめて提供します。

## Features

- **Analytics 収集・分析** - YouTube Analytics API からデータを自動収集し、CTR・エンゲージメント分析レポートを生成
- **AI 音楽生成** - Google Lyria RealTime API / Suno プロンプト生成で楽曲を自動作成
- **AI 動画生成** - Google Veo で動画を生成、FFmpeg で静止画＋音声から MP4 を合成
- **AI 画像生成** - Gemini API でサムネイル・カバー画像を自動生成
- **YouTube 自動アップロード** - 動画・サムネイル・メタデータを一括アップロード
- **メタデータ生成** - チャンネル設定に基づくタイトル・説明文・タグ・多言語ローカライゼーションの自動生成
- **ベンチマーク分析** - 競合チャンネルのパフォーマンス比較
- **プレイリスト管理** - プレイリストの自動作成・動画追加

## Architecture

```
channel-repo/              # チャンネル固有リポジトリ
├── config/
│   ├── channel_config.json    # チャンネル設定
│   └── localizations.json     # 多言語テンプレート
├── automation/            # ← このリポジトリ（サブモジュール）
│   ├── agents/            # 自動化エージェント
│   ├── auth/              # OAuth 2.0 認証
│   ├── utils/             # コアユーティリティ
│   ├── templates/         # 説明文テンプレート
│   └── tests/             # テストスイート
└── collections/           # コンテンツ成果物
```

各チャンネルリポジトリの `automation/` ディレクトリにサブモジュールとして組み込んで使います。チャンネル固有の設定は親リポジトリの `config/` に配置します。

## Prerequisites

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) (動画生成に必要)
- Google Cloud Project (YouTube Data API v3 有効化済み)
- [1Password CLI](https://developer.1password.com/docs/cli/) (オプション: シークレット管理)

## Quick Start

### 1. チャンネルリポジトリにサブモジュールとして追加

```bash
git submodule add git@github.com:daiki-beppu/youtube-channels-automation.git automation
```

### 2. 依存パッケージをインストール

```bash
cd automation
pip install -e .
```

### 3. チャンネル設定を作成

`config/channel_config.json` と `config/localizations.json` を作成します。
サンプルは [`examples/`](examples/) を参照してください。

### 4. OAuth 認証をセットアップ

[auth/SETUP.md](auth/SETUP.md) の手順に従って Google Cloud Console で OAuth 2.0 認証情報を作成し、`auth/client_secrets.json` に配置してください。

```bash
python auth/oauth_handler.py
```

### 5. 環境変数を設定

```bash
cp .env.example .env
# .env を編集して API キーを設定
```

1Password CLI を使用する場合:

```bash
bash setup_env.sh
```

## Configuration

### channel_config.json

チャンネルのメタデータ、ジャンル、タグ、タイトルテンプレートなどを定義します。
詳細なフィールド説明は [`examples/channel_config.example.json`](examples/channel_config.example.json) を参照してください。

### 環境変数

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `GEMINI_API_KEY` | AI生成機能使用時 | Google Gemini API キー |
| `CHANNEL_DIR` | 自動検出可 | チャンネルリポジトリのルートパス |
| `CLIENT_SECRETS_DIR` | 任意 | OAuth 認証情報のディレクトリ（デフォルト: `./auth/`） |

## Development

### テスト実行

```bash
pip install -e ".[dev]"
pytest
```

### Lint

```bash
ruff check .
```

## License

[MIT](LICENSE)
