# youtube-channels-automation

YouTube チャンネル運営を自動化するツールキット。Analytics データ収集、AI コンテンツ生成、動画アップロード、メタデータ管理をまとめて提供します。

> [!WARNING]
> **移行告知（2026-07-02）**: 本 Python 版は **2026-08 中に提供終了**し、TypeScript 製の後継 **`tayk`**（npm パッケージ）へ切り替わります。cutover 当日に main ブランチが TS 実装になり、branch 参照の `uv add git+https://` は取得不可になります（git tag は残ります）。詳細と移行手順は [`docs/migration/python-to-tayk.md`](docs/migration/python-to-tayk.md) を参照してください。

> **新規利用者の方へ**: セットアップ手順は [`ONBOARDING.md`](ONBOARDING.md) を参照してください。

## Features

- **Analytics 収集・分析** - YouTube Analytics API からデータを自動収集し、CTR・エンゲージメント分析レポートを生成
- **AI 音楽生成** - Google Lyria RealTime API / Suno プロンプト生成で楽曲を自動作成
- **AI 動画生成** - Google Veo で動画を生成、FFmpeg で静止画＋音声から MP4 を合成
- **AI 画像生成** - Gemini API でサムネイル・カバー画像を自動生成
- **YouTube 自動アップロード** - 動画・サムネイル・メタデータを一括アップロード
- **メタデータ生成** - チャンネル設定に基づくタイトル・説明文・タグ・多言語ローカライゼーションの自動生成
- **ベンチマーク分析** - 競合チャンネルのパフォーマンス比較
- **プレイリスト管理** - プレイリストの自動作成・動画追加

> **個別 skill のカタログ**: `yt-skills sync` で配布される全 47 skill の「なにができるか」一覧は [`docs/features.md`](docs/features.md) を参照。
>
> **workflow 系 skill の使い分け**: `/wf-new` `/wf-next` `/wf-status` `/collection-ideate` と `workflow-state.json` の扱いは [`docs/workflow-cheatsheet.md`](docs/workflow-cheatsheet.md) を参照。
>
> **自前動画素材を結合する場合**: fps が違う素材を FFmpeg concat する際の注意点は [`docs/media-concat-fps.md`](docs/media-concat-fps.md) を参照。

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
└── auth/                         # submodule 利用者向け後方互換 shim
```

各チャンネルリポジトリ側では、以下のいずれかの方法で導入します:

```
channel-repo/                  # チャンネル固有リポジトリ
├── config/
│   ├── channel/               # チャンネル設定（責務別分割、v2.0.0 以降）
│   │   ├── meta.json          #   channel / youtube_channel
│   │   ├── content.json       #   genre / tags / descriptions / title
│   │   ├── youtube.json       #   youtube / music_engine / content_model
│   │   ├── analytics.json     #   analytics / benchmark (optional)
│   │   ├── playlists.json     #   playlists (optional)
│   │   ├── workflow.json      #   (optional, 拡張用 reserved)
│   │   ├── audio.json         #   audio (optional)
│   │   ├── shorts.json        #   shorts (optional)
│   │   ├── comments.json      #   comments (optional)
│   │   ├── pinned-comment.json # pinned_comment (optional)
│   │   └── distrokid.json     #   distrokid (optional)
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

> **submodule 形式 (legacy)**: `auth/` shim のみ後方互換を維持します。GCP セットアップスクリプト（`.claude/skills/channel-new/references/`）は、submodule 利用者は `automation/.claude/skills/channel-new/references/gcp-bootstrap.sh` のように submodule パス経由で参照するか、`yt-skills sync` を先に実行してください（pip install 環境のみ）。新規チャンネルは pip install を推奨。移行手順: [`docs/migration-submodule-to-uv.md`](docs/migration-submodule-to-uv.md)

### 2. Claude Code 配布物を同期

チャンネルリポジトリのルートで:

