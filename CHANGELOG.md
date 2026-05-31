# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `feat(doctor)`: `yt-doctor` の診断範囲を api/channel/data/upload のカテゴリ 4 段階に拡張した（#565）。`CheckResult` に `category` フィールドを追加し `render_table` でカテゴリ別に段階表示する。新 check として `channel_config`（config/channel/ ロード可能性）・`analytics_report`（reports/analysis_*.md 存在確認）・`benchmark_data`（docs/benchmarks/*.md 存在確認）・`upload_ready`（upload 必須 scope 充足・channel_id 紐付け）を追加し、api check 通過後に `/wf-new` 起動前提とアップロード可能性まで連続診断できるようにした。`onboard` SKILL.md を新カテゴリ Steps・ハイブリッド方針（analytics=案内/benchmark=ai-exec/scope=HUMAN STEP）・完了メッセージ（wf-new 起動 + アップロード可能）へ更新し、`channel-setup` SKILL.md の skip 条件を api カテゴリ限定へ整合した
- `feat(image_provider)`: gemini CLI 経由のサブスク認証で画像生成する新 provider `gemini_cli` を追加した（#474）。Google AI Pro/Ultra サブスクで認証済みの `gemini` CLI（`@google/gemini-cli`）を subprocess で非対話起動（`gemini --yolo -m <model> -p <prompt>`）し、出力パスをプロンプトに埋め込んで画像を書き出させる。GCP 従量課金（ADC 経由の既存 `gemini` provider）を発生させずに枚数の多いサムネ生成のコストを抑えられる。`image_generation.provider: gemini_cli` + `image_generation.gemini_cli.{model,image_size,timeout_seconds}` で設定。CLI 未導入時は `ConfigError`、生成後は出力ファイルの存在と PNG 妥当性を検証し指数バックオフでリトライする。既存 ADC 経由 `gemini` provider はそのまま温存（非破壊）。skill デフォルトの provider は `gemini` のまま（切り替えはスコープ外）
### Changed

- `fix(lyria)`: Lyria の Ctrl+C 中断で支払い済みオーディオ応答が失われる問題を修正した（#481）。Lyria は単一同期リクエストで billing が確定するため、`requests.post` の戻り後（課金確定後）に Ctrl+C を受けると支払い済み bytes を取りこぼしていた。`generate_music()` が response 受信後の `KeyboardInterrupt` を捕捉し、bytes を `<CHANNEL_DIR>/tmp/lyria-recovered/<sha1>.mp3`（内容ハッシュ命名・冪等）へ退避してから中断を再送出する。`requests.post` 処理中の中断は response 未受信のため救済不能として明示。呼び出し側 `generate_lyria_master.py` の WAV 保存（ffmpeg）中の中断も同じ退避経路（`persist_recovered_audio`）で救済する。退避ファイルは手動で WAV 化して `02-Individual-music/` に置けば再課金なしで再利用できる
### Fixed

- `fix(short-upload)`: `ShortUploader.upload_short` に resumable upload session URI 永続化を適用し、Shorts 投稿の中断→再実行時の video_id 重複（二重 publish）の余地を解消した（#466、CC 経路 #381 と同等）。これまで `upload_video` を `resume_session_uri=None` のまま呼んでいたが、`workflow-state.json` の `post_upload.shorts[].resume_session_uri` に session URI を読み書きするクロージャ（`on_session_uri_changed` / `on_upload_complete`）を配線。開始前に保存済み URI を読んで再開し、成功時はクリア、中断時は残して次回再開する。tracking 媒体は CC の `upload_tracking.json` ではなく Shorts 専用の `workflow-state.json`（既存 entry には key を増やさず書込み時のみ append する schema 互換）。再開不要な単発投稿は従来どおり `resume_session_uri=None` で挙動不変
### Changed

- `chore(config)`: `_build_playlists` の per-key 想定外型（list / int / null / float / bool 等）に対する `ConfigError` メッセージへ実際の型名（`got <type>`）を含め、トップレベル shape チェックと文言を揃えた（#419）。`Playlists.items: dict[str, dict]` 型注釈とランタイム挙動の乖離を Fail Fast で防ぐ既存ガードの actionable 化。list / null / float / bool での `ConfigError` 発生をパラメトライズドテストで担保
- `refactor(streaming)`: `utils/streaming/archive_counter.py` を `monthly_archive.py` にリネームし、日単位の `daily_archive.py` との命名対称性を取り戻した（#423、#156 の move only refactor 追従）。`cli/stream_bandwidth.py` の import とテスト（`test_stream_archive_counter.py` → `test_stream_monthly_archive.py`）を追従。公開関数 `count_archives` と `utils/streaming/__init__.py` の公開 API は不変、ロジック変更なし
### Added

- `feat(comments-reply)`: `CommentRule` に `scope: "top_level" | "reply" | "any"` を追加した（#524）。#365 で reply も返信対象に含まれるようになり keyword/pattern ルールが top-level / reply の区別なく当たっていたため、ルール単位でマッチ対象の階層を絞れるようにした。`rule_engine` が `FetchedComment.parent_id`（reply 判定）と scope を突合し、`top_level` は top-level のみ・`reply` は reply のみ・`any`（既定）は両方にマッチする。`scope` 未指定の既存ルールは `"any"` として #365 以前と等価のマッチ挙動を維持する。`config/channel/comments.json` の rules に任意指定でき、無効値は `ConfigError`。`examples/channel_config.example/comments.json` に指定例を追加
- `feat(yt-channel-settings)`: `push` に channel_id mismatch 時の safety check を追加した（#561）。`config/channel/meta.json` の `channel.channel_id` が設定済みの場合、`channels().list(mine=True).id` と照合し、不一致なら別チャンネルの OAuth トークンで設定を上書きする取り違え事故として `push` を refuse する（`channel_settings.verify_channel_id()`）。`channel_id` 未設定のチャンネルは後方互換でスキップしつつ、初回 push 時に取得した id を `meta.json` へ追記するよう警告する。`ChannelMeta` に `channel_id` フィールドを追加（任意キー）
- `feat(agents)`: `short_uploader` の `_check_upload_interval` / `_calculate_short_publish_at` が `workflow-state.json` / `upload_tracking.json` から読んだ datetime を TZ-naive と判定して backfill する直前に、どのファイル・どのフィールドが TZ-naive かを `logger.warning` で記録するようにした（#532）。#359 で書き込み側は TZ-aware ISO 8601 に統一済みのため、ここを踏むのは既存 live/ 配下のレガシーデータのみ。将来 backfill 補正自体を撤去するタイミングの判断材料（warning ゼロ観測）になる。2 箇所の backfill ロジックは共通ヘルパー `_backfill_naive_datetime()` に集約した
- `feat(agents)`: 永続化用 timestamp の TZ-naive 混入を書き込み時点で検出する防御コードを追加した（#533）。`utils/schedule.py` に `now_in_schedule_tz(schedule_config)`（schedule.timezone の現在時刻を TZ-aware datetime として返し生成を一点集約）と `ensure_tz_aware(dt, *, context)`（TZ-naive なら `ValidationError` を送出する防御ヘルパ）を追加し、`short_uploader._update_workflow_state`（`workflow-state.json::uploaded_at`）と `collection_uploader._completed_tracking_record`（`upload_tracking.json::upload_time`）/ `_update_workflow_upload`（`workflow-state.json::updated_at`）の書き込み点を `now_in_schedule_tz()` 経由に統一した。#359 で書き込み側を TZ-aware に統一した後の再リグレッションを、読み手側 backfill で吸収される前に書き込み時点で検知できる
### Fixed

