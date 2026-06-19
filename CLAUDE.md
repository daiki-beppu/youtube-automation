# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

YouTube チャンネル運営を自動化するツールキット。`youtube-channels-automation` パッケージとして配布し、各チャンネルリポジトリへ git+https または submodule 経由で導入される。Analytics 収集、AI コンテンツ生成（Lyria / Veo / Gemini / Suno）、動画アップロード、メタデータ生成、ベンチマーク分析を統合提供する。

## プロジェクト固有コマンド

```bash
uv run yt-skills sync                                # チャンネルリポジトリへ .claude/skills を配布
uv run yt-skills sync --asset claude-md              # .claude/CLAUDE.md (BGM 運営方針テンプレ) を配布
uv run yt-skills list                                # 同梱スキル一覧
uv run yt-skills list --asset claude-md              # 同梱 CLAUDE.md テンプレ一覧
uv run yt-skills diff                                # 同梱版と target の差分確認
uv run yt-skills diff --asset claude-md              # CLAUDE.md テンプレの差分確認
uv run yt-config-migrate diff                        # 旧 channel_config.json → 責務別分割のプレビュー
uv run yt-config-migrate migrate --apply             # 実際に分割実行
uv run yt-config-migrate verify                      # 新 loader で読み込み検証
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
- `.claude/skills/` — 自動化スキル群（Claude Code / Codex 共用）。wheel に `_skills/` として `force-include` され、`yt-skills sync` で各チャンネルへ展開される
- `.claude/CLAUDE.template.md` — BGM チャンネル運営方針テンプレ（共通骨格）。wheel に `_claude_md/CLAUDE.template.md` として `force-include` され、`yt-skills sync --asset claude-md` で各チャンネルの `.claude/CLAUDE.md` として展開される
- `.agents/skills` — `.claude/skills` への symlink。Codex CLI 用の探索パス（Codex 規約 `$REPO_ROOT/.agents/skills`）
- `AGENTS.md` — Codex CLI 向けエージェント指示。本ファイル（CLAUDE.md）と並立し、Codex 視点のドキュメント補足を含む
- `auth/` — submodule 利用者向け **後方互換 shim**（OAuth 認証情報のみ維持。`utils/`・`agents/`・`scripts/` のルート shim は廃止済み）

### 下流チャンネルリポジトリ（`CHANNEL_DIR` が指す先）

```
config/channel/         # 責務別分割設定（v2.0.0 以降）
  meta.json             # channel / youtube_channel
  content.json          # genre / tags / descriptions / title
  youtube.json          # youtube / music_engine / content_model
  analytics.json        # analytics / benchmark
  playlists.json        # playlists
  workflow.json         # (v4.0.0 で short / community 撤去、後方互換で素通し)
  audio.json            # audio
config/localizations.json
auth/{client_secrets,token}.json
.claude/skills/         # yt-skills sync で展開
.agents/skills          # → ../.claude/skills の symlink。skills sync が併設（Codex 探索パス）
collections/            # コンテンツ成果物
assets/stock/           # ボツ画像ストック (#364)。<theme-slug>/ 配下に画像 + .meta.json
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
| `utils.stock` | ボツ画像ストック化（`assets/stock/<theme>/` への退避・列挙・整理、隣接 `.meta.json` 管理） |
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

### 依存ポリシー: deprecated 表明済み依存の取り扱い

- **`google-auth-httplib2`（PyPI 0.4.0 で deprecated 表明）**:
  - `src/youtube_automation/` / `tests/` 配下に `google_auth_httplib2` の **直 import を新規追加しない**（現状 0 件、回帰テスト `tests/test_no_google_auth_httplib2_direct_import.py` で機械担保）
  - 既存の transitive 依存は `googleapiclient.discovery.build(..., credentials=credentials)` 経由で残置する（上流 `google-api-python-client` が内部で `google_auth_httplib2.AuthorizedHttp` を要求しているため、即時撤去不可）
  - 上流が non-httplib2 transport（`google.auth.transport.requests` など）を正式サポートした際の移行手順・撤去判断は `docs/migration/google-auth-httplib2.md` を参照
  - `pyproject.toml::dependencies` の `"google-auth-httplib2"` 直接宣言の撤去は transport 切替完了後に別 issue で再検証する