```bash
yt-skills list                            # 全 asset の同梱一覧（skills / CLAUDE.md / docs / auth-template）
yt-skills sync                            # 全 asset を一括展開 (--asset all がデフォルト)
yt-skills sync --asset skills             # 個別: Claude Code スキルだけ
yt-skills sync --asset claude-md          # 個別: 運営方針テンプレ (.claude/CLAUDE.md)
yt-skills sync --asset workflow-cheatsheet  # 個別: workflow チートシート (docs/workflow-cheatsheet.md)
yt-skills sync --asset features           # 個別: 全 skill カタログ (docs/features.md)
yt-skills sync --asset auth-template      # 個別: OAuth client_secrets テンプレ (auth/client_secrets.template.json)
yt-skills sync --symlink                  # 開発時はシンボリックリンク
yt-skills diff                            # 全 asset で同梱版との差分表示
yt-skills sync --force                    # 既存ファイルを上書き
yt-skills sync --asset skills --prune     # skills で同梱に無い entry を列挙 (実削除しない)
yt-skills sync --asset skills --prune --yes  # 列挙したうえで実際に削除する
```

> `yt-skills sync` のデフォルト挙動は `--asset all` で、`.claude/skills/`・`.claude/CLAUDE.md`・`docs/{workflow-cheatsheet,features}.md`・`auth/client_secrets.template.json` の全てを 1 コマンドで配布します。配布される SKILL.md / CLAUDE.md は `docs/` 配下に相対 link を張るため、`--asset skills` だけを単独で sync すると link 切れになります。
>
> `--target` で配布先を独自パスに変えたい場合は `--asset <name>` を必ず明示してください（`--asset all` + `--target` は asset ごとに default_target が異なり曖昧なため error 終了します）。

### 3. チャンネル設定を作成

`config/channel/*.json`（責務別分割の必須ファイル + optional ファイル）と `config/localizations.json` を作成します。
サンプルは [`examples/channel_config.example/`](examples/channel_config.example/) と [`examples/localizations.example.json`](examples/localizations.example.json) を参照してください。

v1.x から v2.0.0 へ移行するチャンネルは [`docs/migration/v2-config-split.md`](docs/migration/v2-config-split.md) の手順に従い、`uv run yt-config-migrate migrate --apply` で旧 `config/channel_config.json` を自動分割できます。

### 4. OAuth 認証をセットアップ

[auth/SETUP.md](auth/SETUP.md) の手順に従って Google Auth Platform の Branding / Audience / Clients を設定し、チャンネルディレクトリの `auth/client_secrets.json` に配置してください。

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
$EDITOR .env  # Vertex AI 用変数 (`GOOGLE_CLOUD_LOCATION` 等) を書く。project_id は ADC quota project から自動解決される
```

`.claude/skills/channel-new/references/gcp-bootstrap.sh` または `infra/terraform/gcp/` を実行すれば `.env` に自動書き出しされます。`load_dotenv()` で `os.environ` に読み込まれ、上記 (1) の経路で利用されます。

#### B. 1Password CLI 方式（秘密をディスクに書かない）

`op` CLI にサインインしておけば、Python スクリプト実行時に必要な瞬間だけ `op read` で取得します。シェルの環境変数や `.env` ファイルには一切残りません。

```bash
op signin
# 以降、スクリプト実行時に utils/secrets.py が op read を呼ぶ
```

シークレット参照は `utils/secrets.py` の `_SECRET_REFS` で定義されています（デフォルト: `op://Personal/YouTube_OAuth_Client_Secrets/credential`）。AI 系は ADC 経由の認証のため `op` 取得は不要です。

### 6. (オプション) Nix devShell

ランタイム（Python / uv / FFmpeg / op）の再現性が必要な場合:

```bash
nix develop
```

`flake.nix` の `devShells.default` が Python 3.11 / uv / FFmpeg / 1Password CLI を提供します。Nix を使わない OSS 利用者は、システムの Python と FFmpeg を自前で用意してください。

## Configuration

### config/channel/*.json

チャンネルのメタデータ、ジャンル、タグ、タイトルテンプレートなどを責務別ファイルに分割して定義します（v2.0.0 以降）。

| ファイル | 責務 |
|---|---|
| `meta.json` | `channel` / `youtube_channel` |
| `content.json` | `genre` / `tags` / `descriptions` / `title` |
| `youtube.json` | `youtube` / `music_engine` / `content_model` |
| `analytics.json` | `analytics` / `benchmark` (optional) |
| `playlists.json` | `playlists` (optional) |
| `workflow.json` | (optional, 拡張用 reserved) |
| `audio.json` | `audio` (optional) |
| `shorts.json` | `shorts` (optional) |
| `comments.json` | `comments` (optional) |
| `pinned-comment.json` | `pinned_comment` (optional) |
| `distrokid.json` | `distrokid` (optional) |

