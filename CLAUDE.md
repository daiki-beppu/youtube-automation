# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

YouTube チャンネル運営を自動化するツールキット。`youtube-channels-automation` パッケージとして配布し、各チャンネルリポジトリへ git+https または submodule 経由で導入される。Analytics 収集、AI コンテンツ生成（Lyria / Veo / Gemini / Suno）、動画アップロード、メタデータ生成、ベンチマーク分析を統合提供する。

## プロジェクト固有コマンド

```bash
uv run yt-skills sync                       # チャンネルリポジトリへ .claude/skills を配布
uv run yt-skills list                       # 同梱スキル一覧
uv run yt-skills diff                       # 同梱版との差分確認
uv run yt-config-migrate diff               # 旧 channel_config.json → 責務別分割のプレビュー
uv run yt-config-migrate migrate --apply    # 実際に分割実行
uv run yt-config-migrate verify             # 新 loader で読み込み検証
```

`yt-*` 系 CLI 全 30 件超は `pyproject.toml` の `[project.scripts]` に登録されている。新規 CLI を追加するときは **必ず `yt-*` プレフィックス**を踏襲し、entry point を登録すること。

## アーキテクチャ

このリポジトリは **このリポジトリ自体** と **下流のチャンネルリポジトリ** の 2 層構造で動く。

### 自リポジトリ

- `src/youtube_automation/utils/` — コアライブラリ（設定ローダー、API クライアント、analytics、upload）
- `src/youtube_automation/agents/` — アップロードエージェント（Auto / Collection）
- `src/youtube_automation/scripts/` — `yt-*` CLI 本体
- `src/youtube_automation/cli/` — ユーザー向け CLI（`yt-skills`, `yt-config-migrate`, `yt-cost-report`）
- `src/youtube_automation/templates/` — 説明文テンプレート
- `.claude/skills/` — Claude Code スキル群。wheel に `_skills/` として `force-include` され、`yt-skills sync` で各チャンネルへ展開される
- `utils/`, `agents/`, `auth/`, `scripts/` — submodule 利用者向け **後方互換 shim**（新規開発は `src/youtube_automation/` 側で行う）

### 下流チャンネルリポジトリ（`CHANNEL_DIR` が指す先）

```
config/channel/         # 責務別分割設定（v2.0.0 以降）
  meta.json             # channel / youtube_channel
  content.json          # genre / tags / descriptions / title
  youtube.json          # youtube / music_engine / content_model
  analytics.json        # analytics / benchmark
  playlists.json        # playlists
  workflow.json         # post_upload.short_publish_time (Shorts 公開時刻、デフォルト "08:00")
  audio.json            # audio
config/localizations.json
auth/{client_secrets,token}.json
.claude/skills/         # yt-skills sync で展開
collections/            # コンテンツ成果物
```

## 主要モジュール

| モジュール | 責務 |
|---|---|
| `utils.config` | `config/channel/*.json` の glob ロード／バリデーション。`load_config()` / `channel_dir()` / `reset()` / `ChannelConfig` を export |
| `utils.config.{meta,content,youtube,analytics,playlists,workflow,audio,localizations}` | 責務別 dataclass |
| `cli.config_migrate` | `yt-config-migrate` 本体（v1 → v2 変換） |
| `utils.youtube_service` | YouTube API サービスファクトリ（ServiceRegistry） |
| `utils.upload_core` | 再開可能アップロード・サムネイル圧縮の共通コア |
| `utils.exceptions` | ドメイン例外（`AutomationError` 基底、`ConfigError` / `YouTubeAPIError` / `ValidationError` / `UploadError`） |
| `utils.collection_paths` | コレクションディレクトリ構造の解決 |
| `utils.metadata_generator` | タイトル・説明文・タグ・ローカライゼーション生成 |
| `utils.analytics_collector` | Analytics API 収集（Mixin 構成、`VideoDailyAnalyticsMixin` で動画×日次取得） |
| `utils.launch_curve_*` / `channel_trend` / `theme_performance` | 視聴推移分析（pandas / matplotlib） |
| `utils.thumbnail_features` / `thumbnail_correlation` | サムネ特徴量＋ CTR/views 相関（Pillow） |
| `utils.image_provider` | 画像生成プロバイダー抽象化（Gemini / OpenAI 切り替え） |
| `auth.oauth_handler` | OAuth 2.0 トークン管理 |
| `utils.secrets` | シークレット解決（`_SECRET_REFS` で参照定義） |
| `cli.skills_sync` | `yt-skills` 本体 |