### スクリプト配置

- **skill 固有のスクリプト**は `.claude/skills/<skill>/references/` に配置する（例: `.claude/skills/videoup/references/generate_videos.sh`）
- 共通スクリプト（例: `gcp-bootstrap.sh` / `gcp-terraform-apply.sh`）も該当 skill の `references/` 配下に置く（現状は `.claude/skills/channel-setup/references/`）。ルート直下に `scripts/` ディレクトリは設けない

### テスト

- `tests/conftest.py` が `src/` を sys.path に追加し `CHANNEL_DIR` を `tests/fixtures/sample_channel/` に向ける
- `_reset_config_singleton` autouse fixture が各テスト前後で `utils.config.reset()` を呼ぶ。**追加で** `ServiceRegistry.reset()` が必要なテストは個別に呼ぶこと
- ユニット: `tests/test_*.py` / 統合: `tests/integration/`（API・外部依存あり）
- フィクスチャ JSON は新構造（`config/channel/*.json`）で配置

### パッケージング

- `.claude/skills/` は `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_skills/` に同梱され、`yt-skills sync` が `importlib.resources` で参照する
- `.claude/CLAUDE.template.md` も同様に `[tool.hatch.build.targets.wheel.force-include]` で wheel 内 `_claude_md/CLAUDE.template.md` に同梱され、`yt-skills sync --asset claude-md` で `.claude/CLAUDE.md` として展開される
- 配布アセットの追加は `src/youtube_automation/cli/skills_sync.py::_ASSET_SPECS` に entry を追加するだけで `list/sync/diff` が自動的にサポートされる（`kind="dir" | "file"` を選ぶ）
- `skills` asset を標準レイアウト（`.claude/skills`）へ sync すると、下流リポにも `.agents/skills -> ../.claude/skills` の相対 symlink を併設する（Codex CLI 探索パス規約）。既存の正しい symlink は冪等にスキップし、張り直しは `--force`、symlink 非対応環境では警告のみで sync は継続する（`_ops.py::_ensure_agents_skills_symlink`）
- バージョン bump は `pyproject.toml::version` のみを更新する（`src/youtube_automation/__init__.py::__version__` は `importlib.metadata` 経由で動的に読み込むため触らない）。リリース運用全体は `/automation-release` スキルで一気通貫に実行する

### TS レイヤー（packages/）

Python → TypeScript 書き換え（ADR-0001）の TS コードは `packages/` に配置する。runtime は Bun、型チェックは `tsc -b --noEmit`、lint は oxlint、formatter は oxfmt、dead code 検出は knip。

#### パッケージ構成

- `packages/core/` — ドメインロジック（analytics, config, image, oauth, upload, metadata, suno-prompts, skills-sync）。`@youtube-automation/core` として export
- `packages/cli/` — CLI コマンド（`tayk` エントリポイント）。core の service を呼び出す adapter 層

#### コマンド追加手順

1. `packages/core/src/<domain>/service.ts` に service 関数を作成。`Result<Output, ServiceError>` を返す。入力は zod schema で `.parse()` する
2. `packages/core/src/<domain>/schema.ts` に入出力の zod schema を定義
3. `packages/core/src/<domain>/index.ts` で public API を re-export
4. `packages/core/src/registry.ts` に service entry を登録（`deps` / `run` を定義）
5. `packages/cli/src/commands/<name>/cli.ts` に CLI adapter を作成
6. `packages/cli/bin/tayk.ts` で command を import し、`subCommands` に登録
7. service のテストは `packages/core/test/<name>.test.ts` に配置。DI seam（`deps`）経由で fake を注入
8. CLI adapter の smoke test は `packages/cli/test/<command>.test.ts` に配置。dispatcher 経由で args / output / exit code / error path / deps 解決を検証

#### service 境界契約（ADR-0003）

- service 関数は `async (input, deps) => Result<Output, ServiceError>` のシグネチャ
- `deps` で外部依存を注入（YouTube API client, sleep, persist 等）— テスト時に fake に差し替え可能
- core 内部は throw OK。境界の `try/catch` で `toServiceError` に集約
- retry は `withRetry` に委譲。quota は retry せず `err(domain: "quota")` で返す

