# youtube-channels-automation

YouTube チャンネル運営を自動化するツールキット。git+https インストール（推奨）またはサブモジュール（後方互換）でチャンネルリポジトリに導入する。

## コマンド

```bash
uv sync --extra dev                 # 開発用依存含めて解決
uv run pytest                       # テスト実行
uv run ruff check .                 # lint
uv run ruff format .                # フォーマット
uv run yt-skills sync               # チャンネルリポジトリへスキル配布
uv run yt-skills list               # 同梱スキル一覧
uv run yt-skills diff               # 同梱版との差分確認
uv run yt-config-migrate diff       # v1 → v2 config 分割のプレビュー
uv run yt-config-migrate migrate --apply   # config/channel_config.json を分割
uv run yt-config-migrate verify     # 新 loader で読み込み検証
```

CLI スクリプトは `pyproject.toml` `[project.scripts]` 配下に **`yt-*` プレフィックス**で登録する（例: `yt-analytics`, `yt-upload-collection`）。新規追加時もこの規約を踏襲。

## アーキテクチャ

```
youtube-channels-automation/         # ← このリポジトリ
├── pyproject.toml                   # hatchling / [project.scripts] entry points
├── src/
│   └── youtube_automation/
│       ├── utils/                   # コアライブラリ（設定, API, 分析, アップロード）
│       ├── agents/                  # アップロードエージェント（Auto/Collection）
│       ├── auth/                    # OAuth 2.0 認証（YouTubeOAuthHandler）
│       ├── scripts/                 # CLI スクリプト（analytics, upload, AI 生成）
│       ├── cli/                     # ユーザー向け CLI ツール (yt-skills)
│       └── templates/               # 説明文 Markdown テンプレート
├── .claude/skills/                  # Claude Code スキル群（yt-skills sync で配布）
├── tests/                           # pytest テストスイート
├── scripts/*.sh                     # シェルスクリプト（worktree_sync.sh 等）
└── auth/client_secrets.json         # (gitignored) ローカル開発用 OAuth 認証情報
```

downstream のチャンネルリポジトリ:

```
channel-repo/                  # チャンネル固有リポジトリ
├── config/
│   ├── channel/               # チャンネル設定（責務別分割、v2.0.0 以降）
│   │   ├── meta.json          #   channel / youtube_channel
│   │   ├── content.json       #   genre / tags / descriptions / title
│   │   ├── youtube.json       #   youtube / music_engine / content_model
│   │   ├── analytics.json     #   analytics / benchmark (optional)
│   │   ├── playlists.json     #   playlists (optional)
│   │   ├── workflow.json      #   (v4.0.0 で short / community 撤去、後方互換で素通し)
│   │   └── audio.json         #   audio (optional)
│   └── localizations.json     # 多言語テンプレート（config/ 直下）
├── auth/                      # チャンネル固有 OAuth 認証
│   ├── client_secrets.json
│   └── token.json
├── .claude/skills/            # yt-skills sync で展開
└── collections/               # コンテンツ成果物（音源, 動画, サムネイル）
```

## 主要モジュール

| モジュール | 責務 |
|-----------|------|
| `youtube_automation.utils.config` | `config/channel/*.json` の glob ロード・バリデーション。`load_config()` / `channel_dir()` / `reset()` / `ChannelConfig` を export |
| `youtube_automation.utils.config.meta` / `content` / `youtube` / `analytics` / `playlists` / `workflow` / `audio` / `localizations` | 責務別 dataclass（`ChannelMeta`, `Content`, `YoutubeSection` 等） |
| `youtube_automation.cli.config_migrate` | `yt-config-migrate` 本体（旧 `channel_config.json` → `config/channel/*.json` 変換） |
| `youtube_automation.utils.youtube_service` | YouTube API サービスファクトリ（ServiceRegistry） |
| `youtube_automation.utils.upload_core` | 再開可能アップロード・サムネイル圧縮の共通コア |
| `youtube_automation.utils.exceptions` | ドメイン固有例外（ConfigError, YouTubeAPIError 等） |
| `youtube_automation.utils.collection_paths` | コレクションディレクトリ構造の解決 |
| `youtube_automation.utils.metadata_generator` | タイトル・説明文・タグ・ローカライゼーション自動生成 |
| `youtube_automation.utils.analytics_collector` | Analytics API データ収集（Mixin 構成、`VideoDailyAnalyticsMixin` で動画×日次取得） |
| `youtube_automation.utils.analytics_analyzer` | CTR・エンゲージメント分析（レガシー、statistics ベース） |
| `youtube_automation.utils.launch_curve_data` / `launch_curve_analyzer` / `launch_curve_plotter` | 動画別 launch curve + 過去ベンチマーク（pandas/matplotlib） |
| `youtube_automation.utils.channel_trend` | チャンネル日次トレンド + 異常検知（pandas rolling） |
| `youtube_automation.utils.theme_performance` | テーマ別平均曲線比較 |
| `youtube_automation.utils.thumbnail_features` / `thumbnail_correlation` | サムネ特徴量抽出 + CTR/views 相関（Pillow） |
| `youtube_automation.auth.oauth_handler` | OAuth 2.0 トークン管理・リフレッシュ |
| `youtube_automation.utils.secrets` | シークレット解決（env → 1Password CLI → ConfigError） |
| `youtube_automation.cli.skills_sync` | `yt-skills` コマンド本体 |