詳細なフィールド説明は [`examples/channel_config.example/`](examples/channel_config.example/) を参照してください。多言語テンプレートは `config/localizations.json` に集約します（単一ソース）。`community.example.json` は `/community-post` が直接読む skill-local raw JSON の雛形で、共通 config loader の必須/optional section ではありません。

### 環境変数

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `GOOGLE_CLOUD_PROJECT` | 任意 | Vertex AI を呼ぶ GCP プロジェクト ID。未設定なら ADC quota project から自動解決 |
| `GOOGLE_CLOUD_LOCATION` | 任意 | Vertex AI リージョン（既定: `us-central1`） |
| `GOOGLE_GENAI_USE_VERTEXAI` | 任意 | google-genai SDK の自動検出用フラグ（アプリ側は参照しない） |
| `CHANNEL_DIR` | 自動検出可 | チャンネルリポジトリのルートパス |
| `CLIENT_SECRETS_DIR` | 任意 | `client_secrets.json` を置いたディレクトリ。設定時はそのディレクトリのみ検査。未設定時は `<channel_dir>/auth/`、`<channel_dir>/automation/auth/`、1Password / `CLIENT_SECRETS_JSON` fallback の順で探索 |

## Development

### Editable install

```bash
git clone git@github.com:daiki-beppu/youtube-automation.git
cd youtube-automation
uv sync --extra dev
```

### テスト実行

```bash
uv run pytest
```

`uv sync --extra dev` 単独で `uv run pytest tests/` が collection error 0 件で走るために必要な依存がすべて揃います。

- テスト用ツール (`pytest` / `ruff`) は `[project.optional-dependencies].dev` 経由で導入されます。
- テストが間接的に require する `Pillow` / `pandas` / `pyyaml` / `matplotlib` / `japanize-matplotlib` / `seaborn` / `google-api-python-client` / `google-auth-oauthlib` などは `[project] dependencies`（main deps）に同梱されています。
- 現時点で optional dependency 扱いの test dep は存在しません（Issue #216 で `pyyaml`、コミット `801ffa8` / v5.5.0 で `Pillow` を main deps へ統合済み。本 Issue #329 はその状態を README に明文化したもの）。

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
| `yt-generate-image` | Gemini / OpenAI で画像生成（サムネイル兼用） |
| `yt-generate-lyria-master` | Lyria 3 で N セグメント生成 + クロスフェード結合してマスター音源を作成 |
| `yt-generate-master` | 個別音声 (MP3 / WAV) をクロスフェード結合してマスター音源を作成 |
| `yt-generate-suno` | Suno プロンプト生成 |
| `yt-generate-loop-video` | Veo ループ動画生成 |
| `yt-init-collection` | 新規コレクションの雛形作成 |
| `yt-metadata-audit` | メタデータの整合性監査 |
| `yt-playlist-manager` / `yt-playlist-status` | プレイリスト管理 |
| `yt-benchmark-collect` / `yt-benchmark-comments` | 競合チャンネル分析 |
| `yt-thumbnail-compare` | サムネイル比較検証 |
| `yt-video-analyze` | Gemini で YouTube 動画を直接解析（フック構造・BGM 展開・シーン・サムネ整合性・編集指標） |
| `yt-channel-status` | チャンネル最新状況 |
| `yt-upload-collection` / `yt-upload-auto` | YouTube アップロード |

完全な一覧は `pyproject.toml` の `[project.scripts]` を参照してください。

> **`yt-video-analyze` の動画公開範囲制約**: Gemini API は YouTube URL を直接受け取って動画本体を解析しますが、対象動画は **Public または Unlisted** である必要があります。Private 動画は API 側で取得できず解析できません。

## License

This project is **source-available**. You may view and study the code for educational and personal purposes, but redistribution, commercial use, and modification are prohibited without prior written permission. See [LICENSE](LICENSE) for full terms.
