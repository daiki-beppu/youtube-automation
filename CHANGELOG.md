# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

コメント自動返信機能を追加した。YouTube Data API v3 の `commentThreads.list` / `comments.insert`
を使い、`config/channel/comments.json` のルール・テンプレートに沿って自チャンネル動画の
コメントへ返信する。`dry-run` / `apply` 2 モードと `comment_reply_history.json` での
二重返信防止を備える。関連: #72

- `src/youtube_automation/utils/config/comments.py`: 新規 dataclass `Comments` / `CommentRule`（optional セクション）。`loader._build_comments` と `config_migrate.SECTION_MAP` に統合
- `src/youtube_automation/utils/comments/`: 新規パッケージ。`fetcher` / `rule_engine` / `template` / `history` / `replier` の 5 モジュール
- `src/youtube_automation/scripts/comment_reply.py`: CLI 本体
- `pyproject.toml`: `yt-comments-reply` entry point を登録
- `examples/channel_config.example/comments.json`: サンプル設定
- `.claude/skills/comments-reply/SKILL.md`: Claude Code スキル（`yt-skills sync` で downstream 配布）
- `tests/test_comments_*.py`: rule_engine / template / history / replier のユニットテスト、`test_config_loader.py` に comments セクション検証を追加

## [4.0.0] - 2026-04-23

### Added

`yt-generate-master` に `--loop N` / `--target-duration MIN` オプションを追加した。
Suno / Lyria のトラック数が少ないコレクションで raw master 尺が target に届かないケース向けに、
個別トラックを N 回または目標尺以上になる最小回数だけ繰り返して acrossfade 連結する。
`--loop` と `--target-duration` は排他指定。関連: #79

- `src/youtube_automation/scripts/generate_master.py`: `_resolve_loop_count` / `_sum_track_duration` を追加。`generate_master()` に `loops` / `target_duration_min` キーワード引数を追加し、入力ファイルリストを `files * effective_loops` で展開してから既存の `build_filter` / ffmpeg 経路に流す
- `tests/test_generate_master.py`: 新規。ループ回数解決・ファイル展開・CLI 排他性・値バリデーションを検証
- `.claude/skills/masterup/SKILL.md`: Quick Reference と Step 5 に `--loop` / `--target-duration` 例を追記し、`metadata_generator` のタイムスタンプは 1 ループ分のみである運用注意を明記

### Changed

`generate_videos.sh` のマスター音声入力を `.wav` 固定から DAW バウンス形式（`.m4a` / `.aac` / `.mp3` / `.flac`）へ拡張した。
Logic / Ableton 等で書き出した `master-mix.m4a` をそのまま動画化できるようになり、手動の `.m4a` → `.wav` 変換が不要。
関連: #76

- `scripts/generate_videos.sh`: `master-mix.{wav,m4a,aac,mp3,flac}` を優先順に検出。`m4a` / `aac` は `-c:a copy` で再エンコード回避、それ以外は従来どおり `aac_at` / `aac` で再エンコード
- `youtube_automation.utils.audio_formats`: 新規共通モジュール。`AUDIO_EXTS` を `metadata_generator` と `video_validator` で共有
- `youtube_automation.utils.video_validator`: 個別楽曲カウントを `*.wav` 限定から `AUDIO_EXTS` 共通定数に統一
- `.claude/skills/videoup/SKILL.md`: `master-mix.{wav,m4a}` 受け入れの旨を反映

### Removed (BREAKING)

YouTube Shorts 関連機能を完全撤去した。今後 short チャンネルを運用しない方針に伴う。
関連: #74

- **スキル**: `.claude/skills/short/` / `.claude/skills/short-thumbnail/` ディレクトリ一式
- **Python モジュール**: `youtube_automation.agents.short_uploader` / `youtube_automation.scripts.generate_short_loop`
- **CLI entry points**: `yt-generate-short-loop` / `yt-upload-short`
- **設定スキーマ**: `Workflow.post_upload` / `Workflow.short` フィールド、および `PostUpload` / `ShortSettings` dataclass
- **workflow-state.json**: `assets.short_thumbnail` / `shorts.count` / `shorts.videos` フィールド

YouTube Community Tab 投稿ドラフト生成機能を完全撤去した。下流チャンネルが毎日投稿化に伴い
コミュニティ投稿運用を停止する方針に伴う。関連: #75

- **Python モジュール**: `youtube_automation.scripts.community_draft` / `youtube_automation.scripts.post_upload_actions`
- **CLI entry points**: `yt-community-draft` / `yt-post-upload`
- **スキル参照**: `.claude/skills/wf-next/references/community_draft.py` / `post_upload_actions.py`（symlink）
- **スキル記述**: `wf-next/SKILL.md` の community-draft ステップ、`wf-new/references/schema.md` の `community` フィールド定義、`ideate/SKILL.md` と `ideate/references/object-design-examples.md` の「コミュニティ投稿での展開 / 活用」セクション、`channel-setup/references/config-generation-rules.md` の `post_upload` オプション行
- **workflow-state.json**: `community.drafted` / `community.posted` フィールド（init_collection の生成から削除）

