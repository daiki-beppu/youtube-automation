# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

詳細ドキュメント: アーキテクチャ全容・主要モジュール表は `docs/architecture.md`、パッケージング / extensions / lefthook 詳細は `docs/development.md`、takt 運用詳細は `docs/takt-operations.md`。

## プロジェクト概要

YouTube チャンネル運営を自動化するツールキット。`youtube-channels-automation` パッケージとして配布し、各チャンネルリポジトリへ導入される（Analytics 収集、AI コンテンツ生成、動画アップロード、メタデータ生成、ベンチマーク分析）。

## プロジェクト固有コマンド

```bash
uv run yt-skills sync             # チャンネルリポジトリへ .claude/skills を配布（--asset claude-md で CLAUDE.md テンプレ）
uv run yt-skills list             # 同梱スキル一覧
uv run yt-skills diff             # 同梱版と target の差分確認
uv run yt-config-migrate diff     # 旧 channel_config.json → 責務別分割のプレビュー（migrate --apply / verify も有り）
```

`yt-*` 系 CLI 全 30 件超は `pyproject.toml` の `[project.scripts]` に登録されている。新規 CLI を追加するときは **必ず `yt-*` プレフィックス**を踏襲し、entry point を登録すること。

## アーキテクチャ要点

このリポジトリは **このリポジトリ自体** と **下流のチャンネルリポジトリ** の 2 層構造で動く（全容・主要モジュール表は `docs/architecture.md`）。

- `src/youtube_automation/{utils,agents,scripts,cli,templates}/` — コアライブラリ / アップロードエージェント / `yt-*` CLI 本体 / ユーザー向け CLI / 説明文テンプレート
- `.claude/skills/` — 自動化スキル群（Claude Code / Codex 共用）。wheel に同梱され `yt-skills sync` で各チャンネルへ展開。`.agents/skills` は Codex CLI 探索パス用の symlink（実体は常に `.claude/skills/` 側を編集）
- `auth/` — submodule 利用者向け後方互換 shim（OAuth 認証情報のみ）
- 下流チャンネルリポジトリ（`CHANNEL_DIR`）: `config/channel/*.json`（責務別分割。meta / content / youtube / analytics / playlists / workflow / audio + optional の shorts.json / comments.json / pinned-comment.json / distrokid.json）、`config/localizations.json`、`auth/`、`.claude/skills/`、`collections/`、`assets/stock/`

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
- サンプルは `examples/channel_config.example/`（必須 + optional ファイル、`community.example.json` は skill-local raw JSON 例外）と `examples/localizations.example.json`

### エラーハンドリング

- `utils/exceptions.py` のドメイン例外を使用すること
- 生の `Exception` / `KeyError` を catch しない — `ConfigError`, `YouTubeAPIError` 等を使う
- `YouTubeAPIError.from_http_error(error, context)` で googleapiclient の HttpError を変換できる

### Import 規約

- パッケージ内コードは必ず `from youtube_automation.xxx import ...` の fully-qualified import を使う

### 依存ポリシー: deprecated 表明済み依存の取り扱い

- `google-auth-httplib2` の **直 import を新規追加しない**（回帰テスト `tests/test_no_google_auth_httplib2_direct_import.py` で機械担保）
- transitive 依存の残置理由・移行手順は `docs/migration/google-auth-httplib2.md` と `docs/development.md` を参照

### スクリプト配置

- skill 固有・共通スクリプトはいずれも該当 skill の `.claude/skills/<skill>/references/` に配置する。ルート直下に `scripts/` ディレクトリは設けない

### skill frontmatter

- SKILL.md の frontmatter `description:` は **必ず double-quoted string** で書く（値内の `: ` が strict YAML でマッピング区切りと誤解釈されるため）

### テスト

- `tests/conftest.py` が `src/` を sys.path に追加し `CHANNEL_DIR` を `tests/fixtures/sample_channel/` に向ける
- `_reset_config_singleton` autouse fixture が各テスト前後で `utils.config.reset()` を呼ぶ。**追加で** `ServiceRegistry.reset()` が必要なテストは個別に呼ぶこと
- ユニット: `tests/test_*.py` / 統合: `tests/integration/`（API・外部依存あり）
- フィクスチャ JSON は新構造（`config/channel/*.json`）で配置

### パッケージング

- `.claude/skills/` と `.claude/CLAUDE.template.md` は wheel に force-include され `yt-skills sync` で配布される。バージョン bump は `pyproject.toml::version` のみ（`__version__` は動的読込）。詳細は `docs/development.md`、リリースは `/automation-release` スキル

### extensions（Chrome 拡張開発）

- `extensions/` 配下は WXT + React + TypeScript + Tailwind CSS（pnpm）。規約詳細は `docs/development.md` と `extensions/README.md`

## セキュリティ

- `auth/client_secrets.json` / `auth/token.json` / `.env` は **絶対にコミットしない**
- シークレット解決順序: `os.environ` → `op read`（1Password CLI）→ `ConfigError`
- 参照定義は `utils/secrets.py` の `_SECRET_REFS`（デフォルト: `op://Personal/YouTube_OAuth_Client_Secrets/credential`）
- AI 系（Vertex AI）は ADC 認証のため `op` 取得は不要

### CHANGELOG ゲート

- 実コード（`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`）を変更したら `CHANGELOG.md` の `[Unreleased]` 追記が必須（lefthook pre-push + CI で機械担保）
- tests / docs だけの変更はゲート対象外。意図的に省く場合は `SKIP_CHANGELOG=1 git push`（CI 側は PR の `skip-changelog` ラベル）
- lefthook の有効化手順・pre-commit の詳細は `docs/development.md`

## 開発ワークフロー

このリポジトリの開発は **必ず worktree 上で行う**（メインの作業ツリーで直接ブランチを切らない）。標準ルートは **takt + GitHub issue**。worktree 置き場・takt 設定の継承・skill 編集と takt の関係・Codex 読み替えの詳細は `docs/takt-operations.md`。

- **issue 起票**: `gh issue create` または `/issue` スキル
- **takt 起動**: `takt add '#<N>'` → `takt run`（base branch は **main** 固定、PR は通常 PR）
- **workflow 使い分け**: 小〜中規模 issue はリポジトリ同梱の軽量 workflow **`lite`**（plan → implement → review の 3 step、トークン消費が少ない）。セキュリティ・認証・アップロード系、スキル横断・破壊的変更、テスト戦略設計が要る issue は組み込み **default**（9 step）を使う。基準は `docs/takt-operations.md`
- **commit 規約**: 日本語 Conventional Commits + タイトル末尾に `(#<N>)`。`commit-convention` スキル参照
- **リリース**: `/automation-release` スキル（post-release は `/release-notes`）
