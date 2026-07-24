# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

詳細ドキュメント: アーキテクチャ全容・主要モジュール表は `docs/architecture.md`、パッケージング / extensions / lefthook 詳細は `docs/development.md`、takt 運用詳細は `docs/takt-operations.md`。

本リポジトリの開発者 bootstrap は `docs/development.md#開発者-bootstrap正規入口` を単一ソースとする。親 checkout / linked worktree の各 checkout で最初に `bash .lefthook/setup-worktree.sh` を実行し、非対話 shell は同 wrapper に command を渡す。

## プロジェクト概要

YouTube チャンネル運営を自動化するツールキット。`youtube-channels-automation` パッケージとして配布し、各チャンネルリポジトリへ導入される（Analytics 収集、AI コンテンツ生成、動画アップロード、メタデータ生成、ベンチマーク分析）。

## プロジェクト固有コマンド

```bash
uv run yt-skills sync             # チャンネルリポジトリへ .claude/skills を配布（--asset claude-md で CLAUDE.md テンプレ）
uv run yt-skills list             # 同梱スキル一覧
uv run yt-skills diff             # 同梱版と target の差分確認
uv run yt-skills lint [<skill>..] # SKILL.md frontmatter の軽量検証（strict YAML / double-quote。pytest 不要で秒単位）
```

`yt-*` 系 CLI 全 30 件超は `pyproject.toml` の `[project.scripts]` に登録されている。新規 CLI を追加するときは **必ず `yt-*` プレフィックス**を踏襲し、entry point を登録すること。

## アーキテクチャ要点

このリポジトリは **このリポジトリ自体** と **下流のチャンネルリポジトリ** の 2 層構造で動く（全容・主要モジュール表は `docs/architecture.md`）。

- `src/youtube_automation/{utils,agents,scripts,cli,templates}/` — コアライブラリ / アップロードエージェント / `yt-*` CLI 本体 / ユーザー向け CLI / 説明文テンプレート
- `.claude/skills/` — 自動化スキル群（Claude Code / Codex 共用）。wheel に同梱され `yt-skills sync` で各チャンネルへ展開。`.agents/skills` は Codex CLI 探索パス用の symlink（実体は常に `.claude/skills/` 側を編集）
- `auth/` — submodule 利用者向け後方互換 shim（OAuth 認証情報のみ）
- 下流チャンネルリポジトリ（`CHANNEL_DIR`）: `config/channel/*.json`（責務別分割。meta / content / youtube / analytics / playlists / workflow / audio + optional の shorts.json / comments.json / pinned-comment.json / distrokid.json / community-draft.json）、`config/localizations.json`、`auth/`、`.claude/skills/`、`collections/`、`assets/stock/`

## 開発規約

### 設定アクセス

- チャンネル固有値は **必ず** `from youtube_automation.configuration import load_config` 経由で取得
- 責務別ネームスペースでアクセス: `config.meta.channel_name` / `config.content.tags.base` / `config.youtube.api.category_id`
- ハードコーディング禁止 — `config/channel/*.json` に集約
- 新しい設定キーを追加する場合:
  1. 該当責務の dataclass（`configuration/<section>.py`）にフィールド追加
  2. `configuration/loader.py::_build_*` で JSON からの組み立てを追加
  3. 必須キーであれば `_REQUIRED_KEYS_BY_SECTION` にも登録
- Path のみ必要な場合（loader を起動したくない）は `channel_dir()` を使う
- サンプルは `examples/channel_config.example/`（必須 + optional ファイル、`community.example.json` は skill-local raw JSON 例外）と `examples/localizations.example.json`

### エラーハンドリング

- `infrastructure/errors.py` のドメイン例外を使用すること
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
- スキルの新規作成・改訂時は `docs/skill-design/skill-authoring-guidelines.md` の 7 ルール（発動キーワードの相互排他 / 承認ゲート / 前提存在ガード / 判断基準の明確化 / references 単一ソース化 / Hard Gates 冒頭配置 / 未接続参照の隔離）に従う。既存スキルの一括改修は不要

### テスト

