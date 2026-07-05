# アーキテクチャ詳細

CLAUDE.md の「アーキテクチャ」節の詳細版。要点は CLAUDE.md を参照。

このリポジトリは **このリポジトリ自体** と **下流のチャンネルリポジトリ** の 2 層構造で動く。

## 自リポジトリ

- `src/youtube_automation/utils/` — コアライブラリ（設定ローダー、API クライアント、analytics、upload）
- `src/youtube_automation/agents/` — アップロードエージェント（Auto / Collection）
- `src/youtube_automation/scripts/` — `yt-*` CLI 本体
- `src/youtube_automation/cli/` — ユーザー向け CLI（`yt-skills`, `yt-config-migrate`, `yt-cost-report`）
- `src/youtube_automation/templates/` — 説明文テンプレート
- `.claude/skills/` — 自動化スキル群（Claude Code / Codex 共用）。wheel に `_skills/` として `force-include` され、`yt-skills sync` で各チャンネルへ展開される
- `.claude/CLAUDE.template.md` — BGM チャンネル運営方針テンプレ（共通骨格）。wheel に `_claude_md/CLAUDE.template.md` として `force-include` され、`yt-skills sync --asset claude-md` で各チャンネルの `.claude/CLAUDE.md` として展開される
- `.agents/skills` — `.claude/skills` への symlink。Codex CLI 用の探索パス（Codex 規約 `$REPO_ROOT/.agents/skills`）
- `AGENTS.md` — Codex CLI 向けエージェント指示。CLAUDE.md と並立し、Codex 視点のドキュメント補足を含む
- `auth/` — submodule 利用者向け **後方互換 shim**（OAuth 認証情報のみ維持。`utils/`・`agents/`・`scripts/` のルート shim は廃止済み）

## 下流チャンネルリポジトリ（`CHANNEL_DIR` が指す先）

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
.claude/skills/         # yt-skills sync で展開
.agents/skills          # → ../.claude/skills の symlink。skills sync が併設（Codex 探索パス）
collections/            # コンテンツ成果物
assets/stock/           # ボツ画像ストック (#364)。<theme-slug>/ 配下に画像 + .meta.json
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
| `utils.stock` | ボツ画像ストック化（`assets/stock/<theme>/` への退避・列挙・整理、隣接 `.meta.json` 管理） |
| `auth.oauth_handler` | OAuth 2.0 トークン管理 |
| `utils.secrets` | シークレット解決（`_SECRET_REFS` で参照定義） |
| `cli.skills_sync` | `yt-skills` 本体 |