## 開発規約

### Python
- Python 3.11+
- リンター: ruff（E, F, I, W）
- 行長: 120 文字
- テスト: pytest
- パッケージマネージャ: uv

### エラーハンドリング
- `utils/exceptions.py` のドメイン例外を使用すること
- 生の `Exception` / `KeyError` を catch しない — `ConfigError`, `YouTubeAPIError` 等を使う
- API 呼び出しには適切なリトライ・タイムアウトを設定

### 設定
- チャンネル固有値は必ず `load_config()` 経由で参照（`from youtube_automation.utils.config import load_config`）
- 責務別ネームスペースでアクセス: `config.meta.channel_name` / `config.content.tags.base` / `config.youtube.api.category_id` など
- ハードコーディング禁止 — `config/channel/*.json` に集約
- 新しい設定キーを追加する場合:
  1. 該当責務の dataclass（`utils/config/<section>.py`）にフィールド追加
  2. `utils/config/loader.py::_build_*` で JSON からの組み立てを追加
  3. 必須キーであれば `_REQUIRED_KEYS_BY_SECTION` にも登録
- サンプル設定は `examples/channel_config.example/`（7 ファイル）と `examples/localizations.example.json`
- Path のみ必要な場合（loader を起動したくない）は `channel_dir()` を使う

### Import 規約
- パッケージ内コードは必ず `from youtube_automation.xxx import ...` の fully-qualified import を使用
- ルート直下の `scripts/` にはシェルスクリプト（`.sh`）のみ配置。Python shim は廃止済み

### テスト
- `tests/conftest.py` が `src/` を sys.path に追加し `CHANNEL_DIR` をフィクスチャに向ける
- `youtube_automation.utils.config.reset()` / `ServiceRegistry.reset()` でシングルトンをリセット
- `tests/fixtures/sample_channel/config/channel/*.json` にテストデータを配置（新構造）
- ユニット: `tests/test_*.py` / 統合: `tests/integration/`（API・外部依存あり）

### パッケージング
- ビルドバックエンド: hatchling (`[build-system]` 参照)
- パッケージレイアウト: `src/youtube_automation/` (PyPA src layout)
- `.claude/skills/` は `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_skills/` に同梱され、`yt-skills sync` で配布される
- 新しい CLI スクリプトを追加するときは `pyproject.toml` の `[project.scripts]` にも entry point を登録すること
- バージョン bump は `pyproject.toml` `version` と `src/youtube_automation/__init__.py` の `__version__` の両方

## セキュリティ

- `auth/client_secrets.json` / `auth/token.json` / `.env` は **絶対にコミットしない**
- API キーは環境変数経由（`.env` または 1Password CLI）
- OAuth スコープは必要最小限に制限
- シークレット解決順序: `os.environ` → `op read`（1Password CLI）→ `ConfigError`。参照は `utils/secrets.py` の `_SECRET_REFS` で定義

## 開発ワークフロー

このリポジトリの開発は **takt + GitHub issue** に乗せる。手作業でブランチを切らず、
`takt-issue` スキル経由で issue → worktree → PR を統一手順化する。手順詳細は
`~/01-dev/dotfiles/config/.claude/skills/takt-issue/SKILL.md`。

- **issue 起票**: `gh issue create` または `/issue` スキル
- **takt 起動**: `takt add '#<N>'` → `takt run`（base branch は **main** 固定、PR は通常 PR）
- **commit 規約**: 日本語 Conventional Commits + タイトル末尾に `(#<N>)`。詳細は `commit-convention` スキル参照
- **takt 設定**: リポジトリ固有 `.takt/config.yaml`（`draft_pr: false`）、
  グローバル `~/.takt/config.yaml`（`provider: claude`, `language: ja`）。
  workflow は組み込み **default**（plan → review → ... → reviewers の 9 step）