## 開発規約

### 設定アクセス

- チャンネル固有値は **必ず** `from youtube_automation.utils.config import load_config` 経由で取得
- 責務別ネームスペースでアクセス: `config.meta.channel_name` / `config.content.tags.base` / `config.youtube.api.category_id`
- ハードコーディング禁止 — `config/channel/*.json` に集約
- 新しい設定キーを追加する場合:
  1. 該当責務の dataclass（`utils/config/<section>.py`）にフィールド追加
  2. `utils/config/loader.py::_build_*` で JSON からの組み立てを追加
  3. 必須キーであれば `_REQUIRED_KEYS_BY_SECTION` にも登録
- Path のみ必要な場合（loader を起動したくない）は `channel_dir()` を使う
- サンプルは `examples/channel_config.example/`（7 ファイル）と `examples/localizations.example.json`

### エラーハンドリング

- `utils/exceptions.py` のドメイン例外を使用すること
- 生の `Exception` / `KeyError` を catch しない — `ConfigError`, `YouTubeAPIError` 等を使う
- `YouTubeAPIError.from_http_error(error, context)` で googleapiclient の HttpError を変換できる

### Import 規約

- パッケージ内コードは必ず `from youtube_automation.xxx import ...` の fully-qualified import を使う
- ルート直下の `scripts/` にはシェルスクリプト（`.sh`）のみ配置。Python shim は廃止済み

### スクリプト配置

- **skill 固有のスクリプト**は `.claude/skills/<skill>/references/` に配置する（例: `.claude/skills/videoup/references/generate_videos.sh`、`.claude/skills/lyria/references/generate_music.py`）
- ルート `scripts/` には複数の文脈から共有される **共通スクリプトのみ** を置く（例: `gcp-bootstrap.sh`, `gcp-terraform-apply.sh`）
- 単一 skill からしか呼ばれないものを `scripts/` に残すと、skill の自己完結性が崩れて配布時に取り残されるので避ける

### テスト

- `tests/conftest.py` が `src/` を sys.path に追加し `CHANNEL_DIR` を `tests/fixtures/sample_channel/` に向ける
- `_reset_config_singleton` autouse fixture が各テスト前後で `utils.config.reset()` を呼ぶ。**追加で** `ServiceRegistry.reset()` が必要なテストは個別に呼ぶこと
- ユニット: `tests/test_*.py` / 統合: `tests/integration/`（API・外部依存あり）
- フィクスチャ JSON は新構造（`config/channel/*.json`）で配置

### パッケージング

- `.claude/skills/` は `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_skills/` に同梱され、`yt-skills sync` が `importlib.resources` で参照する
- バージョン bump は `pyproject.toml` の `version` と `src/youtube_automation/__init__.py` の `__version__` の **両方**

## セキュリティ

- `auth/client_secrets.json` / `auth/token.json` / `.env` は **絶対にコミットしない**
- シークレット解決順序: `os.environ` → `op read`（1Password CLI）→ `ConfigError`
- 参照定義は `utils/secrets.py` の `_SECRET_REFS`（デフォルト: `op://Personal/YouTube_OAuth_Client_Secrets/credential`）
- AI 系（Vertex AI）は ADC 認証のため `op` 取得は不要

## 開発ワークフロー

このリポジトリの開発は **takt + GitHub issue** に乗せる。手作業でブランチを切らず、`takt-issue` スキル経由で issue → worktree → PR を統一手順化する。

- **issue 起票**: `gh issue create` または `/issue` スキル
- **takt 起動**: `takt add '#<N>'` → `takt run`（base branch は **main** 固定、PR は通常 PR）
- **commit 規約**: 日本語 Conventional Commits + タイトル末尾に `(#<N>)`。`commit-convention` スキル参照
- **takt 設定**: リポジトリ固有 `.takt/config.yaml`（`draft_pr: false`）、グローバル `~/.takt/config.yaml`（`provider: claude`, `language: ja`）
- workflow は組み込み **default**（plan → review → ... → reviewers の 9 step）
