# アーキテクチャ詳細

CLAUDE.md の「アーキテクチャ」節の詳細版。要点は CLAUDE.md を参照。

このリポジトリは **このリポジトリ自体** と **下流のチャンネルリポジトリ** の 2 層構造で動く。

## 自リポジトリ

- `src/youtube_automation/utils/` — コアライブラリ（設定ローダー、API クライアント、analytics、upload）
- `src/youtube_automation/agents/` — アップロードエージェント（Auto / Collection）
- `src/youtube_automation/scripts/` — `yt-*` CLI 本体
- `src/youtube_automation/cli/` — ユーザー向け CLI（`yt-skills`, `yt-doctor`, `yt-cost-report`）
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
| `scripts.collection_serve_discovery` | 固定 loopback endpoint の稼働 server registry、heartbeat、TTL、owner takeover |
| `extensions/shared/server-discovery.ts` | registry schema v1 の検証と `/server-info` probe を両 helper 拡張へ提供 |
| `extensions/shared/server-source-migration.ts` | 廃止した配信元候補履歴 storage key の共通 migration |

### collection-serve discovery schema v1

固定 endpoint は `http://localhost:7872/.well-known/yt-collection-serve`。`yt-collection-serve` は起動時と heartbeat ごとに `Content-Type: application/json`、`Origin` なしで次を POST する。

```json
{
  "instance_id": "fixture-instance",
  "server_info": {
    "channel_name": "Fixture Channel",
    "channel_short": "fixture",
    "hostname": "fixture.localhost",
    "port": 49152,
    "base_url": "http://fixture.localhost:49152",
    "label": "Fixture Channel"
  }
}
```

GET の schema v1 応答は次の完全形。`schema_version` は互換性番号、`ttl_seconds` は heartbeat が更新する生存期間、`servers` は `base_url` 順の稼働登録である。各 entry の `instance_id` はプロセス識別子、`expires_at` は Unix time の失効時刻、`server_info` はチャンネル名・短縮名・loopback host/port/base URL・selector 表示 label を表す。

```json
{
  "schema_version": 1,
  "ttl_seconds": 30,
  "servers": [
    {
      "instance_id": "fixture-instance",
      "expires_at": 130.0,
      "server_info": {
        "channel_name": "Fixture Channel",
        "channel_short": "fixture",
        "hostname": "fixture.localhost",
        "port": 49152,
        "base_url": "http://fixture.localhost:49152",
        "label": "Fixture Channel"
      }
    }
  ]
}
```

同じ `instance_id` の POST は entry を増やさず `expires_at` を更新する。正常終了は `{"instance_id":"fixture-instance"}` を DELETE して即時削除し、異常終了した entry は TTL 境界（`expires_at` と同時刻）で失効する。最大 body は 16384 bytes、`instance_id` は最大 128 文字、同時登録は最大 128 件。POST/DELETE は JSON 以外を 415、`Origin` 付き要求を 403、不正 schema を 400、body 超過を 413、登録数超過を 429 にし、状態を変更しない。未知 path は 404、未対応 method は 405。

拡張側 storage schema は Suno が `chrome.storage.local["sunoServerUrl"]`、DistroKid が `chrome.storage.local["serverUrl"]` に選択中 URL 文字列だけを保存する。共通の旧候補配列 `chrome.storage.local["ytCollectionServeSources"]` は更新時 migration で削除し、以後は再作成しない。