#### 検証コマンド

```bash
bun run typecheck          # tsc -b --noEmit
bun test                   # bun test（全パッケージ）
bun run lint               # oxlint
bun run format:check       # oxfmt
bun run knip               # dead code 検出
bun run ci                 # 上記すべて一括
```

#### エラーハンドリング

- `packages/core/src/errors.ts` のドメインエラーを使用: `YouTubeAPIError`, `QuotaExhaustedError`, `toServiceError`
- `Result` 型（`ok(value)` / `err(serviceError)`）で caller にエラーを伝搬。throw しない
- service error の `domain` フィールド: `"validation"` / `"quota"` / `"api"` / `"auth"` / `"io"` / `"config"`

### extensions（Chrome 拡張開発）

`extensions/` 配下の Chrome 拡張は **WXT + React + TypeScript + Tailwind CSS** スタックで開発する（Python 本体とは独立した Node ツールチェーン）。詳細は `extensions/README.md`。

- **ディレクトリ規約**: 各拡張は `extensions/<name>/` に WXT 規約（`entrypoints/` 構成）で配置。複数拡張で再利用する共通コードは `extensions/shared/`（契約定数 / API client / origin allowlist / DOM ヘルパ）に集約し、各拡張から相対 import（`../../shared/*`）で参照する
- **manifest は自動生成**: `manifest.json` を手書きせず `wxt.config.ts` から生成する。権限は最小権限を `lib/manifest.ts` の `MANIFEST_PERMISSIONS` 単一定数で宣言し、`wxt.config.ts` がそれを参照する（過剰権限の混入は Vitest で機械担保）
- **型安全**: 全 source を TypeScript で書き、`@types/chrome` で `chrome.*` を型付け。message は `@webext-core/messaging`、`chrome.storage` は `@wxt-dev/storage` の型付き wrapper を経由する
- **契約文字列**: サーバー（`yt-collection-serve`）との互換契約値（storage key / 配信ルート / phase 値）は `extensions/shared/constants.ts` の定数として 1 箇所で定義する。メッセージ種別（`run` / `stop` / `progress`）は各拡張の `lib/messaging.ts` で `@webext-core/messaging` の ProtocolMap として型付け定義する。ハードコーディング禁止
- **テスト必須**: unit は Vitest（`pnpm test`）、e2e は Playwright（`pnpm test:e2e`、Suno UI mock への DOM 注入スモーク）。CI は `.github/workflows/extensions.yml` が lint / 型チェック / Vitest / Playwright を実行する
- **成果物は commit しない**: `node_modules/` / `dist/` / `.wxt/` / `.output/` は `.gitignore` 済み。配布は `release-extensions.yml` が tag push 時に zip を GitHub Release へ添付する
- **パッケージマネージャ**: `pnpm`（`ni`/`nr` ではなく直接 `pnpm` を使う。WXT/Playwright の前提）

## セキュリティ

- `auth/client_secrets.json` / `auth/token.json` / `.env` は **絶対にコミットしない**
- シークレット解決順序: `os.environ` → `op read`（1Password CLI）→ `ConfigError`
- 参照定義は `utils/secrets.py` の `_SECRET_REFS`（デフォルト: `op://Personal/YouTube_OAuth_Client_Secrets/credential`）
- AI 系（Vertex AI）は ADC 認証のため `op` 取得は不要

### Git hooks（lefthook）

