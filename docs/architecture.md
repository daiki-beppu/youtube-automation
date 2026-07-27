# アーキテクチャ詳細

CLAUDE.md の「アーキテクチャ」節の詳細版。要点は CLAUDE.md を参照。

このリポジトリは **このリポジトリ自体** と **下流のチャンネルリポジトリ** の 2 層構造で動く。

## プロジェクト用語集

`CONTEXT.md` から移管した、本プロジェクト固有の用語と決定の正本。実装詳細ではなく、設計・運用・移行時に使う語彙を定義する。

### 配布・移行

**tayk**: cutover 後に公開する予定のブランド、npm package 名、bin 名。現行 Python 版の canonical CLI は `yt-*` であり、cutover 後の起動方式として `bunx tayk <cmd>` を計画している。

**cutover**: first-party 下流の日常運用が tayk のみで回るようになり、Python 版のメンテナンスを終了するイベント。tayk のリリース単位とは独立した判断であり、同一リポジトリ内の big-bang merge ではない。

**dogfood**: cutover 前に first-party 2 リポジトリで各コレクション 1 本のフルライフサイクルを実走させる受け入れ検証。期間ではなく完走で判定する。

**critical regression**: cutover をブロックする欠陥。誤公開・誤メタデータ、analytics 履歴または collection 成果物のデータ破壊、auth 破壊の 3 種に限る。

**first-party**: 運営者自身が保有するチャンネルリポジトリ。dogfood の対象であり、第三者 consumer が存在しないことを意味しない。

**external user**: `uv add git+https://` で Python 版を導入し skills 経由で運用する第三者コミュニティ。first-party ではないため dogfood 対象外だが、cutover の告知義務と移行コスト判断に影響する。

### 計画・設定

**Phase**: 実行順の見出しで、「いつ書くか」を表す。Tier とは直交する。

**Tier**: マイルストーンゲート所属のバッジ。[T1] は dogfood ブロッカー、[T2] は cutover ブロッカー、[T3] は port せず削除を表す。優先度ではない。

**config format**: tayk core が読み書きするファイル形式。すべて JSON とし、core は YAML パーサー依存を持たない。takt や CI など外部ツール所有ファイルは各ツールの規約に従う。

**skill config**: チャンネル固有のスキル挙動パラメータ。`config/skills/<skill>.json` のフルファイル 1 本で管理し、default と override の deep merge は行わず、zod schema の `.default()` が省略キーを補完する。

### アーキテクチャ

**MCP tool**: tayk が expose する型付き操作で、agent が直接呼ぶ第一級インターフェース。workflow tool と primitive tool の 2 層で構成する。

**workflow tool**: 人間の GO/NO-GO 判断ゲートで区切られた粗粒度の MCP tool。`collection.plan`、`collection.produce`、`collection.publish` があり、tool 内部で状態管理し resume できる。

**primitive tool**: 単一操作を行う細粒度の MCP tool。workflow tool が内部で呼ぶほか、agent が直接呼んで細かく制御できる。

**knowledge codec**: MCP tool の WHAT に対して WHEN/HOW を提供するドメイン知識パッケージ。60+ skill を `collection-lifecycle`、`channel-management`、`analytics`、`content-quality`、`distribution` の 5 本に集約し、cutover 時点で下流へ配布する操作面はこの 5 本だけとする。

**adapter**: core の MCP tool を各プロトコルへ橋渡しする薄いラッパ。MCP adapter と CLI adapter（`tayk <cmd>`）がある。

**tracer**: アーキテクチャ規約を確定させるため最初に end-to-end で通す垂直スライス。0 ベース再設計では `collection.plan` が該当し、PoC とは区別する。

### 動画生成・コンテンツ制作

**renderer**: collection の映像を生成するバックエンド。`remotion` は React コンポーネントから Chromium フレームキャプチャと ffmpeg エンコードまでを行い、`ffmpeg` は ffmpeg CLI を直接実行する。

**collection**: 1 本の YouTube 動画としてまとめられる楽曲群と成果物一式。`collections/planning/<slug>/` で制作し、公開後 `collections/live/` へ移動する。アルバムや YouTube playlist とは別概念である。

**collection lifecycle**: collection 固有の制作フロー。分析 → 企画 → GO/NO-GO → サムネ生成 → GO/NO-GO → 音源生成 → MIX/マスタリング → 動画生成 → upload → 公開後運用の順で進み、3 本の workflow tool に対応する。

**master**: collection 内の個別トラックをクロスフェード結合した最終音声ファイル（`master.mp3` / `master.wav`）。結合後に正規化し、videoup の音声トラックにする。

### Chrome 拡張

**yield guard**: suno-helper が生成曲の `metadata.duration` を検査し、尺が閾値外なら同一プロンプトで自動再生成する品質最低ライン。良い曲を選ぶ masterup-pairs のキュレーションとは別責務である。

**community-helper**: YouTube のチャンネル投稿ページへ DOM 注入し、`yt-collection-serve` から取得した投稿データを投稿 UI へ自動入力する Chrome 拡張。`suno-helper`、`distrokid-helper` と同列に配置する。

