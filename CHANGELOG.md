# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [5.2.0] - 2026-04-29

### Added

#### `yt-generate-master`: `--shuffle` / `--shuffle-seed` で MP3 連結順をランダム化する

`yt-generate-master` CLI に `--shuffle` フラグと `--shuffle-seed N` を追加した。`--shuffle`
指定時は `02-Individual-music/` 配下の MP3 リストをループ展開の前に 1 回だけランダム順に
並べ替えてから ffmpeg `acrossfade` で連結する。`--shuffle-seed N` で再現性のある順序
（同 seed → 同入力 → 同順序）を確保でき、seed 単独指定で `--shuffle` を暗黙有効化する。
seed 未指定時は `random.SystemRandom().randrange(2**32)` で確定 seed を引いて使用前に
stdout へ `[Shuffle] seed=<N>` を出力するため、ログを見れば常に再現できる。`--quiet`
指定時もシャッフル再現性ログは抑制しない。関連: #99

skill-config 側にも `audio.shuffle: true` / `audio.shuffle_seed: N` を追加した。CLI
フラグ未指定時のデフォルトとして読み取られる優先順位は CLI > skill-config > デフォルト。
`audio.shuffle: true` が明示要求で、`audio.shuffle_seed` 単独設定では shuffle を有効化
しない（skill-config は永続設定のため誤動作防止に明示要求とする / CLI の `--shuffle-seed`
単独指定で shuffle を暗黙有効化する挙動とは異なる）。`audio.shuffle_seed` が整数以外（文字列・
`bool` など）の場合は `ValidationError` でフェイルする（`bool` は `int` のサブクラスなので
明示除外）。

これにより Suno で同一プロンプトから生成した類似イントロ群がマスター後半で連続する
問題（typical: 1 collection × 26 tracks）を CLI フラグ一つで回避でき、SKILL.md 側で
案内していたランダムリネームの 2 段階ワークアラウンドが不要になる。`--loop` /
`--target-duration` と組み合わせると、シャッフル後の順序がループごとに同じ並びで N 回
繰り返される（ループごとに独立してシャッフルし直すわけではない）。

issue spec の `random.seed(N)` 表記に対し、コードベース既存規約
（`generate_music_dj.py` の `random.Random(seed)` インスタンス使用）に合わせて
`random.Random(effective_seed).shuffle(files)` を採用した。グローバル RNG 状態を
汚染せずテスト隔離を保つため。

- `src/youtube_automation/scripts/generate_master.py`: `argparse` に `--shuffle` /
  `--shuffle-seed` を追加。`generate_master()` に `shuffle` / `shuffle_seed`
  キーワード専用引数を追加し、ループ展開（`files * effective_loops`）の手前で
  `random.Random(effective_seed).shuffle(files)` を実行。再現性ログを quiet モード
  でも常に stdout へ出力。`main()` の skill-config 解決ブロックに
  `_SHUFFLE_KEY` / `_SHUFFLE_SEED_KEY` のフォールバック処理を追加
- `.claude/skills/masterup/config.default.yaml`: `shuffle` / `shuffle_seed` の
  コメント例を追記（同梱デフォルトでは未設定 = 既存挙動を維持し、
  チャンネル側で opt-in する設計）
- `.claude/skills/masterup/SKILL.md`: 設定表 / Quick Reference / Step 5 例に
  `--shuffle` / `--shuffle-seed` および skill-config キーを追記。シャッフルが
  ループ展開の前に 1 回だけ行われる挙動を明記
- `tests/test_generate_master.py`: `TestGenerateMasterShuffle` 9 ケース（決定論性 /
  seed ログ / quiet モード時もログ出力 / 自動 seed の SystemRandom 利用 /
  ループ展開前のシャッフル / 1 ファイル時の copy 経路 / shuffle=False で seed
  無視）、`TestCliShuffle` 5 ケース（CLI 引数解析・暗黙有効化・境界値）、
  `TestCliSkillConfigShuffle` 10 ケース（skill-config 解決・CLI 優先・seed
  フォールバック・型バリデーション）

#### `yt-generate-master`: skill-config の `audio.target_duration_min` をデフォルト目標尺として読み取る

