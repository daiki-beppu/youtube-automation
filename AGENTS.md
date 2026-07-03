# AGENTS.md

This file provides guidance to Codex CLI (developers.openai.com/codex) when working with code in this repository. Claude Code 向けの同等ドキュメントは `CLAUDE.md` を参照。

## このリポジトリのエージェント構成

このリポジトリは Claude Code と Codex CLI の **両方** のエージェントから操作される。スキル群は単一の実体を共有する:

- 実体: `.claude/skills/`（Claude Code 規約のパス）
- Codex 用 alias: `.agents/skills` → `.claude/skills` の **symlink**

Codex CLI は `$REPO_ROOT/.agents/skills` を skill 探索パスとして読み込むため、symlink 経由で `.claude/skills/` 配下の SKILL.md をそのまま利用できる。スキルを編集するときは **必ず `.claude/skills/` 側を直接編集する**（symlink を貼り替えない）。

新規 skill の `SKILL.md` を作成・編集する際は、frontmatter の `description:` を **必ず double-quoted string**（`description: "Use when 〜"`）で書く。値内の `: `（コロン+スペース）が strict YAML パーサ（PyYAML `safe_load` 等）でマッピング区切りと誤解釈されパースが破綻するため。

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
- `.agents/skills` — `.claude/skills` への symlink。Codex CLI 用の探索パスとして配置
- `AGENTS.md` / `CLAUDE.md` — エージェント向けプロジェクトドキュメント（本ファイルが Codex 用、`CLAUDE.md` が Claude Code 用）
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
  shorts.json           # shorts (optional)
  comments.json         # comments (optional)
  pinned-comment.json   # pinned_comment (optional)
  distrokid.json        # distrokid (optional)
config/localizations.json
auth/{client_secrets,token}.json
.claude/skills/         # yt-skills sync で展開（Codex 利用時は .agents/skills の symlink も併設可）
collections/            # コンテンツ成果物
```

## 主要モジュール

| モジュール | 責務 |
|---|---|
| `utils.config` | `config/channel/*.json` の glob ロード／バリデーション。`load_config()` / `channel_dir()` / `reset()` / `ChannelConfig` を export |
| `utils.config.{meta,content,youtube,analytics,playlists,workflow,shorts,audio,localizations,comments,pinned_comment,distrokid}` | 責務別 dataclass |
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
- サンプルは `examples/channel_config.example/`（必須 + optional ファイル、`community.example.json` は skill-local raw JSON 例外）と `examples/localizations.example.json`

### エラーハンドリング

- `utils/exceptions.py` のドメイン例外を使用すること
- 生の `Exception` / `KeyError` を catch しない — `ConfigError`, `YouTubeAPIError` 等を使う
- `YouTubeAPIError.from_http_error(error, context)` で googleapiclient の HttpError を変換できる

### Import 規約

- パッケージ内コードは必ず `from youtube_automation.xxx import ...` の fully-qualified import を使う

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
- バージョン bump は `pyproject.toml::version` のみを更新する（`src/youtube_automation/__init__.py::__version__` は `importlib.metadata` 経由で動的に読み込むため触らない）。リリース運用全体は `/automation-release` スキルで一気通貫に実行する

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
- **takt 設定**: リポジトリ固有 `.takt/config.yaml` は `draft_pr: false` / `base_branch` のみ上書きし、provider・model・language・persona はグローバル `~/.takt/config.yaml` を継承する。グローバルは Codex + Opus ハイブリッド（default `provider: claude` / `model: opus 4.6`、doer/planner 系のみ `codex` に override、レビュー系・supervisor は opus、`language: ja`）
- workflow は組み込み **default**（plan → review → ... → reviewers の 9 step）
- **リリース**: `/automation-release` スキルで Release PR パターンを自動化（prepare → リリース PR → publish の 2 フェーズ）

### skill 編集と takt の関係

`.claude/skills/**` を含む `.claude/` 配下は Claude Code の **protected paths**（`acceptEdits` モードでも write 時に必ず prompt が出る領域）に該当する。takt は Claude Agent SDK を `settingSources: ['project']` + `permissionMode: 'acceptEdits'` で呼ぶため prompt に答える人間がおらず、**Claude provider が走る persona から** `.claude/skills/<name>/SKILL.md` 等への Edit/Write は `Claude requested permissions to write to ..., but you haven't granted it yet.` で deny される（`permissions.allow` ルールでは bypass 不可、`bypassPermissions` のみが bypass）。

ただし、**実装を担う `coder` persona を codex provider にしている（グローバル設定から継承）ため**、実装ファイルへの編集は Codex CLI 経由で行われ Claude Code の protected paths 制約を回避できる（Codex は独自のサンドボックスで動作し、`$REPO_ROOT/.agents/skills` を探索パスに含む）。レビュー系 persona は opus（Claude）だが書き込みは行わないため影響しない。そのため、**skill 配下を変更する issue も takt から問題なく回せる**。実際の運用例として、`.claude/skills/videoup/references/generate_videos.sh` 等の skill 配下スクリプト修正も takt 経由で完走実績がある。

逆に `coder` を Claude provider に戻している環境では、従来通り skill 配下の Edit が deny される。その場合は通常の対話セッション（Claude Code / Codex CLI どちらでも可、cmux pane 等）で直接編集し、コミット・PR 作成は `commit-convention` / `pr` スキル経由で実施する。

### Codex CLI 固有の注意

- AGENTS.md は Codex CLI が起動時に読み込むプロジェクトドキュメント。Codex 側で本ファイルを参照する前提で記述している
- skill 機能（`.agents/skills/` 配下の SKILL.md）も Codex CLI 標準仕様に沿って読み込まれる
- ただし、本リポジトリのスキル群は Claude Code 文脈で設計された記述が多い（例: `claude-code-setup` プラグイン前提、TodoWrite ツール前提）。Codex 経由で個別スキルを起動する際は記述差異を考慮すること
- skill 内の Claude Code 固有表現は、Codex 実行時に次のように読み替える: `AskUserQuestion` は通常のユーザー確認、`Read ツール` は画像/ファイル閲覧手段、`Bash ツール run_in_background=true` は長時間コマンドを非同期 session で起動して進捗を poll、`TodoWrite` は Codex の plan/checklist 更新。これらの表記が残っていても実装不整合とは扱わず、同等の Codex 機能で実行する。