- `fix(uploader)`: サムネ候補の優先順を `CollectionPaths.find_thumbnail()` に集約して統一した（#535）。従来 `find_thumbnail()`（`thumbnail.jpg > main.png > main.jpg`）と `_upload_complete_collection` のインライン候補（`thumbnail.jpg > thumbnail.png > main.jpg > main.png`）で順序が食い違っており、将来 `find_thumbnail()` へ統一する際に拾われる画像が変わるリスクがあった。実際にアップロードで使われていた後者の順を正とし、`find_thumbnail()` を `thumbnail.jpg > thumbnail.png > main.jpg > main.png`（`_THUMBNAIL_CANDIDATES`）に揃え、`_upload_complete_collection` は `find_thumbnail()` へ委譲。全候補組み合わせで統一前のアップロード経路と同一ファイルを指すことを回帰テストで担保（既存コレクションのサムネ選択は不変）
### Changed

- `fix(channel-settings)`: `yt-channel-settings push --apply` 直後の `diff` に旧 localizations が表示される問題を修正した（#564）。`fetch_channel()` が `channels.list(part="brandingSettings,localizations,status,snippet")` で一括取得していたが、`localizations` を他 part と同じ呼び出しに混ぜると YouTube Data API のキャッシュ層に当たり push 直後に旧版が返る。combined fetch は `brandingSettings,status,snippet` に絞り、`localizations` は単独 part で取り直してマージする二段 fetch に変更した（push 反映済みの新版が安定して返る）。`diff` / `push` / `pull` はいずれも `fetch_channel()` 経由のため自動的に最新化される
### Added

- `feat(yt-channel-settings)`: `keywords` の合計 500 文字制限を push 前に事前バリデーションするようにした（#563）。`build_update_body` で `_keywords_to_api()` の結果長を検証し、500 文字を超える場合は `channels().update()` の汎用的な 400（`Request contains an invalid argument.`）を待たずに `YouTubeAPIError` で停止する。エラーメッセージに現在の文字数・超過分・長い順の短縮候補タグを含め、原因が keywords 長であることを即座に判別できるようにした
- `feat(video-upload)`: アップロード preflight に公開タイトルの TTP 鋳型準拠チェックを追加した（#602）。`preflight_checks.check_title_template_compliance()` が「鋳型逸脱（` | ` で LHS/RHS に分割でき RHS が `N Hours of ...` 系に一致）」「巻数表記（`Vol.` / `Vol N` / `Part N` / 末尾ローマ数字 / `#N`）」「既存 live タイトルとの RHS 完全重複」「核語彙欠落（任意）」を機械検出し、`youtube_auto_uploader._preflight_check` で違反時にアップロードを block する。soulful-grooves で発生した `Funky Spirit Vol.2 | 3 Hours of Soulful Retro Funk Grooves`（コレクション内部名の公開タイトル流用）を巻数表記 + RHS 重複で停止できる。鋳型語彙・パターン・セパレータは `content.json::title.template_check` から導出し、`title.template` に ` | ` を含まないチャンネルは自動スキップ（既定値はフォールバック、ハードコードなし）。既存 live タイトルは `collections/live/*/20-documentation/descriptions.md` の `## タイトル案` から収集する
### Changed

- `perf(scripts)`: `yt-generate-image` の attempt ループ（`--max-attempts N`）を `concurrent.futures.ThreadPoolExecutor` で並列化し、複数バリエーション生成の総実行時間を短縮した（#584）。出力パス（`-vN`）と参照画像のローテーション割り当てをループ前に全 attempt ぶん確定（`plan_output_paths` / `plan_reference_assignments`）して `resolve_unique_path` の直列依存を排除し、逐次実行と同一の採番・参照割り当てを保つ。失敗（`ConfigError`）は future の例外として回収して `sys.exit(1)` をループ外に集約（1 件でも失敗ならプロセスを落とす従来挙動を維持）。並列度は CLI `--max-workers`（未指定時はレート制限を考慮した控えめな固定値 3）で制御し、`--max-attempts 1`（単発）の挙動・出力は従来どおり。`cost_tracker.log_generation` は既存の `fcntl.flock` でスレッド間も直列化されるためコスト記録の取りこぼし・重複は起きない
- `fix(metadata-generator)`: `title.template` / `localizations.json::title_template` に metadata_generator が提供しない未知プレースホルダ（例 `{adjective}`）が含まれていても、Complete Collection アップロード全体が `KeyError` でクラッシュしないようにした（#574）。(1) `descriptions.md` の `## タイトル案` が最終タイトルを供給する経路では `generate_complete_collection_metadata(title_override=...)` で本来捨てられる中間タイトル生成（`_generate_title`）をスキップし完走させる。(2) 中間タイトル生成や localizations タイトル整形では新ヘルパー `format_title_template()` を経由し、未知プレースホルダを opaque な `KeyError` ではなく「不正プレースホルダ名 + 許可キー一覧」を含む actionable な `ValidationError` に変換して fail-loud する。`youtube_auto_uploader._upload_complete_collection()` は `descriptions.md` を先に読み込み `title_override` として渡す
- `fix(benchmark)`: ベンチマーク未取得・空・取得失敗時に空データ/デフォルト値（`[]` / `{}` / `avg_views=0`）のまま黙って完走する fallback を是正した（#619）。`load_benchmark_videos()` は JSON 未検出 / フィルタ後 0 件で `ConfigError`、`collect_channel()` はチャンネル欠落で `YouTubeAPIError`・API 失敗（`HttpError`）を `YouTubeAPIError.from_http_error` でドメイン例外化、`collect_all()` は欠落チャンネルを `if data:` で暗黙スキップせず明示検知して `YouTubeAPIError`、`ensure_benchmark_fresh()` は取得失敗・`benchmark.channels` 未設定で黙って `return` せずドメイン例外で通知する。いずれも原因と次アクション（`/benchmark` 再実行・設定確認）をメッセージに含め、下流（サムネ比較・分析）が無効データに基づいて成功扱いされる経路を塞ぐ
### Added

- `feat(comment-reply)`: `yt-comments-reply` にメインループ先頭で動く video status preflight を追加した（#576）。`commentThreads.list` の前に対象 video の `status` を `videos.list`（50 件単位で chunk 化）で一括取得し、API 応答に存在しない（削除済み）video は `plan.skipped` に `reason="video_not_found"`、`privacyStatus="private"` の video は `reason="video_private"` で積んで除外する。これまで apply 段階でしか出なかった 404 / 403 を dry-run プレビューで事前可視化し、無駄な `comments.insert` の quota 消費を避ける。unlisted はオーナーがコメント可能なため通過、quota 節約のため history に返信実績がある video は status check 対象外。dry-run / apply 共通で動作（`utils/comments/replier.py::fetch_video_status` / `_preflight_video_status`、`ReplyHistory.replied_video_ids`）

### Changed

- `refactor(video-upload)`: 動画アップロード時の AI 開示フラグ `status.containsSyntheticMedia` と子供向け申告 `status.selfDeclaredMadeForKids` を `youtube_auto_uploader.py` のハードコードから config 解決へ外出しした（#605、audit R-5）。`config/channel/youtube.json` の `youtube.contains_synthetic_media` / `youtube.self_declared_made_for_kids` で上書きでき、`YoutubeApi` dataclass の任意フィールド（デフォルト `True` / `False`）として `channel_settings.build_upload_status_flags()` 経由で解決する。未設定時は現行の振る舞い（`containsSyntheticMedia: True` / `selfDeclaredMadeForKids: False`）を維持するため挙動は不変。YouTube 側ポリシー変更や下流チャンネルごとの開示要否差異への追従が容易になる

## [5.5.6] - 2026-05-31

### Added