**helper extension shell**: first-party Chrome helper 拡張が共有する、開発ゲート、manifest 管理、server 連携、popup/background/content の責務境界、エラー表示の考え方を揃える構造的な外枠。対象サイト固有の機能を同一にすることではない。

### マルチチャンネル運用・データ

**workspace**: 複数チャンネルを `channels/<slug>/` として同居させる単一リポジトリ。共有物はルートに 1 セット、per-channel 状態は各チャンネル配下に置く。単一チャンネルリポ構成は恒久サポートで、workspace への移行は opt-in とする。

**channel slug**: workspace 内でチャンネルを識別する `channels/` 直下のディレクトリ名。`--channel <slug>` または `CHANNEL=<slug>` で実行対象を指定する。

**competitor**: `analytics.benchmark.channels` に登録するベンチマーク分析対象の他者チャンネル。CLI フラグは `--competitor` であり、`--channel` は自チャンネル指定に予約する。

**channel registry**: first-party チャンネルの絶対パス一覧を `~/.config/tayk/channels.json` に JSON 配列で保持するもの。表示名などは各チャンネルの `config/channel/meta.json` から解決し、dashboard が消費する。

**dashboard**: 全 first-party チャンネルの analytics スナップショットを起動時に最新化して一覧表示するローカル Web UI。Python HTTP server が registry、全チャンネルの直列収集、read model/API/build asset 配信を担い、`dashboard/` の React + Vite + shadcn/ui 表示層は同一 origin の API だけを読む。SSOT は各チャンネルの `data/analytics_data_*.json`（将来は local store）。channel registry で対象チャンネルを解決し、失敗はチャンネル単位の部分エラーとして隔離する。

**データ 4 分類**: SSOT を、① git 管理 JSON の宣言的インテント、② local store のランタイム状態・履歴、③ SSOT を持たない再生成可能な生成成果物、④ YouTube のリモート実状態、に分類するもの。④のローカルデータは reconcile 対象のミラーである。

**local store**: チャンネルごとの `<CHANNEL_DIR>/data/local.db` に置く libSQL (Turso) embedded DB。時系列データと collection 状態を保持し、チャンネル設定の SSOT ではない。

**read model**: local store が提供する読み取り専用のクエリ面。① と ④ のミラーを読むが、SSOT はそれぞれ git と YouTube のままである。

## 自リポジトリ

- `src/youtube_automation/configuration/` — 設定 loader / dataclass owner
- `src/youtube_automation/utils/` — コアライブラリ（API クライアント、analytics、upload）
- `src/youtube_automation/commands/` — `yt-*` CLI の thin adapter。`analytics` / `channel` / `collections` / `distrokid` / `media` / `metadata` / `suno` / `system` / `thumbnail` / `uploads` / `youtube` の 11 domain に分割し、argparse・stdio・exit・composition を所有する。アップロード CLI（Auto / Collection / Shorts）は `commands/uploads/` が入口で、実装は `domains/uploads/` が持つ
- `src/youtube_automation/entrypoints.py` — console script wrapper。`pyproject.toml [project.scripts]` の全 `yt-*` がここを経由し、**例外なく** `commands/` 配下の module を `import_module` して `main` を呼ぶ
- `src/youtube_automation/templates/` — 説明文テンプレート
- `.claude/skills/` — 自動化スキル群（Claude Code / Codex 共用）。wheel に `_skills/` として `force-include` され、`yt-skills sync` で各チャンネルへ展開される
- `.claude/CLAUDE.template.md` — BGM チャンネル運営方針テンプレ（共通骨格）。wheel に `_claude_md/CLAUDE.template.md` として `force-include` され、`yt-skills sync --asset claude-md` で各チャンネルの `.claude/CLAUDE.md` として展開される
- `.agents/skills` — `.claude/skills` への symlink。Codex CLI 用の探索パス（Codex 規約 `$REPO_ROOT/.agents/skills`）
- `AGENTS.md` — Codex CLI 向けエージェント指示。CLAUDE.md と並立し、Codex 視点のドキュメント補足を含む

## 下流チャンネルリポジトリ（`CHANNEL_DIR` が指す先）

```
config/channel/         # 責務別分割設定（v2.0.0 以降）
  meta.json             # channel / youtube_channel
  content.json          # genre / tags / descriptions / title
  youtube.json          # youtube / music_engine / content_model
  analytics.json        # analytics / benchmark
  playlists.json        # playlists
  workflow.json         # wf_next / post-publish / scheduled_automation の optional workflow 設定
  audio.json            # audio
  shorts.json           # shorts (optional)
  comments.json         # comments (optional)
  pinned-comment.json   # pinned_comment (optional)
  distrokid.json        # distrokid (optional)
  community-draft.json  # community_draft (optional)
config/localizations.json
auth/{client_secrets,token}.json  # + 任意の token.readonly.json（read-only 系用。docs/oauth-scopes.md）
.claude/skills/         # yt-skills sync で展開
.agents/skills          # → ../.claude/skills の symlink。skills sync が併設（Codex 探索パス）
collections/            # コンテンツ成果物
assets/stock/           # ボツ画像ストック (#364)。<theme-slug>/ 配下に画像 + .meta.json
```