Git hooks は [lefthook](https://lefthook.dev) で宣言的に管理する（設定は `lefthook.yml`）。

- **pre-commit**: 変更した Python ファイルに `ruff check` / `ruff format --check` をかける（CI の lint ジョブと同等）
- **pre-push**: CHANGELOG ゲート。CI（`.github/workflows/ci.yml` の `changelog` ジョブ）と同じく、実コード（`src/youtube_automation/` / `.claude/skills/` / `.claude/CLAUDE.template.md` / `pyproject.toml`）を変更したのに `CHANGELOG.md` の `[Unreleased]` が未更新なら push を止める。ロジック本体は `.lefthook/pre-push/changelog-gate.sh`

有効化と運用:

- **有効化**: `nix develop`（または direnv `use flake`）で devShell に入ると `flake.nix` の shellHook が `lefthook install` を自動実行する。手動なら `lefthook install`（クローン後 1 回）
- **全 hook をスキップ**: `LEFTHOOK=0 git push` / `LEFTHOOK=0 git commit`
- **CHANGELOG ゲートのみ省く**: `SKIP_CHANGELOG=1 git push`（CI 側は PR の `skip-changelog` ラベル）
- refactor / fix でも src を触れば CHANGELOG 追記が要る。tests / docs だけの変更はゲート対象外（hook も CI も自動 skip）

## 開発ワークフロー

このリポジトリの開発は **必ず worktree 上で行う**。メインの作業ツリー（リポジトリ本体のチェックアウト先）で直接ブランチを切って作業してはならない — 作業状態の競合や他作業との干渉を避けるため。

標準ルートは **takt + GitHub issue**（`takt-issue` スキル経由で issue → worktree → PR を統一手順化）。takt を使わないアドホックな修正でも、`git worktree add` で worktree を作成してから作業すること。

worktree の置き場は以下に統一する:

- **takt 自動生成**: `<repo-parent>/takt-worktrees/<timestamp>-<N>-<slug>/`（takt が自動管理）
- **手動 `git worktree add`**: `$REPO_ROOT/.worktrees/<slug>/`（リポジトリ内・gitignore 済み・`parallel` スキルと共通）

`<repo-parent>/automation-worktrees/` 等のリポジトリ外手動置き場は非推奨（過去の残骸のみ）。

- **issue 起票**: `gh issue create` または `/issue` スキル
- **takt 起動**: `takt add '#<N>'` → `takt run`（base branch は **main** 固定、PR は通常 PR）
- **commit 規約**: 日本語 Conventional Commits + タイトル末尾に `(#<N>)`。`commit-convention` スキル参照
- **takt 設定**: リポジトリ固有 `.takt/config.yaml` は `draft_pr: false` / `base_branch` のみ上書きし、provider・model・language・persona はグローバル `~/.takt/config.yaml` を継承する。グローバルは Codex + Opus ハイブリッド（default `provider: claude` / `model: opus 4.6`、doer/planner 系のみ `codex` に override、レビュー系・supervisor は opus、`language: ja`）
- workflow は組み込み **default**（plan → review → ... → reviewers の 9 step）
- **リリース**: `/automation-release` スキルで Release PR パターンを自動化（prepare → リリース PR → publish の 2 フェーズ）。post-release の運営者向けガイドと下流追従 issue は `/release-notes` が担当

### skill 編集と takt の関係

`.claude/skills/**` を含む `.claude/` 配下は Claude Code の **protected paths**（`acceptEdits` モードでも write 時に必ず prompt が出る領域）に該当する。takt は Claude Agent SDK を `settingSources: ['project']` + `permissionMode: 'acceptEdits'` で呼ぶため prompt に答える人間がおらず、**Claude provider が走る persona から** `.claude/skills/<name>/SKILL.md` 等への Edit/Write は `Claude requested permissions to write to ..., but you haven't granted it yet.` で deny される（`permissions.allow` ルールでは bypass 不可、`bypassPermissions` のみが bypass）。

ただし、**実装を担う `coder` persona を codex provider にしている（グローバル設定から継承）ため**、実装ファイルへの編集は Codex CLI 経由で行われ Claude Code の protected paths 制約を回避できる（Codex は独自のサンドボックスで動作し、`$REPO_ROOT/.agents/skills` を探索パスに含む）。レビュー系 persona は opus（Claude）だが書き込みは行わないため影響しない。そのため、**skill 配下を変更する issue も takt から問題なく回せる**。実際の運用例として、`.claude/skills/videoup/references/generate_videos.sh` 等の skill 配下スクリプト修正も takt 経由で完走実績がある。

逆に `coder` を Claude provider に戻している環境では、従来通り skill 配下の Edit が deny される。その場合は通常の Claude Code 対話セッション（cmux pane 等）で直接編集し、コミット・PR 作成は `commit-convention` / `pr` スキル経由で実施する。