- `feat(scripts)`: 公開済み動画の `status.containsSyntheticMedia` を遡及的に `True` へ一括是正する `yt-bulk-update-synthetic-media` を追加した（#606、#603 の遡及対応）。#603 是正前にアップロードされた公開動画は `False` のまま残るため、チャンネルの uploads playlist から全公開動画を列挙し、`videos().list(part="status")` で現状 `True` でないものを抽出して `videos().update(part="status")` で反映する。`videos.update(part="status")` は status リソース全体を置換するため、現 status をコピーして read-only キー（`uploadStatus` / `madeForKids` 等）を除去し `containsSyntheticMedia` だけ差し替える read-modify-write で `privacyStatus` / `publishAt` / `selfDeclaredMadeForKids` 等を保持する。デフォルト dry-run（read のみ）、`--apply` で実反映、`--include-private` で private も対象化。冪等（再実行で対象 0 件なら遡及完了）。手動 fallback 手順は `docs/investigations/2026-05-30-606-bulk-update-synthetic-media.md`
- `feat(skills-sync)`: `yt-skills sync`（`skills` asset）を標準レイアウト（`.claude/skills`）へ展開すると、下流チャンネルリポジトリにも `.agents/skills -> ../.claude/skills` の相対 symlink を併設するようにした（#617）。upstream リポと同じ Codex CLI 探索パス規約（`$REPO_ROOT/.agents/skills`）を下流でも成立させ、これまで `.claude/skills` だけが配布され下流の Codex が同期済みスキルを発見できなかった問題を解消する。既存の正しい symlink は冪等にスキップ、張り直しは `--force`、`--dry-run` では作成予定のみ表示、symlink 非対応環境では警告のみで sync 全体は継続する。`--target` で非標準パスを指定した場合は `.agents` 規約が成立しないため対象外（`_ops.py::_ensure_agents_skills_symlink`）

### Changed

- `fix(video-upload)`: 動画アップロード時の `status.containsSyntheticMedia` を `False` 固定から `True` に是正した（#603）。本ツールは AI 生成音楽（Lyria / Suno）を主軸とするため、YouTube の AI 開示（altered or synthetic content）ポリシー上 `true` の申告が正しい。`YouTubeAutoUploader.upload_video()` を経由する全アップロード経路（Auto / Short / Collection は同メソッドへ委譲）に反映され、`.claude/skills/video-upload/SKILL.md` の記載（`true`）とも整合する。値の config 外出し（#605）と公開済み動画への遡及対応（#606）は別 issue
- `refactor(metadata_generator)`: 散在していた `workflow-state.json` のパス解決リテラル（8 箇所の `self.collection_path / "workflow-state.json"`）を `CollectionPaths(self.collection_path).workflow_state_path` 経由に統一した（#534）。ディレクトリ命名規約の単一ソース化を `utils/` 側にも広げた。挙動・公開シグネチャは不変
- `fix(veo)`: `smooth_loop()` の ffmpeg 失敗（`CalledProcessError`）経路で tmp ファイル `_smooth.mp4` が残骸化する問題を修正した（#480）。ffmpeg 実行を `try/finally` で囲み `output.unlink(missing_ok=True)` で確実に削除する（成功時は `rename` 済みのため no-op）
- `refactor(scripts)`: `metadata_audit` / `playlist_manager` に残っていたコレクションサブパスリテラル（`20-documentation` / `descriptions.md` / `workflow-state.json` / `upload_tracking.json`）を `CollectionPaths` のプロパティ（`docs_dir` / `descriptions_md_path` / `workflow_state_path` / `tracking_path`）経由に統一した（#536）。挙動は不変

### Migration

所要時間の目安: 5〜10 分（pin bump → `uv lock` → `yt-skills sync`）。公開済み動画の遡及是正（任意・後述）を含める場合は対象動画数に応じて +数分

local fix 衝突注意:

- 無し（今回のリリースで `.claude/skills/<name>/` 配下の挙動変更は無し。`metadata-audit/SKILL.md` は Cross References へ `yt-bulk-update-synthetic-media` の参照を 1 行追加したのみで、`yt-skills sync --force` で上書きされても下流の挙動に影響しない）

サマリ:

- 新規 CLI `yt-bulk-update-synthetic-media` を追加（#606）。#603 是正前にアップロードされた公開動画の `status.containsSyntheticMedia` を `True` へ遡及的に一括是正する。デフォルト dry-run、`--apply` で実反映、`--include-private` で private も対象化、冪等（対象 0 件で遡及完了）。手動 fallback は `docs/investigations/2026-05-30-606-bulk-update-synthetic-media.md`
- `yt-skills sync`（`skills` asset）が下流に `.agents/skills -> ../.claude/skills` の相対 symlink を併設するようになった（#617）。sync 再実行で自動成立し、下流の Codex CLI が同期済みスキルを発見できるようになる。`--force` で張り直し、symlink 非対応環境は警告のみで継続
- 動画アップロード時の `status.containsSyntheticMedia` を `False` → `True` に是正（#603）。AI 生成音楽（Lyria / Suno）主軸のため YouTube の AI 開示ポリシー上 `true` が正しい。今後のアップロードに自動適用され下流の手動対応は不要。既存の公開済み動画は上記 `yt-bulk-update-synthetic-media` で遡及是正する
- `fix(veo)`: `smooth_loop()` の ffmpeg 失敗時に tmp ファイル `_smooth.mp4` が残骸化する問題を修正（#480）。`workflow-state.json` / コレクションサブパスのパス解決を `CollectionPaths` 経由へ集約（#534, #536、挙動不変）

## [5.5.5] - 2026-05-30

### Added

- `feat(suno)`: サムネのキャラ性別と歌詞の語り手 gender・`genre_line` のボーカル性別を一致させる gender 整合ルールを追加した（#591）。`lyrics_guidelines.vocal_gender`（`male` / `female` / `neutral` / `auto`、既定 `""` は従来通り AI がサムネを見て判断）を新設し、SKILL.md のボーカルモード歌詞設計に「8. gender 整合（サムネ連動）」を明文化。サムネと歌唱の性別不一致による没入崩れ・AI 生成バレを防ぐ。ドキュメント / 設定のみで `generate_suno_prompts.py` は改修不要
- `feat(suno)`: 英語歌詞のネイティブ感を高めるため、`lyrics_guidelines.style_reference` と `lyrics_generation.provider` を追加した（#586）。参考歌詞は文体・行長・loose rhyme・mantra 的 Chorus の抽出に限定し、本文のコピーは禁止する。`lyrics_generation.provider: codex` では `.claude/skills/suno/references/codex-lyrics.sh` から ChatGPT ログイン済み Codex CLI に初稿生成を委譲でき、ChatGPT / OpenAI API の直接統合は行わない
- `feat(pinned-comment)`: 固定コメント（オーナーコメント）自動投稿の `yt-pinned-comment` CLI と `pinned-comment` skill を upstream に同梱した（#575）。`commentThreads.insert` で自チャンネル動画にトップレベルコメントを投稿し、`comments-reply` と同じ dry-run / apply / history（`pinned_comment_history.json`）パターンで二重投稿を防止する。設定は config loader 統合で `config/channel/pinned-comment.json`（トップキー `pinned_comment`、`enabled` はオプトイン）を `config.pinned_comment` dataclass として読む。**preflight**: 投稿前に `videos.list(part="status")` を 50 件 chunk で一括し、削除済み動画 → `SKIP video_not_found` / `privacyStatus=="private"` → `SKIP video_private` を dry-run / apply 共に事前 skip（unlisted は通過）。history 未記録 video のみ status check して quota を節約する。video_id は `20-documentation/upload_tracking.json` の `complete_collection.video_id` → `workflow-state.json` の `upload.video_id` → トップレベル `video_id` の fallback chain で解決。ピン留めは Data API v3 非対応のため投稿後に Studio UI で手動
- `feat(loop-video)`: skill-config にトップレベル `enabled`（default: `true`）を追加し、channel 単位でループ動画化を停止可能にした（#577）。`config/skills/loop-video.yaml::enabled: false` のチャンネルでは `yt-generate-loop-video` を fail-loud で停止（`--smooth` / `--skip-existing` 含む全経路をブロック）し、取り消し不可な Veo 課金のうっかり実行を防ぐ。`comments-reply` / `pinned-comment` の `enabled` semantic と統一（`compression.enabled` の FFmpeg 圧縮 on/off とは別概念）。`videoup` skill の Step 3 は `enabled: false` のとき `/loop-video` を案内せず `10-assets/main.png` を静止背景にフォールバックする