### Migration

downstream チャンネルリポジトリでの対応手順:

1. automation を本バージョンに pin-bump 後 `uv sync` を実行
2. `.claude/skills/short*` / コミュニティ関連スキル参照は `uv run yt-skills sync --force` で自動的に除去される
3. `config/channel/workflow.json` の `post_upload` / `short` / `community` キーは**削除しなくても loader は素通しする**ため任意。整理したい場合は手動削除
4. 既存コレクションの `10-assets/short.png` / `short.jpg`、`01-master/shorts/` / `01-master/short-*.mp4` は必要に応じて `git rm`
5. `workflow-state.json` の `assets.short_thumbnail` / `shorts.*` / `community.drafted` / `community.posted` フィールドは未使用となる（読み取りもされない）

**注意**: `ChannelMeta.channel_short`（チャンネル短縮コード、例: `"VC"` / `"TC"`）は短尺動画と無関係なので残存する。

### Fixed

`yt-upload-collection` 実行時に `collection_uploader.py` の import パス誤り（`from playlist_manager import PlaylistManager`）で
プレイリスト自動追加が全コレクションで常時失敗していた問題を修正。`except Exception` で握り潰されていたため
warning ログのみで気付かれず、v3.2.0 以降の全アップロードでプレイリストに一切追加されない状態になっていた。
関連: #77

- `src/youtube_automation/agents/collection_uploader.py`: `PlaylistManager` の import を正しいパス（`youtube_automation.scripts.playlist_manager`）に修正し、モジュール先頭へ移動。`_assign_to_playlists()` の `except` を `(ConfigError, YouTubeAPIError, HttpError)` に限定し、モジュール欠落などの実装バグは早期検知できるよう変更
- `tests/test_collection_uploader.py`: 回帰テストを新設（import smoke test + `_assign_to_playlists` のプレイリスト API 呼び出し検証）

`PlaylistManager.assign_video` / `resolve_playlists` の activity 解決を堅牢化。
`Title.activity_for_theme` が dict 挿入順の substring 先勝ちで短いキーに hit してしまい、
`campus-cafe` のような長いキーが常に `cafe` に吸収されて dead code 化する問題を修正。
あわせて `content.json` 未登録の新テーマでも `workflow-state.json` の
`planning.activities` を明示 override として利用可能にし、`late-night` 等の
`auto_add_activities` ルールへ確実にアサインできるようにした。関連: #80

- `src/youtube_automation/utils/config/content.py`: `Title.activity_for_theme` を完全一致優先 → longest substring match → `default_activity` の順に変更（`theme_scenes` / `theme_activities` 両系で対称）
- `src/youtube_automation/scripts/playlist_manager.py`: `resolve_playlists` に `activity` override 引数、`assign_video` に `collection_path` 引数を追加。`_planning_activities` ヘルパーで `workflow-state.json` の `planning.activities` を読み取り、あれば activity 解決の先頭に差し込む
- `src/youtube_automation/agents/collection_uploader.py`: `_assign_to_playlists` が `collection_path` を `assign_video` に転送
- `tests/test_config_loader.py` / `tests/test_playlist_manager.py` / `tests/test_collection_uploader.py`: exact-match / longest-match 優先、`activity` override、`collection_path` の各経路に対する回帰テストを追加・更新

## [2.0.0] - 2026-04-21

`channel_config` を責務別分割する **破壊的リリース**。Epic #28 / #29 / #30 / #31 / #32 を一括で解決。

### Migration

このリリースは downstream のチャンネルリポジトリに手動移行が必要。詳細手順は
[docs/migration/v2-config-split.md](docs/migration/v2-config-split.md) を参照。

サマリ:

```bash
# automation v2.0.0 に pin-bump 済のチャンネルリポジトリで:
uv run yt-config-migrate diff                    # 分割結果を確認
uv run yt-config-migrate migrate --apply         # config/channel/*.json に分割
uv run yt-config-migrate verify                  # 新 loader で読めるか検証
```

### Added

- **`utils.config` パッケージ** — 責務別に分割された設定ローダー・dataclass 群。
  - `youtube_automation.utils.config.load_config()`: シングルトン取得（旧 `ChannelConfig.load()` 相当）
  - `youtube_automation.utils.config.channel_dir()`: チャンネルディレクトリ path 解決のみ
  - `youtube_automation.utils.config.reset()`: シングルトン state リセット（テスト用）
  - サブモジュール: `meta` / `content` / `youtube` / `analytics` / `playlists` / `workflow` / `audio` / `localizations`
- **`yt-config-migrate` CLI** — 旧 `config/channel_config.json` を新 `config/channel/*.json` 構造に分割する移行ツール。
  - `migrate` (default: dry-run、`--apply` で実書き込み、`--backup`/`--no-backup`、`--delete-source`、`--strict`)
  - `verify` — 分割後を新 loader で読み込み検証
  - `diff` — 分割マッピングを表形式で表示、未マップキー検出
