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
youtube-channels-automation/      # ← このリポジトリ
├── src/
│   └── youtube_automation/       # インストール対象パッケージ
│       ├── utils/                # コアユーティリティ
│       ├── agents/               # 自動化エージェント
│       ├── auth/                 # OAuth 2.0 認証
│       ├── scripts/              # CLI スクリプト (yt-* entry points)
│       ├── cli/                  # ユーザー向け CLI (yt-skills)
│       └── templates/            # 説明文テンプレート
├── .claude/skills/               # Claude Code スキル群 (yt-skills sync で配布)
├── tests/                        # テストスイート
└── auth/, scripts/, agents/      # submodule 利用者向け後方互換 shim
```

各チャンネルリポジトリ側では、以下のいずれかの方法で導入します:

```
channel-repo/                  # チャンネル固有リポジトリ
├── config/
│   ├── channel_config.json    # チャンネル設定
│   └── localizations.json     # 多言語テンプレート
├── auth/                      # OAuth 2.0 認証情報 (channel 固有)
│   ├── client_secrets.json
│   └── token.json
├── .claude/skills/            # yt-skills sync で展開される
└── collections/               # コンテンツ成果物
```

チャンネル固有の設定は親リポジトリの `config/` と `auth/` に配置します。

## Prerequisites

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) (動画生成に必要)
- Google Cloud Project (YouTube Data API v3 有効化済み)
- (オプション) [Nix](https://nixos.org/): `flake.nix` で開発環境を再現可能に
- (オプション) [1Password CLI](https://developer.1password.com/docs/cli/): シークレットをディスクに書かずに管理

## Quick Start

### 1. パッケージをインストール (推奨)

`uv` または `pip` で git+https からインストールします:

```bash
# uv
uv add git+https://github.com/daiki-beppu/youtube-automation
# 特定タグで固定する場合
uv add "git+https://github.com/daiki-beppu/youtube-automation@v1.1.0"

# pip
pip install "git+https://github.com/daiki-beppu/youtube-automation@v1.1.0"
```

インストールすると `yt-*` という CLI コマンド群と `yt-skills` 同期ツールが PATH に入ります。

> **submodule 形式 (legacy)**: 既存のチャンネルリポジトリは `git submodule add git@github.com:daiki-beppu/youtube-automation.git automation` でも引き続き動作します（`utils/`, `agents/`, `auth/`, `scripts/` の互換 shim を維持）。新規チャンネルは pip install を推奨。

### 2. Claude Code スキルを同期

チャンネルリポジトリのルートで:

```bash
yt-skills list                       # 同梱スキル一覧 (28 件)
yt-skills sync                       # ./.claude/skills/ にコピー
yt-skills sync --symlink             # 開発時はシンボリックリンク
yt-skills diff                       # 同梱版との差分表示
yt-skills sync --force               # 既存ファイルを上書き
```

### 3. チャンネル設定を作成

`config/channel_config.json` と `config/localizations.json` を作成します。
サンプルは [`examples/`](examples/) を参照してください。

### 4. OAuth 認証をセットアップ

[auth/SETUP.md](auth/SETUP.md) の手順に従って Google Cloud Console で OAuth 2.0 認証情報を作成し、チャンネルディレクトリの `auth/client_secrets.json` に配置してください。

```bash
# どのスクリプトでも初回実行時に OAuth フローが立ち上がります
yt-channel-status
```

### 5. 環境変数を設定

シークレットは次の優先順位で取得されます:

1. `os.environ` に既にセットされていればそれを使う
2. 1Password CLI (`op`) が利用可能なら `op read` で取得
3. 失敗した場合は `ConfigError`

#### A. 標準方式: `.env` を直接編集（OSS 利用者向け）

```bash
cp .env.example .env
$EDITOR .env  # GEMINI_API_KEY を書く
```

`load_dotenv()` で `os.environ` に読み込まれ、上記 (1) の経路で利用されます。

#### B. 1Password CLI 方式（秘密をディスクに書かない）

`op` CLI にサインインしておけば、Python スクリプト実行時に必要な瞬間だけ `op read` で取得します。シェルの環境変数や `.env` ファイルには一切残りません。

```bash
op signin
# 以降、スクリプト実行時に utils/secrets.py が op read を呼ぶ
```

シークレット参照は `utils/secrets.py` の `_SECRET_REFS` で定義されています（デフォルト: `op://Personal/GEMINI_API_KEY/credential`）。

### 6. (オプション) Nix devShell

ランタイム（Python / uv / FFmpeg / op）の再現性が必要な場合:

```bash
nix develop
```

`flake.nix` の `devShells.default` が Python 3.11 / uv / FFmpeg / 1Password CLI を提供します。Nix を使わない OSS 利用者は、システムの Python と FFmpeg を自前で用意してください。

## Configuration

### channel_config.json

チャンネルのメタデータ、ジャンル、タグ、タイトルテンプレートなどを定義します。
詳細なフィールド説明は [`examples/channel_config.example.json`](examples/channel_config.example.json) を参照してください。

### 環境変数

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `GEMINI_API_KEY` | AI生成機能使用時 | Google Gemini API キー |
| `CHANNEL_DIR` | 自動検出可 | チャンネルリポジトリのルートパス |
| `CLIENT_SECRETS_DIR` | 任意 | `client_secrets.json` を置いたディレクトリ（デフォルト: `<channel_dir>/auth/`、フォールバック: `<channel_dir>/automation/auth/`） |

## Development

### Editable install

```bash
git clone git@github.com:daiki-beppu/youtube-automation.git
cd youtube-automation
uv sync --extra dev --extra veo
```

### テスト実行

```bash
uv run pytest
```

### Lint

```bash
uv run ruff check .
```

### CLI commands

インストール後に利用できる主な entry points:

| Command | Description |
|---------|-------------|
| `yt-skills` | Claude Code スキルの sync / list / diff |
| `yt-analytics` | Analytics データ収集 |
| `yt-generate-image` | Gemini API で画像生成 |
| `yt-generate-thumbnail` | コレクションサムネイル生成 |
| `yt-generate-music` / `yt-generate-music-dj` | Lyria 音楽生成 |
| `yt-generate-suno` | Suno プロンプト生成 |
| `yt-generate-loop-video` / `yt-generate-short-loop` | Veo ループ動画生成 |
| `yt-init-collection` | 新規コレクションの雛形作成 |
| `yt-metadata-audit` | メタデータの整合性監査 |
| `yt-playlist-manager` / `yt-playlist-status` | プレイリスト管理 |
| `yt-benchmark-collect` / `yt-benchmark-comments` | 競合チャンネル分析 |
| `yt-thumbnail-compare` | サムネイル比較検証 |
| `yt-channel-status` | チャンネル最新状況 |
| `yt-upload-collection` / `yt-upload-short` / `yt-upload-auto` | YouTube アップロード |
| `yt-video-uploader` / `yt-post-upload` | 動画アップロード補助 |

完全な一覧は `pyproject.toml` の `[project.scripts]` を参照してください。

## License

[MIT](LICENSE)