### Changed

- `fix(video-upload)`: dedup 安全網が search index のヒットを無検証で採用していた問題を修正（#593）。`_find_existing_video_by_title` は exact-title 候補を `videos().list(part="status,snippet")` で再検証し、`uploadStatus` が `processed` / `uploaded` の実在動画のみ「既存」と判定する（削除済み orphan の false-positive スキップを防止）。dedup スキップ時も `collection_uploader` が `workflow-state.json` の `upload.video_id/url/publish_at` と `upload_tracking.json` を書き戻し、`stage:live` ⇔ `video_id:null` の不整合を解消。結果には `upload_source`（`new_upload` / `existing_video`）を持たせ、新規アップロードと既存流用スキップをログ・戻り値で区別する
- `feat(video-upload)`: アップロード preflight で `config.localizations.supported_languages` の高 CPM 必須言語 `ja` / `en` / `de` を検証し、欠落時はアップロード前に fail-loud で停止するようにした（#587）。低 CPM 言語 `ko` / `es` / `pt` / `zh-CN` が混在する場合は意図的な例外を許容するため警告ログに留める
- `feat(benchmark)`: channel-video 収集でも競合動画の `snippet.description` 全文を `description` として保存し、benchmark Markdown に概要欄 TTP サンプルを出力するようにした（#588）。`/video-description` skill は生成前に `docs/benchmarks/*.md` の概要欄サンプルまたは `data/benchmark_*.json` の `videos[].description` を参照し、冒頭文・目次/Tracklist 書式・CTA・ハッシュタグ記法・装飾量を転写対象にする。benchmark データがない場合のみ既存テンプレートへフォールバックする
- **破壊的変更**: `comments-reply` を LLM 生成専用に変更（#589）。`TemplateGenerator` / `comments.templates` / `comments.rules[].template_key` / `comments.rules[].generator` / `comments.generator.type` を廃止し、`comments.generator.provider`（`codex` / `gemini`、既定 `codex`）へ一本化。`fallback_on_error` は `skip` / `retry` のみ有効で、旧 `template` fallback は利用不可。downstream の `config/channel/comments.json` は `provider` 軸へ移行が必要
- `feat(videoup)`: 静止画 fallback 経路（`loop.mp4` 不在時）の master.mp4 生成 ffmpeg オプションを最適化（#579）。`generate_videos.sh` の静止画モードで全フレームを I-frame 化していた `-x264opts keyint=1:min-keyint=1` を廃止し `-g 300`（1fps で 5 分間隔）へ、`-preset ultrafast` → `-preset medium`、`-crf 23` → `-crf 28` に変更。変化のないフレームを P-frame で圧縮し容量を大幅削減する（rjn / 2h17m 公開実績 3.35GB に対し ~450-500MB の試算。実機ベンチは未取得で rjn 次回コレクション公開時に取得予定）。ループ動画背景モード（`-c:v copy` の stream copy 経路）は変更なし
- `chore(repo-audit)`: AGENTS.md / CLAUDE.md のドキュメント陳腐化を解消（#538, #539, #540）。`utils/`・`agents/`・`scripts/` のルート shim 記述を `auth/` のみへ修正、実体のないルート `scripts/` 配置ルールを AGENTS.md / CLAUDE.md 双方から削除して共通スクリプトは該当 skill の `references/` 配下に置く方針へ統一、「skill 編集は takt 経由で行わない」を「skill 編集と takt の関係」へ改題し `coder=codex` なら skill 配下も takt で回せる条件付き事実へ追従
- `refactor`: `video_validator` のビットレート判定の `except Exception: pass` を `(ValueError, TypeError, AttributeError)` に絞りスキップ意図をコメント化（#541）。`benchmark_collector` の実装済みページング処理に残った TODO コメントを削除（#542）
- `docs(community-draft)`: SKILL.md の `poll` type を deprecated 表記に統一し、現役 type の列挙から除去（#544）。config 側は後方互換受理のため維持

### Migration

所要時間の目安: 〜15 分（`comments.json` 移行 + `yt-skills sync`）

local fix 衝突注意:

- **`config/channel/comments.json`（#589 破壊的変更・対応必須）**: `comments.templates` / `comments.rules[].template_key` / `comments.rules[].generator` / `comments.generator.type` を廃止。`comments.generator.provider`（`codex` / `gemini`、既定 `codex`）へ手動移行が必要。`fallback_on_error` は `skip` / `retry` のみ有効で旧 `template` fallback は利用不可
- **`config/localizations.json`（#587）**: アップロード preflight が高 CPM 必須言語 `ja` / `en` / `de` を検証し、欠落時は fail-loud で停止する。`supported_languages` に 3 言語が揃っているか確認すること
- **`generate_videos.sh`（#579）**: 静止画 fallback 経路の ffmpeg オプションを変更。`videoup` skill のスクリプトを下流で local 改変している場合は `yt-skills sync` で上書きされるため diff 確認推奨

サマリ:

- **破壊的変更**: `comments-reply` を LLM 生成専用化（#589）。downstream の `comments.json` は `provider` 軸へ移行必須
- `feat(video-upload)`: dedup 安全網が削除済み動画を実在検証するよう修正 + preflight で高 CPM 言語 `ja`/`en`/`de` を fail-loud 検証（#593, #587）
- `feat(pinned-comment)`: 固定コメント自動投稿の `yt-pinned-comment` CLI / `pinned-comment` skill を同梱（#575）。`yt-skills sync` で取得、`config/channel/pinned-comment.json`（`enabled` オプトイン）で有効化
- `feat(loop-video)`: skill-config に `enabled`（既定 `true`）を追加しチャンネル単位でループ動画化を停止可能に（#577）
- `feat(suno)`: gender 整合ルール + 英語歌詞の `style_reference` / `lyrics_generation.provider`（codex 委譲）を追加（#591, #586）
- `feat(videoup)`: 静止画 fallback master.mp4 の ffmpeg 最適化で容量を大幅削減（#579）
- `feat(benchmark)`: channel-video 収集で競合概要欄全文を保存し `/video-description` の TTP サンプルに活用（#588）

## [5.5.4] - 2026-05-25

### Added

- `feat(image-provider)`: サムネ/画像生成の provider に `codex`（`codex-image.sh`・ChatGPT サブスク認証・GCP 課金なし）を正規 provider として追加（#568, root cause #567）。`image_provider/config.py` の `ProviderName` / `SUPPORTED_PROVIDERS` に `codex` を許容値として追加し、`_build_from_new_namespace` で `ImageGenerationConfig(provider="codex")` を構築可能に。`collection-ideate` Phase 4（コスト確認・生成）と `wf-new` Phase 2c がチャンネル config の `image_generation.provider` を見て分岐し、`codex` 指定時は `codex-image.sh`（位置引数 `<prompt> <output> [refs...]`）を呼ぶ。`thumbnail` skill は codex を従来の「補助生成」から「正規の生成経路」へ再ポジションし、コスト（GCP 課金なし・`cost_tracker` 非記録・ChatGPT サブスクの fair-use 対象）とリトライ（wrapper 自体の自動リトライなし・失敗時は prompt 短縮で手動再実行）を文書化。レイヤ逆転を避けるため `yt-generate-image` / `get_provider` の API 経路は `codex` を明示エラー（`ConfigError` / `sys.exit(1)`）で拒否し `codex-image.sh` 経路へ誘導する
- `yt-channel-seed` を追加し、`/channel-new` で参考チャンネル URL / handle を YouTube Data API で早期 fetch して `benchmark.channels` に初期反映できるようにした（#559）