- **`docs/migration/v2-config-split.md`** — ダウンストリーム 5 ステップ移行ガイド。
- **`examples/channel_config.example/`** — 新構造のサンプル（7 ファイル）。

### Changed

- **設定ファイル構造（BREAKING）** — `config/channel_config.json` 単一ファイルを `config/channel/*.json` 7 ファイルに分割。
  新 loader は旧 `channel_config.json` を検出すると `ConfigError` を投げる。
- **設定アクセス API（BREAKING）** — `ChannelConfig.load().channel_name` のようなフラット属性から、責務別ネームスペース
  `load_config().meta.channel_name` などへ変更。下記「属性マッピング早見表」を参照。
- **`ChannelConfig`** — シングルトンクラスから frozen dataclass へ変更。`load()` / `reset()` / `channel_dir()`
  クラスメソッドは `utils.config` のモジュール関数に移動。
- **`localizations.json`** — 旧 `channel_config.json` の `localization`（単数形）トップレベルキーは
  `yt-config-migrate` が `config/localizations.json`（複数形）へマージする。ファイル名は複数形で固定。

### Removed

- **`src/youtube_automation/utils/channel_config.py`** — 旧モノリシック `ChannelConfig` クラス（395 行）。
- **`tests/test_channel_config.py`** — 旧 API 専用テスト。`tests/test_config_loader.py` に代替実装済。
- **`examples/channel_config.example.json`** — 旧 example。`examples/channel_config.example/` に置換。

### 属性マッピング早見表

旧 `ChannelConfig.load()` 時代のフラット属性を新 API でどう参照するかの対応表。

| 旧 (`config.X`) | 新 (`load_config().X`) |
|---|---|
| `config.channel_name` | `config.meta.channel_name` |
| `config.channel_short` | `config.meta.channel_short` |
| `config.youtube_handle` | `config.meta.youtube_handle` |
| `config.channel_url` | `config.meta.channel_url` |
| `config.core_message` | `config.meta.core_message` |
| `config.cta_subscribe` | `config.meta.cta_subscribe` |
| `config.tagline` | `config.meta.tagline` |
| `config.youtube_channel` (dict) | `config.meta.branding` (dataclass, `as_api_dict()` で旧形式取得) |
| `config.genre` (dict) | `config.content.genre.primary` / `.style` / `.context` |
| `config.tags` (dict) | `config.content.tags.base` / `.themes` / `.channel_specific` |
| `config.default_tags` | `config.content.tags.default()` |
| `config.get_tags_for_collection(name)` | `config.content.tags.for_collection(name)` |
| `config.descriptions` (dict) | `config.content.descriptions.opening` / `.perfect_for` / `.hashtags` / `.metadata` |
| `config.title` (dict) | `config.content.title.template` / `.default_activity` / `.theme_scenes` / `.theme_activities` |
| `config.get_activity_for_theme(t)` | `config.content.title.activity_for_theme(t)` |
| `config.category_id` | `config.youtube.api.category_id` |
| `config.privacy_status` | `config.youtube.api.privacy_status` |
| `config.language` | `config.youtube.api.language` |
| `config.content_model` (dict) | `config.youtube.content_model.type` / `.languages` |
| `config.music_engine` | `config.youtube.music_engine` |
| `config.analytics` (dict) | `config.analytics.collection_filter_keywords` |
| `config.benchmark_channels` | `config.analytics.benchmark.channels` |
| `config.playlists` (dict) | `config.playlists.items` (dict) |
| `config.post_upload` (dict) | `config.workflow.post_upload.short_publish_time` |
| `config.short` (dict) | `config.workflow.short.raw` (dict) |
| `config.audio` (dict) | `config.audio.target_duration_min` |
| `config.localizations` (dict) | `config.localizations.data` (+ `.exists` / `.supported_languages` / `.default_language`) |

### ファイル分割早見表

旧 `channel_config.json` のトップレベルキーが新 `config/channel/*.json` のどのファイルに振り分けられるか。

| 旧トップレベルキー | 新ファイル |
|---|---|
| `channel`, `youtube_channel` | `config/channel/meta.json` |
| `genre`, `tags`, `descriptions`, `title` | `config/channel/content.json` |
| `youtube`, `music_engine`, `content_model` | `config/channel/youtube.json` |
| `analytics`, `benchmark` | `config/channel/analytics.json` |
| `playlists` | `config/channel/playlists.json` |
| `workflow`, `post_upload`, `short` | `config/channel/workflow.json` |
| `audio` | `config/channel/audio.json` |
| `localization`（単数） | `config/localizations.json`（複数）へマージ |

未マップキー（例: `suno` 等のチャンネル独自拡張）は `yt-config-migrate` が warning を出力し、
`--strict` 指定時は `ConfigError` で中止する。

[2.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v2.0.0