`yt-generate-master` CLI で `--loop` / `--target-duration` のどちらも未指定の場合、
skill-config (`.claude/skills/masterup/config.default.yaml` または
チャンネル側の `config/skills/masterup.yaml`) の `audio.target_duration_min` を
`--target-duration MIN` 相当のデフォルト値として参照するようにした (#98)。

これによりチャンネル単位で「最低尺」をプロジェクト設定として宣言できるようになり、
`/masterup` スキル側で CLI フラグを補完するローカルワークアラウンド
(`yt-skills sync` で上書きされる脆弱な実装) を排除できる。

優先順位:

1. CLI `--loop N` 指定時はそれが最優先 (既存挙動)
2. CLI `--target-duration MIN` 指定時はそれを使用 (既存挙動)
3. 上記未指定時に `audio.target_duration_min` があればその値を採用
4. それも未設定なら従来どおり 1 ループで終了

- `src/youtube_automation/scripts/generate_master.py`: `main()` の引数解決部に
  skill-config フォールバックを追加。値が `< 1` のときは `ValidationError` で
  弾く（メッセージにソース `skill-config masterup.audio.target_duration_min`
  を明示）。`--loop` 指定時は skill-config 値を黙って無視する
- `.claude/skills/masterup/config.default.yaml`: `target_duration_min` の
  コメント例を追記（同梱デフォルトでは未設定 = 既存挙動を維持し、
  チャンネル側で opt-in する設計）
- `.claude/skills/masterup/SKILL.md`: 設定表 / Quick Reference に新キーを追記
- `tests/test_generate_master.py`: `TestCliSkillConfigTargetDuration` 5 ケース
  （CLI 未指定時の採用 / CLI 上書き優先 / `--loop` 指定時の skill-config 無視 /
  `< 1` バリデーション / キー欠落時の既存挙動保持）

### Fixed

#### 画像生成コストの skill ドキュメント表記を `cost_tracker.PRICING` ベースに揃える

`thumbnail` / `ideate` skill のドキュメント上の `$0.04` ハードコーディングを削除し、
`cost_tracker.PRICING` を single source of truth として参照する形に揃えた (#102)。
従来は `gemini-3.1-flash-image-preview` 等の現行モデル価格 (1K で $0.067〜) と乖離した
古い見積りが表示されていた。

- `.claude/skills/thumbnail/SKILL.md`: ttp_swap モードのコスト表記を
  `cost_tracker.PRICING` 参照に変更。例示値は `gemini-3.1-flash-image-preview`
  の 2K で `$0.101 〜 $0.303`（最大 3 回試行込み = 初回 + 最大 2 回リトライ）に更新
- `.claude/skills/ideate/SKILL.md`: Phase 4-2 の静的コスト見積りを
  `cost_tracker.estimate_cost` + `load_skill_config` + `image_generator.DEFAULT_MODEL`
  / `DEFAULT_IMAGE_SIZE` を使う動的算出ワンライナーに置換。`cost_per_image_usd`
  カスタム単価優先 (`if per is None:` 判定で `generate_image.py:90-94` と整合)
- `.claude/skills/thumbnail/config.default.yaml`: `cost_per_image_usd: 0.04` の
  数値例を削除し、「PRICING の値を上書きしたい場合のみ指定（用途例: エンタープライズ
  割引価格や予算上限値の固定）」に置換
- `tests/test_skill_cost_documentation.py`: 14 テスト追加。3 対象ファイルへの
  旧ハードコード不在検証 + `cost_tracker.PRICING` / `estimate_cost` /
  `load_skill_config` 参照の存在検証 + `.claude/skills/**/*.{md,yaml,yml}`
  横断走査リグレッションガード

## [5.1.1] - 2026-04-28

### Fixed

#### Reporting API: Reach レポートに切り替えて thumbnail impressions / CTR を実取得する

`ReportingAPIClient.select_report_type()` が選定する `_REPORT_TYPE_PRIORITIES` を
`channel_basic_*` から **Reach 系**（`channel_reach_basic_a1` /
`channel_reach_combined_a1`）に変更した。

問題: `channel_basic_a3` には views / engaged_views / card_impressions /
annotation_impressions しか含まれず、`video_thumbnail_impressions` /
`video_thumbnail_impressions_ctr` を **CSV カラムとして提供しない**
（[公式ドキュメント](https://developers.google.com/youtube/reporting/v1/reports/channel_reports)）。
そのため `--include-reporting` を実行しても全レポートで「impressions / ctr 列が
見つかりません」のパース警告が発生し、`per_video` / `per_day` が常に空になっていた。

修正:

- `_REPORT_TYPE_PRIORITIES`: `channel_reach_basic_a1` を 1 番目、
  `channel_reach_combined_a1` を 2 番目に変更
- `_CTR_COLUMNS`: 公式名 `video_thumbnail_impressions_ctr` を 1 番目に
  （旧版 `video_thumbnail_impressions_click_through_rate` は将来の version suffix
  揺れに備え互換のため残す）
- モジュール docstring・`select_report_type` docstring・エラーメッセージを
  Reach レポート前提の表現に更新
- ユニットテスト・フィクスチャ CSV を Reach レポートのスキーマに合わせて更新
  (`tests/fixtures/reporting_api/channel_basic_a2_sample.csv` →
  `channel_reach_basic_a1_sample.csv`)

**移行手順** (各チャンネルリポジトリ):

旧バージョンで作成された `channel_basic_a3` ジョブは無害な状態で残るが、新版起動時に
`channel_reach_basic_a1` の新規ジョブが自動作成される。最初のレポート生成までは
**最大 48 時間**（backfill で過去 30 日分）、以降は D+2 ラグで日次レポートが届く。

```bash
uv run yt-analytics --reporting-create-job   # 新ジョブ作成（冪等）
# 24-48h 待機
uv run yt-analytics --include-reporting --days 28
```

- `src/youtube_automation/utils/reporting_api.py`: `_REPORT_TYPE_PRIORITIES` /
  `_CTR_COLUMNS` / docstring / エラーメッセージ更新
- `tests/test_reporting_api.py`: 期待 reportType を `channel_reach_basic_a1` 系に変更
- `tests/fixtures/reporting_api/channel_reach_basic_a1_sample.csv`: Reach レポート
  スキーマ（dimensions: date / channel_id / video_id, metrics:
  video_thumbnail_impressions / video_thumbnail_impressions_ctr）に合わせて更新

#### Reporting API: CTR 集計を impression 加重平均に変更

`_aggregate_rows` の CTR 計算を **単純平均** から **impression 加重平均** に変更
（`weighted_ctr = Σ(imp × ctr) / Σ(imp)`）。

旧実装は segment / 日 / video の CTR を単純平均していたため、`channel_reach_combined_a1`
にフォールバックして 1 (video, date) に traffic_source / country / device 等の複数
dimension 行が含まれた場合、impression が大きい segment が過小評価され統計的に
正しくない値になっていた（例: search 1000imp/CTR5% と suggest 500imp/CTR10% の真の
CTR は 6.67% だが、旧実装は 7.5% を返していた）。

`channel_reach_basic_a1` 単一行ケースでも `aggregated_ctr_percentage` の値が変わる
（impression が大きい video の重みが正しく反映される）。

- `src/youtube_automation/utils/reporting_api.py`: `_aggregate_rows` を加重平均化
- `tests/fixtures/reporting_api/channel_reach_combined_a1_sample.csv`: 新規追加
  （1 video × 1 date に複数 segment を持つサンプル）
- `tests/test_reporting_api.py`: `test_collect_impressions_summary_aggregates` を
  basic / combined の parametrize 化、加重平均の期待値で書き直し +
  `test_collect_impressions_summary_combined_uses_weighted_ctr` 追加

## [5.0.0] - 2026-04-26

### Changed (BREAKING)

#### OAuth スコープに `yt-analytics-monetary.readonly` を追加 (#84)

YouTube Reporting API v1 経由で thumbnail impressions / CTR を取得する基盤を導入する
ため、OAuth スコープに `https://www.googleapis.com/auth/yt-analytics-monetary.readonly`
を追加した。既存 `auth/token.json` のスコープ集合と一致しなくなるため、ダウンストリーム
チャンネルリポジトリでは再認証が必要。

**移行手順** (各チャンネルリポジトリで実行):

```bash
rm auth/token.json
uv run yt-analytics --days 7   # ブラウザで再認証フロー
```

ブラウザに表示されるスコープ一覧で `YouTube アナリティクスの収益データ` が含まれる
ことを確認し、許可する。

- `src/youtube_automation/auth/oauth_handler.py`: `SCOPES` に追加

#### 中国語コードを YouTube 公式 `zh-CN` / `zh-TW` に統一

中国語ローカライゼーションコードを `zh-Hans` / `zh-Hant` から YouTube Data API v3 公式の
`zh-CN` / `zh-TW` に統一した。`i18nLanguages.list()` が返す中国語の公式コードは
`zh-CN` / `zh-HK` / `zh-TW` のみで、`zh-Hans` / `zh-Hant` は含まれない。アップロード時に
YouTube 側で canonical へ強制正規化される挙動も観測されており、リポジトリ内のリテラル・
期待値・サンプル設定を canonical に揃える。関連: #82

- `src/youtube_automation/scripts/metadata_audit.py`: `audit_remote()` の zh-codes 期待値を `["zh-CN", "zh-TW"]` に変更、エラーメッセージも合わせる
- `src/youtube_automation/scripts/populate_scene_phrases.py`: `SCENE_PHRASES` 12 サンプルのキー `zh-Hans` / `zh-Hant` を `zh-CN` / `zh-TW` に rename
- `examples/localizations.example.json`: `supported_languages` および `languages.zh-Hans` ブロックを `zh-CN` に rename。`tests/fixtures/sample_channel/config/localizations.json` はこのファイルへの symlink のため自動同期
- `tests/test_metadata_generator.py`: フィクスチャ内のキー名を canonical に変更
- `tests/test_metadata_audit.py`: 新規。`audit_remote()` の zh-codes 判定について canonical / 旧キー / 片方欠落の 3 ケースを mock ベースで回帰防止

### Migration

downstream チャンネルリポジトリで `zh-Hans` / `zh-Hant` を `config/localizations.json` または
`collections/*/workflow-state.json` に含む場合、手動で書き換えが必要。詳細手順は
[docs/migration/v5-zh-codes.md](docs/migration/v5-zh-codes.md) を参照。

サマリ:

```bash
# 該当箇所の有無を確認
grep -rln '"zh-Hans"\|"zh-Hant"' config/ collections/
# ガイド記載の python ワンライナーで置換 → 検証
uv run yt-metadata-audit --local
```

過去アップロード済み動画の `videos.update` 書き換えは本リリースのスコープ外。
新キーで再アップロード時に YouTube 側が canonical で上書きする挙動を踏襲する想定。
明示的に CLI 化したい場合は別 issue で起票。

### Added

#### YouTube Reporting API v1 による thumbnail impressions / CTR 取得基盤 (#84)

YouTube Analytics API では `videoThumbnailImpressions` /
`videoThumbnailImpressionsClickThroughRate` がどの dimensions パターンでも 400 拒否され
自動収集できない（Google 公式 Looker Studio Connector でも同症状の未解決問題）。
代替として Reporting API v1（非同期 CSV bulk download）経由で取得する基盤を追加した。

- `src/youtube_automation/utils/reporting_api.py`: 新規 `ReportingAPIClient`。
  `reportTypes.list()` から `channel_basic_a3 > a2 > a1` の優先順で動的選定、
  `jobs.list()` で同名ジョブを再利用（冪等化）、`AuthorizedSession` で CSV ダウンロード、
  `per_video` / `per_day` / `aggregated` の 3 階層サマリに集計
- `src/youtube_automation/utils/reporting_analytics.py`: `ReportingAPIMixin` を新規追加し
  `YouTubeAnalyticsCollector` の Mixin 末尾に結線（fail-open 設計、取得失敗時も他 Mixin は継続）
- `src/youtube_automation/utils/youtube_service.py`: `ServiceRegistry.reporting` プロパティを追加
- `src/youtube_automation/scripts/analytics_system.py`: `--include-reporting` フラグを追加。
  ON 時に `data/analytics/reporting_api/<start>_to_<end>.json` へサマリを保存、
  さらに `analytics_data` トップレベルの `reporting_api.impressions_summary` キーにも格納。
  config 非依存のサブモードとして `--reporting-dry-run`（reportTypes / jobs 観察、副作用なし）と
  `--reporting-create-job`（ジョブのみ冪等作成）も追加
- `src/youtube_automation/utils/ctr_resolver.py`: 新規ヘルパー `resolve_ctr_summary`。
  `reporting_api.impressions_summary` → `ctr_analysis.impressions_summary` →
  `channel_ctr.average_ctr` の優先順で CTR を解決
- `src/youtube_automation/utils/analytics_analyzer.py`: 各 `_analyze_*` 系で
  per-video Reporting CTR を最優先参照、`generate_performance_report` の
  `channel_overview.average_ctr` も resolver 経由
- `src/youtube_automation/utils/report_generator.py`: `_generate_weekly_insights` で
  Reporting API 由来 per-video CTR / aggregated CTR を最優先表示
- `src/youtube_automation/utils/launch_curve_data.py`: `build_launch_curve_frame` に
  `reporting_snapshot` 引数を追加し `reporting_ctr_snapshot` /
  `reporting_impressions_snapshot` 列を broadcast。`load_latest_reporting_snapshot()` も追加
- `src/youtube_automation/utils/ctr_analytics.py`: 既知制約コメントに代替経路を追記
- `tests/test_reporting_api.py` / `tests/test_ctr_resolver.py`: 新規ユニットテスト 20 件
- `tests/fixtures/reporting_api/channel_basic_a2_sample.csv`: 新規 CSV fixture

**運用上の注意**:

- ジョブ作成後、**最大 48 時間**以内に最初のレポートが取得可能になる
  （初回取得時はジョブ作成日から **過去 30 日分**が backfill される）
- それ以降は日次で **D+2**（その日のデータは翌々日）にレポートが生成される
- API データ保持上限は現在から過去 **60 日**（それ以前のデータは取れない）
- `--include-reporting` は opt-in（既定 OFF）

#### コメント自動返信機能 (#72)

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

[5.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.0.0
[2.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v2.0.0