## [5.5.3] - 2026-05-23

### Added

- workflow チートシート `docs/workflow-cheatsheet.md` を新設（#363）。`/wf-new` `/wf-next` `/wf-status` `/collection-ideate` の判定フローと `workflow-state.json` の扱い基準（OK / NG / 限定 OK の操作別表）を 1 枚にまとめ、初心者でも使い分けに迷わないようガイド化
- 全 skill カタログ `docs/features.md` を新設（#355）。`.claude/skills/` 配下 43 skill すべてをカテゴリ別テーブルで「なにができるか」1 行で列挙
- `yt-skills sync --asset workflow-cheatsheet` / `--asset features` を新設。`pyproject.toml::force-include` で wheel 内 `_docs/` に同梱し、配布される SKILL.md / CLAUDE.md の docs 相対 link が同 version で整合
- `.claude/skills/{wf-new,wf-next,wf-status}/SKILL.md` の冒頭に「When to Use」短表を追加（#363）。他 wf-* skill との使い分け境界を明示
- `.claude/CLAUDE.template.md` §6 に Claude への明示指示を追加（#363）。新セッションで workflow 起点の質問を受けたら `docs/workflow-cheatsheet.md` を 1 回だけ提示するよう運用化
- `feat(terraform)`: streaming VM の SSH host key 検証を追加（#164）。`null_resource.deploy.connection.host_key` を結線し、`tls_private_key` で生成した Ed25519 host key を cloud-init の `ssh_keys` で VM に固定配置。`hashicorp/tls` provider を `versions.tf` / `.terraform.lock.hcl` に追加
- `feat(loop-video)`: 末尾に CRF 圧縮ステップを追加し本編動画容量を約 40% 削減（#175）。Veo 3.1 由来の `loop.mp4` を libx264 CRF 22 / preset slow（既定）で再エンコード。`compression.{enabled,crf,preset}` を skill-config で上書き可能。`--smooth` 経路も同 crf/preset を継承して圧縮効果を維持。`generate_videos.sh` 側は stream copy 設計を維持
- high-CPM locale へ移行するための運用ガイド `docs/migration/high-cpm-locales.md` を追加（#272）
- `thumbnail` スキルに `codex exec` を直接 shell 実行する補助導線を追加（#501, #547）。`.claude/skills/thumbnail/references/codex-image.sh` が codex 0.131 系の `codex exec --json --sandbox workspace-write --add-dir <out_dir> --skip-git-repo-check` で起動し、prompt 末尾に `After generation, copy the produced PNG to <out>. Then reply with exactly <out>.` を自動付与することで agent 自身に生成 PNG を `<out>` まで `cp` させる。wrapper 側は JSONL の最終 `agent_message.text` を `jq` で解析し、起動前の stale 出力削除・`final_msg == <out>` の契約検証・`<out>` の存在・PNG ヘッダ・サイズで多段検証する。`SKILL.md` の `## codex 経由の補助生成` セクションから独立経路として案内
- `feat(comments-reply)`: 返信スレッド (replies) を走査対象に追加（#365）。`commentThreads.list(part="snippet,replies")` で 1 階層 reply まで取得し、`totalReplyCount > 5` の場合は `comments.list(parentId=...)` でページネーション補完。`fetch_top_level_comments` を `fetch_comments` にリネームし、`FetchedComment.parent_thread_id` を追加。自分の返信に対する視聴者の再返信や視聴者同士の返信にも反応できるようにする。`_resolve_owner_channel_id` / `_iter_uploaded_video_ids` を SRP で分離し、`authorChannelId` でオーナー自身のコメントを除外する `own_comment` skip 理由も追加
- `feat(comments-reply)`: LLM (Gemini) 駆動の返信生成バックエンドを追加（#366）。`utils/comments/generator.py` に `ReplyGenerator` 抽象基底、`TemplateGenerator`、`GeminiGenerator` を導入し、`comments.generator.type` で `template` / `gemini` を切り替え可能に。`comments.rules[].generator` で rule 単位の上書きにも対応。`fallback_on_error` で Gemini 失敗時のテンプレフォールバック / skip を選べる。`channel_persona` / `max_length` / `requests_per_minute` を `GeneratorConfig` に集約し、`utils/exceptions.py::GeneratorError` を新規ドメイン例外として追加

### Changed

- **破壊的変更**: `yt-skills sync` のデフォルトを `--asset all` に変更（#363, #355）。skills / claude-md / workflow-cheatsheet / features を 1 コマンドで一括配布。配布される SKILL.md / CLAUDE.md の docs 相対 link が link 切れになる問題を解消。skill 単独 sync は `--asset skills` を明示
- **破壊的変更**: `yt-skills sync --target X` を asset 未指定で叩くと `exit 2` で止まるように変更（#363, #355）。asset ごとに default_target が異なる all モードで silent に意図しない場所へ書き込まれる事故を防止。skills 単独で X に出すには `--asset skills --target X` のように asset を明示
- `_guard_target_with_all` を導入し、library 経路（`cmd_sync` / `cmd_diff` の直呼び）では `ValueError`、CLI 経路では `sys.exit(2)` という 2 段構成で経路別に振る舞いを分離
- `utils/daily_archive.py` を `utils/streaming_archive.py` に rename（#164）。`streaming_archive_check.py` の import を追従
- `feat(video-description)`: 概要欄タイムスタンプを **テーマ単位** から **テーマ見出し + 個別楽曲単位** に変更（#494）。`metadata_generator` に pattern_key 抽出と pattern 表示名解決を追加し、`format_timestamps_text()` がテーマ見出し + 楽曲行の構造化出力を返すように。`NN.` 番号付けは廃止。`\d+-pattern-[a-d]` 規約に従わない legacy コレクションはフラット出力で後方互換。テーマ見出し行は YouTube chapter parser の strictly-ascending 要件に合わせて先頭 timestamp を持たない形式
- `feat(video-description)`: 同名楽曲の自動リネーム機構（#494）。`detect_duplicate_track_titles()` で重複検出、`apply_track_display_names()` で LLM 命名結果を `workflow-state.json` の `track_display_names` に永続化。次回ロード時は `_apply_persisted_display_names()` で自動再適用
- `examples/localizations.example.json` と `channel-setup` の `localizations-template.json` を high-CPM tier の `ja` / `en` / `de` に更新し、low-CPM 言語 `ko` / `es` / `pt` / `zh-CN` を canonical テンプレから削除（#272）
- `thumbnail` スキルの TTP 運用を再点検し、`TTP プリフライト・チェックリスト` と `/thumbnail-compare` × `/alignment-check` の役割分担を追記（#493）
- `refactor(cli)`: `cli/skills_sync/_sync.py::_sync_dir_asset` で重複していた `_list_entries` 呼び出しを 1 回に統一（#369）
- `refactor(agents)`: `agents/short_uploader.py` / `agents/youtube_auto_uploader.py` / `scripts/generate_short_loop.py` / `scripts/bulk_update_short_localizations.py` を `utils/collection_paths.py` のヘルパー（`short_video_search_paths` 等）に集約し、ハードコードされた `01-master/shorts/short-NN-*.mp4` グロブ重複を撤去（#357）

### Deprecated

- `yt-fix-timestamps` (`scripts/fix_per_theme_timestamps.py`) を deprecation 注記付きで残置（#494）。新規コレクションは `metadata_generator.format_timestamps_text()` を使うこと

### Fixed