## 主要モジュール

| モジュール | 責務 |
|---|---|
| `configuration` | `config/channel/*.json` の glob ロード／バリデーション。`load_config()` / `channel_dir()` / `reset()` / `ChannelConfig` を export |
| `configuration.{meta,content,youtube,analytics,playlists,workflow,shorts,audio,localizations,comments,pinned_comment,distrokid,community_draft}` | 責務別 dataclass |
| `infrastructure.google.youtube` | YouTube API clients（instance-scoped） |
| `domains.uploads.youtube` | 再開可能アップロード・サムネイル圧縮の共通コア |
| `infrastructure.errors` | ドメイン例外（`AutomationError` 基底、`ConfigError` / `YouTubeAPIError` / `ValidationError` / `UploadError`） |
| `utils.collection_paths` | コレクションディレクトリ構造の解決 |
| `domains.suno` | Suno 設定、歌詞、プロンプト、プレイリスト、選曲の生成・検証 |
| `domains.suno.downloaded` | downloaded payload、workflow、検証、archive、apply transaction |
| `domains.metadata` | `service` の状態付き orchestration と titles / descriptions / tags / localizations leaf |
| `domains.analytics` | Analytics の Protocol、収集、分析、レポート、時系列 policy。SDK/client は adapter 境界で解決 |
| `domains.thumbnail` | サムネ特徴量、相関、参照、archive、選択 policy（Pillow） |
| `domains.media` | 音声、字幕、画像、動画の provider-neutral model / policy |
| `domains.distrokid` | DistroKid naming、metadata、specification、preparation、release policy |
| `domains.collections.weekly_vote_log` | 週次投票ログ reader、initializer、schema、保存・検証 |
| `utils.image_provider` | 画像生成プロバイダー抽象化（Gemini / OpenAI 切り替え） |
| `utils.stock` | ボツ画像ストック化（`assets/stock/<theme>/` への退避・列挙・整理、隣接 `.meta.json` 管理） |
| `infrastructure.auth.youtube` | OAuth 2.0 トークン管理 |
| `infrastructure.secrets` | シークレット解決（`_SECRET_REFS` で参照定義） |
| `utils.live_chat.{codex,filters,history,models,runner}` | active broadcast のチャット取得、Codex 構造化判定、入出力フィルタ、PT 日次・時間・連続 user 上限、重複防止履歴、返信投稿 loop |
| `scripts.live_chat_reply` | `yt-live-chat-reply` 常駐 CLI。`comments.live_chat.enabled` を opt-in とし、VPS では独立した `live-chat-reply.service` から起動 |
| `cli.skills_sync` | `yt-skills` 本体 |
| `scripts.collection_serve_discovery` | 固定 loopback endpoint の稼働 server registry、heartbeat、TTL、owner takeover |
| `extensions/shared/server-discovery.ts` | registry schema v1 の検証と `/server-info` probe を両 helper 拡張へ提供 |
| `extensions/shared/server-source-migration.ts` | 廃止した配信元候補履歴 storage key の共通 migration |

### dashboard architecture

`yt-dashboard` は channel registry、起動時の収集、read model、JSON API、loopback 限定配信を担当する。通常起動では `yt-dashboard` が全チャンネルを更新し、1 チャンネルの更新失敗は部分エラーとして隔離する。`dashboard/` の React + Vite frontend は shadcn/ui を使った JSON API の表示だけを担当し、dashboard 限定の TypeScript 例外として `extensions/shared-ui` を直接 import しない。

### B2 domain ownership receipt / B3 handoff

B3 の owner と後続 handoff は機械可読な
[`b3-owner-receipt.json`](architecture/b3-owner-receipt.json) に固定する。domain は
SDK・ADC・network・subprocess の実装を持たず、それらは B4 の adapter 境界へ渡す。

Issue #2305 で Suno の旧 `utils.suno_*` 14 module と `utils.metadata_generator` を削除し、実行 consumer と patch seam を新 owner へ移行した。`domains.metadata.__all__` は次の9 symbolに固定する。

`BAHMetadataGenerator`, `LOCALIZED_TITLE_PLACEHOLDERS`, `SceneTitleViolation`, `build_short_description`, `build_short_localizations`, `format_scene_title_violations`, `format_title_template`, `validate_localizations_title_templates`, `validate_scene_phrases`.

B3 が直接利用する leaf API は `domains.metadata.descriptions.build_short_description` / `domains.metadata.localizations.build_short_localizations` と、placeholder 検証の `domains.metadata.titles.format_title_template` / `domains.metadata.localizations.validate_localizations_title_templates`。既知 downstream の `wf_batch_runner.py` と `bulk_update_collection_localizations.py` は、旧 metadata import を `domains.metadata`（または owner leaf）へ置換する。

歴史監査資料の旧パス表記は監査時点の記録として保持し、active source / skill / docs では新 owner のみを参照する。

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