- `tests/conftest.py` が `src/` を sys.path に追加し `CHANNEL_DIR` を `tests/fixtures/sample_channel/` に向ける
- `_reset_config_singleton` autouse fixture が各テスト前後で `configuration.reset()` を呼ぶ。追加の実行スコープ状態が必要なテストは、生成した `YouTubeClients` インスタンスを直接 reset／再生成すること
- ユニット: `tests/test_*.py` / 統合: `tests/integration/`（API・外部依存あり）
- フィクスチャ JSON は新構造（`config/channel/*.json`）で配置

### パッケージング

- `.claude/skills/` と `.claude/CLAUDE.template.md` は wheel に force-include され `yt-skills sync` で配布される。バージョン bump は `pyproject.toml::version` のみ（`__version__` は動的読込）。詳細は `docs/development.md`、リリースは `/automation-release` スキル

### TS レイヤー（dashboard 限定例外）

TS 版（tayk）の開発は専用の別リポジトリで行う（`docs/adr/0021-separate-repo-restart.md`）。本リポジトリは Python 版のメンテナンスモードであり、**`dashboard/` の React + Vite + shadcn/ui 表示層だけを dashboard 限定の TypeScript 例外**とする。dashboard frontend は Python の起動時 Analytics 収集・読み取り専用 JSON API・build asset 配信に従属し、詳細は ADR-0013 と `docs/development.md::dashboard 開発` を正とする。

他の TypeScript 実装・fix、tayk core、削除済み `packages/` の復活は禁止する。Chrome 拡張は既存 `extensions/` 規約に従う独立例外であり、dashboard から `extensions/shared-ui` を直接 import しない。

## セキュリティ

- `auth/client_secrets.json` / `auth/token.json` / `.env` は **絶対にコミットしない**
- シークレット解決順序: `os.environ` → `op read`（1Password CLI）→ `ConfigError`。`YOUTUBE_AUTOMATION_DISABLE_OP_READ=1` の場合は `op read` をスキップし、通常テストではこの opt-out を既定有効化する
- 参照定義は `utils/secrets.py` の `_SECRET_REFS`（デフォルト: `op://Personal/YouTube_OAuth_Client_Secrets/credential`）
- AI 系（Vertex AI）は ADC 認証のため `op` 取得は不要

### CHANGELOG ゲート

- 実コード（`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`）を変更したら `CHANGELOG.md` の `[Unreleased]` 追記が必須（lefthook pre-push + CI で機械担保）
- tests / docs だけの変更はゲート対象外。意図的に省く場合は `SKIP_CHANGELOG=1 git push`（CI 側は PR の `skip-changelog` ラベル）
- lefthook の有効化手順・pre-commit の詳細は `docs/development.md`
- bootstrap / 対話・非対話 shell / 依存同期の正規手順は `docs/development.md#開発者-bootstrap正規入口`、`.envrc` と `.lefthook/install.sh` を含む hook の診断・再インストールは同文書の「Git hooks（lefthook）」を参照

## 開発ワークフロー

このリポジトリの開発は **必ず worktree 上で行う**（メインの作業ツリーで直接ブランチを切らない）。標準ルートは **takt + GitHub issue**。worktree 置き場・takt 設定の継承・skill 編集と takt の関係・Codex 読み替えの詳細は `docs/takt-operations.md`。

- **issue 起票**: `gh issue create` または `/issue` スキル
- **takt 起動**: `takt add '#<N>'` → `takt run`（base branch は **main** 固定、PR は通常 PR）
- **workflow 使い分け**: issue の `takt:*` ラベルと同名の workflow で実行する（ラベル = workflow 名）。`takt:feature`（新規 feature・セキュリティ/認証・公開インターフェース/スキーマ変更。テスト先行の厳格 7 step）/ `takt:improve`（既存機能の意図的な挙動変更・拡張、interface 変更なし）/ `takt:diagnose-fix`（原因不明バグの診断 → 条件付き自動修正）/ `takt:fix`（原因特定済みの軽量修正）/ `takt:docs`（ドキュメント・skill のみの変更）/ `takt:lite`（refactor / chore 等の軽量タスク。迷ったらこれ）。`takt:manual` は takt を使わず `/issue-direct` や手動で直接実装する。判定基準と対応表は `docs/takt-operations.md`
- **commit 規約**: 日本語 Conventional Commits + タイトル末尾に `(#<N>)`
- **リリース**: `/automation-release` スキル（post-release は `/release-notes`）