- `fix(comments-reply)`: コメント無効動画で `yt-comments-reply` の全動画走査が停止する問題を修正（#590）。`commentThreads.list` の 403 `commentsDisabled` は動画単位で `skipped(reason=comments_disabled)` に記録して次の動画へ継続し、quota/auth など他の API エラーは従来どおり伝播する。`--video-id` 明示指定時も同じ skip 挙動に統一
- `fix(videoup)`: `generate_videos.sh` の loop 背景モードで高ビットレート `loop.mp4` を `-c:v copy` して長尺 master.mp4 が肥大化する問題を修正（#592）。正規化済み判定に実測ビットレート上限（6Mbps）を追加し、超過時は `loop_normalized.mp4` を CRF22 / maxrate 6000k / bufsize 12000k で再エンコードしてから stream copy する
- `fix(videoup)`: `generate_videos.sh` の loop 正規化判定に `r_frame_rate` を追加し、24fps 以外の `loop.mp4` を `-r 24` 付き `loop_normalized.mp4` 経路へ強制するよう修正。30fps loop と 24fps 系アセットの concat/stream copy 不整合を予防

### Migration

所要時間の目安: 〜10 分

local fix 衝突注意: 下流で `youtube_automation.utils.daily_archive` を直接 import している箇所は `streaming_archive` への rename に追従が必要（#164）

サマリ:

- **破壊的変更**: `yt-skills sync` の default が `--asset all` に変わり、skills / claude-md / workflow-cheatsheet / features を一括配布する（#363, #355）。skill 単独 sync に戻すには `--asset skills` を明示
- **破壊的変更**: `yt-skills sync --target X` を asset 未指定で叩くと `exit 2` で止まる（#363, #355）。asset ごとに default_target が異なる all モードで意図しない出力先への silent 書き込みを防止。skills を別 target に出すには `--asset skills --target X`
- `utils/daily_archive.py` → `utils/streaming_archive.py` への rename（#164）。direct import している箇所は import path 修正
- `feat(comments-reply)`: replies 走査の追加 + Gemini 駆動の返信生成バックエンドを追加（#365, #366）。`comments.generator.type` で `template` / `gemini` を切り替え可能
- `feat(video-description)`: 概要欄タイムスタンプを個別楽曲単位に変更 + 同名楽曲の自動リネーム機構（#494）。`\d+-pattern-[a-d]` 規約外の legacy コレクションはフラット出力で後方互換
- `feat(loop-video)`: 末尾 CRF 圧縮ステップで本編動画容量を約 40% 削減（#175）。`compression.{enabled,crf,preset}` で skill-config 上書き可能
- `feat(thumbnail)`: codex 0.131 系の `codex exec` を直接 shell 実行する補助導線を追加（#501, #547）
- `feat(terraform)`: streaming VM の SSH host key 検証（#164）
- 新規 docs: `docs/workflow-cheatsheet.md`（#363）/ `docs/features.md`（#355）/ `docs/migration/high-cpm-locales.md`（#272）

## [5.5.2] - 2026-05-20

### Added

- `/automation-release` スキル新設とバージョン 1 ソース化（#435）。`pyproject.toml::version` を唯一のソースとし、prepare（リリース PR 作成）→ publish（tag + GitHub Release）の 2 フェーズを 1 コマンドで実行
- `/automation-update` スキル新設で下流チャンネルリポジトリの upstream 追従を 1 コマンド化（#430）。CHANGELOG.md / GitHub Release 本文を入力源として累積影響を要約
- `/automation-update` に self-overwrite ハンドリングと `config.default.yaml` 直接編集検出時の移行案内を追加（#430 系）
- Codex CLI 向け `AGENTS.md` と `.agents/skills` symlink を追加（#477）。`.claude/skills/` を Codex 規約パスから探索可能に
- `assets/stock/<theme>/` へボツ画像を自動退避する仕組み（#364）。隣接 `.meta.json` で由来を管理
- `reference_images` プールへの自動合成機構（#364）。退避済み画像を参照プールへ流用可能に
- `feat(thumbnail)`: single_step を default 化し参照画像ローテーション / プリフライトを追加（#356）
- `feat(loop-video)`: Veo プロンプトを motion/static targets で構造化（#358）
- `feat(loop-video)`: 既存 `loop.mp4` 検出時の `--skip-existing` ロジックを追加（#451 / #378）
- `feat(skills)`: 長時間処理を background 実行 + 「処理中・質問 OK」案内に統一（#361）
- `feat(suno)`: `video_analysis` の `suno_preset` を fallback として参照（#360）
- `feat(collection-ideate)`: skill に `thumbnail_mode` フラグ受けを追加（#449）
- `feat(upload-core)`: resumable upload の session URI を `upload_tracking.json` に永続化（#381）。失敗後の再実行で二重 publish を防止

### Changed

- `/release-notes` を廃止し、`/automation-update` を CHANGELOG.md / Release 本文ベースに刷新（#434）
- `scripts/gcp-{bootstrap,terraform-apply}.sh` を `scripts/gcp/` 配下の canonical path に一本化（#388）
- `pyproject.toml` 全 16 依存に major upper bound を付与（#407）。互換性予防
- `refactor(suno)`: `suno_preset` fallback collector の self-review 整理（#360）

### Fixed

#### `playlists.json` の string-shape entry で `PlaylistManager` が `AttributeError` で落ちる問題を修正

`config/channel/playlists.json` がシンプル形式（`{"main": "PL..."}`）のとき、
`PlaylistManager.resolve_playlists` 内の `pl.get("auto_add")` が
`'str' object has no attribute 'get'` を投げ、`/video-upload` 経由の playlist
自動追加が失敗していた。loader (`_build_playlists`) で string value を
`{"playlist_id": <元値>, "auto_add": True, "title": None}` に正規化し、消費側
（`PlaylistManager` の各メソッド、`PlaylistStatusViewer.show_status`、
`collection_uploader._assign_to_playlists`）が常に dict shape を仮定できるよう
contract を確定させた。dict 形式の既存運用は後方互換性を保つ。関連: #275

- `src/youtube_automation/utils/config/loader.py`: `_build_playlists` で string /
  dict を分岐し、string は 3 キー固定の dict に展開、dict は shallow copy して
  入力 dict との参照を切る
- `src/youtube_automation/utils/config/playlists.py`: `Playlists.items` の型注釈を
  `dict[str, str]` から `dict[str, dict]` へ。docstring に正規化契約を明記

#### その他の修正

- `fix(veo)`: Ctrl+C 中断時に `operation_id` 永続化で再開可能に（#453）
- `fix(skill_config)`: preview 非 mapping 時の `AttributeError` を `ConfigError` に置換（#449）
- `fix(lyria-client)`: Lyria 3 Interactions API の legacy `outputs` schema 単一依存を解消（#377）。スキーマ切替時のサイレント失敗を防止
- `fix(upload-policy)`: `429 Too Many Requests` を retryable に追加し backoff 化（#379）
- `fix(yt-config-migrate)`: `verify` が `--target` 指定なしで複数ファイル構成チャンネルを解決できない問題を修正（#347）

### Removed

- `/release-notes` スキル廃止（#434）。後継は `/automation-update`（下流追従）と `/automation-release`（リリース実施）
- `scripts/gcp-bootstrap.sh` / `scripts/gcp-terraform-apply.sh` の旧パスを削除（#388、`scripts/gcp/` 配下に移行済み）

### Migration

所要時間の目安: 〜10 分

local fix 衝突注意: 無し（下流が独自に skill を改変していない場合）

サマリ:

- 新 skill: `/automation-release`（本リポジトリ運用）と `/automation-update`（下流追従）
- `/release-notes` スキル廃止（後継は上記 2 スキル）
- `upload-core` が resumable session URI を永続化し、失敗後の再実行で二重 publish を防止（#381）
- `lyria-client` / `upload-policy` / `yt-config-migrate` の安定性修正
- GCP 系シェルスクリプトを `scripts/gcp/` 配下の canonical path に一本化（#388）

主要な追従ポイント:

1. `uv run yt-skills sync` で新 skill `/automation-release` / `/automation-update` を取り込み
2. `/release-notes` をローカルで叩いていた場合は `/automation-update` に置き換え
3. `scripts/gcp-bootstrap.sh` / `scripts/gcp-terraform-apply.sh` を参照する自前スクリプトがあれば `scripts/gcp/` 配下のパスに書き換え

## [5.5.1] - 2026-05-19

※ 本セクションは v5.5.0 リリース後に Unreleased への記述が見送られていたため、
v5.5.1 で実装されたサマリのみを記録する（詳細実装は各 PR を参照）。

### Added

- `/onboard` AI 主導 wizard と `yt-doctor` 状態診断 CLI で GCP / OAuth セットアップをオンボーディング化（#334 / Phase 1 MVP）
- `/community-post` スキルと `community.example.json` を共有コアに追加（#237、Flow365 TTP の汎用化）
- `/community-draft` スキル新設（day-of-reminder / weekly-feedback テンプレを汎用形で配布、#309、jazzgak. TTP 由来）
- Shorts スキル群を v5 規約でゼロベース再実装し復活: `/short` / `/short-thumbnail` / `/short-release`（#287）
- `config/channel/shorts.json` 新設で Shorts 投稿可否・公開時刻・収益化設定を集約（#287）
- `/release-notes` スキル新設と v5.5.0 アップグレードガイド初版（#333 / Closes #253）
- `/video-description` に bulk-update モードを統合（#247、`yt-bulk-update-desc` の内部呼び出し）
- `/masterup` に `yt-fix-timestamps` 統合（#249、マスター生成 → タイムスタンプ整合 → 修正の一気通貫）
- preflight `chapter_max` 設定で per-track 命名運用をデフォルト許容（#421、12 chapters の一律上限を config 化）

### Changed

- `GOOGLE_CLOUD_PROJECT` を ADC fallback 化（#280）。Vertex AI 系の呼び出しが env 設定なしで動くようになり、`.env` の必須行が 1 つ減る
- `cli/skills_sync.py` (443 行) を 5 サブモジュール構成にリファクタ（#327）。外部 CLI 仕様は不変
- `yt-skills diff` 出力で `--prune` の存在を案内（#328）
- `gcp-bootstrap.sh` と `yt-doctor` を ADC ベースに統一（#280）
- スキル運用リスク監査レポート / スキル汎用化整合性監査レポートを `docs/audits/` に追加（#353 / #372）

### Fixed

- `.claude/skills/short/references/generate_short_loop.py` および `.claude/skills/short-thumbnail/references/generate_short_loop.py` の broken symlink を実体ファイルで復元（#345、wheel ビルド失敗解消）
- v5.5.0 アップグレードガイドに `command not found` / `No module named` 偽陽性ガードを追記（#335）
- pytest collection error を解消（#329）

### Migration

downstream チャンネルリポジトリで v5.5.0 → v5.5.1 への追従手順は
**チャンネル運営者向け** の平易なガイド [docs/upgrades/v5.5.1.md](docs/upgrades/v5.5.1.md) を参照。

サマリ:

- 新規 skill 7 件（`/onboard` / `/release-notes` / `/community-post` / `/community-draft` / `/short` / `/short-thumbnail` / `/short-release`）と新規 CLI 1 件（`yt-doctor`）
- 既存 skill の挙動変更（`/masterup` に `yt-fix-timestamps` 統合 #249、`/video-description` に bulk-update モード追加 #247、preflight `chapter_max` を config 化 #421、`yt-skills diff` で `--prune` 案内 #328）
- `GOOGLE_CLOUD_PROJECT` 必須環境変数の撤廃（ADC fallback 化、#280）
- broken symlink 修正で wheel ビルドエラー解消（#345）

なお、v5.4.0 → v5.5.0 への追従手順は引き続き [docs/upgrades/v5.5.0.md](docs/upgrades/v5.5.0.md) を参照。

## [5.5.0] - 2026-05-17

### Changed

#### `yt-populate-scene-phrases` を汎用 CLI として書き直し、`/wf-new` に統合

`yt-populate-scene-phrases` を RJN 専用ハードコード辞書ベースの移行スクリプトから、
任意のチャンネルで使える汎用 CLI に書き直した。`config/channel/content.json::title.theme_scenes[<theme>].scene`
を英語ソースとして取得し、`localizations.json::supported_languages` 全件へ Vertex AI Gemini で
翻訳して `workflow-state.json.scene_phrases` に書き込む。多言語非対応（`supported_languages` が
1 言語以下）のチャンネルでは no-op で正常終了する。関連: #246

- `src/youtube_automation/scripts/populate_scene_phrases.py`: ハードコード `SCENE_PHRASES` 辞書を
  削除し、`<collection>` を引数で受ける汎用実装に置き換え。`--en` / `--overwrite` / `--dry-run` /
  `--model` オプションを追加。`translate_phrase()` は google-genai Client を DI 可能で、テスト時に
  モック注入できる
- `.claude/skills/wf-new/SKILL.md`: Phase 2a 直後に `2a-2. scene_phrases 初期化` ステップを追加。
  多言語非対応チャンネルでは CLI 側で自動スキップされるため条件分岐は不要
- `.claude/skills/wf-new/references/scene_phrases.md`: CLI 単体実行（再投入・`--dry-run` プレビュー・
  `--en` 明示指定）のドキュメントを追加
- `tests/test_populate_scene_phrases.py`: 翻訳・dry-run・overwrite・theme_scenes 解決・コレクション
  探索の 15 ケースを追加

### Added

#### サムネイル生成プロバイダーを設定から切り替え可能にする（gpt-image-2 対応）

サムネイル生成パスを `youtube_automation.utils.image_provider` 抽象化レイヤに刷新し、
skill-config の `image_generation.provider: gemini | openai` で OpenAI gpt-image-2 系と
Gemini を案件単位で切り替えられるようにした。OpenAI provider は CJK 文字描画が綺麗で
16:9 / 9:16 をネイティブサポートする gpt-image-2 を `images.generate` / `images.edit`
経由で利用する。`thumbnail` スキルは内部で `aspect_ratio: "16:9"` 固定で provider を呼び
出し、9:16 縦型は将来の `short-thumbnail` 復活時に同 API で接続できる構造を保つ。
`OPENAI_API_KEY` は `youtube_automation.utils.secrets._SECRET_REFS` 経由（env →
1Password CLI）で解決する。`cost_tracker.PRICING` に `gpt-image-2` / `gpt-image-1.5` /
`gpt-image-1-mini` を追加し、`gpt-image-2` の `high` 品質を 1024×1024 約 $0.21/枚で
登録（他 2 モデルは 2026-04 時点の暫定値）。関連: #67

- `src/youtube_automation/utils/image_provider/__init__.py`: ファクトリ
  `get_provider(cfg)` と skill-config ラッパ `load_image_generation_config()` を公開
- `src/youtube_automation/utils/image_provider/base.py`: `ImageProvider` Protocol、
  `ImageGenerationRequest` / `ImageGenerationResult`、共通リトライ定数
  `RETRY_MAX=3` / `RETRY_BACKOFF=[10, 30, 60]`
- `src/youtube_automation/utils/image_provider/config.py`: `ImageGenerationConfig` /
  `GeminiConfig` / `OpenAIConfig` dataclass。`OpenAIConfig.__post_init__` で
  `aspect_ratio in ("16:9", "9:16")` を検査（不一致は `ConfigError`）
- `src/youtube_automation/utils/image_provider/gemini.py`: 旧 `image_generator.py` の
  Gemini ロジックを `GeminiImageProvider` に移植
- `src/youtube_automation/utils/image_provider/openai.py`: gpt-image 系の新規実装。
  `aspect_ratio → size`（`16:9 → 1536x1024` / `9:16 → 1024x1536`）マッピングと
  `OPENAI_API_KEY` 解決、リトライ、参照画像のハンドルクローズを担う
- `src/youtube_automation/utils/image_provider/composition.py`: provider 中立な
  `apply_composition_rules` / `confirm_cost` / `resolve_unique_path` /
  `log_image_cost` / `resolve_composition_source` /
  `resolve_cost_per_image`（`cost_per_image_usd` 上書き解決）/
  `persist_image`（PNG/JPEG 保存・YouTube サムネ 2MB 上限対応）/
  `prompt_overwrite_or_rename`（既存出力の上書き確認 + ``-vN`` 採番）/
  `resolve_reference_paths`（参照画像パス解決、欠損時 `ConfigError`）を集約。
  Gemini / OpenAI 両 provider が同一の保存ロジックを共有し、`scripts/generate_*` 2 本も
  単価解決・上書き分岐・参照画像解決の共通ロジックをここから import する
- `src/youtube_automation/utils/image_provider/config.py`: `replace_model(cfg, model)`
  を新設。CLI `--model` 引数による `ImageGenerationConfig` の active provider 側
  モデル ID 差し替えを `scripts/generate_*` 2 本から共通利用
- `src/youtube_automation/utils/secrets.py`: `_SECRET_REFS` に `OPENAI_API_KEY` を追加
- `src/youtube_automation/utils/cost_tracker.py`: `PRICING` に gpt-image 3 モデルを
  追加。OpenAI は `quality` で課金階層が決まるため `unit="image"` ＋
  `by_size: {low, medium, high}` を維持
- `src/youtube_automation/utils/skill_config.py`: `load_channel_override(skill)` を
  公開。`gemini_image:` 旧 namespace の override 検出に使用
- `pyproject.toml`: `dependencies` に `openai` を追加
- `tests/test_image_provider_*.py`: provider 切り替え／aspect_ratio バリデーション／
  Gemini・OpenAI 各実装／統合フローのテストを追加

### Changed

- `.claude/skills/thumbnail/config.default.yaml`: ルート namespace を `gemini_image:`
  から `image_generation:` に刷新し、`provider` / `gemini` / `openai` の階層に
  分割。OpenAI 設定例（`model` / `quality` / `aspect_ratio` / `thinking` / `batch`）を
  追記
- `.claude/skills/thumbnail/SKILL.md`: provider 非依存の表現に書き換え
  （`gemini_image.*` → `image_generation.gemini.*`）。Channel Adaptation セクションに
  provider 切り替え手順を追加
- `.claude/skills/ideate/SKILL.md`: Phase 4-2 の skill-config 参照を新 namespace
  （`image_generation.gemini.*` / `image_generation.openai.*`）に追従
- `src/youtube_automation/scripts/generate_image.py`: import 経路を
  `image_provider` 直叩きに変更（旧 `image_generator.generate_image()` 呼び出し撤去）
- `src/youtube_automation/scripts/generate_thumbnail.py`: 同上。Gemini provider の
  `image_size` は `cfg.gemini.image_size` から解決（ハードコード撤去）
- `tests/test_skill_cost_documentation.py`: namespace 検査ヘルパーを
  `image_generation.gemini` に置換

### Deprecated

- skill-config の `gemini_image:` 旧 namespace は非推奨。`image_generation.provider:
  gemini` + `image_generation.gemini.*` への移行を推奨。後方互換のため当面ロードは
  継続するが、`DeprecationWarning` を発行する。default.yaml に `image_generation:`
  を持たせている都合でユーザー override の `gemini_image:` が上書きされて silently
  破棄されるバグを避けるため、`load_image_generation_config()` は override ファイル
  単体に `gemini_image:` のみが宣言されている場合に legacy パスへ分岐する

### Removed

- `src/youtube_automation/utils/image_generator.py`: `image_provider` パッケージへ
  ロジックを完全移植したため削除（grep 上の外部参照ゼロ確認済み）

#### 廃止予定 CLI 3 件を撤去 (#264)

廃止予定だった 3 つの CLI エントリーポイントを `[project.scripts]` から削除し、
配線元 `.py` モジュール・関連テスト・スキル参照を後継 CLI に書き換えた。

- `yt-generate-music`（後継: `yt-generate-music-dj` / `/lyria` スキル経由）#250
- `yt-generate-thumbnail`（後継: `yt-generate-image` / `/thumbnail` スキル経由）#251
- `yt-video-uploader`（後継: `yt-upload-auto` / `yt-upload-collection` / `/video-upload` スキル経由）#252

あわせて `scripts/video_uploader.py` の `VideoUploader.create_playlist` /
`add_video_to_playlist` が `scripts/playlist_manager.py` だけから参照されていた中間層
だったため、両メソッドを `PlaylistManager._create_playlist` /
`PlaylistManager._add_video_to_playlist` として内包し、`VideoUploader` クラスごと撤去した。
これによりプレイリスト操作は `PlaylistManager` に集約される。

- `pyproject.toml`: `yt-generate-music` / `yt-generate-thumbnail` / `yt-video-uploader` の
  3 entry point を削除
- `src/youtube_automation/scripts/generate_music.py` / `generate_thumbnail.py` /
  `video_uploader.py`: 削除
- `src/youtube_automation/scripts/playlist_manager.py`: `VideoUploader` import / 初期化
  を撤去。`_create_playlist` / `_add_video_to_playlist` を内部メソッド化
- `tests/test_video_uploader.py`: 削除（対象モジュール撤去に伴う）
- `tests/test_playlist_manager.py`: `VideoUploader` モック patch を撤去し、新メソッド
  （`_create_playlist` / `_add_video_to_playlist`）の単体テストを追加
- `tests/test_image_provider_composition_cli.py`: parametrize から
  `generate_thumbnail.py` を外す
- `README.md`: CLI 一覧から 3 行を削除し、`yt-generate-image` を「サムネイル兼用」と明記
- `.claude/skills/collection-ideate/references/collection-lifecycle.md`: サムネ生成手順を
  `/thumbnail` スキル経由（`yt-generate-image`）に書き換え
- `.claude/skills/video-upload/SKILL.md`: `video_uploader.py を直接使用` を
  `yt-upload-auto を使用` に置換
- `.claude/skills/channel-setup/references/claude-md-template.md`: `uv run yt-video-uploader`
  行を削除

### Migration

downstream チャンネルリポジトリで v5.4.0 → v5.5.0 への追従手順は
**チャンネル運営者向け** の平易なガイド [docs/upgrades/v5.5.0.md](docs/upgrades/v5.5.0.md) を参照。

サマリ:

- 新規 skill 2 件（`/playlist`, `/metadata-audit`）、新規 CLI 1 件（`yt-channel-init`）
- 既存 skill の挙動変更（`/masterup` Step 6 を rsync 化 #324、`/wf-next` で main repo の master-mix を検出 #325、`/channel-setup` に設定 push モード #248、`/collection-ideate` を `freshness_days` 参照に統一 #326）
- `yt-channel-settings push --apply` の `brandingSettings cannot be used with other parts` 400 エラー修正（#230）
- `/wf-new` に `yt-populate-scene-phrases` 統合で多言語 scene_phrases を自動生成（#246）

なお、v5.3.0 → v5.4.0 への追従手順（スキル名 rename 8 件・`image_generator.py` 削除など、本リリースに累積で含まれる破壊的変更）は引き続き [docs/upgrades/v5.4.0.md](docs/upgrades/v5.4.0.md) を参照。

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

[5.5.6]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.6
[5.5.5]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.5
[5.5.4]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.4
[5.5.3]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.3
[5.5.2]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.2
[5.5.1]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.1
[5.5.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.0
[5.4.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.4.0
[5.3.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.3.0
[5.2.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.2.0
[5.1.1]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.1.1
[5.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.0.0
[2.0.0]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v2.0.0
