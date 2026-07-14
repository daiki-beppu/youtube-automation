# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- `docs(collection-ideate)`: stale な Analytics report 検出時に推論コスト見積もり付きの 3 択を提示し、承認時または上限内の `freshness.stale_action: auto` 時だけ `/analytics-analyze` を同一セッションで実行する導線を追加した。`/wf-new` は判定を委譲し二重ダイアログを防ぐ（#1716）。
- `docs(skills)`: wf-* から委譲される制作系 10 skill に subagent 入出力契約を追加し、リポジトリ相対の入力、成果物絶対パスの完了報告、state 非更新、承認・選択確定後のみの委譲を明記した。state を扱う `/masterup` の over-max 例外採用と `/suno` vocal の標準 collection 生成はメインエージェントが実行する（#1662）。

- `feat(thumbnail)`: TTP 参照画像の直近コレクション重複除外を追加（#1649）。`reference_images.dedup_recent_collections`（既定 5）が collection ごとに採用企画の参照 1 件を Reference Assignments へ保存し、全割当節から未使用参照を先頭候補として優先する。不足する候補枠だけ位置順で補うため、候補数より大きいプールは全参照が採用されるまで先頭候補を再利用しない。

### Added

- `docs(feedback)`: `/feedback` に、`status="recorded"` の未還流 entry を一覧・選択し、open issue の類似タイトル照合とユーザー承認を経て `daiki-beppu/youtube-automation` へ `feedback` ラベル付き issue を起票する還流モードを追加した。成功した entry は `status="filed"` と `issue_url` を記録して候補から除外し、二重起票を防ぐ。起票本文テンプレート、発生チャンネル掲載の個別確認、起票直前の機密情報再マスクも明記した（#1829）。
- `docs(channel-research)`: サムネイルのフォント傾向・テキスト内容パターン・配置傾向を、固有名詞やコピー原文を除いた構造化プロファイル `docs/benchmarks/thumbnail-text-profile.md` として生成する契約を `/channel-research` に追加した。前回生成したプロファイルは個別ベンチマークレポートの存在判定と fallback 入力から除外する（#1906）。
- `docs(thumbnail-research)`: `/benchmark` の収集済み JSON と競合サムネイル画像を再生数上位群 / 下位群で比較し、構図・配色・テキスト配置・視線誘導・被写体の勝ちパターンを `docs/benchmarks/thumbnail-analysis.md` に出力する `/thumbnail-research` スキルを追加した。レポートの推奨事項と参照候補を `/thumbnail` の TTP 入力として相互参照し、データ収集・チャンネル全体分析・320px 視認性比較との発動条件を分離した（#1796）。
- `docs(channel-new)`: 入口系またはモード判別不能な発動時に既存チャンネル / 新規開設を最初に確認するゲートを追加した。既存チャンネルでは `yt-channel-seed --no-write-benchmark --json` の登録者数・動画数・直近タイトルを提示して既存踏襲 / 方向性見直しを確認し、見直し選択時も取り込み完了後に必要な TTP メモまたは分析レポートを明示して方向性検討モードへ接続する（#1897）
- `docs(analytics)`: `/analytics-analyze` の必須 3 CLI 出力と数値 evidence を `reports/analysis_YYYYMMDD.json` に構造化保存し、Markdown とのペア生成と validator 成功を完了条件にした。`/collection-ideate` は同 validator で検証済みの固定キーから §5 / §6 / §8 相当を読み取る（#1805）。
- `docs(thumbnail)`: YouTube Studio のサムネイル A/B テストについて、候補 2〜3 案の設計、operator 向け手動設定、watch time share・結果のコレクション別 JSON 記録を行う `/thumbnail-test` スキルを追加した。確定 Winner の構図・配色・文字量が 2 entry 以上で反復した場合に限り次回 `/thumbnail` のプロンプト方針へ還元し、`/postmortem` では対象動画のテスト結果を flop 仮説の根拠・反証として併記する（#1808）。
- `docs(skills)`: 下流チャンネルリポジトリでスキル実行中の不具合・摩擦・改善案を `data/feedback/feedback-log.jsonl` に append-only JSONL として記録する `/feedback` スキルを追加した。entry schema は `.claude/skills/feedback/references/feedback-entry.schema.json` に単一ソース化し、`date` / `skill` / `category` / `summary` / `context` / `status` / `issue_url` の構造、`status="recorded"` の新規記録、機密情報の `***REDACTED***` マスクを SKILL.md に明記した。下流配布 CLAUDE.md テンプレにもスキル摩擦時に `/feedback` を案内する導線を追加した（#1828）。
- `docs(setup)`: `/setup` の全 check 緑後・完了報告前に、`workflow.wf_next` の音源 / アップロード承認ゲート、手動マスタリング検出スキップ、Veo 課金を伴う loop-video の有効状態を 1 問ずつ確認する運用設定インタビューを追加した。現在値と推奨回答を提示し、変更時だけ config を更新する（#1902）
- `feat(upload)`: collection の `workflow-state.json::title_template_check.allow_volume_patterns: true` で、そのコレクションだけ公開タイトルの `Vol.` / `Part` / `#N` / ローマ数字の巻数表記を upload preflight で許可できるようにした。未設定・`false` の既定検出、RHS 鋳型・完全重複・核語彙の検査、および `content.json::title.template_check.volume_patterns` は変更しない（#1729）
- `docs(setup)`: `/setup` wizard の起動直後にライブ配信予定の有無を確認し、予定ありの場合は YouTube のライブ配信有効化に最大 24 時間かかる旨と YouTube Studio での有効化リクエスト手順を `[HUMAN STEP]` で案内するようにした。案内後は有効化完了を待たず通常の setup フローを続行する（#1896）
- `feat(analytics-report)`: HTML レポートのテーマ色を `analytics-report/config.default.yaml::theme.colors` に移し、`config/skills/analytics-report.yaml` の channel override で差し替えられるようにした。未設定チャンネルでは既存パレットを維持する（#1691）

### Changed

- `feat(suno-helper)`: Queue mode の duration guard 全滅 entry を、全 entry の ACK 先行投入後に既存 pacing で同一 prompt から最大 2 回自動再生成する挙動を明示し、Queue mode の説明文にも自動再生成を追記した（#1775）。

- `perf(discover-competitors)`: `search.list` 結果を 24 時間キャッシュし、`--refresh` による強制更新と benchmark 登録済みチャンネルの除外を追加した（#1694）

- `feat(suno-helper)`: duration guard NG の同一 prompt 再生成を popup の「異常値の曲を再生成する」で切り替え可能にした。既定 ON は安全・高速モードとも最大 2 回再生成し、OFF は NG を警告表示しつつ生成済み全 clip を playlist / download 候補に維持する。選択は popup 再表示、resume、失敗分再実行、playlist 再実行へ引き継ぐ（#1733）
- `docs(skills)`: リサーチ・戦略チェーンの 6 スキル（benchmark / discover-competitors / viewer-voice / audience-persona-design / viewing-scene / channel-research）の冒頭 60 行以内に、停止する fail と許容する fail を分離した前提成果物ガードを統一書式で整備した。必須入力が無い場合は生成元の前工程スキルを案内して停止し、後続 Step で生成・自動更新・代替できる入力欠如は停止条件から除外する（#1825）

- `docs(automation-release)`: extension release の skill / checklist を Nix extensions shell 契約（Node 24 / pnpm 11.12.0）へ同期した（#1956）。両拡張の frozen install → build → zip、期待名 zip、lockfile 無差分を `verify-extensions.sh` で検証し、ambient Node / pnpm と `--ignore-workspace` を使わないことを明記。Python 本体の release flow と `release-extensions.yml` は変更なし

- `docs(extensions)`: extension のローカル install / build / zip / Vitest / Playwright / 成果物確認と `/suno` の初回 build 導線を、CI と同じ Nix extensions shell（Node 24 / pnpm 11.12.0）入口へ統一した（#1957）。ambient pnpm / 旧 npx pnpm 導線の不在を文書契約テストで固定
- `docs(suno-helper)`: Suno UI の旧「Custom Mode」および「Instrumental ON/OFF」表記を、現行の Advanced タブと Lyrics mode（Write / Instrumental）の用語へ更新した。operator 手順、拡張 description、保守用コメントを対象とし、実行時のセレクタ・エラーメッセージ・テスト期待値は変更していない（#1900）

### Fixed

- `fix(suno)`: ボーカルの標準コレクション生成時に、`workflow-state.json::track_count` を曲数の SSOT として `suno-patterns.yaml::tracks` の完全一致および展開後 prompt entry 数の下限を fail-loud で検証するようにした。entry 数が曲数未満、または両ファイルの曲数が不一致なら `suno-prompts.json` を生成しない（#1785）。
- `fix(doctor)`: `uv tool install youtube-channels-automation` によるグローバル導入を `uv_project` / `automation_package` の bootstrap check で検出し、pyproject.toml に依存がない正常な環境を fail と誤判定しないようにした（#1724）。

- `fix(api)`: playlist / benchmark / analytics / comments-reply / discover-competitors の YouTube API 呼び出しで、429・5xx・quota 系 403・network error を jitter 付き指数 backoff で最大 3 回試行し、恒久 4xx は即座にドメイン例外へ変換する共通 retry 境界を追加した（#1695）。

- `fix(suno-helper)`: Download all メニューの短時間 auto-close レースに対し、More クリック直後から探索を開始し、検出失敗時は最大 3 回再クリックしてダウンロードを継続できるようにした（#1926）。
- `fix(suno-helper)`: 拡張更新時に既存の Suno タブを自動リロードし、旧 content script の orphaned context を残さず新しい bundle を再注入するようにした（#1718）。
- `fix(suno-helper)`: feed/v3 の active poll が `ids` フィルタ無効化後も cursor ページネーションを追跡し、最新ページ外の保存済み clip を完了確認できるようにした（#1929）。
- `fix(thumbnail)`: `/thumbnail` SKILL.md の標準生成順序と Single-Step / TTP 章を、テキスト付き `thumbnail.jpg` 先行 → 承認済み `thumbnail.jpg` から textless `main.png/jpg` 後続再生成の契約へ統一した。`config.default.yaml` の single_step コメント、サンプルプロンプト、`short-thumbnail` の前提案内も同じ順序へ追従し、旧 textless 先行文言を回帰テストでロックした（#1901）。
- `fix(thumbnail)`: `codex-image.sh` に codex CLI とサーバー側デフォルトモデルの互換性プリフライトを追加し、非互換時は画像生成を試みず CLI version・検出モデル・アップグレード手順を stderr に出して停止するようにした。生成失敗時の診断 dump にも codex CLI version と default model 推定値を含める（#1915）。
- `fix(suno-helper)`: Download all ZIP の展開・音声配置・`workflow-state.json` 更新がすべて成功した後に、元 ZIP を自動削除するようにした。ZIP 削除だけが失敗した場合は、成功済みの音声と workflow-state を維持し、警告を記録する（#1890）。
- `fix(upload)`: `yt-upload-collection` の `-c` 未指定時の自動選択を、`collections/planning/` 配下で `phase=mastered` かつ `upload.video_id=null` の未公開コレクション 1 件だけに限定した。`live/` の公開済みコレクションは候補外とし、候補が 0 件または複数件なら `-c` 明示を要求して停止する。`--plan` / `--status` / 実アップロードと日次実行に同じ選択条件を適用した（#1731）。
- `fix(upload)`: タグ件数下限が YouTube の 500 字上限の下で到達不能な場合、upload preflight と metadata audit が件数不足ではなく、`tags.min_count` を下げるか base タグを短縮するよう案内する明示診断を返すようにした。配布する content.json テンプレートの `tags.min_count` も 26 に統一した（#1732）。
- `fix(loop-video)`: Ctrl+C 後の Veo operation resume state に入力画像の SHA-256 を保存し、再実行時に指定モデルまたは入力画像内容が state と異なる場合は旧 operation を破棄して指定どおり新規生成するようにした（#1746）。旧形式 state は安全側で破棄する。
- `fix(analytics)`: `yt-channel-trend` の z-score 基準から当日を除外し、min_periods 未達を `null` として明示するよう修正した。トレンド判定は直近 28 日とその前の 28 日の平均を比較し、週次前週比は完全な 7 日間の週だけで計算する（#1803）。

## [5.5.17] - 2026-07-10

### Added

- `fix(loop-video)`: 通常生成時の `loop-v{n}.mp4` バックアップに保持上限（default 3、skill-config の `max_backups` で上書き可）を追加し、上限超過分を最古から削除して削除ファイル名を表示するようにした。`--skip-existing` / `--smooth` の early-exit 経路は既存バックアップを変更しない（#1654）
- `feat(comments-reply)`: Author の返信案を別コンテキスト Reviewer が persona / NG ワード / 最大文字数 / 言語一致の 4 基準で判定する品質ゲートを追加。判定条件は候補 JSON と comments config の正規値から固定し、FAIL の `reply_text` のみ最大 2 周再生成する。上限後も FAIL の候補は dry-run 前に除外して件数と理由を承認サマリへ表示する（#1666）
- `feat(video-description)`: skill-config に `chapters_enabled`（既定 `true`）を追加し、章運用を廃止したチャンネル（BGM / ASMR 等）向けの標準 opt-out を提供した（#1665）。`config/skills/video-description.yaml` で `chapters_enabled: false` を設定すると、タイムスタンプ列（チャプター行・テーマ見出し行）の生成・重複トラック名の LLM リネーム・`workflow-state.json` への `track_display_names` 永続化をすべて skip する（構造化メタブロック / Music Time セパレータ / playlist 名 / CTA / hashtag は変わらず生成）。未設定チャンネルは既定 `true` で挙動不変
- `feat(skills)`: 2026-05 skills 監査の残件として、skill-config 未適用スキルの直書き値を skill-config 機構へ切り出した（#1669）。(1) analytics-collect / analytics-analyze 双方に直書きされていた鮮度判定しきい値（30 分）を `analytics-collect/config.default.yaml::freshness_minutes` に単一ソース化（`config/skills/analytics-collect.yaml` の上書きが両スキルの判定に効く）。(2) `discover-competitors`（検索フィルタ既定値・キーワード数ガイドレール）/ `live-clean`（削除対象・保護パターン）/ `postmortem`（症状判定しきい値・仮説マッピング係数）/ `video-upload`（preflight 探索パターン・誇張語 NG リスト）に `config.default.yaml` を新設し、各 SKILL.md の直書き値を config 参照へ書き換えた。`yt-discover-competitors` は CLI フラグ既定値を `load_skill_config("discover-competitors")` 経由で解決する（CLI フラグ明示指定 > チャンネル上書き > default）。(3) `analytics-report` の `#Shorts` 除外キーワードと KPI カード構成を `analytics-report/config.default.yaml::html.{exclude_title_keywords,kpi_cards}` に、`metadata-audit` の REMOTE チャプター上限（>12）を `metadata-audit/config.default.yaml::chapters.remote_max` に skill-config 化し、`metadata_audit.py::audit_remote` が実行時に読むよう変更した
- `chore(repo)`: リポジトリルートに `.gitattributes` を追加し、画像 / 音声 / 動画 / アーカイブ / フォント / PDF（計 20 拡張子）を `binary` macro で diff 抑止指定した（#1671）。`git diff` にバイナリ差分がテキスト表示されなくなる
- `feat(live-clean)`: `/live-clean tmp` として collections 配下の `tmp/` 残骸クリーンアップモードを追加した（#1671）。`find collections -type d -name tmp` で検出し、既存の大容量メディア削除と同じ「スキャン → ドライラン → 明示承認 2 択 → 削除 → レポート」フローを適用する。削除は `rm -rf` を使わず「ファイル単位 `rm -f` → 空ディレクトリ `rmdir`」の depth-first 方式で、`<CHANNEL_DIR>/tmp/`（`veo-operations/` / `lyria-recovered/` は /loop-video・/lyria の管理領域）と symlink は対象外。yt-clean CLI を新設しない棲み分けの根拠を SKILL.md に明記した
- `docs(skills)`: 「## 前提」セクション未導入だった 18 skill（automation-release / automation-update / channel-new / channel-research / community-post / discover-competitors / distrokid-helper / ext-install / live-clean / masterup / metadata-audit / setup / suno / suno-lyric / thumbnail-compare / videoup / viewer-voice / wf-new）に skill-authoring-guidelines 準拠の前提存在ガード（確認 → 満たさなければ前工程を案内して停止）を追加した（#1671）。これで全 skill が導入済みになる。設定読み込みゲートを持つ skill ではゲートより後に配置する既存契約（`test_skill_config_defaults_have_read_gate_in_skill_docs`）を維持
- `docs(skills)`: `/discover-competitors` の SKILL.md に他 skill と同一フォーマット（状況 / 兆候 / 対処）の「障害時ガイダンス」節を追加（#1652）。OAuth 未認証・失効時の再認証手順、YouTube quota 超過（HTTP 429 / `quotaExceeded`。本スキルは約 660 units/回消費）時のリセット待ち・呼び出し抑制、同一 `--output` での再実行時に出力ペア（`.md` + 同名 `.csv`）が全体上書きされ部分結果は保持されないこと（途中失敗時はファイル未書き込みで前回出力が残ること）を文書化した
- `feat(suno-helper)`: 連続実行に投入方式セレクタ（Serial / Queue）を追加（#1586）。Queue は投入 ACK と clip ID 観測を確認したら生成完了を待たずに次 entry を先行投入し、最大 10 request（20 clip）まで Suno queue を使って全体の実行時間を短縮する。全 entry 投入後に生成完了をまとめて待ってから playlist 追加へ進む。進捗 UI には投入済み・生成未完了を表す `submitted` 状態（琥珀色）を追加。選択は chrome.storage.local（`sunoRunMode`）に永続化し、既定は従来挙動の Serial。中断時は投入方式を resume state に保存し、再開は popup の現在選択ではなく元 run のモードで行う。制約: Queue は per-entry duration guard の自動再生成を行わず（範囲外 clip は playlist 追加時に除外のみ）、bridge の clip ID 観測が必須（未観測は fail-loud で run 停止）
- `feat(suno-helper)`: `/suno-helper` を browser use 主経路で操作・監視できるように、SKILL.md に agent primary flow、DOM signal、無限待機回避、handoff 条件を追加。Chrome DevTools MCP は診断・補助・フォールバック扱いに固定し、拡張 overlay / popup には `data-suno-*` と `role="status"` の観測 signal を追加した。`/wf-new` の Suno 後続案内も `/suno-helper` の browser use 主導フローへ接続する表現に更新（#1382）
- `feat(doctor)`: `yt-doctor` に playlist スキル向けの `playlist_config` / `playlist_create_dry_run` チェックを追加（#1504）。`config/channel/playlists.json` の欠落・JSON 破損・`playlist_id` 未設定を channel カテゴリで診断し、`PlaylistManager.create_all_playlists(dry_run=True)` 経路で作成計画を検証する。dry-run は YouTube API への書き込みを行わず、失敗時は human next_action で設定修正手順を示す。
- `feat(collection-serve)`: `yt-collection-serve` に unpacked Chrome 拡張名から exact origin lock を自動解決する `--allow-extension <name>` を追加（#1486）。macOS Chrome profile の `Secure Preferences`（無ければ `Preferences`）を走査し、`extensions.settings[*].path` が絶対パスかつ basename が指定名に一致する拡張 IDから `chrome-extension://<id>` を組み立て、既存の `/auth/token` / write endpoint lock にそのまま適用する。`--allow-origin` とは排他で、検出 0 件・複数 ID 競合・profile root 走査不可・Preferences 読み取り不可・Preferences JSON parse failure は `--allow-origin` fallback 案内付きの `ConfigError` で fail-loud する。`/suno-helper` / `/distrokid-helper` / `/wf-new` のサーバー起動手順と拡張 README も `--allow-extension` 基準へ更新した
- `test(deps)`: 2020 年から未更新の `japanize-matplotlib` の font 登録が壊れたら検知する回帰テスト `tests/test_japanize_font_regression.py` を追加した（plan 024）。壊れた場合の症状（日本語ラベルの豆腐化）を matplotlib の `Glyph ... missing from font(s)` UserWarning で機械検知する
- `feat(automation-release)`: `/automation-release` に Chrome 拡張リリース（`ext-vX.Y.Z`）の extension release phase を追加した（#1735）。`suno-helper をリリースしたい v0.2.2` / `ext-v0.2.2` 形式の依頼を Phase R（リリース種別判定）で extension release と判定して Python 本体の `pyproject.toml` bump flow から分離し、`release/ext-v<VER>` ブランチでの `extensions/<name>/package.json::version` のみの bump、`release-extensions.yml` と同一の Nix extensions shell 契約（Node 24 / pnpm 11.12.0、`pnpm install --frozen-lockfile` → `pnpm zip`）の local verify と version 以外の差分で停止する差分ガード、merge 済み PR の merge commit への `ext-v<VER>` tag push、Release Extensions workflow の成功確認と Release asset（`<name>-<VER>-chrome.zip`）の確認、worktree 環境で `gh pr merge --delete-branch` が local checkout 後処理で non-zero を返す footgun の復旧手順（remote PR state / mergeCommit を確認して merge 済みなら続行）までを手順化した。エッジケースは `references/extension-release-checklist.md` に整理。Python 本体の `vX.Y.Z` flow は変更なし

### Changed

- `refactor(suno)`: ボーカルモードの `tracks_per_pattern` / `(Take N)` 展開を廃止し、1 pattern = 1 prompt entry の生成・検証契約へ単純化した（#1923）。下流の `config/skills/suno.yaml` に旧キーが残っていても読み取らず、`yt-generate-suno` / `yt-suno-verify` は展開なしの entry name と件数で処理する。
- `docs(channel-setup)`: チャンネル初回制作前に、サムネイルと楽曲の小規模パイロット試作を行い、結果を確認してから本制作へ進む検証フェーズを channel-new / wf-new / onboarding に追加した（#1657）。
- `docs(skills)`: analytics / benchmark 系スキルに subagent 委譲時の入力・出力契約、委譲対象、結果の統合手順を明記し、収集・分析・競合発掘・視聴者調査の各経路で委譲後の検証責務を揃えた（#1663）。
- `feat(suno-helper)`: 投入方式の表示名を `Serial` →「安全モード」、`Queue` →「高速モード」へ改称し、各モードの説明文を速度と安定性の違いが 1 行で伝わる簡潔な文面（安全モード:「1件ずつ完了を待つ、安定性重視のモードです。」/ 高速モード:「最大10件を先行投入する、速度重視のモードです。」）に簡素化した（#1862）。変更は `shared/constants.ts` の `RUN_MODES` 表示ラベル・説明文のみで、内部識別子 `serial` / `queue`（chrome.storage.local の `sunoRunMode` 保存値・run payload・resume state）は互換性維持のため不変。`/suno-helper` SKILL.md の利用者向け `Queue mode` 表記も「高速モード（内部値: queue）」へ追従
- `perf(videoup)`: effect なしの静止画背景を 1 GOP 分だけベイクし、`-stream_loop -1 -c:v copy -t <audio_duration> -shortest` で全尺化する経路へ統合。生成後は ffprobe で映像の読み取りと尺を検証し、1 フレーム超の差または probe 失敗を fail-loud にした（#1681）
- `docs(extensions)`: Chrome 拡張のローカル検証を npm の現行 pnpm 11.11.0 に固定した。`suno-helper` / `distrokid-helper` 共通の pinned install / build / zip、期待 zip、lockfile 無差分の確認手順を共通・各拡張 README、開発 docs、`/suno`、`/automation-release` へ明記した（#1682）
- `fix(distrokid-helper)`: `yt-distrokid-prepare plan` が 35 曲以下の単一 disc には `{coll_slug}` / `{Theme}` を、35 曲超の複数 disc にのみ `disc{N}-{coll_slug}-vol{N}` / `{Theme} Vol.{N}` を生成するよう修正した。build の slug 検証も単一 disc の kebab-case slug を受理する（#1734）
- `docs(wf-new)`: Phase 2c の codex / single_step 分岐に残っていた textless 背景先行の旧フロー記述を、#1611 のテキスト付き thumbnail 先行フロー（テキスト付き `thumbnail.jpg` を先に生成・承認 → 承認済み `thumbnail.jpg` から textless `main.png/jpg` を再生成）へ更新した（#1854）。契約テスト `test_wf_new_routes_codex_and_single_step_through_thumbnail_contract` も新フロー表記をロックするよう追従
- `refactor(repo)`: GitHub owner `daiki-beppu` のハードコード残存（fork 運営者に生成物のズレを生む固定参照）を整理した（#1653）。`yt-doctor` の `automation_package` fail 時の `next_action.cmd` を `automation_update_refs.UPSTREAM_REPO` 定数（official upstream 検証と同じ単一ソース）から組み立てるよう変更し、リテラル重複を削減。`/automation-update` に Step 1-0、`/ext-install` に Step 0 を新設し、両スキルの `gh` / `curl` コマンドの upstream 参照を導入済みパッケージの `UPSTREAM_REPO` から実行時導出する形へ置換。定数から導出できない箇所（`/setup` の bootstrap 用 `uv add`（パッケージ導入前に実行）、prose・doc リンク等）は固定のまま、`.claude/CLAUDE.template.md` に新設した「fork 運用者向け」節（§9）に残存ファイル一覧と `rg` ポインタを明記した。サプライチェーン保護の `_require_official_upstream` / `UPSTREAM_REPO` 自体は変更していない
- `docs(skills)`: `content_model.type` の docs 表記を実装（`ContentModel.type = "release" / "collection"`、`src/youtube_automation/utils/config/youtube.py`）の正に合わせ、`single_release` を `release` に統一した（#1772）。対象は `video-upload/SKILL.md`（完了条件 / Channel Adaptation 表 / release アップロードフロー / コマンドリファレンス）、`video-upload/references/posting-checklist.md`、`channel-new/references/claude-md-template.md`。型名の初出箇所には「release 型（単曲リリース）」の補足を付与し、doc-contract テスト（`tests/test_skill_docs_consistency.py`）の見出し担保も新表記へ追従。無関係な GitHub release 集約テスト名 `test_attaches_both_zips_to_single_release` は誤検知回避のため `test_attaches_both_zips_to_one_gh_release` にリネーム
- `fix(thumbnail)`: `.claude/skills/thumbnail/config.default.yaml` の `image_generation.codex.default_prompt_template` を #1611 のテキスト付き thumbnail 先行フローへ更新し、SKILL.md「既定テンプレート」ブロックと完全一致させた（#1680）。#1502 の textless 背景先行テンプレートが出荷 default に残っており、Phase 2 のテキスト付き候補生成で「タイトルテキストを入れるな」と指示する矛盾があった。channel-new の config-template（`references/config-template/skills/thumbnail.yaml`）も同一テンプレートへ追従。`{title}` の意味論（サムネに焼く見出し + 短いサブタイトルのみ。動画タイトル全文を渡さない — 全文焼き込み事故の再発防止）を thumbnail / collection-ideate の codex 例と config コメントに明文化し、collection-ideate SKILL.md の「textless 背景先行」コメント（parallel / sequential 両分岐）と Next Step / コスト拒否時の旧フロー記述を現行の thumbnail 先行フローへ修正。SKILL.md 記載テンプレートと config.default.yaml の完全一致は `tests/test_thumbnail_skill_assets.py::test_thumbnail_default_config_codex_template_matches_skill_md_block` で機械担保する
- `docs(distrokid-helper)`: SKILL.md の前提チェックに `config/channel/distrokid.json::profile.songwriter` の設定確認を追加した（#1745）。schema 上は任意のまま（CLI バリデーション追加なし）、未設定時は plan / build 前に「設定して進める / フォーム手入力を了承して進める」の 2 択を AskUserQuestion で提示する。ステップ 7 のリリース日提案を「申請日から 4 営業日後の最短日をデフォルト提案（営業日 = 土日除外、祝日は考慮しない）」と明文化し、agent ごとの提案ぶれを排除。あわせて `distrokid.json` に PII（songwriter の本名）が入りうる旨・記入例・`.gitignore` 運用（public リポジトリでは untrack、コミット済みなら `git rm --cached`、履歴残存時は filter-repo 検討）を `references/pii-gitignore.md` に単一ソース化し、SKILL.md の Overview と前提チェックから Read 誘導で接続した
- `docs(suno-lyric)`: `/suno-lyric` の名言取得元 iyashitour.com の安全境界を実サイト構造に合わせて更新した（#1728）。英語名言の原文ページは `/meigen/` 配下ではなく `/archives/<ID>` にあるため、host=iyashitour.com / scheme=https 固定のまま「`/meigen/` 配下のインデックスからリンクで辿った `/archives/<ID>` への 1 ホップ限定」を許可 path に追加（`/archives/<ID>` を起点にした更なる遷移は不可）。別 host / private IP / `..` を含む path / 許可 path 以外の停止規則は従来どおり。SKILL.md の Quote Source Safety 節と config.default.yaml の安全境界コメントを整合させた
- `feat(channel-new)`: 新規チャンネル初期化時のデフォルト `schedule.cadence` を週 3 回（`["tue", "thu", "sat"]`）から毎日投稿（`["sun", "mon", "tue", "wed", "thu", "fri", "sat"]`）に変更した（#1730）。対象は配布テンプレート `.claude/skills/channel-new/references/schedule-template.json` と `yt-channel-init` が生成する `schedule_config.json`（`cli/channel_init_templates.py::_render_schedule`）の 2 箇所。`publish_time`（20:00）・`auto_schedule_enabled`（true）等の他キーは変更なし。既存チャンネルの `schedule_config.json` には影響しない
- `fix(thumbnail)`: OpenAI Image provider の既定 `quality` を `high` から `medium` に変更した（#1697）。provider を OpenAI に切り替えた際に無自覚に高単価 API を叩くのを防ぐため、`high` は `image_generation.openai.quality: high` の明示 opt-in のみとする。`src/youtube_automation/utils/image_provider/config.py::_build_openai` のフォールバック既定値と `.claude/skills/thumbnail/config.default.yaml` の同梱既定値の両方を `medium` にし、thumbnail SKILL.md の provider 切替 runbook に quality 既定値と単価差の注記を追記した
- `docs(live-clean)`: SKILL.md の障害時ガイダンスに Ctrl+C（SIGINT）中断ケースを追記した（#1696）。削除はファイル単位 `rm -f` で idempotent（`workflow-state.json` は保護対象のため再実行時の安全性検証もそのまま機能）であり、スキル再実行で Step 1 / T1 の再スキャンにより残件から安全に継続できることを文書化。再実行時も承認ゲートを改めて通る
- `docs(video-upload)`: SKILL.md の frontmatter description に release 型（単曲リリースアップロード）の発動トリガー語（「楽曲リリースをアップロード」「リリース動画を公開」）と /short-release への棲み分けを追記した（#1692）。従来は collection 型のみ前提に読める記述で、実装は release 型対応済みにもかかわらず発動語が欠けていた。型名表記は実装の正（`ContentModel.type = "release"`、#1772 の用語統一方針）に合わせた
- `docs(skills)`: チャンネル運用系 6 スキル（channel-new / setup / playlist / comments-reply / pinned-comment / community-post）の SKILL.md を 7 観点チェックリストでレビューし、意味・機能を変えない記述改善を適用した（#1678）。channel-new は 3 スキル統合（#1460/#1461/#1499）で 945 行に肥大していた SKILL.md から、方向性検討モード（Step D1〜D5）・再生成モード（Step R1〜R8）・既存チャンネル取り込みモード（取り込み Step 1〜8）の手順詳細を `references/{direction-mode,regeneration-mode,import-mode}.md` へ逐語切り出しして 553 行に削減（本文には目的・前提・完了条件と Read 誘導のスタブを残置、モード判別・新規開設モード・設定 push モード・TTP 完了条件は本文のまま）。playlist / pinned-comment / comments-reply / community-post に「## 完了条件」を明示（既存の終了記述の再掲）、setup の完了条件記述を見出し化、playlist init の「確認」を dry-run 出力提示 + ユーザー応答に具体化、comments-reply は Phase 4 と承認ゲートの間に割り込んでいた「設定スキーマ」節を Phase 5 の後へ移動し Read / Agent ツール記述に Codex 読み替え注記を追加。sonnet-safe #1517（channel-new Step 7 入口ゲート）の適用済み修正は保持
- `docs(skills)`: 戦略・リサーチ系 7 スキル（audience-persona-design / channel-research / collection-ideate / viewer-voice / viewing-scene / discover-competitors / community-draft）の SKILL.md を 7 観点チェックリストでレビューし、意味・機能を変えない記述改善を適用した（#1677）。全 7 スキルの冒頭 60 行以内に「## 完了条件」を明示（既存の出力・終了記述の再掲）、「最新ファイル」検出基準を更新時刻順（`ls -t`）に一意化（audience-persona-design / channel-research / viewing-scene / collection-ideate）、Read / Agent / Task ツール記述に既存定型の Codex 読み替え注記を追加、audience-persona-design Phase 3 の「必要に応じて確認」と community-draft の「interactive に尋ねる」を AskUserQuestion 基準に明確化した。sonnet-safe 群（#1512〜#1524）適用済み修正は保持
- `docs(skills)`: 基盤・配信系 9 スキル（automation-release / automation-update / ext-install / distrokid-helper / live-clean / streaming / wf-new / wf-next / wf-status）を 7 観点チェックリスト（トリガー明確性 / 手順の決定性 / progressive disclosure / 前提条件と失敗時挙動 / 完了条件 / 確認ポイント / Codex 共用互換）でレビューし、意味・機能を変えない記述改善を適用した（#1706）。wf-new の重複セクション見出し `2b. ドキュメント保存` を削除（内容は 2c-1 に既存）し references/scene_phrases.md の参照番号を実セクションに一致、automation-release の prepare/publish 判定条件の排他を明示し PR 本文 heredoc のプレースホルダ置換を注記、automation-update の同梱版取得スニペットを `uv run python` に統一、ext-install の Notes 重複記載を「## 前提」への単一ソース化で解消、streaming の前提に失敗時挙動の lead-in を追加、distrokid-helper のタイトルユニーク化実例テーブルに抜粋注記を追加
- `docs(skills)`: 音楽制作系 7 スキル（suno / suno-lyric / suno-helper / masterup / lyria / videoup / loop-video）を 7 観点チェックリスト（トリガー明確性 / 手順の決定性 / progressive disclosure / 前提条件と失敗時挙動 / 完了条件 / 確認ポイント / Codex 共用互換）でレビューし、意味・機能を変えない記述改善を適用した（#1703）。(1) 7 スキル全てに「完了条件」セクションを冒頭（Overview 直後）へ追加し、後方に散在していた成功基準を先出し（詳細は各 Step を正とする要約でロジック重複なし）。(2) suno-helper の「前提」の拡張ロード済み bullet 重複と loop-video の「前提条件」の ADC bullet 重複を統合。(3) videoup のステップ 4「実行コマンドを案内」を「長時間処理の取り扱い」の background 起動規約と整合する表現へ統一。(4) lyria の Step 3 承認ゲートに確認手段（AskUserQuestion の明示 2 択 + Codex 向けテキスト承認待ち）を明記（承認必須自体は既存要件のまま）。(5) masterup / lyria / videoup / loop-video の「長時間処理の取り扱い」に Codex 等 `run_in_background` 非対応環境向けの `nohup` 読み替えを追記。(6) masterup の Step 5.0（opt-in 音質補正）直後に「Step 5 本体: マスター結合の実行」小見出しを追加し誤読を防止
- `docs(skills)`: 視覚・公開系 8 スキル（thumbnail / thumbnail-compare / short-thumbnail / video-description / video-upload / short / short-release / metadata-audit）の SKILL.md を 7 観点チェックリストでレビューし、意味・機能を変えない記述改善を適用した（#1704）。全 8 スキルの冒頭に既存記述から導出した「完了条件」セクションを追加し、short-thumbnail の前提に失敗時挙動（前工程案内 + 停止）を明記、thumbnail-compare のサブエージェント並列分析に Codex 等サブエージェント非対応環境向けの順次実行読み替えを追記、short / short-release の生成 Step から「長時間処理の取り扱い」の background 必須パターンへの参照を接続、thumbnail に章別の読み順ガイド（progressive disclosure）を追加した
- `docs(skills)`: 分析系 8 スキル（analytics-analyze / analytics-collect / analytics-report / benchmark / channel-status / video-analyze / postmortem / alignment-check）の SKILL.md を 7 観点チェックリストでレビューし、意味・機能を変えない記述改善を適用した（#1705）。全 8 スキルの冒頭に「## 完了条件」を明示（既存の出力・終了記述の再掲）、analytics-analyze / analytics-report の「最新ファイル」検出基準を更新時刻順（`ls -t`）に一意化、analytics-collect の Quick Reference にモード別実行コマンド対応を明記、benchmark / alignment-check の Read / Agent ツール記述に Codex 読み替え注記を追加、alignment-check Phase 5 の「必要に応じて更新」を AskUserQuestion 承認条件に明確化した。sonnet-safe 群（#1512〜#1524）適用済み修正は保持
- **BREAKING** `refactor(repo)`: ADR-0021 に基づき `packages/`（TS core / cli 約 28K 行）と root TS ツールチェーン（`package.json` / `bun.lock` / `bunfig.toml` / `tsconfig.json` / `oxlint.config.ts` / `oxfmt.config.ts` / `knip.json` / root `pnpm-lock.yaml`）を削除し、本リポジトリを Python 版メンテナンスモードに純化した（#1629）。CI の TS レーン（ts-lint / ts-format-check / ts-typecheck / ts-test / ts-knip）と push トリガーの `feat/ts-rewrite`、lefthook pre-commit の oxlint / oxfmt / typecheck、CHANGELOG ゲート（CI / lefthook）の `packages/` / `package.json` 対象、flake.nix devShell の `bun` を撤去。CLAUDE.md の「TS レイヤー（packages/）」節は ADR-0021 参照へ置換。tayk の TS 開発は専用の別リポジトリで行う
- **BREAKING** `refactor(channel-new)`: 旧 `/channel-direction` を削除し、`/channel-new` の方向性検討モード（Step D1〜D5）へ統合した。新規開設モードでは従来どおり方向性・差別化・ポジショニングを聞かず TTP 対象の転写要素だけを確認し、必要な方向性ブレストは同じ `/channel-new` の別モードで `docs/channel/channel-direction.md` に保存する。config 生成用の初期値確認は Step 1 から Step 4 へ分離し、再生成モードは方向性検討モードの成果物を入力にする契約へ更新した（#1499）
- `docs(wf-new)`: workflow-state schema の `assets.music_downloaded` 説明に、Suno 一括 DL 完了と `raw_master` 生成前の中間状態（DL 済み・raw master 未生成）の意味を明記した（#1568）
- `docs(skills)`: 主要スキル 5 件の前後工程 cross-reference を現行ワークフロー基準で補完（#1670）。`/videoup` に前工程 `/masterup`（Suno 系）/ `/lyria`（Lyria 系）を明記、`/thumbnail` の Next Step に Lyria チャンネル分岐（`/lyria`）を追加、`/video-description` に前工程 `/videoup` への参照、`/metadata-audit` の Cross References に前工程 `/video-upload` を追加し、`/analytics-analyze` の When to Use に `/wf-next` 完了（動画公開）から T+7 日後に実行する前提を追記した
- `chore(deps)`: dev 依存（`pytest` / `ruff`）を `[project.optional-dependencies].dev` と `[dependency-groups].dev` の二重宣言から `[dependency-groups].dev` へ一本化した（plan 024）。素の `uv sync` で `ruff` が入るようになり、`--extra dev` 指定は不要（README / ONBOARDING / flake.nix / CI の該当記述を更新）
- `chore(lint)`: ruff の `select` に `B`（flake8-bugbear）/ `RUF` を追加した（plan 024）。`RUF001`/`RUF002`/`RUF003`（全角文字の ambiguous-unicode 検知、日本語コードベースでは誤検知のみ）は ignore、`RUF043`（pytest.raises の正規表現メタ文字警告）は `tests/**` のみ per-file-ignore。新規追加ルールで検出されたバックログ（`B904` の `raise ... from` 欠落、`B905` の `zip()` strict 未指定、`RUF012` の mutable class default、`RUF013` の implicit Optional、`RUF005` のリスト結合、`RUF046`/`RUF059`/`RUF015`/`RUF017`/`B007`/`B017` 等）を機械的に解消した
- `chore(ci)`: 新規 Any 使用を検知する `.lefthook/pre-push/any-usage-gate.sh` を CI の `any-gate` job（PR イベントのみ）としても実行するようにした（plan 024）。従来は client-side lefthook のみで `origin/main` 不在時は self-skip していたため、CI バックストップを追加して実質 advisory だったゲートを強制力のあるものにした

### Removed

- `refactor(cleanup)`: deprecated 表明済みの単発移行スクリプト `yt-fix-timestamps`（`scripts/fix_per_theme_timestamps.py`、2026-03/04 の特定コレクションをハードコード対象とする一括補修用）を削除した（#1673）。`pyproject.toml` の entry point / `cli_entrypoints.py` / `tests/test_fix_per_theme_timestamps.py` / `tests/test_cli_stdio.py` の参照も併せて除去。masterup SKILL.md が本 CLI を現役手順として記述していた矛盾（Step 5.7 / CLI 対応表 / フォールバック手動手順 / 完了条件）も解消した。現行のタイムスタンプ生成は `metadata_generator` の `generate_timestamps()` 系が正
- `refactor(config)`: `/Users/mba/02-yt` 配下の下流チャンネル 6/6 件が `config/channel/*.json` の v2 分割構成でロードでき、旧 `config/channel_config.json` が 0 件であることを確認したため、移行専用の `yt-config-migrate` CLI（entry point / 実装 / テスト / 移行ガイド）を撤去した。channel-new の生成後検証と `yt-automation-update apply` の config smoke check は、loader と localization title placeholder を検証する `yt-doctor` の `channel_config` check に統一した（#1672）
- `chore(deps)`: import ゼロで宣言のみ残っていた直接依存 `seaborn` を削除した（plan 024）。transitive に必要な `pandas` / `matplotlib` は引き続き `[project] dependencies` に独立宣言済み
- `refactor(utils)`: 旧 analytics モノリスの unreachable な残骸（`report_generator.py` / `report_renderer.py` / `analytics_analyzer.py`、計 1,016 行）を削除した（plan 023）。現行の analytics は `analytics_base.py` Protocol + `strategic_analytics.py` / `ctr_analytics.py` 等の mixin 構成に移行済みで、これら 3 ファイルはどこからも import されていなかった。`ctr_analytics.py` の docstring に残っていた `analytics_analyzer._analyze_collection_ctrs` への stale な参照も削除した

### Fixed

- `fix(thumbnail)`: Codex の thumbnail prompt に設定済み composition rules を含めるよう修正した（#1727）。
- `fix(suno-helper)`: Lyrics 欄の不在・注入失敗時に、現行 Suno UI の ARIA 選択状態を read-only で診断し、Prompt / Instrumental なら Write、Simple / Sounds なら Advanced への切り替えを案内するよう改善した。状態を特定できない場合は Advanced / Write / 英語 UI 推奨のチェックリストを表示する（#1899）。
- `fix(comments-reply)`: 同一スレッド内で対象コメントより後に投稿されたオーナー返信を検出し、Studio 等で手動返信済みのコメントへの重複返信を防止した。オーナー返信後の視聴者フォローアップは引き続き候補に含める（#1895）
- `fix(suno-helper)`: Lexical Lyrics 欄で paste 反映検証が失敗した場合に inject retry 後 beforeinput fallback を試し、全方式が失敗したときは entry 名・歌詞長・差分付き診断を出して停止するようにした（#1676）。
- `fix(suno-helper)`: ユーザー操作による `stopped` を赤いエラー扱いにせず、「停止しました。再実行できます。」と通常状態で表示するようにした。
- `fix(suno-helper)`: ダウンロード完了済み collection を popup の一覧から消さず、「完了 N/N」として再表示するように戻した。完了済み collection も選択でき、同じテストを再実行できる。
- `fix(suno-helper)`: playlist 追加前に Lyrics editor など入力欄の focus を外し、Suno が trusted `Cmd+P` を無視して Add to Playlist dialog を開けない問題を修正した。
- `fix(suno-helper)`: Suno の Lexical Lyrics editor で複数行の段落を改行付きで比較し、空文字クリア時は `beforeinput` fallback を使うことで、反映済みでも paste / clear 失敗として停止する問題を修正した。重複 content script が同じ run を二重実行しない DOM lock も追加した。
- `fix(suno-helper)`: Chrome が Suno タブへの静的 content script 登録を取りこぼして overlay が表示されない場合、ページ読込完了時に background から bundle を明示再注入して自己復旧するようにした。通常注入済みなら DOM probe でスキップし、重複起動を避ける。
- `fix(suno-helper)`: Exclude Styles 欄の selector に日本語 UI の placeholder / aria-label（「スタイルを除外」等）を追加し、表示言語が日本語でも欄を検出して値を投入できるようにした（#1840）。
- `fix(suno-helper)`: Suno 新 Create UI の slider リネーム（Weirdness → Bizarreness / Style Influence → Style influence〈小文字 i〉）で aria-label 完全一致セレクタが不一致となり、slider が視認できても `Weirdness slider not found` で run 全体が中断する問題を修正（#1720）。`shared/dom.ts` のセレクタを旧新両ラベルにマッチする case-insensitive substring match（`[role="slider"][aria-label*="weirdness" i], [role="slider"][aria-label*="bizarre" i]` / `[role="slider"][aria-label*="influence" i]`）へ tolerant 化し、slider 未検出時も throw（`FatalRunError`）せず `console.warn` + skip で run を続行するようにした（値は UI で手動設定でき Create を跨いで永続するため中断に値しない）。skip はサイレントにせず、新設の `onSliderSkip` 通知を GENERATING の progress message に載せて overlay / popup の status（`[n/total] 生成待ち…（Weirdness slider を skip しました（値は手動設定できます））`）で観測可能にした。exclude_styles / vocal_gender の fail-loud 契約は従来どおり
- `docs(suno)`: `/suno` ボーカルモードの pattern 数 → 最終 track 数の計算式（1 pattern = 1 prompt entry = 1 採用曲。必要 pattern 数 ≈ track_count + 数%の試聴落選バッファ）を SKILL.md に明記した（#1726）。インストモード節の `ceil(N/2)` 公式と対称の比較表で並記して類推適用の余地を排除し、`ceil(track_count / tracks_per_pattern)` が誤りであること、`pattern_strategy` / `tracks_per_pattern` は 1 パターンあたりの再生成回数の設計であって最終採用数には影響しない（採用は常に 1 グループ 1 曲）ことを SKILL.md と config.default.yaml のコメントに明文化した。曲数不足 prompts を fail-loud で止める機械検証は #1785 が扱う
- `fix(utils)`: `metadata_generator.py::generate_localizations` の Usage & Attribution 本文がハードコードされており、skill-config `usage_attribution_lines`（`config/skills/video-description.yaml`）の上書きが多言語ローカライズ概要欄に反映されない問題を修正した（#1650）。姉妹メソッド `generate_complete_collection_metadata` と同じ `_video_description_config.get("usage_attribution_lines", [])` 参照に統一。これに伴い、上書きなしのデフォルト時も localizations の本文が旧ハードコード文言（`• Original AI composition` / `• Free for personal & non-commercial use` / `• For commercial use, check the platform's AI content policy` / `• Redistribution prohibited`）から `config.default.yaml` の文言（`• This music is original AI composition` / `• Free to use for personal & commercial projects` / `• Attribution appreciated but not required` / `• Redistribution as-is prohibited`）に変わり、デフォルト言語概要欄と同一になる
- `fix(masterup)`: `02-Individual-music/` に音源が揃っているのに playlist URL 未指定を理由に「URL を教えてください」と案内して停止する誤導線を SKILL.md から除去した（#1743）。Step 1.6 の title list 取得を「第1引数の URL → `workflow-state.json::planning.music.suno_playlist_url` の保存済み URL（再質問しない）→ どちらも無ければ title list の提示 or 混入込み続行の明示確認の 2 択分岐」の解決順序として明記し、引数の解釈・前提・Quick Reference にも URL 省略可であることを明示した。#1530 の fail-loud 突合ゲート契約（silent 続行禁止・混入込み続行はユーザー明示指示のみ）と Step 1.5 の DL 完全性チェック（音源不足時は不足数を提示して停止）は変更なし
- `fix(loop-video)`: 既定 `prompt_template` が `{motion_clause}` の直後に強度断定「— subtle, gentle, barely perceptible, natural.」を必ず付加していたため、`motion_targets` で "clearly rolling ocean waves" 等の強い動きを指定してもテンプレ側の弱化文言と自己矛盾し Veo がほぼ静止画を生成していた問題を修正（#1747）。強度断定をテンプレから除去し、動きの強度は motion_targets の文言のみで制御する方式に変更（静かな動きは "subtle steam rising from coffee" のように強度語を対象側に書く）。`motion_targets` 未指定時は従来どおり `default_prompt`（subtle 系の静的シーン向け文言）へフォールバックするため後方互換、チャンネル側 `config/skills/loop-video.yaml` の `prompt_template` 上書きも引き続き有効
- `fix(veo)`: `smooth_loop` の後処理が `loop.mp4` → `loop_raw.mp4` の rename を存在チェックなしで行っており、再生成時に前回の `loop_raw.mp4` が残存していると FileExistsError でクラッシュ（POSIX では無警告上書き）する問題を修正した（#1748）。rename 前に残存 raw を検出し、`generate_loop_video` の `loop-v{n}` 退避と同じ連番方式で `loop_raw-v{n}.mp4` へ退避してログに明示する（raw は Veo 生成・課金済みの原本のため削除しない）。`/short-loop` 経路（`short-loop_raw.mp4`）と `--smooth` 単独経路にも同様に適用される。退避ファイルの保持数上限は #1654 のスコープ
- `fix(audio-gen)`: Suno がダウンロード ZIP 内のファイル名からアポストロフィを除去する（例: `Greed's Rhythm` → `Greeds Rhythm.m4a`）ため、`suno_downloaded_archive.py` の名前照合が失敗して該当トラックがスキップされ、`placed_count < expected_count` で ZIP 展開全体がロールバックされる問題を修正した（#1787）。`_build_name_to_index` で index 構築後にアポストロフィ（`'` / `’`）除去版キーを `setdefault` で fallback 登録する（exact match キーを優先、他の記号は Suno 仕様未確認のため除去しない）
- `fix(lyria)`: `yt-generate-lyria-master` のセグメント数算出（`_resolve_segment_count`）に hard cap（`_MAX_SEGMENT_COUNT = 60`）を導入した（#1698）。従来は `target_duration_min` の桁ミスで Lyria API リクエスト（= Vertex AI 課金）が無制限に発行され得たが、上限超過時は 60 に clamp して warning を stderr に出力する。上限以内の算出結果は従来どおり
- `fix(scripts)`: `bulk_update_descriptions_from_md.py`（`yt-bulk-update-desc`）が `videos().update(part="snippet")` の body を手組みで列挙しており、`defaultAudioLanguage` を含めていなかったため、このツールを通した全動画で音声言語設定が消えていた問題を修正。`defaultLanguage` 未設定の動画に `"en"` を注入していた挙動も廃止。`bulk_update_synthetic_media.py::build_update_body` と同じ read-modify-write 方式（`build_snippet_update_body`）に統一し、mutable 6 キー（title / description / tags / categoryId / defaultLanguage / defaultAudioLanguage）だけを whitelist で保持する
- `fix(suno-helper)`: queue mode で全 entry 投入後に duration guard を一括実行し、範囲外 clip のみだった entry を `ENTRY_FAILED` として `failedIndices` に保存するようにした（#1762）。対象 entry は「失敗分のみ再実行」導線に載せ、playlist 追加は保留する。部分的に OK clip がある entry は OK clip を accepted として `DONE` にし、duration filter 未指定時は `DEFAULT_DURATION_FILTER` で検査する。
- `fix(suno-helper)`: queue mode の `clipIdsByEntry` を投入前後の Set 差分で捕捉し、entry retry 中に遅延観測された clip ID も同じ entry へ帰属させるようにした（#1762）。DOM-only ACK で clip ID が未観測の entry は fatal 停止せず、finalizer の warn + `DONE` 縮退へ到達する。
- `fix(agents)`: `_tracking_io.py::_save_tracking` を tmp ファイル + `os.replace` によるアトミック書き込みに変更し、アップロード中のクラッシュで `upload_tracking.json` が truncate され resume 情報を喪失する不具合を修正した（plan 020）。`_load_tracking` は破損 JSON（`JSONDecodeError` / `UnicodeDecodeError`）を検出すると `*.json.corrupt` へ退避してから `None` を返し、無言で握りつぶさず証拠を保全するようにした
- `fix(agents)`: Complete Collection（`_complete_collection_executor.py`）と Shorts（`short_uploader.py`）のアップロード経路で `QuotaExhaustedError`（HTTP 429・リトライ可能）を通常の例外と区別するようにした（plan 020）。Complete Collection 側は tracking を `status="failed"` にせず新 action `complete_collection_quota_exhausted` を返し、resume session URI を温存したまま次回実行に委ねる。Shorts 側は `details.retryable=True` / `retry_after_seconds` を結果に含める
- `fix(utils)`: `upload_core.py::_compress_thumbnail` が全品質での圧縮に失敗した場合に一時ファイルをリークしていた不具合を修正した（plan 020）。失敗時は temp ファイルを削除してから元ファイルパスを返し、ffmpeg が一度も出力しなかった場合の `FileNotFoundError` も回避する
- `fix(analytics)`: `analytics-collect` の uploads playlist 二重取得を解消し、`video_listing.py` の例外握りつぶしと TZ 境界ズレを修正（plan 022）。`VideoListingMixin.get_all_channel_videos` にインスタンスキャッシュ（`_all_videos_cache`、空リストは非キャッシュ）を導入し `refresh: bool = False` 引数を追加、`strategic_analytics.py` / `analytics_system.py` からの再呼び出しが同一プロセス内で API を再度叩かないようにした。`get_all_channel_videos` / `get_recent_videos` の生 `except Exception` を削除し、`HttpError` は `YouTubeAPIError.from_http_error` で変換して re-raise するよう変更（認証切れ・クォータ枯渇が「動画 0 本」として無言で握りつぶされなくなった）。`get_recent_videos`（`video_listing.py`）と `get_combined_analytics`（`strategic_analytics.py`）の直近 N 日フィルタを naive `datetime.now()` と UTC `publishedAt` の比較から `datetime.now(timezone.utc)` の aware 比較へ統一し、JST/UTC の 9 時間ズレによる境界直後動画の取りこぼしを解消した
- `fix(skills)`: 基盤・配信系 9 スキル（automation-release / automation-update / ext-install / distrokid-helper / live-clean / streaming / wf-new / wf-next / wf-status）の整合性監査で検出した記述ドリフトを実装準拠に修正（#1688）。`automation-release/SKILL.md` と `references/changelog-promotion.md` の旧リポジトリパス `/Users/mba/02-yt/automation` を実パス `/Users/mba/02-yt/00-automation` に更新し、実在しないスキル参照（`commit-convention` / `/pr` / グローバル `/release`（`~/.claude/skills/release/`））を CLAUDE.md の日本語 Conventional Commits 規約参照・一般表現へ差し替え（automation-update も同様）。`distrokid-helper/SKILL.md` の verify 検証項目から release_date を error 扱いする記述を修正（実装 `distrokid_prepare.py` は `planning.publish_target_at` 欠落を warning 止まりとし、error は cover サイズ / タイトル重複 / >35 曲のみ）。`streaming/SKILL.md` の `terraform plan` コメントを実リソース構成（`tls_private_key` / `vultr_firewall_group` / `vultr_firewall_rule×N` 含む）に更新。`wf-new/references/schema.md` に実在するトップレベルキー `scene_phrases`（`yt-populate-scene-phrases` が投入）の定義を追加し、`assets.music_downloaded` が初期化時には含まれない遅延追加キーであることを明記。ext-install / live-clean / wf-next / wf-status はドリフト検出なし
- `fix(skills)`: チャンネル運用系 6 スキル（channel-new / setup / playlist / comments-reply / pinned-comment / community-post）の整合性監査で検出した記述ドリフトを実装準拠に修正（#1675）。`setup/SKILL.md`: `yt-doctor` のカテゴリ別チェック構成表を現行実装に合わせて更新（bootstrap 6→7 check に `numbered_duplicates`、channel 1→3 check に `playlist_config` / `playlist_create_dry_run`、data 3→4 check に `initial_setup_readiness` を追加）し、新規 4 check の対応手順（Steps）を追記。`channel-new/SKILL.md`: Step 3 の「config 未生成由来の許容 fail」一覧に `playlist_config` / `playlist_create_dry_run` / `initial_setup_readiness` を追加、Step 9 の `yt-benchmark-collect --keep-thumbnails` を非推奨 no-op フラグ（サムネイルは常に保持）のためフラグなし表記へ修正、統合前の旧称「初回モード」6 箇所を現行モード名「新規開設モード」に統一（`references/gcp-bootstrap.md` の同表記も含む）。`channel-new/references/config-template/skills/thumbnail.yaml`: 実在しない CLI 名 `yt-download-benchmark-thumbnails` への言及を実体の `/benchmark`（`yt-benchmark-collect`）に修正。`channel-new/references/directory-structure.md`: 正準構造・作成コマンドに `yt-setup-dirs` が実際に作成する `docs/channel/personas/` / `research/` を反映。playlist / comments-reply / pinned-comment / community-post はドリフト検出なし
- `fix(skills)`: 戦略・リサーチ系 7 スキル（audience-persona-design / channel-research / collection-ideate / viewer-voice / viewing-scene / discover-competitors / community-draft）の整合性監査で検出した記述ドリフトを実装基準で修正（#1674）。`channel-research/SKILL.md` の thumbnail スキル参照を現行 SKILL.md に存在しない「TTP Swap モード」から `single_step` モード（TTP 推奨実装）表記に更新、`collection-ideate/SKILL.md` の Phase 1-1 戦略ドキュメントからどこにも生成されない `docs/channel/strategy.md` を除去して実在する `/channel-new`（方向性検討モード）の方向性決定記録と `docs/channel-research.md` の参照に置換し、設定キー `ideate.objects`（4 箇所）を実装 `thumbnail_check.py` が読むトップレベル `objects` に統一（`references/object-design-examples.md` 例 2 の `ideate` ラッパー付き JSON もトップレベル `objects` の YAML に修正）、`discover-competitors/SKILL.md` の seed 抽出元の不存在キー `descriptions.template_note` を実在する `descriptions.perfect_for` に修正、`community-draft/SKILL.md` の config パス 4 箇所を実ファイル構造 `community_draft.templates.*` に合わせ、不存在キー `content.json::genre.label`（2 箇所、実装 `Genre` は `primary` / `style` / `context` のみ）と `signature_template`（実キーは `append_footer.signature`）、変数解決元の誤記（channel-config の `objects.swappable` → `workflow-state.json::planning.signature_objects` / `config/channel/community-draft.json::shared_variables`）を実装準拠に修正。audience-persona-design / viewer-voice / viewing-scene はドリフト検出なし
- `fix(skills)`: 視覚・公開系 8 スキルの整合性監査（#1685）で検出した記述ドリフトを実装準拠に修正。`/short`: 実在しない `yt-upload-shorts --ignore-interval` フラグの記述を削除（bypass は config 側の `min_hours_between_shorts_per_collection` 調整で行う）、`yt-shorts-bulk-update-loc` は collection パス引数を取らず `collections/live/` 全件走査であることを明記、loop-mp4 クロップ位置は `generate-shorts.sh` 側 env（`SHORT_CROP_X`）ではなく中央固定であり center 以外は手動 ffmpeg 実行が必要と修正。`/short-thumbnail`: `yt-generate-shorts-loop` の Veo 設定は skill-config `short`（`.claude/skills/short/config.default.yaml` の `veo` セクション / `config/skills/short.yaml`）を読む実装に合わせて設定表を修正し、`yt-generate-image` が生成しない「自動生成 `short.jpg`」と固定解像度 1536x2752 の記述を削除。`/video-upload`: `references/scheduled-publish.md` の関連リンクを `_calculate_publish_at` / `_scheduling_enabled` の実体 `agents/_published_dates.py` に修正
- `fix(skills)`: 分析系 8 スキル（analytics-analyze / analytics-collect / analytics-report / benchmark / channel-status / video-analyze / postmortem / alignment-check）の整合性監査で検出した記述ドリフトを修正（#1687）。`analytics-collect/SKILL.md` の出力例を実装の実ファイル名 `data/analytics_data_YYYYMMDD_HHMMSS.json` と `config/channel/meta.json` の `channel.name` 参照に更新、`channel-status/SKILL.md` から `yt-channel-status` が実装していない「いいね数・コメント数」「制作中コレクション（workflow-state.json）表示」の記述を削除して実出力（再生数・総視聴時間・平均視聴時間）と `/wf-status` への案内に置換、`postmortem/SKILL.md` の実装参照 3 件を現行実体に更新（`strategic_analytics.py::_collect_top_videos`（不存在）→ `get_combined_analytics`、`benchmark_collector.py:378-394`（現在は collect_playlists の行域）→ `benchmark_collector.py::collect_channel`、schema_version=3 の生成元 `collection_uploader.py` → `agents/_tracking_io.py`（分離済み））。analytics-analyze / analytics-report / benchmark / video-analyze / alignment-check はドリフト検出なし
- `fix(skills)`: `video-description/SKILL.md` の「ハッシュタグ 13 個」と `channel-new/references/config-generation-rules.md` の「5 個程度」の数値矛盾を解消（#1669、監査 M-10）。実装 `metadata_generator.py` は `config/channel/content.json::descriptions.hashtags` をそのまま出力し個数を強制しないため、両ファイルを `descriptions.hashtags` 単一ソース参照 + 目安 5 個程度（examples / fixtures は 3 個、YouTube がタイトル下に表示するのは先頭 3 個）へ統一した
- `fix(skills)`: `video-analyze/SKILL.md` の「呼び出し側スキル」から、現行 `/lyria` に実装が存在しない `bgm_arc` 平均読み込み・`composition.json` フェーズ境界・`phase.at_min` の記述（DJ Engine 時代の phase 設計の残骸）を削除した（#1651）。あわせて `.claude/CLAUDE.template.md` の音源生成表・音楽エンジン比較表の `/lyria` 表記を現行実装（プロンプト + API 入力パラメータ設計）に合わせて修正
- `fix(suno-helper)`: queue 実行の resume payload 境界で `submittedClipIds` / `playlistExpectedClipCount` を fail-loud に検証し、未完了 clip を保持した再開時に不正な raw payload が playlist 完了待ちへ流れ込まないようにした（#1586）。
- `fix(suno-helper)`: SKILL.md の進捗 phase 表に queue mode の `submitted` を追記（#1586）。shared/constants の PHASE と skill doc の照合テスト `test_suno_helper_phase_table_matches_shared_phase_constants` が新 phase 追加に追従しておらず fail していた
- `fix(extensions)`: suno-helper の Playwright e2e が `SyntaxError: Named export ... not found（CommonJS module）` で全滅していた CI 失敗を修正（#1586 ブランチで顕在化）。根本原因は #1629（ADR-0021）の root `package.json`（`"type": "module"`）削除で `extensions/shared/` が Node ESM loader に CJS スコープ判定されるようになったこと。`extensions/shared/package.json`（`type: module`）を新設してスコープを復元した。あわせて #1586 が e2e に追加していた queue runner / completion gate の純ロジックテスト 3 件（page 不使用）を `tests/queue-runner.test.ts`（vitest）へ移設し、e2e は実ブラウザ layout を要する DOM スモークに限定した
- `fix(suno-helper)`: reload 後の resume / playlist 再実行で、保存済み clip が照会時点で complete 済みだと完了待ちゲートが永遠に pending 扱いして 10 分の stall timeout まで空回りし偽 ERROR で停止する回帰を修正（#1586 レビュー指摘）。active feed poll（`FEED_V3_POLL_RESPONSE`）の応答は `ClipTracker.applyRequestedStatuses` で未知+終端 clip も登録する（passive `FEED_CLIPS` の「未知+終端は捨てる」規則は据え置き）。あわせて同レビューの指摘を反映: `retryPlaylist` の完了待ち中に popup が `[1/0] 注入中` を表示し続ける問題へ待機中 progress を追加、queue runner の中断分岐が `isEntrySubmitted` へ `EntryRunResult` を誤って渡していた型不整合をシグネチャ縮小（`(index) => boolean`）で解消、no-op だった `resolveQueueFatalInterruptIndex` を削除、entry 表示名 fallback（`title ?? name`）を `entryDisplayName` に一本化、payload 検証で `-0` を非負整数/数として拒否、run mode storage I/O の未処理 rejection に warn fallback を追加、実行中は投入方式ラジオを無効化、`RUN_MODE_ORDER` を `RUN_MODES` のキーから導出、queue 投入ループの冗長な固定 25ms sleep を除去、`content-run-preflight` の `waitForQueueSlot` 既定モックを実装呼び出しへ戻し空 queue 回帰テストの空洞化を解消
- `fix(skills)`: lifecycle skill の起動文字列を `bunx tayk <cmd>` から `uv run yt-<cmd>` へ戻した（#1625）。tayk は次世代版 CLI で現時点では運用未使用（実装は別リポジトリへ分離予定）のため、#965 で置換した表記のままではスキルを読んだ AI 実行者が未実装 subcommand（suno: `video-analyze` / `suno-verify`、masterup: `suno-audio-cleanup` / `suno-verify-playlist` / `fix-timestamps` / `finalize-master` / `apply-rain-layers` / `suno-select-tracks` ほか）で実行不能になっていた。対象は masterup / suno / suno-lyric / suno-helper / thumbnail / video-upload / video-description / wf-new / wf-next / playlist / analytics-collect / distrokid-helper の SKILL.md・references・config.default.yaml（wf-new が references として同梱する `yt-init-collection` の復旧ヒント文言も同様に戻した）。起動文字列のみの置換で、周辺の手順・節構成・TS 実装（packages/）は変更しない。回帰テストは方針を反転し、tayk cutover まで lifecycle skill に `tayk` 表記が入らないことを担保する `tests/test_lifecycle_skills_no_tayk.py` へ改称・書き換えた
- `fix(skills)`: 音楽制作系 7 スキル（suno / suno-lyric / suno-helper / masterup / lyria / videoup / loop-video）の整合性監査で検出した記述ドリフトを修正（#1432）。`suno/SKILL.md` の slug 自動実行 argv 例に残っていた `["uv", "run", "bunx tayk video-analyze", ...]` の混在表記を `["bunx", "tayk", "video-analyze", ...]` に統一、`suno/references/suno-examples.md` から実装に存在しない設定キー `banned_adjective_free_instruments` への言及を削除、`loop-video/SKILL.md` の `generate_videos.sh` バージョン表記（v11.0 → v14）とループ背景の正規化 CRF 表記（20 → 22）を現行実装に合わせた
- `fix(distrokid-helper)`: `ext-v0.2.3` リリース前に DistroKid Helper の manifest / popup 表示名へ残っていた `(TEST)` 接尾辞を外し、配布 zip が本番名 `DistroKid Helper` として表示されるようにした。
- `fix(videoup)`: `generate_videos.sh` の overlays 経路で `overlays.audio_visualizer.enabled` が false/未設定（`subscribe_popup` のみ有効等）のとき、`AUDIO_LABEL="1:a"`（生の入力ストリーム指定）を最終 ffmpeg コマンドが常に `-map "[${AUDIO_LABEL}]"` とブラケットで囲むため `-map "[1:a]"` という無効な filtergraph ラベル参照になり `Output with label '1:a' does not exist in any defined filter graph` で失敗するバグを修正。音声 map を出し分ける方式とし、(1) 音声をフィルタしない場合は生ストリーム指定のままブラケットなしで `-map 1:a` する（m4a/aac マスターの `-c:a copy` を温存）、(2) 音声が filter_complex を通る場合（`audio_visualizer` 有効 or loudnorm 統合時）はブラケット付き map + 音声再エンコードを強制する。後者により、filtergraph 出力へ `-c:a copy` を要求して `Streamcopy requested for output stream fed from a complex filtergraph` で失敗する潜在バグ（`audio_visualizer` 有効 + m4a/aac マスターの組み合わせ）も解消。下流チャンネルリポジトリで実際に再現（`overlays.enabled=true` + `subscribe_popup.enabled=true` + `audio_visualizer` 未設定の組み合わせ）。
- `fix(suno-helper)`: `weirdness` / `styleInfluence` セレクタに日本語ラベル（`ユニーク度` / `スタイルの影響度`）の tolerant match 対応を追加し、`setLyricsValue` の Lexical 反映確認に行頭・行末の空白差異を吸収する正規化（`normalizeLexicalText`）を導入した（#1872）

### Migration

所要時間の目安: 5〜10 分

local fix 衝突注意:
- suno-helper: queue mode 追加・DOM signal 変更・resume payload 検証強化など大幅改修。local fix があれば sync 時に上書きされる可能性が高い
- channel-new: `/channel-direction` を削除し方向性検討モードへ統合、SKILL.md 本文を `references/{direction-mode,regeneration-mode,import-mode}.md` へ切り出し。`/channel-direction` を参照する local fix は要更新
- videoup: overlays 音声 map の ffmpeg バグを修正。同箇所を local fix していた場合は要確認
- distrokid-helper: 拡張 manifest/popup の表示名修正のみ、影響小

サマリ:

- BREAKING: `packages/`(TS core、約28K 行)と root TS ツールチェーンを削除し、本リポジトリを Python 版メンテナンスモードに純化(ADR-0021、#1629)
- BREAKING: `/channel-direction` を `/channel-new` の方向性検討モードへ統合(#1499)
- suno-helper に queue mode(並列投入で生成時間短縮)を追加、関連バグ修正多数(#1586, #1762)
- skill-config 機構の適用を6 スキル(discover-competitors / live-clean / postmortem / video-upload / analytics-report / metadata-audit)へ拡大(#1669)
- videoup の ffmpeg フィルタグラフバグ、analytics-collect の重複取得・TZ 境界バグなど計 12 件の Fixed

## [5.5.16] - 2026-07-06

### Added

- `feat(suno)`: `/suno` と `/suno-lyric` に generator-reviewer 分離の意味的品質検証フローを追加した（#1485）。生成は subagent / 別コンテキストに委譲し、reviewer は成果物 JSON（`suno-prompts.json` / `suno-lyrics.json`）と共通ルーブリックだけを読んで entry ごとに `PASS` / `FAIL` + 理由を判定する。`suno-lyrics.json` には reviewer-only の `review_context` を含め、JSON だけで theme / scene / mood / persona / quote essence を判定できる契約にした。`yt-suno-verify` 通過後に LLM semantic review を実行し、`FAIL` entry のみ最大 2 周まで再生成、上限到達時は残課題をユーザーへ引き継ぐ
- `feat(suno)`: `/suno` / `/suno-lyric` の成果物を検証する `yt-suno-verify` CLI を追加。`suno-patterns.yaml` / `suno-prompts.json` / `suno-lyrics.json` の曲数、entry name 整合、歌詞構造、`genre_line` 文字数を Suno UI 投入前に fail-loud で確認できるようにした（#1484）
- `feat(helper)`: `yt-collection-serve` に `GET /server-info` とチャンネル別 `*.localhost` の canonical URL 表示を追加し、suno-helper / distrokid-helper の popup がローカル配信元候補を保存・選択できるようにした（#1352）。既定候補は `http://youtube-automation.localhost:7873` と legacy `http://localhost:7873` を併存し、複数チャンネルのサーバーを label 付きで切り替えられる
- `feat(video-description)`: `BAHMetadataGenerator.generate_timestamps()` / `format_timestamps_text()` に `loops` パラメータを追加した。master をループ生成しているコレクション（`yt-generate-master --loop N` / `--target-duration`）で全ループ分のチャプターを機械展開できる。2 周目以降の開始秒は 1 周目と同じクロスフェード算術（`int(current + duration - crossfade)`）で連続計算し、各行に 1 始まりの `loop` フィールドを付与（2 周目以降のタイトル装飾は呼び出し側の LLM リネームに委ねる）。既定 `loops=1` は従来挙動と完全互換。従来は 1 ループ分しか生成できず、全ループ展開運用のチャンネルでは毎回 LLM が手計算していた
- `feat(masterup)`: `/masterup` の playlist 取得直後に playlist 曲名 × `suno-prompts.json` entry name の突合ゲート `yt-suno-verify-playlist` を追加した。別コレクション曲の混入（unknown）・生成漏れ（missing）・clip 不足（underfilled、既定 2 clip/entry・`--expected-clips-per-entry` で調整）を fail-loud で検出し、非 0 終了時は Step 3（ダウンロード）へ進まない。曲名は `/suno` が Song Title 欄へ注入する `{name_jp} — {name_en}` を照合キーとし、NFKC・空白圧縮・casefold で表記ゆれを吸収する。背景: 最新セット未完のまま前後コレクションの曲が playlist に混入して master 化される事故の再発防止（下流チャンネル実例: 深夜コレクションに昼テーマ 2 ペア混入 + 深夜 2 entry 未生成）
- `feat(collection)`: コレクション標準骨格の検証・補完 CLI `yt-collection-preflight` を追加（#1494）。`01-master/` 等の必須サブディレクトリ欠落を fail-loud で検知し、`--fix` で冪等・非破壊に補完する。骨格定義は `youtube_automation.utils.collection_paths.REQUIRED_SUBDIRS` に一本化し、`yt-init-collection` の scaffold も同定義を共有。`/wf-new`（init 直後の検証）/ `/wf-next`（フェーズ処理前のプリフライト）/ `/suno-helper`（サーバー起動前のプリフライト）/ `/wf-status`（詳細表示に骨格行）へ導線を追加し、`/wf-new` SKILL.md の scaffold 説明から漏れていた `01-master` / `02-Individual-music` の記載も修正
- `feat(thumbnail)`: thumbnail 候補の自動選択を標準化する `yt-thumbnail-auto-select` CLI を追加。TTP 参照画像プール（`image_generation.gemini.reference_images.default`）の特徴量 centroid に最も近い候補を `10-assets/thumbnail.jpg` として自動確定する。`config/skills/thumbnail.yaml` の `image_generation.auto_selection.enabled: true` で opt-in（未設定チャンネルは従来の手動承認フローのまま）。dry-run / apply を分離し、apply 時は `workflow-state.json` に選択候補・distance・ランキング・実行時刻の監査ログを記録。候補なし・参照画像なし・16:9 逸脱・確定済みサムネ上書きは silent fallback せず明示エラーにする（#1370）
- `feat(cli)`: 下流リポの automation 追従を機械実行する `yt-automation-update` CLI を追加（#1473）。`check` が実行場所・pin 形式（inline table / URL 直接参照の tag pin、main 追従、sha pin）・upstream 最新リリースとの差分を判定し exit code（0=最新 / 1=差分あり / 2=エラー）で返す。`apply` が pin 書き換え → `uv lock` → `yt-skills sync`（skills / claude-md 両 asset）→ smoke check（`yt-skills list` / `yt-config-migrate verify`）を順に実行し、失敗ステップを明示して非 0 終了する。commit / push は責務外（スキル・人間側に残置）
- `feat(video-description)`: `yt-title-duplicate-check` に YouTube タイトル上限（100 codepoint）の前倒しチェックを追加した。超過時は `--strict` に関係なく exit 1 で報告し、`/video-description` の品質チェックにも「100 codepoint 以内」を明記。upload preflight（`agents/_preflight.py`）まで持ち越すと quota と時間を浪費するため、タイトル案の保存前に検出する（下流チャンネル実例: 104 codepoint でアップロード時に fail、2026-07-05）
- `feat(thumbnail)`: サムネイル文字フォントを安定して指定できる決定的合成経路を追加（#1332）。`yt-thumbnail-text` CLI が textless 背景（`main.png` 系）に実フォントファイル（.ttf/.otf/.ttc）を Pillow で描画し、同一の背景・テキスト・設定なら常に同一の出力を生成する。フォント指定は skill-config `image_generation.gemini.thumbnail_text.overlay`（`config/skills/thumbnail.yaml`）で行い、フォント未設定・ファイル不在時は理由と代替手順（AI 経路へのフォールバック含む）を明示して停止する。AI プロンプト経路向けにも `single_step.typography_clause` を追加し、SKILL.md に 2 経路の使い分けを示す「フォント安定化」章を新設
- `feat(suno)`: `/suno` の Style プロンプト生成に entry ごとの自動バリエーション機構（`style_variation`、既定で有効）を追加。`genre_line` のコアジャンルを維持したまま texture / rhythm feel の descriptor を entry 通し番号ベースの決定的ローテーションで Style 第 1 行へ付与し、Suno V5.5 での楽曲同質化を防ぐ。先頭 entry は base style を維持（単一 entry の既存コレクションは出力不変）、`style` variant の明示 override がある entry は従来どおり優先、`style_variation.enabled: false` で従来動作へ戻せる。全 entry の Style 文が完全一致する組は生成時に警告する（#1456）
- `feat(wf-next)`: `config/channel/workflow.json::workflow.wf_next.skip_manual_mastering`（default `false`）を新設。`true` のとき `/wf-next` のマスター音源検出（2-B）で `01-master/` に別ファイルが無くても `assets.raw_master` をそのまま `assets.master_audio` として採用し `phase: "mastered"` へ進む（raw=final 運用）。`approval_gates.audio` とは独立で、後方互換（未設定は従来通り停止）。docs/workflow-cheatsheet.md のよくある質問に設定手順を追記（#1449）

### Changed

- `docs(claude-md)`: 配布用 `CLAUDE.md` テンプレートの行動原則に自律実行方針を追加。ユーザー確認が必須でない限り合理的な仮定を置いて調査・実装・検証・簡潔な報告まで進めることと、公開・削除・課金 API・外部投稿・機密情報・不可逆操作は明示確認が必要な境界であることを明記した（#1608）
- `refactor(suno-helper)`: popup の実行モード選択（Fast / Balanced / Safe）を廃止し、content 実行時のペーシングを Balanced 固定にした。legacy `sunoSpeedPreset` が chrome.storage.local に残っていても実行設定へ反映せず、README と `/suno-helper` スキルの手順から mode 選択・preset 永続化の説明を削除した（#1573）
- `docs(thumbnail)`: `/thumbnail` の標準手順を textless `main.png/jpg` 背景先行に変更し、承認済み背景を参照してテキスト付き `thumbnail.jpg` を生成する契約へ更新した。`single_step` / `two_phase` / codex 経路、TTP チェックリスト、prompt 保存、下流スキルの入力説明、フォント指定失敗時の実行時ガイダンスも同じ順序へ揃えた（#1502）
- `refactor(suno-helper)`: 旧 Suno playlist capture 互換 route（`POST /suno/playlists`）と `write_suno_playlists()` / `normalize_suno_title()` / `--playlist-capture-*` を撤去し、DistroKid release 記録用の capture root を `--distrokid-capture-root` に分離（#1301）
- `docs(distrokid)`: `/distrokid-prep` スキルを `/distrokid-helper` に改名し、参照スクリプトと docs/features の表記を同期（#1350）
- `feat(video-analyze)`: `yt-video-analyze` を全尺解析から動画冒頭のクリップ窓解析（既定 900 秒 = 15 分、skill-config `analysis_window_sec` で上書き可）に変更。Gemini へ渡す Part に `video_metadata`（`start_offset` / `end_offset`）を付与して冒頭 2〜3 曲相当のみを解析し、長尺 Complete Collection の API コストを削減する。プロンプトをクリップ窓前提（`bgm_arc.outro` は窓内終盤、`scene_timeline` / `editing_metrics` は窓内対象）に整合させ、SKILL.md に解析後のレポート検証ステップ（窓超過タイムスタンプ・スキーマ欠落・不自然値の subagent レビュー）を追加。下流 `/suno` にも冒頭クリップ窓データである旨を注記した（#1495）
- **BREAKING** `refactor(skills)`: `/channel-setup` スキルを削除し、`/channel-new` に統合した。詳細セットアップ/再生成（旧 Step 1〜8）は再生成モード（Step R1〜R8）、設定 push（旧 Step 9: `yt-channel-settings` diff / push / pull）は設定 push モードとして `/channel-new` が文脈から自動判別して受ける。共通テンプレート・スクリプト置き場は `.claude/skills/channel-setup/references/` から `.claude/skills/channel-new/references/` へ移設し、競合 branding snapshot 取得はインライン Python を廃止して `references/fetch_branding_snapshot.py` に一本化。`yt-doctor` / preflight の `/channel-setup` 案内文言と CLAUDE.md / AGENTS.md のスクリプト配置規約も `/channel-new` 系へ更新した。下流リポジトリは `yt-skills sync` の prune で追従する（#1461）
- `refactor(automation-update)`: `/automation-update` スキルの機械的ステップ（実行場所判定 / pin 形式判定 / 差分判定 / pin 書き換え / `uv lock` / sync / smoke check）を `yt-automation-update` CLI 呼び出しに置き換え、スキルは判断ポイント（リリース要約 / local fix 衝突 / 同意取得 / コミット）専任に薄型化（#1473）
- `feat(hooks)`: review 頻出パターンのうち機械検出可能なテスト差分ゼロと広すぎる Any / any 型注釈を lefthook pre-push で検出するゲートを追加。`SKIP_TEST_DIFF=1` でテスト差分警告のみ明示 skip できるようにし、Python 未使用コード検出は既存 Ruff `F` 系継続、TS 未使用 export / dead code は既存 `ts-knip` 継続として docs に採否根拠を記録した（#1510）。その後の review-takt-default 指摘を受け、(1) any-usage-gate のスコープを `src/` / `tests/` / `extensions/` / `packages/` 限定からディレクトリ非依存の全 `*.py` / `*.ts` / `*.tsx` に拡大（`.claude/skills/*/references/*.py` 等も対象化）、(2) Python 側で `from typing import Any` 直接 import 経由の裸 `Any` 使用も検出、(3) test-diff-gate の `extensions/*/lib/*.test.ts` が lib 判定に先取りされテスト差分ありなのに誤警告するバグを修正、(4) test-diff-gate に対応テスト差分ありなら警告しない成功パスの契約テストを追加、(5) lefthook の「同一 hook で use_stdin を持てるコマンドは 1 つ」制約に対応するため test-diff-gate / any-usage-gate を独立コマンドから外し changelog-gate.sh 1 本のエントリポイントに統合、ブランチ削除 push のスキップを 3 ゲート共通にした（#1510、PR #1525 review-takt-default 指摘対応）。再レビューでの追加指摘を受け、(6) Python 側の Any import 検出を 1 行正規表現から `python3`/`ast` ベースに置き換え、複数行の括弧 import と `as` alias も解決できるようにし、(7) TypeScript 側は `: any` 直書きに加え `Array<any>` / `Record<string, any>` 等のジェネリック引数・union / intersection・tuple 要素の型位置 `any` も検出し、英語コメント・文字列リテラル中の "any" は誤検知しないよう型導入記号の直後という制約を追加、(8) `SKIP_CHANGELOG=1` が CHANGELOG チェックのみを省略し test-diff-gate / any-usage-gate は継続する契約テストを追加した（PR #1525 2 回目の review-takt-default 指摘対応）。3 回目の review-takt-default 指摘を受け、any-usage-gate の検出方式を正規表現の継ぎ足しから構造的な解析へ刷新した: Python 側は `.lefthook/pre-push/any_usage_python_resolver.py`（新設）が `ast` でファイルを解析し、`typing.Any` 修飾アクセスと直接 import 経由の裸 `Any`（alias 含む）の両方を実際の参照行番号として解決するため、コメント・docstring・文字列リテラル中の "Any" は AST 上に現れず誤検知しない。TypeScript 側は型エイリアス代入（`type X = any;`）・型アサーション（`value as any`）も検出対象に加え、正規表現で候補行を検出したのち `.lefthook/pre-push/any_usage_ts_line_cleaner.py`（新設）で行コメント・文字列リテラルの中身を除去してから再判定することでコメント・文字列内の "any" 誤検知を防ぐ。あわせて diff の基準点（`origin/main` との merge-base）を changelog-gate.sh で一度だけ解決し `PRE_PUSH_DIFF_BASE` として子ゲートへ export することで、3 スクリプトが個別に基準を再計算する重複を解消した（PR #1525 3 回目の review-takt-default 指摘対応）
- `docs(channel-new)`: `/channel-new`（新規開設モード）の Step 7「簡易ペルソナ導出」冒頭に入口ゲートを追加し、承認済み TTP 対象（`config/channel/analytics.json::benchmark.channels`）が 0 件のままペルソナ生成へ進めないようにした。従来は 0 件検出が Step 9 の最終ゲートに集中しており、空のまま生成 → 差し戻しの手戻り（AI 生成コストの無駄）が発生し得た。判定基準は冒頭「TTP 完了条件（新規開設モード）」を単一ソースとして参照し、完了条件本体はコピーしない（#1517）
- `feat(skills)`: comments-reply / pinned-comment に apply 実行前の承認ゲートを追加した（#1513）。両スキルの dry-run 確認ポイントを「全項目 PASS の場合のみ次フェーズへ進む」形式に統一し、1 項目でも FAIL なら dry-run を修正・再実行するまで apply へ進んではならない旨を明記した。comments-reply は Phase 4→5、pinned-comment は Phase 1→2 の間に承認ゲートを新設し、Claude Code では AskUserQuestion で dry-run 結果の要約を提示したうえで「投稿する」「キャンセル」の明示 2 択、AskUserQuestion 非対応環境（Codex 等）ではテキスト提示 + 明示的な承認発言待ちに統一した
- `feat(takt)`: lite workflow に提出前セルフ監査を組み込んだ（#1508）。過去の review-takt-default 指摘 371 件（183 レビュー）の全件分類から頻出 8 パターンを抽出した `.takt/facets/policies/pre-review-checklist.md` を新設し、`implement` step（自己監査 + 受入条件充足表の出力）と `review` step（独立照合、スコープ外の改善提案は verdict に影響させない）に注入。あわせて lite の `plan` step に `instruction: plan` を追加し、リポジトリ強化版 plan instruction（`.takt/facets/instructions/plan.md`）が lite でも注入されるようにした。運用・更新手順は `docs/takt-operations.md` の「提出前セルフ監査」節を参照
- `docs(skills)`: takt 各 step の固定コンテキスト削減のため全スキルの frontmatter description を短縮（合計 22.4KB → 10.1KB。同義トリガー語の羅列と処理手順の重複を削り、スキル間 dispatch の境界語と機械検証キーワードは維持）。あわせて CLAUDE.md（18.9KB → 7.4KB）/ AGENTS.md（14.6KB → 2.2KB、CLAUDE.md への一元化）をスリム化し、詳細を `docs/architecture.md` / `docs/development.md` / `docs/takt-operations.md` へ移設。`.takt/config.yaml` に observability（usage_events_phase）を有効化し、小〜中規模 issue 用の軽量 3-step workflow `.takt/workflows/lite.yaml` を追加（使い分け基準は `docs/takt-operations.md`）。さらに takt 内部実装（phase 分割実行）の調査に基づき、lite の review step を全 step codex 方針に合わせて codex 化し、`structured_output`（`.takt/schemas/review-verdict.json`）+ deterministic `when:` ルールで状態判定 phase の LLM 呼び出しを排除。phase コストモデルと workflow 設計指針を `docs/takt-operations.md` に文書化
- `chore(distrokid-helper)`: manifest / package の shell を suno-helper 基準に揃えた（ADR-0016、#1359）。manifest 権限を `lib/manifest.ts` の `MANIFEST_PERMISSIONS` / `MANIFEST_HOST_PERMISSIONS` に SSOT 化して `wxt.config.ts` から参照し、`tests/manifest.test.ts` と CI（extensions.yml）の生成 manifest 検査で drift（広域権限や suno-helper 専用権限の混入、distrokid.com 以外の host 追加）を機械検知するようにした。あわせて dependencies の caret 指定を既存解決値へ exact pin（`@webext-core/messaging` 2.3.0 / `@wxt-dev/storage` 1.2.8 / `react` `react-dom` 19.2.7）し、`pnpm.onlyBuiltDependencies: ["esbuild"]` を追加
- `fix(skills)`: collection-ideate と wf-new の SKILL.md に別々の散文で重複記述され、既に文言が食い違っていた stale/freshness 判定ロジック（相対比較・絶対鮮度の OR 条件）を `references/freshness-rules.md` へ単一ソース化した。文言の食い違い（片方のみ #1427 と自動呼び出し不可を記載、もう片方のみ deep-merge 手順を記載）を解消し、両 SKILL.md は挙動指示（stale なら中断 / `/analytics-collect` → `/analytics-analyze` の順 / 自動呼び出し不可）を残したまま「定義は freshness-rules.md を正とする」参照に縮約した。判定規則の内容（日数・順序・OR 条件）自体は変更していない（#1519）
- `docs(postmortem)`: `postmortem/SKILL.md` の症状判定閾値「チャンネル特性に応じて文脈調整可」に調整ルーブリックを追加した。調整して良い 3 ケース（新チャンネル: 公開 10 本未満 or 開設 30 日未満 → 平均比閾値を ±0.1 まで緩和可 / 直近テーマ転換: 過去平均比較は参考値とし `ratio_vs_median` 系を優先 / 外部要因の明確な痕跡: 該当指標の判定を保留し外部要因を先に記録）を表で固定し、該当ケースがなければ表の係数をそのまま使う（自由裁量での調整は不可）ことを明記した。Sonnet 級モデルでの週次分析の再現性低下（恣意的調整または無調整への偏り）を防ぐ（#1522）
- `docs(skills)`: 後工程スキルが前工程の出力を暗黙に信じて実行し、入口ではなく途中で失敗する問題を防ぐため、4 箇所に「存在確認 → なければ前工程を案内して停止」ガードを追加した。channel-setup は Step 2.1 の inline Python 実行前に `auth/token.json` / `auth/client_secrets.json` の存在確認（無ければ `/setup` を案内）、Step 3.5 の転記前に `docs/channel/channel-direction.md` の存在確認（無ければ `/channel-direction` を案内、順序固定）を追加。channel-research は手順冒頭に Step 0 を新設し `data/benchmark_*.json` / `data/comments_*.json` / `docs/benchmarks/*.md` の存在確認（欠損種別ごとに `/benchmark` または `/viewer-voice` を案内）を追加。audience-persona-design は Phase 6 入口に `docs/plans/viewing-scene-matrix.md` の存在確認を追加し、ユーザーがスキップを明示した場合のみ「viewing-scene 未検証」と注記して確定できるようにした（#1516）

### Removed

- **BREAKING** `refactor(skills)`: `/channel-import` スキルを削除し、`/channel-new` の「既存チャンネル取り込みモード」として統合した（#1460、epic #1459 の 1/2）。取り込みモードは呼び出し文脈（「既存チャンネル」「チャンネル取り込み」「config 生成」「channel-import」）から自動判別し、ヒアリング → config 生成 → 検証 → OAuth / channel_id 取得 → 次ステップ案内を担う。旧 Step 0 のテンプレートリポジトリ clone 手順は廃止し、`/channel-new` の方式（現在のディレクトリ + `/setup` 前提）に整合させた。`yt-doctor` の `channel_config` ロード失敗時の案内と他スキル SKILL.md / `docs/features.md` の `/channel-import` 言及も `/channel-new`（取り込みモード）へ更新。下流リポジトリは `yt-skills sync` の prune で削除に追従する

### Changed

- `chore(ts-rewrite)`: main を feat/ts-rewrite へ追従 merge した（v5.5.15 まで、ADR-0008 の同期運用）。main 側の OAuth 契約 fix（#1330: `installed` ブロック必須化 + `redirect_uris` 検証）・TTP readiness（#1357）・DistroKid / comments config fix（#1211）を取り込み、OAuth boundary テストの fixture を新契約に追随。main が更新した lifecycle skill 文書（masterup の Suno 選曲 #1308/#1324、video-upload の予約公開 plan #1406、channel-import 統合 #1460 等）へ #965 の `bunx tayk <cmd>` 置換を再適用し、`distrokid-prep` → `distrokid-helper` rename にも追随した。main でリリース済みの [Unreleased] エントリは各リリースセクションへ整理
- `fix(ts-rewrite/cli)`: CLI smoke test が Bun デフォルト timeout（5000ms）に当たり REJECT される構造的問題を修正した（#1107）。subprocess smoke test に明示 timeout を設定し、重いロジック検証は `createXxxCommand()` を直接呼ぶ in-process テストに移行。subprocess テストは「dispatcher が subcommand を認識する」確認のみに限定。
- `refactor(ts-rewrite/core)`: registry の `METADATA_GENERATE_REGISTRY_KEY` 定数を除去し、service キーをリテラル文字列でインライン化した（#1112）。public export を減らし registry データ内に閉じ込めることで、外部からの参照結合を排除。回帰テスト `registry-deps.test.ts` で定数非 export を機械担保。
- `refactor(ts-rewrite/core)`: OAuth service（`interactiveAuthService` / `refreshTokenService`）を `createService` フレームに移行し、ADR-0003 の構造的不整合を解消した（#1139）。output schema を `oauth/schema.ts` に追加し、OAuth callback の `state` 生成・検証を追加。boundary テスト（input validation / success / failure）も追加。
- `refactor(ts-rewrite/core)`: ADR-0003 の service 境界 frame（try/catch → Result 変換）を `createService` ヘルパ（`service-frame.ts`）に抽出し、対象 10 service（analytics 5 + image / skills-sync 2 / suno-prompts / upload）を移行した（#1109）。新規 service は core function + schemas だけ書けば frame を正しく適用できるようになり、手書き frame のレビュー負荷と誤実装 fail mode を除去。
- `refactor(ts-rewrite/core)`: analytics 5 service の共通クエリ実行を `analytics/query.ts::executeQuery` に、列ヘッダー解決を `analytics/columns.ts` に集約し、各 service の try/catch/ok/err ボイラープレートを `service.ts::createService` ラッパーで除去した（#1110）。`column-helpers.ts` → `columns.ts` リネーム、`analytics/query.ts` / `service.ts` 新設。テスト追加: `analytics-query.test.ts` / `service.test.ts`
- `feat(ts-rewrite/core)`: Audience analytics の demographics / country / subscribedStatus 3 クエリを並列開始するよう変更した（#1115）。失敗時は開始済み retry が settled になるまで待ってから Result へ変換し、service 戻り後に API retry が残らないようにした。
- `refactor(ts-rewrite/core)`: analytics service の列ヘッダー解決とセル読み取り処理を `analytics/column-helpers.ts` に共通化し、channel / audience / traffic-source の重複実装を整理した（#1113）。
- `refactor(ts-rewrite/core)`: analytics のエラー分類ロジックを `errors.ts` に統合した（#1108）。`analytics/query-error.ts` と `audience/service.ts` 内の重複実装（`toAnalyticsQueryError` / `shouldRetryAnalyticsQuery` / `parseRetryAfterSeconds`）を削除し、`classifyGaxiosError` / `shouldRetryApiQuery` / RFC 7231 準拠の `parseRetryAfterSeconds` に一本化。ネットワークエラーの retry 漏れも修正。
- `feat(skills)`: dogfood ライフサイクルが踏む 12 skill（wf-new / wf-next / suno / suno-helper / masterup / videoup / video-upload / thumbnail / video-description / analytics-collect / playlist / distrokid-prep）の `uv run yt-*` 呼び出しを `bunx tayk <cmd>`（ADR-0007 rebrand / ADR-0004 単一 dispatcher）へ置換した（#965）。TS 版を pin した下流でも skill 経由で Python が実行され dogfood が始まらない問題を解消する。対象 skill の `uv run` 残骸ゼロを `tests/test_lifecycle_skills_no_uv_run.py` で機械担保。lifecycle 外の skill の置換は #966 で対応予定。

### Added

- `feat(ts-rewrite/core)`: Traffic source 内訳（search / browse / external / suggested 等）を期間集計する `collectTrafficSourceService` を ADR-0003 準拠で実装した（#832）。`packages/core/src/analytics/traffic-source/`（schema / service / index）を新設し、Python `utils/traffic_source_analytics.py` Mixin を翻訳せず TS で新規記述。あわせて analytics 共通のエラー分類を `analytics/query-error.ts`（`toAnalyticsQueryError` / `shouldRetryAnalyticsQuery`）へ集約し、video / channel / video-daily / traffic-source の各 service から参照する。quota（429）は `withRetry` で retry せず `domain: "quota"` の Result で返す
- `feat(ts-rewrite/core)`: resumable upload + thumbnail 圧縮 + metadata update を 1 atomic service に集約した `uploadVideoService` を ADR-0003 準拠で実装した（#837）
- `feat(ts-rewrite/core)`: Per-video metrics（views / likes / comments / shares 等 8 指標）を YouTube Analytics API から収集する analytics video service を ADR-0003 準拠で実装した（#829）
- `refactor(ts-rewrite/cli)`: `generate-suno` の `getCwd()` を遅延評価に変更し explicit path 指定時の不要な cwd 解決を排除。`skills-bundle-pack.test.ts` の `beforeAll` 共有 fixture を各テスト独立生成に改善（#1156）

### Fixed

- `fix(secrets)`: テスト実行時に実 `op read` へ落ちる経路を遮断するため、Python / TS の secret resolver に `YOUTUBE_AUTOMATION_DISABLE_OP_READ=1` の opt-out を追加した。pytest は `tests/conftest.py` で既定有効化し、op fallback を検証する単体テストだけ明示的に解除する。本番の既定契約（env 未設定かつ `op` 利用可能なら `op read` fallback）は維持する（#1622）
- `fix(wf-new)`: `/wf-new` の冒頭に channel config / Suno readiness の Hard Gates を置き、前提未達時は `/channel-new` や `bunx tayk video-analyze --source benchmark --channel <slug> --top 5` を案内して停止し、`/collection-ideate`、`bunx tayk init-collection`、`/suno`、`workflow-state.json` / `assets.*` 更新へ進まない契約を明記した（#1609）
- `fix(thumbnail)`: `/thumbnail` の手順でテキスト付き `thumbnail.jpg` を先に確定し、承認済み `thumbnail.jpg` から textless `main.png/jpg` を後続再生成する契約を再固定した。frontmatter の旧 `main.png` サムネ表現、Two-Phase の draft 背景を最終 `main.png` に確定するよう読める手順、決定的合成経路で textless 再生成を不要扱いする記述、config コメントと設計ドキュメントの旧 Two-Phase 表現を修正し、`/wf-new` / `/collection-ideate` / `/loop-video` の役割契約と整合させた（#1611）
- `fix(thumbnail)`: `yt-generate-image` の `generation_mode: single_step` で `--reference` 未指定の実行を `--ttp-strict-references` の有無に関係なく provider 初期化前に拒否するようにした（#1612）。`two_phase` など非 TTP 経路は従来どおり参照なし生成を許可し、`gemini_cli` provider 単体でも `single_step` request が参照なしなら gemini CLI 起動前に `ConfigError` で停止する
- `fix(collection)`: `tayk collection-preflight` を追加し、`yt-init-collection` の既存ディレクトリ検出時と `/wf-new` / `/wf-next` の復旧手順で実在する `bunx tayk collection-preflight <collection-dir-name> --fix` を案内するようにした（#1614）
- `fix(config)`: `channel_dir()` / `_resolve_channel_dir()` と TS `channelDir()`、comments / pinned_comment の `history_file` docstring、thumbnail skill / channel-new テンプレートの `path_base: "channel_dir"` 説明を、`config/channel/` 自体ではなくそれを含むプロジェクトルートを指す説明へ統一した（#1569）
- `fix(benchmark)`: ベンチマーク収集でショート動画の `thumbnail_url` を選ぶ際、縦型を返しうる `maxres` / `standard` ではなく横型キー（`high` / `medium` / `default`）を優先するようにした。通常動画は従来どおり `maxres` 優先を維持する（#1501）
- `fix(ts-rewrite/generate-master)`: review 指摘を受け、`masterup.yaml` fallback は `audio` 直下の generate-master 用キーだけを読み、finalize-master 用 namespace の `audio.finalize.*` は無視するよう修正した。JSON 優先は `masterup` override に限定し、inline / scalar `audio`、JSON root / audio shape 不備、空白 `bitrate` は config / validation error に統一した。registry 経由でも明示 CLI 値の presence が config override より優先されるよう schema 境界を分離した。`ffmpeg` の bitrate 指定では `-b:a` と `-q:a` の併用をやめ、single MP3 も bitrate 契約どおり encode 経路へ統一した。`generate-master` public subpath から CLI 用 path resolver を外し、`tayk generate-master` の CLI flag 実行 smoke と関連回帰テストを追加した（#772）
- `fix(ts-rewrite/core)`: ADR-0009（JSON-only config）との実装乖離を解消し、`packages/core` から `yaml` 依存を排除した（#1415）。suno-prompts の定義ファイルを JSON 化（`suno-patterns.yaml` → `suno-patterns.json`、`config/skills/suno.yaml` → `suno.json`）し、parser を `JSON.parse` ベース（`parseTopLevelJson` / `parsePatternsJson`）に変更。`packages/core/package.json` から `yaml` を削除し、ADR-0009 に Status（乖離解消日）を追記した。
- `fix(ts-rewrite/core)`: `uploadVideoService` の予約公開時刻正規化で、不正な timezone offset（例: `+25:99`）を UTC 変換対象にしないよう修正した（#1120）。
- `refactor(ts-rewrite/core)`: `collectVideoDailyAnalyticsService` の列マッピングをハードコード位置参照から `columnHeaders` ベースの動的解決（`requireHeaders` / `resolveColumnIndex`）へ移行した（#1114）。API レスポンスの列順変更に対する堅牢性を向上
- `fix(ts-rewrite/core)`: `readReferenceFiles` の参照画像読み込み失敗時エラーに対象パスを含め、元の filesystem error を `cause` に保持するよう修正した（#1121）。
- `fix(config)`: `channel-import`（`/channel-new` 取り込みモード）が生成する `config/localizations.json` の `title_template` がアップローダー許可プレースホルダ（`{scene_phrase}` / `{activities}` / `{scene_emoji}`）と不整合になり、アップロード時までエラーに気づけない問題を修正。`yt-config-migrate verify` が生成直後に不正プレースホルダを検出して失敗するようにし（`validate_localizations_title_templates` を新設）、`channel-setup/references/localizations-template.json` を許可プレースホルダのみの形へ更新、SKILL.md / config-generation-rules.md に許可リスト契約を明記した（#1471）
- `fix(suno)`: ボーカルモードの `tracks_per_pattern` を prompt entry name 契約に反映し、`/suno` が `suno-prompts.json` を展開後 entry 数で生成、`/suno-lyric` / `yt-suno-verify` が同じ `Take N` 付き name と件数を検証するよう修正（#1484）
- `fix(suno)`: `yt-suno-verify` と `/suno` の final entry name 生成を共有化し、`suno-patterns.yaml` / `suno-prompts.json` / `suno-lyrics.json` の `name` に外側 whitespace がある場合は暗黙正規化せず fail-loud するよう修正（#1484）
- `fix(suno-helper)`: duration NG clip を playlist 対象から除外する処理を origin/main の run 完了時リロード・stale selection guard と統合し、全 clip が NG の場合に raw ID を resume state へ残さないようにした。`playlistExpectedClipCount` は OK clip 数として保存しつつ、resume / failed-only rerun の raw 観測期待数は保存済み OK IDs + 今回実行 entry 数から別計算し、Download 再開可否は full collection 完走状態で判定するよう分離。active feed poll は duration を取得できる feed v3 POST に揃え、bridge 由来 duration は finite non-negative number のみ受け入れる。`retryPlaylist` / failed-only rerun でも正規化済み OK clip ID 契約を維持し、duration 未観測 ID を新規 playlist 対象にしないようにした。manual adoption は未検証 ID として保持して retryPlaylist 側の duration filter に通し、`duration_filter` は snapshot / resume state に保存して popup 再 open 後も custom 閾値を維持する。download 完了 POST の `expected_file_count` は duration-filtered 採用数としてサーバー側 workflow-state / collection index / artifact 展開の完了判定にも反映する。`suno-prompts.json` 生成も collection-level `duration_filter` envelope へ対応し、bool / NaN / Infinity / 非 mapping を fail-loud にする（#1269）
- `fix(doctor)`: `yt-doctor` の `ttp_wf_new_readiness` が `branding/icon.png` / `branding/banner.png` 不在時に、同名 stem の別拡張子や `-vN` 付き候補を `branding/` から列挙してリネーム/変換を促すようにした。複数候補がある場合は最終版の人間確認を促し、自動判定しない旨を明示する。あわせて `/channel-new` と `/automation-update` に、新規生成前の既存 branding ファイル確認手順を追記した（#1550）
- `fix(masterup)`: `/masterup` Step 4.5 の本実行前に `yt-suno-select-tracks --dry-run` で `pair_selection.min_song_sec` 未満候補を確認する手順を追加し、該当候補がある場合はファイル名・duration・設定中の `min_song_sec` を提示して続行可否を確認するようにした。あわせて dry-run stdout に短尺候補専用の `[dropped_under_min]` セクションと `dropped_under_min` 件数を追加した（#1526）
- `fix(masterup)`: `.claude/skills/masterup/SKILL.md` の Step 1(コレクション特定条件)と「完了時の更新」セクションが workflow-state.json 旧スキーマ(v1、`music.generated` / `music.approved` / `mp3_count` / `phase: "music-approved"`)のまま残っており、現行スキーマ(v2、`.claude/skills/wf-new/references/schema.md`)の `assets.music_prompts` / `assets.raw_master` / `phase` 定義と食い違っていた。`/wf-next` 側の既存検出ロジック(`assets.music_prompts = true` かつ `assets.raw_master = null` を対象とする)、および実装(`apply_rain_layers.py` が書き込むフィールドは `assets.raw_master`)と突き合わせて記述を修正し、`/masterup` は raw master 生成 + `assets.raw_master` 記録までを担い `phase` は遷移させない(`raw_master` → `master_audio` 確定後の `"mastered"` 遷移は `/wf-next` の責務)旨を明記した。現行スキーマに対応フィールドが存在しない `mp3_count` は削除した(#1521 の実装中に副次的に発見。ドキュメントのみの変更でコード変更なし)
- `fix(video-analyze)`: `analysis_window_sec` を API 呼び出し前に bool ではない正の整数として検証し、不正な channel override（0 / 負数 / 文字列 / bool / null）が Gemini `VideoMetadata.end_offset` へ流れないよう fail-fast にした。解析に使った窓幅は JSON の `analysis_window_sec` / `analysis_scope` と Markdown レポートに保存し、レポート検証 Step 3 には Gemini 生成物を untrusted data として扱う境界指示を追加。`data/video_analysis` を読む下流 skill には冒頭クリップ窓データである旨を明記した（#1495）
- `fix(upload)`: `yt-upload-collection --plan` の公開設定表示が schedule 無効時に固定「即時公開 (public)」となり実効 privacy_status と乖離する問題を修正。実効値（`config/channel/youtube.json::privacy_status`）を反映して public / unlisted / private を正しく表示する。あわせて、どこからも参照されていなかった `schedule_config.json::upload_settings.privacy_status` をデフォルト設定・`yt-channel-init` テンプレート・`schedule-template.json` から撤去して設定箇所を `youtube.json::privacy_status` に一本化し、既存の schedule_config.json に残存する場合は警告ログで案内する（#1472）
- `fix(upload)`: 単一言語チャンネル（`supported_languages` が 1 言語以下）で `yt-populate-scene-phrases` は no-op なのに upload preflight / metadata audit / localizations 生成が `scene_phrases` を必須要求してエラー停止する矛盾を解消。「scene_phrases が必要か」の判定を `preflight_checks.requires_scene_phrases()` に一本化し、単一言語では preflight・audit のチェックをスキップ、`generate_localizations()` は空 dict を返す（デフォルト言語のタイトル・概要欄は snippet 側で供給済みのため情報損失なし）。これにより populate → upload の通し実行が手動修正なしで成功する（#1470）
- `fix(upload)`: upload preflight で `workflow-state.json` の存在と JSON parse を単一言語チャンネルでも常時検証するようにし、`scene_phrases` 完全性チェックだけを多言語チャンネル限定にした。`/metadata-audit` と `/wf-new` の skill 手順も単一言語では翻訳 JSON 不要、多言語では `scene_phrases` 必須という契約に揃えた（#1470）
- `fix(upload)`: metadata generator の `workflow-state.json` 読み込みも fail-loud に揃え、単一言語チャンネルでも壊れた `workflow-state.json` を localizations 空 dict の成功扱いで見逃さないようにした。`yt-populate-scene-phrases` の collection 名拒否テストに空・`.`・`..`・backslash 入力を追加し、利用者向け `scene_phrases.md` のエラーハンドリング表も単一言語 no-op / 多言語必須を明示した（#1470）
- `fix(hooks)`: git worktree / Codex 実行環境で lefthook hook が stale な Nix store 固定パスや PATH 不在により silent skip され得る導線を修正。devShell の shellHook は trusted な flake 側 `.lefthook/install.sh` を呼び出して hook を毎回再生成し、生成済み `pre-commit` / `pre-push` は install 時の lefthook 絶対パス + PATH fallback の wrapper へ置き換え、どちらも解決できない場合は exit 1 で fail-closed する。wrapper 生成失敗は部分適用のまま成功扱いにせず、既存の `LEFTHOOK=0` 全 hook skip 契約も維持する。親 checkout / worktree それぞれの診断・再生成手順も docs に追加した（#1552）
- `fix(automation-update)`: `yt-automation-update apply` の sync-only / smoke check / 失敗ステップ表示を hardened。URL 直接参照と inline table の ref 許可規則を `main` / 40 桁 sha / `vX.Y.Z` tag に統一し、`--sync-only` は local fix guard を通したうえで指定 skill の skills asset と claude-md を同期、未知 skill 名は副作用前に拒否、`yt-config-migrate verify --target <repo>` で対象 repo を固定、`pyproject.toml` 書き換え時の I/O 失敗もステップ名付きで報告するようにした（#1473）
- `fix(thumbnail)`: `yt-generate-image` の `${typography_clause}` 展開で malformed な `image_generation.gemini.single_step` / `thumbnail_text.font` 設定を `{}` や `"consistent"` に丸めず、`ConfigError` として `[ERROR]` + exit 1 で fail-loud するようにした（#1332）
- `fix(suno-helper)`: Suno UI 改装（2026-07-04 観測、Lyrics 欄の Lexical エディタ化）で連続実行が「Lyrics 欄が見つかりません」の FatalRunError で必ず中断する問題を修正した（#1506）。Suno Custom Mode の Lyrics 欄が `textarea[data-testid="lyrics-textarea"]` から `div.lyrics-editor-content[contenteditable][data-lexical-editor]`（Meta Lexical エディタ）へ変わり、`resolveFields` が textarea 前提の解決で lyrics を見失っていた。対応: (1) `shared/dom.ts::resolveFields` の lyrics 解決に Lexical contenteditable の fallback を追加（従来の testid textarea を最優先に維持して旧 UI と併存、`contenteditable=""` の boolean 属性形式も許容、bbox 幅非ゼロで非マウント要素を除外）。`ResolvedFields.lyrics` は `HTMLTextAreaElement | HTMLElement | null` へ拡張。(2) Style 解決は `[data-testid="create-form-styles-wrapper"]` 内の可視 textarea を一次識別に昇格（lyrics が textarea でなくなり「Lyrics 以外の可視 textarea」述語だけでは特定根拠が弱くなったため。wrapper 不在の旧 UI は従来述語へ fallback）。(3) 注入は新設の `setLyricsValue` が分岐する: textarea / input は従来の同期 `setNativeValue`、Lexical contenteditable は value setter を持たないため `focus → execCommand("selectAll") → 200ms 待ち → DataTransfer + ClipboardEvent("paste") dispatch → 200ms 待ち` の合成 paste で全置換する（Lexical 自身が購読する paste に text/plain を載せる React 互換経路）。selectAll の選択は Lexical が selectionchange 経由で内部 state に取り込むため反映が非同期で、**同期実行では全選択が乗らず「置換」でなく「先頭挿入」に化ける**（実機検証）— 200ms の selection 同期待ちが本質で、呼び出し側 `content.ts::injectAndGenerate` の lyrics 注入も await 化した。実ページで 6 entries × 12 clips の連続生成 → playlist 一括追加 → ZIP DL の完走を確認済み。Vitest に resolveFields の Lexical fallback 5 ケース / styles-wrapper 一次識別 2 ケース / setLyricsValue の経路分岐・selectAll→paste 順序（fake timer で同期 paste 禁止を pin）・instrumental 空文字 3 ケースを追加、Playwright e2e に Lexical mock（paste 横取りで全置換する contenteditable）への注入スモークを追加。
- `fix(suno-helper)`: #1506 の Lexical Lyrics 空文字注入を空 paste 依存から `selectAll` 後の `delete` command へ切り替え、readback が空にならない場合は Generate へ進まず fail-loud するようにした。actual run handler 経由で空 lyrics が Generate 前にクリア済みであること、非反映時に ERROR で止まること、共有 DOM mock が `setLyricsValue` export に追従していることをテストで固定した。
- `fix(wf-next)`: raw=final 採用時の `/wf-next` state 更新で `workflow-state.json` / `01-master` / 採用音源の symlink を拒否し、collection 外の state 書き込みや外部音源採用を fail-closed にした。あわせて `approval_gates.upload` の非 boolean 拒否テストを `audio` と同じ契約で固定（#1449）
- `fix(suno-helper)`: popup のチェック選択実行を旧 range 指定から `indices` payload に切り替え、done/failed 状態を含む選択復元・再実行で絶対 index がずれないようにした。旧 range UI 文言と helper を撤去し、content runner 側は `indices` を `range` より優先して部分実行する（#1267）
- `fix(suno-lyric)`: `/suno-lyric` がマルチ曲 collection で `[Intro]` `[Pre-Chorus]` `[Bridge]` `[Extended Outro]` を全曲一言一句同一のまま出力するのを防ぐため、Workflow に「これらの section も曲ごとの scene / persona で書き分ける」指示を明記し、Validation に曲間セクション重複のセルフチェックと書き分け直し手順を追加。`suno-lyrics.json` の曲間重複を機械検出する `references/check_lyric_duplication.py` を新設（重複検出時は exit 1、#1445）
- `fix(doctor)`: `ttp_wf_new_readiness` の video_analysis 要件が benchmark top 5 のライブ配信（`duration_iso == "P0D"`、Gemini 取り込み不可で解析不能）により恒久的に充足不能になる問題を修正。live は期待集合から除外して次点 VOD を繰り上げ、VOD が不足する場合は母数を縮小し、除外時は message に「live 配信 N 本を除外」を明示する。`yt-video-analyze --source benchmark` も同じ選定で live をスキップして次点 VOD を解析する（#1462）
- `fix(hooks)`: oxlint.config.ts / oxfmt.config.ts の `ignorePatterns` 対象パス（`examples/**` `docs/**` `config/**` など）のみを変更した commit で lefthook pre-commit の oxlint / oxfmt が「対象ファイルなし」を non-zero exit で返し必ず失敗する問題（#1428 の同型）を修正。`lefthook.yml` の両コマンドに `--no-error-on-unmatched-pattern` を追加し、対象 0 件を成功として扱うようにした（ignorePatterns のパスを exclude へ列挙する二重管理は回避、#1452）
- `fix(videoup)`: `generate_videos.sh` の `build_effect_filter()` で `VIDEOUP_EFFECT=particles` / `bokeh` を指定すると出力が緑一色または黒一色になる問題を修正。原因は 2 点あり、(1) `geq=lum='...'` で `cb`/`cr`（色差）を省略すると環境によってデフォルト値が中央値 128 ではなく 0 になり YUV→RGB 変換で緑被りが発生する、(2) `geq` の直前が `format=yuv420p`（アルファプレーン無し）のままだと `a=` の不透明度式が無視され常時アルファ=255（完全不透明）になり、エフェクトレイヤーが背景を完全に覆い隠して黒一色化する。`gradient` エフェクトは元々 `geq` 直前に `format=yuva420p` を明示していたためこの問題を踏んでいなかった。`particles` は `geq=` に `cb=128:cr=128` を追加して白い粒子を維持し、`bokeh` は `cb='cb(X,Y)':cr='cr(X,Y)'` で元の暖色 chroma を維持したまま、両方で `noise=...` の後・`geq=...` の前に `format=yuva420p` を挿入した。あわせて `fx_baked.params` に filtergraph stamp を含め、旧 filtergraph で焼いた cache を再利用しないようにした
- `fix(analytics-report)`: `analytics-report/SKILL.md` の「CTR 値の解釈」が「整数値 2606」から意味不明な式の否定を経て「そのまま使用」に至る自己矛盾した記述になっており、コード実態（`reporting_api.py` の `total_weighted / total_impressions` が返す百分率 float。例 `4.2` = 4.2%、`tests/test_ctr_resolver.py` のフィクスチャも 4.2）と食い違っていた。百分率 float である旨・表示フォーマット（小数 1〜2 桁 + `%`）・100 で割る/掛ける/整数再解釈の禁止・`None` 時の表示を一義的な規則として書き直した（#1514）
- `fix(skills)`: 兄弟スキル間の frontmatter description 矛盾・発動キーワード衝突を解消。viewer-voice の「/audience-persona-design らの前提データを作る任意後続スキル」を「/audience-persona-design の必須入力（viewer-voice-analysis.md）を作る前工程。実行タイミングは任意」に書き換え、audience-persona-design 側の必須入力表記との矛盾を解消（audience-persona-design 側も対象ファイル名を明記して双方向に整合）。benchmark と channel-research が共に持っていた発動キーワード「競合分析」の重複は、benchmark を「競合データ収集」に変更し末尾に「収集済みデータの分析は /channel-research」の否定トリガーを追加、channel-research 側に「データ収集・更新は /benchmark（未実行なら先に案内）」を追記して解消。videoup / video-upload は名前類似で相互区別が無かったため、互いを名指しする一文（videoup→「YouTube への投稿は /video-upload」、video-upload→「動画ファイルの生成（MP3→MP4）は /videoup」）を追加した（#1515）
- `fix(setup)`: `/setup` の GCP project ID 推奨値生成で、30 文字超過時の truncate 手順が 2 通りに読め、機械的に切ると末尾ハイフン（GCP 制約違反）の ID も生成されうる問題を修正。`yt-` prefix は必ず保持し slug 末尾から削る→切り詰め後の末尾ハイフンを追加除去する→6 文字未満や意味が読み取れなくなる場合は自動生成をやめカスタム入力を求める、の 3 段手順 + 31→30 文字の具体例で一義化した（slug 生成規則自体は無変更、#1523）
- `fix(thumbnail)`: `thumbnail/SKILL.md` の TTP 差分プロンプト解説に地の文で置かれていた `daiki-beppu/rjn`（private リポジトリ）への実装事例参照を、「参考（オペレーター向け・実行時は無視してよい）」の引用ブロックへ隔離した。下流リポジトリの実行者はアクセスできない非公開リポジトリへの取得試行で時間を浪費する問題を防ぎつつ、jazzgak チャンネルの `color_themes.<theme>.reference_image` 多軸切替という参考情報自体は保持する（#1524）
- `fix(suno)`: `/suno` の「### モード判定」がキーワードスキャン 1 本（「ボーカル要素が含まれていれば」）で、対象語リストの範囲が不定・否定文脈（`no vocals` / `instrumental` 等）の扱いが未定義・判断に迷った場合の手順が無く、誤判定が歌詞工程の要否と Suno UI の Instrumental ON/OFF を誤らせる高コストな手戻りを招き得た。4 段の決定木（1. 否定表現が先で他語より優先 → 2. ボーカル語の完全一致 → 3. どちらも該当なしは既定インスト → 4. 確信が持てない場合は推測せず該当箇所を提示して AskUserQuestion でユーザーに確認）に置き換え、リストが網羅ではない旨と該当なし語での歌唱可能性は必ず 4 に落とす旨を明記した（#1520）
- `fix(live-clean)`: `/live-clean` Step 3 末尾の削除承認指示が「AskUserQuestion で確認、承認されるまで実行しない」という自由記述のみで、質問文の内容・選択肢・曖昧応答時の扱いが未指定だった。AskUserQuestion の質問文に削除対象の実数（「削除対象: N コレクション / M ファイル / X.X GB」）と「削除は取り消せません（rm -f による物理削除）」の警告を含め、選択肢を「削除を実行する」「キャンセル」の明示 2 択に固定（デフォルトを実行側にしない）。「削除を実行する」が明示的に選ばれた場合のみ Step 4 へ進み、それ以外の応答（自由文・別話題・無回答）はすべてキャンセル扱いとした。AskUserQuestion 非対応環境（Codex 等）ではテキスト提示 + 明示的な承認発言待ちを明記し、Step 4 の実行条件も同じ選択文言（「削除を実行する」が明示的に選ばれた場合のみ）に揃えた（#1518）
- `fix(masterup)`: `/masterup` が部分ダウンロード（例: 10 曲中 5 曲失敗）を検知できず、`assets.music_downloaded` が `true` のまま欠けた曲数でマスター音源を生成しうる問題を修正。コレクション特定 Step 直後に「DL 完全性チェック」を追加し、`02-Individual-music/` の実ファイル数（mp3/m4a/wav）を期待曲数（`suno-prompts.json` の entry 数 × 2、インスト / ボーカル共通の算式）と突合する。不足時は `music_downloaded` フラグに関わらず揃っているとみなさず不足曲数を提示して停止、ファイルが 0 件なら `/suno-helper` 未実行として案内して停止する。期待曲数・実ファイル数の算出は `/suno-helper` の DL 完了判定・`yt-collection-serve` の status 判定と同じ既存ユーティリティ（`suno_downloaded_workflow_state` / `suno_downloaded_archive`）を再利用し、算式を二重管理しない（#1521）
- `fix(wf-next)`: `/wf-next` の Suno パスが `workflow-state.json::planning.music.suno_playlist_url` に記録済みの playlist URL を確認せず、`02-Individual-music/` のダウンロード完了実態も見ないまま常に AskUserQuestion で URL 再入力を要求していた問題を修正。URL 記録済み + 音声ファイル（mp3/m4a/wav）実在なら記録済み URL で `/masterup <URL>` を自動実行し、URL 記録済みだがファイル未実在ならダウンロード未完了の可能性を案内して停止、URL 未記録なら従来通り AskUserQuestion で入力を求めるようにした。`wf-new/references/schema.md` に `planning.music.suno_playlist_url` / `assets.music_downloaded` のフィールド定義も追記（#1539）
- `fix(skills)`: suno / lyria / videoup の SKILL.md に workflow-state.json 旧スキーマ（v1）由来のフィールド名（`music.*` / `production.*`）が残存し、現行スキーマ（v2、`wf-new/references/schema.md` が正）と食い違っていた問題を修正。`/suno` は `yt-generate-suno` 完了時の更新先を `music.generated = true` から `assets.music_prompts = true` に修正した（`wf-new/SKILL.md` の同フィールド更新箇所・`wf-next/SKILL.md` の Suno/Lyria 両パス前提条件と整合）。`/lyria` は Step 5「完了時の更新」が本来 `/wf-next` の責務である最終マスター確定（`assets.master_audio`）と v2 に存在しない `phase: "music-approved"` への遷移まで誤って自スキルの責務として記述していたため、Lyria 自身が担う `assets.music_prompts = true` への更新と `assets.raw_master` へのファイル名記録のみに縮約した。`/videoup` は自動検出条件を `music.approved = true` かつ `production.generated = false` から `assets.master_audio` が設定済み（`null` 以外）かつ `assets.master_video` が `null` に修正し、完了時の更新も `production.generated = true` から `assets.master_video` への動画ファイル名記録に修正した。`init_collection.py` の `assets` 初期化・`apply_rain_layers.py` の `raw_master` 更新など実装コードとの突合で v2 フィールド名を確認し、SKILL.md のみを修正（コード変更なし）

### Migration

所要時間の目安: 0〜10 分

local fix 衝突注意:
- videoup: `generate_videos.sh` の `build_effect_filter()`（`particles` / `bokeh`）をこのバグの回避のためローカルパッチ済みの下流リポジトリは、`yt-skills sync` 取り込み後にローカルパッチを外すこと（残したままだと二重適用にはならないが、次回 upstream 側の当該箇所の変更が sync で上書きされずローカル差分として残り続ける）。取り込み後は `VIDEOUP_EFFECT=particles` / `bokeh` で一度動画を生成し、緑/黒一色になっていないか確認する。

サマリ:

- `/suno` / `/suno-lyric` の成果物検証、playlist 突合、コレクション骨格 preflight、thumbnail 自動選択など、制作フローの fail-loud 化と自動化を追加した。
- `/channel-setup` / `/channel-import` を `/channel-new` に統合し、旧スキルを削除した。下流リポジトリは `yt-skills sync` の prune で追従する。
- `yt-automation-update` CLI を追加し、下流リポジトリの pin 更新・lock 同期・skill sync・smoke check を機械実行できるようにした。
- `particles` / `bokeh` エフェクトが緑一色・黒一色になる重大バグを修正した。エラーなく「生成完了」と表示されるため気づきにくく、該当エフェクトを使っている下流チャンネルは取り込み後に出力確認を推奨する。

追加移行メモ:

- `#775`: Python `yt-generate-suno` 相当の導線は TS dispatcher の `tayk generate-suno <collection-dir> [--json]` に移行する。per-CLI bin は追加せず、core registry entry `suno.generate` 経由で `suno-prompts.md` / `suno-prompts.json` を生成する。
- `#772`: Python `yt-generate-master` 相当の導線は TS dispatcher の `tayk generate-master <collection-dir> [--json]` に移行する。per-CLI bin / `yt` alias は追加せず、core registry entry `masterup.generate-master` 経由で Suno ダウンロード済み音声を `master.mp3` へクロスフェード結合する。skill-config は `config/skills/masterup.json` を優先し、存在しない場合のみ既存 `config/skills/masterup.yaml` を fallback として読む。`audio` section は optional で、存在する場合は object のみ有効。未対応 YAML 行や空 scalar は config error として停止する。

## [5.5.15] - 2026-07-02

### Added

- `feat(channel-new)`: `/channel-new` にチャンネル画像初期化導線を追加。TTP 対象の `snippet.thumbnails` / `brandingSettings.image` を reference-only として snapshot に保存し、`yt-channel-init` が `thumbnail.yaml` の channel branding 参照枠を生成、`yt-setup-dirs` が `branding/` を作成するようにした（#1367）
- `feat(doctor)`: `yt-doctor` に `numbered_duplicates` チェックを追加し、`.venv/bin/` と `.claude/skills/` の番号付き重複ファイル（iCloud Drive 同期コンフリクトの bounced file name、原因調査 #1409）を検知・警告できるようにした。`yt-skills sync` も sync 先の重複を warning で報告する。クリーンアップ手順は `docs/migration/numbered-duplicate-files-cleanup.md` を新設し、`/automation-update` に検知確認と再発防止ガイダンス（同期対象外への移設が根本対策、`--frozen` は効果なし）を追記（#1410）
- `docs(migration)`: TS 移行告知 + 移行ガイド `docs/migration/python-to-tayk.md` を公開し、README / ONBOARDING 冒頭に告知バナーを追加。Python 版は 2026-08 中に提供終了し `tayk`（npm）へ切り替わる（ADR-0015 の 2026-07 頭告知義務、#1416）
- `feat(channel-new)`: 承認済み TTP 対象だけを使う初回 `/wf-new` readiness を追加し、`yt-doctor` で thumbnail reference / video-analysis partial / Suno style variants / 旧 video-analyze model を検出できるようにした（#1357）

### Changed

- `feat(distrokid-helper)`: `POST /distrokid/releases` を suno-helper の downloaded POST と同じ background + serve token 必須の書き込み境界に統一（ADR-0016）。サーバー側で `X-Serve-Token` を検証し token なし / 不正 token / 不正 origin を 403 で拒否、popup は直接 POST せず background service worker へ typed message（`recordRelease`）で委譲、token stale の 403 は token 再取得で 1 回だけ retry する。token 取得 / 403 retry は shared API の共通ヘルパに集約し、書き込みには `--allow-origin chrome-extension://<EXTENSION_ID>` が必須になった（#1360）
- `refactor(distrokid-helper)`: popup `App.tsx` から fetch / collection 選択 / 注入 / 停止 / 配信済み記録の実行制御を `useDistrokidRunner` hook へ抽出し、suno-helper と同じ helper extension shell 構成（ADR-0016）へ揃えた。popup UI と「注入後にユーザーが目視確認して手動で続行する」安全境界は維持（#1361）
- `refactor(suno-helper)`: サーバー側の旧 `POST /suno/playlists` エンドポイントと `suno-playlists.json` 向け URL マッピング関数を撤去し、playlist URL 記録を `POST /collections/<id>/downloaded` に一本化（#1261）
- `feat(suno-helper)`: `suno-prompts.json` の `duration_filter` envelope を shared API で型付けし、省略時は 60〜300 秒の既定値へ正規化するようにした（#1259）
- `docs(skills)`: `/audience-persona` を `/audience-persona-design` に改名し、`/viewer-voice` と `/viewing-scene` を束ねて第一ペルソナ 1 人へ収束させる設計フローに更新（#1371）
- `feat(channel-init)`: `yt-channel-init` に DistroKid opt-in 初期化を追加し、`--distrokid-enabled` 指定時のみ `config/channel/distrokid.json` を生成するようにした。`/channel-new` のヒアリング手順にも DistroKid 配信設定を追加（#1366）
- `feat(setup)`: `/setup` から `yt-setup-dirs` を実行して `auth/` などの最小ディレクトリを config 生成前に用意し、`/channel-new` は既存ディレクトリを再利用して `config/channel/*.json` 生成に集中する責務へ整理（#1396）
- `feat(doctor)`: `yt-doctor` に `initial_setup_readiness` を追加し、thumbnail 参照画像・composition rules・Suno `genre_line` 文字数・planning 中 `descriptions.md` の parser 不一致を事前検知できるようにした（#1403）
- `docs(distrokid)`: `/distrokid-prep` スキルを `/distrokid-helper` に改名し、参照スクリプトと docs/features の表記を同期（#1350）
- `docs(channel-new)`: `/channel-new` の `/wf-new` 接続前チェックに Analytics / Reporting レポート取得設定と YouTube Live streaming 早期有効化の案内を追加し、Reporting API job 初期化導線を `/analytics-collect` / `/setup` / `yt-doctor` に接続（#1365）
- `docs(channel-new)`: `/channel-new` 完了時に `git status --porcelain` で未コミット変更を確認し、初回 commit 作成または明確な保存手順を案内する完了ゲートを追加。`/automation-update` の dirty worktree 停止時にも `/channel-new` 直後の初回保存未完了を案内するよう更新（#1329）

### Fixed

- `fix(suno-helper)`: 全 entry 投入済みの resume state が残っている場合に popup の「playlist 追加から再開しますか？」バナーを表示しないようにし、既存の「Playlist から再開」ボタンへ導線を一本化した（#1440）
- `fix(collection-ideate)`: 分析レポートの鮮度判定に実行日基準の絶対鮮度チェック（`freshness_days` 既定 7 日、`config/skills/collection-ideate.yaml` で上書き可）を追加し、レポートと収集データが同日付でも収集自体が古い場合は stale として `/analytics-collect` → `/analytics-analyze` の再実行を案内するようにした（#1427）
- `fix(suno-helper)`: Download all ZIP 完了 POST を playlist URL なしで受理し、既存 `suno_playlist_url` を保持したまま `assets.music_downloaded` を更新できるようにした。Download 再開 payload から未使用の `playlistName` 必須契約も削除（#1260）
- `fix(suno-helper)`: run 一式完了時リロード（#1411）が content script の in-memory snapshot（popup 進捗復元の SSOT）を破棄し、run 中に popup を閉じていた運用者が完了後に再 open しても完走結果や per-entry の done/failed を確認できない問題を修正。FINISHED 到達時（リロード予約の直前）に snapshot を timestamp + collectionId 付きで `chrome.storage.local` へ退避し、リロード後の `queryProgress` が in-memory 不在時の fallback として返すようにした（24h stale 判定付き、次の実行開始で消去、退避失敗時はリロードを見送り in-memory 復元を維持）
- `fix(suno-helper)`: dir mode の同一タブ連続実行で前回 run の stale selection が次 run の playlist 追加（Cmd+P）に混入し曲数が累積汚染される問題を修正。run 一式完了時（resume state 消去後）にタブをリロードして Suno 内部の multi-select 状態を破棄し（runAll / retryPlaylist / retryDownload の全選択作成経路が対象）、保険として Cmd+P 直前に選択中 clip 数が対象件数を超えていたら fail-loud で中断してリロード後の再実行を促すようにした。ガード走査は 1 pass + 超過即打ち切りの軽量モードで行い、走査自体の失敗は fail-open（警告して続行）。リロード猶予中に次 run が受理された場合はリロードを取り消して新 run を保護し、resume state 消去失敗時は FINISHED を維持してリロードのみ見送る（#1411）
- `fix(hooks)`: extensions/ 配下のみを変更した commit で lefthook pre-commit の oxlint / oxfmt が「対象ファイルなし」を exit 1 で返し必ず失敗する問題を修正。extensions は自前の ESLint / Prettier / tsc 管理（CI: extensions.yml）のため、`lefthook.yml` の oxlint / oxfmt / typecheck に `exclude: extensions/**` を追加して root ツールチェーンの対象のみに絞った（exclude の glob 配列サポートのため `min_version` を 1.5.0 へ引き上げ、#1428）
- `fix(channel-new)`: `yt-doctor` に `ttp_wf_new_readiness` を追加し、`/channel-new` が TTP 対象承認・relationship・branding snapshot・thumbnail reference・Suno readiness の不足を残したまま完了扱いにならないようにした（#1397）
- `fix(skills)`: `/video-upload` と `/wf-next` の公開承認前に `yt-upload-collection --plan` で即時公開/予約公開を確定し、予約時は実際の公開予定時刻を案内するよう明記（#1395）
- `fix(doctor)`: `yt-doctor` に `ttp_wf_new_readiness` を追加し、`/channel-setup` の benchmark 反映未完了による TTP 参照データ欠落を検知・案内できるようにした（#1400）
- `fix(distrokid)`: `yt-collection-serve` の DistroKid asset 配信で URL encode された日本語ファイル名を decode し、single-file / dir mode の両方で 404 にならないようにした（#1401）
- `fix(masterup)`: `yt-suno-select-tracks` で全候補が `max_song_sec` 超過だけで落ちた prompt を `--allow-best-effort-over-max` で最短候補として例外採用できるようにし、selection log と `workflow-state.json::music_pair_selection` を成功結果に同期するようにした（#1324）
- `fix(launch-curve)`: `yt-launch-curve` で日次データに `impressions` / `impression_ctr` が無い場合も `daily_impressions=0` / `ctr` unavailable として扱い、初期チャンネルの欠損データで落ちないようにした（#1327）
- `fix(skills)`: `config.default.yaml` を持つ skill の SKILL.md に設定読み込みゲートを追加し、チャンネル override の読み飛ばしを防ぐ契約テストを追加（#1243）
- `fix(distrokid)`: `distrokid.profile.artist` を release payload に含め、distrokid-helper が `bandname` と Apple Music credits の performer / producer 名へ反映できるようにした（#1211）
- `fix(automation-update)`: `/automation-update` をチャンネルリポジトリ外で実行した場合に、現在地が不適切な理由と移動先候補または探し方を案内するようにした（#1328）

### Migration

所要時間の目安: 0〜2 分

local fix 衝突注意:
- channel-new, automation-update: 下流で該当 skill を手書き調整している場合は `yt-skills diff` で差分確認が必要。
- channel-new: TTP 完了条件と `yt-doctor::ttp_wf_new_readiness` の完了ゲートを追加。下流で `/channel-new` を手書き調整している場合は TTP 対象承認 / branding snapshot / thumbnail reference / Suno readiness の扱いを確認する。

サマリ:

- 新規チャンネルセットアップ完了時に未コミット変更を残したまま後続の `/automation-update` へ進まないよう、初回保存手順を skill に明記した。
- `/channel-new` が TTP 準拠前に成功案内を出さないよう、`yt-doctor` の readiness check と skill contract を追加した。

## [5.5.14] - 2026-06-30

### Added

- `feat(benchmark)`: `yt-benchmark-comments` に `-y` / `--yes` を追加し、確認プロンプトをスキップできるようにした（#1334）
- `feat(suno)`: Suno V5.5 向けプロンプト設計を更新し、ボーカル曲用の `/suno-lyric` スキルと lyric reference を追加。`suno-lyrics.json` の必須化・entry name 完全一致検証・auto-prep slug / quote source safety guidance も追加（#1305）

### Changed

- `feat(thumbnail)`: single_step TTP 生成で参照画像を必須化し、複数候補では候補ごとに同一ベンチマークチャンネル内のユニークな参照画像を 1 枚ずつ割り当てるように変更。参照不足・重複・同一参照の再利用をエラー化し、参照なし生成フォールバックを削除（#1318）
- `refactor(comments)`: コメント返信の `RuleEngine` / `no_rule_matched` 経路を撤去し、基本フィルタ通過後の全コメントを Agent 生成返信の候補に変更。旧 `comments.rules` は後方互換で読み込むが処理では無視し、返信文の `@投稿者名` 補完と NG ワード監査を追加（#1011）
- `fix(serve)`: `yt-collection-serve` の POST body を 1 MiB に制限し、dir mode の `/distrokid/releases` で実在する collection/disc のみ記録できるようにした（#953）
- `docs(thumbnail)`: 下流チャンネルの `config/skills/thumbnail.yaml` と stock 運用状況を横断監査し、TTP 設定・stock 再利用・live collection 棚卸し結果を `docs/audits/thumbnail-ttp-2026-06-30.md` に追加（#520, #521, #522）
- `docs(skills)`: `masterup` の `yt-suno-fetch` 記述を将来案として明記し、Claude Code 固有表現を Codex 共用時に読み替える注記を AGENTS / CLAUDE に追加（#1181, #1182）
- `fix(thumbnail)`: `main.png/jpg` を textless 動画背景 / 参照画像として扱う契約に統一し、upload thumbnail / DistroKid cover は `thumbnail.jpg/png` のみを候補にするよう skill docs と回帰テストを更新（#1310）
- `docs(channel-new)`: `/channel-new` の初期フローを TTP 対象確認中心に整理し、追加競合発掘・本格 benchmark/comments 収集は後続スキルへ委譲する方針に変更（#1309）
- `docs(skills)`: 初投稿前に `/playlist` で未作成プレイリストを初期化し、`/video-upload` の自動 assign に引き継ぐ導線を追加（#1314）
- `docs(setup)`: Google Auth Platform 新 UI に合わせて OAuth client 作成、client secret 再発行、Test users 追加手順を ONBOARDING / `/setup` / `auth/SETUP.md` に明記（#1330）
- `feat(streaming)`: Terraform streaming module に配信元 MP4 の ffprobe プリフライトを追加。キーフレーム間隔と最低ビットレートを plan/apply 前に hard fail し、H.264 High profile は warning として通知する。README / `/streaming` skill に `-c:v copy` 前提の動画要件と推奨再エンコード例を追記（#1299）
- `docs(skills)`: wf-next / wf-status / analytics-analyze / wf-new / channel-setup / video-upload / community-post / collection-ideate の記述を現行実装に同期し、optional config 一覧を README / AGENTS / CLAUDE に追記（#1173, #1174, #1175, #1176, #1177, #1178, #1179, #1180）
- `feat(masterup)`: Suno 生成後の 2 clip を `20-documentation/suno-prompts.json` の歌詞有無で整理する `yt-suno-select-tracks` を追加。歌詞あり prompt は 1 clip 採用、instrumental は 2 clip 採用とし、極端に短い/長い失敗生成を stock 退避または削除できるようにした（#1308）
- `docs(wf-new)`: `/wf-new` を子スキル順次実行のオーケストレーターとして整理し、Suno チャンネルでは `yt-collection-serve` 起動と疎通確認まで行って `/suno-helper` に引き継ぐ導線を追加（#1308）

### Fixed

- `fix(cli)`: `yt-*` CLI 起動時に標準入出力を UTF-8 へ再設定し、Windows cp932 コンソールで日本語パスや Unicode ダッシュを含む出力が `UnicodeEncodeError` で落ちないようにした（#1331）
- `fix(upload)`: `descriptions.md` の見出し不一致時に、期待する見出し一覧・不足/不一致の見出し・検出済み見出し・修正例を表示するよう改善（#1340）
- `fix(suno-helper)`: `yt-collection-serve` の `/collections/<id>/suno/prompts.json` で URL エンコード済み collection ID をデコードし、スペースを含むフォルダ名でも prompts を取得できるようにした（#1338）
- `fix(suno-helper)`: Suno Helper が `/collections` の `status` 形式と保存済み `suno_playlist_url` に追従し、Download 再開時は保存済み URL を優先するよう修正。Service Worker の `storage` 権限を生成 manifest で検証し、Suno 新 UI の Exclude styles / More メニュー検出とエラー案内も改善（#1321, #1336, #1337, #1339）
- `fix(cost)`: Windows 環境で `fcntl` がない場合も `cost_tracker` と `yt-generate-image` が起動できるよう、`msvcrt` / プロセス内 lock fallback を追加（#1315）
- `fix(upload)`: upload preflight が `audio.target_duration_min/max` を秒単位として誤判定していた master 動画尺チェックを無効化（#1313）
- `fix(metadata-generator)`: `BAHMetadataGenerator` の音声尺取得に `ffprobe` fallback を追加し、Suno 由来の `.m4a` が `afinfo` 失敗だけで 0 秒扱いされないようにした（#1323）

### Migration

所要時間の目安: 5〜10 分

local fix 衝突注意:
- masterup: `pair_selection.*` / `stock.*` の既定値と `yt-suno-select-tracks` 手順を追加。下流で `config/skills/masterup.yaml` や `/masterup` を手書き調整している場合は同期時に確認が必要。
- wf-new, suno-helper: `/wf-new` が Suno-helper server 起動まで担う前提へ導線を更新。下流で開始フローを手書き調整している場合は差分確認が必要。

サマリ:

- Suno vocal 曲は 1 prompt から生成される 2 clip のうち 1 つだけを master 採用し、未採用 clip を stock に残せるようにした。
- instrumental 曲は従来通り 2 clip を活かしつつ、尺外の失敗生成だけを master から除外できるようにした。
- `/wf-new` 完了後に `/suno-helper` が既存 `yt-collection-serve` を再利用できる運用へ整理した。

## [5.5.13] - 2026-06-29

### Changed

- `feat(thumbnail)`: Codex サムネイル生成の既定プロンプトを、参照画像を winning template として扱う短い TTP 上位互換型に変更。`image_generation.codex.default_prompt_template` を追加し、`/collection-ideate` と channel-setup テンプレートの Codex 導線を同方針へ更新（#1300）
- `refactor(shared)`: CollectionSummary を boolean fields (`has_prompts` / `mapped`) から status enum (`needs_prompts` | `ready` | `downloaded`) に置換。`downloaded_count` フィールド追加、`playlist_name` 廃止。POST `/collections/<id>/downloaded` エンドポイント新設（#1216）**BREAKING**
- `feat(suno-helper)`: Playlist 追加後の Download all DOM 操作 + chrome.downloads 連携を実装 (#1146)
- `feat(serve)`: POST `/collections/<id>/downloaded` に冪等更新ロジックを追加（playlist URL 記録 + DL 完了マーク）(#1145)
- `deprecate`: `read_mapped_slugs()` / `write_suno_playlists()` / `normalize_suno_title()` / `POST /suno/playlists` を deprecated 化 (#1145)
- `feat(upload)`: チャンネル設定の既定予約投稿時刻をアップロード時に適用（#1054）
- `feat(upload)`: アップロード完了後に YouTube Studio で確認すべき手動チェックリストを表示（#1052）
- `feat(upload)`: アップロード実行時に操作対象のチャンネル名と channel ID を表示（#1053）
- `feat(thumbnail)`: サムネイル生成で primary provider が失敗した場合の fallback provider 設定と手順を追加（#1097）
- `feat(preflight)`: タイトル重複を公開前に検出する早期警告 CLI と preflight 連携を追加（#1055）
- `feat(metadata)`: Suno パターン名をトラック表示名へ反映する生成ロジックを追加（#1092）
- `feat(masterup)`: Suno 音源の後処理 CLI `yt-suno-audio-cleanup` を追加（#1048）
- `feat(masterup)`: `generate-master` に尺プレビューと `--no-loop` を追加（#1091）
- `docs(masterup)`: Suno ショート URL からの楽曲解決手順を追加（#1094）
- `docs(automation-update)`: GitHub CLI が使えない環境向けに curl での release 取得手順を追加（#1098）
- `docs(short)`: short / short-release の workflow-state schema 記述を実運用の状態ファイルに合わせて修正（#1171）
- `docs(short-release)`: short-release スキルの手順をショート生成までの責務に整理（#1170）
- `docs(short)`: short / short-release の dry-run 手順を現行の `--plan` フラグ表記に修正（#1169）
- `docs(channel-setup)`: Terraform GCP reference を現行テンプレートと同期（#1172）
- `docs(channel-setup)`: benchmark 取得手順で参照する CLI 名を現行名に修正（#1168）
- `fix(cost)`: 高額化しやすい `gemini-2.5-pro` 既定利用を廃止。`/video-analyze` の既定モデルを `gemini-3.5-flash` に変更し、`yt-populate-scene-phrases` は Vertex AI Gemini を直接呼ばず、Claude Code の Agent ツールで生成した翻訳 JSON を `--translations-json` / `--translations-file` で受け取って `workflow-state.json.scene_phrases` に書き込む方式へ変更した。`yt-comments-reply` も `--export-candidates` と `--agent-replies-file` を追加し、Claude Code のメインエージェントがサブエージェントに返信 JSON を作らせて CLI に渡せるようにした。CLI 内部から `claude -p` は呼ばない。
- `feat(channel-init)`: `yt-channel-init` を最小 config 生成からフルパッケージ生成に拡張。`--music-engine` / `--benchmark-channel` / `--branding-description` / `--channel-keyword` / `--target-duration-min` / `--target-duration-max` / `--supported-language` / `--default-language` / `--core-message` / `--country` 引数を追加し、`config/channel/*.json` に加えて `config/localizations.json` / `config/schedule_config.json` / `config/upload_settings.json` / `config/skills/{suno,thumbnail}.yaml` / `.env` / `.gitignore` / `auth/client_secrets.template.json` を一括生成する。テンプレート群を `channel_init_templates.py` に分離（#1271）
- `feat(channel-settings)`: `yt-channel-settings pull --channel-id-only --apply` を追加。YouTube API から `channel_id` のみを取得して `config/channel/meta.json::channel.channel_id` に書き込む。通常の `pull --apply` でも `channel_id` を自動反映するよう `_write_channel_settings` に統合（#1271）
- `docs(skills)`: `/channel-new` を TTP ベンチマーク → config → ペルソナ → branding の end-to-end スキルに刷新。`/audience-persona` / `/channel-direction` / `/channel-research` / `/channel-setup` の description・前提条件・Cross References を新フローに合わせて更新（#1271）
- `refactor(doctor)`: `/onboard` スキルを `/setup` にリネームしツール設定特化に責務整理。`yt-doctor` に `bootstrap` カテゴリを新設（#1273）
- `docs(setup)`: `/setup` の GCP プロジェクト新規作成手順でチャンネル名由来の project ID / 表示名を推奨し、OAuth 同意画面のアプリ名とクライアント ID 名も HUMAN STEP に提示するよう更新（#1277, #1278）
- `docs(wf-new)`: アナリティクス未収集の初回チャンネルでも `/wf-new` から企画生成を開始できるよう、`collection-ideate` / `wf-new` の入力モードに benchmark fallback mode と minimal mode を追加。`yt-doctor` の readiness 判定も analytics 不在をブロッカーにしない契約へ更新（#1272）

### Fixed

- `fix(upload)`: descriptions.md の必須セクション不備時に再作成手順を含むエラーを表示（#1051）

### Migration

所要時間の目安: 10〜20 分

local fix 衝突注意:
- suno-helper: 拡張 version が 0.2.0 になり、`yt-collection-serve` の `/version` も `min_extension_version=0.2.0` を返す。古い拡張を使っている下流は更新が必要。

サマリ:

- `suno-helper` 0.2.0 を前提に、Playlist 追加後の Download all 操作、chrome.downloads 連携、dir mode の collection 切り替え安定化を含めた運用へ更新。
- `yt-channel-init` をフルパッケージ生成へ拡張し、初期チャンネルセットアップで config / localization / schedule / upload settings / skill config をまとめて生成可能にした。
- `/channel-new` と関連スキルを TTP ベンチマークから config・ペルソナ・branding までの end-to-end フローに刷新。
- CollectionSummary の status enum 化と `/collections/<id>/downloaded` 追加により、Suno 生成後の DL 完了状態を明示的に扱う。
- `/setup` へのリネーム、`yt-doctor` bootstrap カテゴリ追加、初回チャンネル向け benchmark fallback / minimal mode を追加。

## [5.5.12] - 2026-06-25

### Changed

- `feat(streaming)`: ライブ配信のデフォルトを 24/7 連続配信に変更（ADR-0014）。Terraform 変数 `stream_hours` / `break_hours`（default=0 = 無制限）を導入し、systemd テンプレートで条件分岐。`yt-stream-archive-check` の `--expected` を必須化（#1219）
- `refactor(streaming)`: Python streaming 定数を 24/7 デフォルトに更新。`THEORETICAL_HOURS_PER_DAY=24`、`ARCHIVES_EXPECTED=False` を導入し、稼働率計算・月次レポートを `ARCHIVES_EXPECTED` で分岐（#1220）

### Fixed

- `fix(masterup)`: Suno CDN ダウンロードに `--fail` + `--retry 3` + 検証ステップを追加し、部分ダウンロードや破損ファイルを検出・警告するようにした。Content-Type 検証・UUID バリデーション・期待ファイル突合チェック・検証ゲート・リトライ設定の外部化も追加（#1090）
- `fix(metadata-generator)`: `analyze_audio_files()` でトラックがサイレントにスキップされる問題を修正。duration が 0 以下や例外発生時にスキップ理由を明示的に警告し、入力数と出力数の不一致を検出するサマリーを追加。`_get_audio_duration()` の内部 try/except を除去し例外を呼び出し元へ伝播させることで skip reason に実際のエラー詳細が含まれるよう改善（#1093）
- `fix(tags)`: `parse_youtube_tags()` を新設し、descriptions.md タグ分割+正規化を一元化。全 5 経路（`Tags.for_collection()` / `_descriptions_md.py` / `preflight_checks.py` / `bulk_update_descriptions_from_md.py` / Shorts タグ生成）で統一的に quote 除去（#1096）
- `fix(veo)`: Veo 生成後に `smooth_loop()` を自動適用し、ループの継ぎ目をクロスフェードで滑らかにする。`generate_videos.sh` で音声ループ時に `loudnorm` フィルターを適用し音割れを防止（#1057）
- `fix(videoup)`: `generate_videos.sh` で loop.mp4 不在時に静止画フォールバックを明示的にログ出力し、loop 生成失敗の痕跡（`loop_raw.mp4` / `loop-v*.mp4`）がある場合は警告を表示。静止画 + effect 経路にもループ不在ログを追加。痕跡検出を `ls | head` パイプから配列ベースのファイル存在チェックに修正（pipefail 非依存化）。テスト 3 件追加（#868）
- `fix(suno-helper)`: Cmd+P によるプレイリスト dialog の起動を最大 3 回リトライし、大規模 collection の multi-select verify タイムアウトを 50→100ms/row に倍増して安定性を改善（#1050）
- `fix(thumbnail)`: Gemini 参照画像生成時に variation guard プロンプトを自動プリペンドし、参照画像の丸パクリを抑制（#1049）
- `fix(comments-reply)`: `comments.insert` 成功後の履歴 `save()` を最大 3 回リトライし、insert→save 間の二重返信余地を縮小。全 save 失敗時は `plan.replied` に `save_failed` フラグを付与（#382）
- `fix(collection-serve)`: `send_error()` 26 箇所を CORS 付き `_send_json_error()` に統一し、suno-helper 拡張が CORS ポリシーでブロックされる問題を修正（#1209）
- `fix(suno-helper)`: dir mode で collection 切り替え・URL 変更時に前回の prompts が残留する問題を修正（#1210）。`syncCollections` で最新 collection 一覧を再取得してから prompts を fetch するフローに変更し、サーバー側で single-file mode の `/collections` と dir mode の `/suno/prompts.json` 直アクセスに JSON 404 レスポンスを返すよう修正。`resolvePromptCollectionId` を shared に新設

## [5.5.11] - 2026-06-22

### Changed

- `docs(skills)`: preflight 緩和（v5.5.10 #1158）に合わせてスキルの記述を更新。`channel-setup` の `supported_languages` 必須言語記述を推奨に変更、`wf-new` の `scene_phrases` preflight 説明を `supported_languages` 準拠に修正

## [5.5.10] - 2026-06-22

### Fixed

- `fix(preflight)`: en-only / チャプター無し運用を阻む 3 つのハードゲートを緩和した（#1158）。`REQUIRED_LOCALIZATION_LANGUAGES` のハードコード撤廃、タイムスタンプ ≥3 必須チェック撤廃、`scene_phrases` を `supported_languages` のみ要求に変更。Closes #867, #1157

### Changed

- `refactor(ts-rewrite/core)`: ChannelConfig の出力構造を 12 フラット名前空間から 4 bucket（identity / publishing / engagement / integrations）へ再編成した（#827）。入力 JSON 形式・パース挙動・エラーメッセージは不変。Phase 2 service が統一的な bucket API で config にアクセスする基盤
- `refactor(ts-rewrite)`: DepsMap を実体化し `config` / `yt` / `ytAnalytics` を型定義、CLI adapter の `resolveDeps()` で lazy に依存構築する基盤を整備した（#993）。`skills-sync/` を `src/skills-sync/` に統一（#984 吸収）。`getYouTubeAnalyticsClient()` を追加
- `refactor(ts-rewrite/core)`: config 15 section を zod boundary parse 化し、手動 `_build_*` / `REQUIRED_KEYS_BY_SECTION` を撤廃した（#825）。`snakeToCamel` 共用ヘルパを `packages/core/internal/case.ts` に新設し、各 section を `z.object().strict().transform(snakeToCamel)` で統一。`loader.ts` は `ChannelConfig.parse(merged)` 1 行に簡素化

### Added

- `feat(ts-rewrite/core)`: channel-level 日次メトリクス（views / estimatedMinutesWatched / subscribersGained）を集計する `collectChannelAnalyticsService` を ADR-0003 準拠で実装した（#828）。`packages/core/src/analytics/channel/`（schema / service / index）を新設し、Python `utils/channel_analytics.py` Mixin を翻訳せず TS で新規記述。YouTube Analytics クライアントを `deps` で受け取り、`reports.query` の wide な行列を `{ date, metric, value }` の LONG レコードへ reshape する。列は位置 index ではなく `columnHeaders[].name` で解決し、quota（429）は `withRetry` で retry せず `domain: "quota"` の Result で返す。`@youtube-automation/core/analytics/channel` サブパスを公開
- `feat(ts-rewrite/core)`: OAuth refresh / interactive auth / YouTube client factory を ADR-0003 準拠の core service として実装した（#826）。`packages/core/src/oauth/` に `refreshTokenService` / `interactiveAuthService` / `buildYouTubeClient` / `buildYouTubeAnalyticsClient` を新設。CLI 側 `packages/cli/lib/oauth.ts` に `getYouTubeClient()` 高レベルヘルパ（token read → refresh → interactive → write 0o600）を追加。`DepsMap` に youtube client を登録し Phase 2 の YouTube API 系 service の前提を確立
- `feat(ts-rewrite/core)`: video×day 日次 analytics service `collectVideoDailyAnalyticsService` を ADR-0003 canonical template 準拠で実装した（#830、epic #727、#826 の上に構築）。`packages/core/src/analytics/video-daily/` に schema / service / index を新設し、`./analytics/video-daily` を package export に追加。入力は zod `.strict()` の `channelId` + `startDate` / `endDate`（YYYY-MM-DD）+ optional `videoIds`（指定時のみ `filters=video==` で絞り込み）、出力は `{ metrics }`（`reports.query` の `[video, day, views]` 行を `Array.prototype.map` で 1 行 = `{ date, videoId, views }` の 1 record に正規化）。dataframe lib は導入しない。retry/backoff は共通 `withRetry`（#959）に委譲し、429 quota は retry せず `domain: "quota"` + `retryAfterSeconds` の `Result` で返す。launch curve / channel trend の基礎データ供給層
- `feat(ts-rewrite/core)`: retry/backoff の共通 seam `withRetry` を `packages/core/src/retry.ts` に導入し、image provider を 1-attempt 契約に縮退した（#959）。従来は `gemini.ts` / `openai.ts` が retry ループを各自実装しており（共有は `base.ts` の定数のみ）、Phase 2 の analytics services や upload で同じ実装が 11+ 箇所に増殖する構造だった。`withRetry(attempt, policy?)` は既定 3 回 / 10-30-60 秒バックオフ（attempts が多い場合は末尾値を再利用）で再試行し、回数を使い切ったら最後のエラーを rethrow する（握りつぶさない）。既定判定 `defaultShouldRetry` は `QuotaExhaustedError`（ADR-0003: quota は retry せず Result で caller へ）と `config:` / `validation:` / `auth:` prefix のドメインエラーを non-retryable として即 rethrow する。`ImageProvider.generate(req)` は `Promise<Uint8Array>`（成功は画像 bytes、失敗は throw）の 1-attempt 契約に変わり、`ImageGenerationResult` / `RETRY_MAX` / `RETRY_BACKOFF` / `backoffMs` は撤去（`SleepMs` は retry.ts へ昇格し core root から `withRetry` / `defaultShouldRetry` / `RetryPolicy` と共に re-export）。リトライ・persist は `generateImageService` が所有し、deps が `{ provider, persist?, sleep? }` に拡張された（SAFETY / RECITATION は `isContentPolicyError`（base.ts へ移動）で non-retryable に倒す。Result マッピング — SAFETY 等の未 prefix throw は io、`config:` prefix は config — は不変）。provider deps は `{ createClient }` のみに縮退。新規 `packages/core/test/retry.test.ts`（fake sleep recorder でバックオフ系列・即 rethrow・末尾再利用を担保）を追加し、`image-gemini.test.ts` / `image-openai.test.ts` を provider 単体（1-attempt）+ service 経由（retry/persist）の 2 層構成に再編した
- `feat(ts-rewrite/core)`: ADR-0004 に従い core feature registry と citty dispatcher を導入した（#842、Phase 3 から前倒し）。`packages/core/src/registry.ts` に feature 名（dotted、例 `skills.list`）→ `{description, inputSchema, outputSchema, deps, run}` の data registry を新設し、`@youtube-automation/core/registry` subpath で公開する。deps は typed `DepsMap` + `Pick` で宣言し、宣言した key だけが `run` の第 2 引数に渡ることを compile が担保する（#826 で youtube client factory が入ったら `DepsMap` を拡張）。CLI 側は `packages/cli/bin/yt.ts` を citty dispatcher（`runMain` + subCommands）に書き換え、`yt skills list`（`--json` / `--skills-dir`）を `packages/cli/src/commands/skills/cli.ts` の `defineCommand` adapter として実装（flags は per-command 手書き、service 呼び出しは registry entry 経由）。Result→exit-code 方針（stderr `[domain] message`、quota=75 / その他 1）は `packages/cli/lib/run-command.ts::emitResult` に集約し、各 command が独自に exit code を決めない。`yt-skills` bin と手書き argv parse（`packages/cli/skills-sync/cli.ts`）、skeleton の `src/index.ts::run()` は削除（機能は `yt skills list` が等価提供）。oxlint に ADR-0004 enforcement（`packages/cli/**` ⇄ `packages/mcp/**` の相互 import を `no-restricted-imports` で error）を追加。e2e テストは `packages/cli/test/yt-skills.test.ts` で citty dispatcher を実プロセス起動して担保する
- `refactor(ts-rewrite/core)`: Python `utils/secrets.py` の secret 解決ロジックを `@youtube-automation/core` に移植した（#735）。`packages/core/src/secrets.ts` に `resolveSecret(name)`（解決順序 `process.env` → 1Password CLI `op read` → `ConfigError` throw）と参照テーブル定数 `SECRET_REFS`（6 件、デフォルト `CLIENT_SECRETS_JSON = op://Personal/YouTube_OAuth_Client_Secrets/credential`）を追加し、`packages/core/src/index.ts` から再エクスポートする。op CLI 呼び出しは `Bun.spawn(["op", "read", ref])` ベース（PATH 判定は `Bun.which`、10s タイムアウト）。ドメイン例外 `ConfigError` は `#734` で port 済みの `packages/core/src/errors.ts` から import する。Python 版の `lru_cache` メモ化と `get_client_secrets_path` / `write_op_secret` は本 issue のスコープ外として未移植。unit test は `packages/core/test/secrets.test.ts`（env 設定/解除 + op mock、12 ケース）
- `chore(ts-rewrite)`: TS monorepo workspace の skeleton を構築した（#731 / S5）。`packages/core`（`@youtube-automation/core`、純粋ロジック。`exports` で `src/index.ts` を公開）と `packages/cli`（`@youtube-automation/cli`、`bin: { yt: "./bin/yt.ts" }` の雛形 + `@youtube-automation/core` への `workspace:*` 依存）の 2 つの private workspace を最小構成で追加。cli は `bin/yt.ts`（薄いシム）→ `src/index.ts::run()` → core の `greeting()` を呼ぶ end-to-end の workspace 解決を実証する。bootstrap 用 `smoke.test.ts` を root から `packages/core/test/smoke.test.ts` へ移設し（中身不変）、`packages/.gitkeep` placeholder を削除。`bun test` は trivial test で 1 pass green を維持。version は root に揃え `0.1.0-alpha.0`。実 CLI（yt-* 群）・Python 資産の移植は big-bang 移行の後続 issue で対応する
- `chore(ts-rewrite)`: TS 移行 epic (#727) のための品質ガードレール tooling を `feat/ts-rewrite` branch (umbrella PR #791) に install した。Ultracite preset の Oxlint (lint) + Oxfmt (format) backend、TypeScript 6.0.3 (`tsc -b --noEmit`)、bun:test、knip 6.15.0、`bun pm audit` を採用（Vitest と Biome は不採用、ADR `docs/adr/0001-ai-first-ts-rewrite.md` / 設計議論は #727 参照）。`lefthook.yml` に pre-commit `oxlint` / `oxfmt --check` / `typecheck` を Python (ruff) と並列追加、`.github/workflows/ci.yml` に `ts-{lint,format-check,typecheck,test,knip,audit}` 6 ジョブを並列追加（Python ジョブは併存、cutover #790 で削除）、`flake.nix` devShell に bun 追加。新規 config: `oxlint.config.ts` / `oxfmt.config.ts` / `tsconfig.json` (strict + noUncheckedIndexedAccess + verbatimModuleSyntax) / `knip.json` / `bunfig.toml`。`.lefthook/pre-push/changelog-gate.sh::GATED_PATHS` に `packages/` と `package.json` を追加。bootstrap 用 `smoke.test.ts` 1 件と `packages/.gitkeep` (S5 で削除予定)。本コミットは #727 子 issue #731 (S5 workspace skeleton) と #733 (S7 CI/lefthook bun 化) の acceptance criteria を大半前倒し充足する。extensions/* (Chrome 拡張) は別 stack (#697 の WXT/Vite/Vitest) で整備するためスコープ外

### Fixed

- `fix(ci)`: `feat/ts-rewrite` を base にした子 PR で CI が 1 つも走らないトリガー欠陥を修正した（#964 / epic #727 / umbrella PR #791）。`.github/workflows/ci.yml` の `on.push.branches` / `on.pull_request.branches` が `[main]` のみだったため、base = `feat/ts-rewrite` の子 PR（実証: #958 / #963 は status check 数 0）が機械的ゲートなしで merge されていた。両トリガーを `[main, feat/ts-rewrite]` に拡張した（Python lint/test ジョブは週 1 の main merge での混入検出のため残置。#790 cutover で branch を外し Python ジョブを削除予定）。あわせて changelog ゲートの対象パスに TS 実コードの `packages/` と `package.json` を追加し、`ci.yml::changelog` job の path filter と `.lefthook/pre-push/changelog-gate.sh::GATED_PATHS`（後者は base で導入済み）を一致させた。`tests/test_changelog_ci_contract.py` に trigger branches 契約と CI/lefthook 両ゲートの packages/ カバレッジ契約を追加

## [5.5.9] - 2026-06-21

### Added

- `feat(extensions)`: `release-extensions.yml` を統一タグ `ext-v*` で suno-helper / distrokid-helper の両 zip を単一 GitHub Release に添付するよう拡張した（#1022）。従来は suno-helper のみ添付され distrokid-helper が配布されていなかった問題を解消。あわせて `softprops/action-gh-release` の `body` に初回インストール（zip 展開 → `chrome://extensions` → Load unpacked）／更新（zip 展開 → リロード）手順テンプレを埋め込み、配布契約を `tests/test_release_extensions_workflow.py` で機械担保した。
- `feat(doctor)`: `yt-doctor accounts` サブコマンドを追加。全チャンネルリポの `auth/client_secrets.json` をスキャンし、GCP プロジェクト・OAuth クライアント ID・トークン有無の対応表を一覧表示する。`--json` で機械可読出力、`--search-root` で探索ルート指定が可能。
- `docs(adr)`: ADR-0010 全チャンネルを単一 GCP プロジェクトに統合。Billing 枠上限 (5/5) 解消とオペレーションコスト削減のため、チャンネルごとの GCP プロジェクト分離から `yt-channels-automation` への一本化を決定。
- `feat(suno)`: プロンプト設計を suno-bgm ベースの品質ルール集に刷新した（#904, #899）。Style text の 5 要素順序検証（ジャンル → 音響特性 → キー楽器 → リズム/ベース → テンポ）、120 文字制限の警告、禁止アーティスト名チェック（`banned_artists` 約 30 名）、`auto_lyrics_structure` による歌詞構造の自動補強（`[Instrumental]` / `[Extended Outro]` 自動付加）を `yt-generate-suno` に追加。`style_influence` を 85 → 95 に引き上げ、`weirdness: 10` / `style_char_limit: 120` を新設。楽曲ごとの固有タイトル自動生成仕様（`name_en`: 2-4 word scene/mood title、`name_jp`: 5-15 文字の日本語訳）を SKILL.md に追記。`references/suno-examples.md` に楽器形容詞 Bad/Good ペア 10 組、`references/lyrics-examples.md` にひらがな歌詞ガイドと Mixing Notes 例を追加。
- `feat(doctor)`: `yt-doctor` に ffmpeg/ffprobe の存在チェックを追加し、新規カテゴリ `system` を導入した。動画パイプラインの中核依存が doctor で事前検証されておらず、未インストール環境では動画処理段で初めて `FileNotFoundError` になっていた問題を解消。`shutil.which` で検出し、見つからない場合は `brew install ffmpeg` / `apt-get install -y ffmpeg` のインストール手順を案内する。
- `feat(suno-helper)`: bridge 縮退の可視化と実測シナリオの回帰テストを追加した（#948 仕上げ）。bridge 無観測で DOM プロキシ計数に縮退しているときは queue 空き待ちの popup 表示に「bridge 未観測: DOM 計数で待機中」を明示し、待ちが長い原因を切り分けられるようにした。実測で確認した「DOM 上 20 clips が Remix disabled だが実 status は complete 16 / streaming 4」の状況で即投入再開されることを clip-tracker × waitForQueueSlot の統合テストで pin。README / suno skill の運用ガイドを #948 の挙動（自動リトライ・スキップ完走・失敗分のみ再実行・stall ベース停止）へ更新した。
- `feat(suno-helper)`: entry 単位の自動リトライ + スキップ継続を導入し、1 entry の失敗で run 全体が止まる fail-loud 一発停止を解消した（#948）。失敗を `lib/entry-retry.ts::runEntryWithRetry` で分類し、一時的な失敗は preset 連動の `maxEntryRetry`（Fast:1 / Balanced:2 / Safe:3）回まで同一 entry を再試行、上限超過は `ENTRY_FAILED` phase（新設・非終了）を emit してスキップ継続、投入済み（Generate click 済みで受理失敗確定でない、典型: 生成完了待ち timeout）は重複生成を避けて生成済み扱い、`FatalRunError`（新設: DOM セレクタ不在 / captcha 手動解決 timeout / queue stall など次 entry でも必ず再発する失敗）のみ従来どおり run 全体を ERROR 停止する。スキップした entry は snapshot / resume state の `failedIndices` に記録され、popup に失敗一覧 +「失敗分のみ再実行」ボタン（`run({indices})`、新設の `RunPayload.indices` 経由）を表示する。失敗が残った完走は playlist 追加を保留し（歯抜け playlist と同名重複作成を防止）、失敗分の再実行が完走したときに playlist 追加まで実行する。
- `feat(suno-helper)`: queue 空き待ちの停止判断を固定 300 秒 timeout から stall ベースへ刷新した（#948）。status ベースの正確な in-flight カウント（同 issue PR1）の下では「上限で長く待つ」のは正常状態（clip 完了に数分かかる）であり、固定 deadline は誤停止になる。`waitForQueueSlot` に `getLastChangeAt` / `stallTimeoutMs` を注入できるようにし、注入時は「in-flight 集合（観測 clip の status）が `INFLIGHT_STALL_TIMEOUT_MS`（10 分）まったく変化しないときのみ」Suno 側の停滞として fail-loud に throw する。status 遷移（submitted→queued→streaming→complete）が続く限り従来の 5 分を超えても待ち続け、queue 上限 toast ガードと中断優先は両経路で維持。`getLastChangeAt` 未注入の呼び出しは従来の固定 deadline（`QUEUE_SLOT_WAIT_TIMEOUT_MS`）で動く後方互換。
- `feat(suno-helper)`: MAIN world fetch bridge による status ベースの in-flight 検知へ刷新した（#948）。「Remix ボタン disabled = 生成中」の DOM プロキシは現在の Suno UI では生成完了後も disabled が残り in-flight を大幅に過大カウントし（実測: disabled 20 clips 中 16 が API status `complete`）、Balanced preset の上限 10 clips を常時超過と誤判定 → queue 空き待ちの常態化 → 300 秒 timeout → ERROR 停止を招いていた。新設の `entrypoints/suno-bridge.content.ts`（MAIN world / document_start）がページ自身の fetch をラップして `POST /api/generate/v2-web/` のレスポンス（投入 clip）と `/api/feed/*`・`/api/challenge/progress` のレスポンスを passive 観測し、`lib/clip-tracker.ts` が「観測済み clip のうち status が complete/error でないもの」を in-flight として集計する。clip status の更新は WebSocket 経由で feed の passive 観測を期待できないため、run 中は `lib/bridge-listener.ts` の poller が未終端 clip がある限り `GET /api/feed/v2?ids=...` を active poll する（Bearer token は MAIN world ローカルに閉じ、401 で破棄→ページの次リクエストで再捕捉）。inject の受理（ACK）検証も「generate レスポンスの観測 OR DOM 増分」のハイブリッド（`lib/ack-probe.ts`）に刷新し、従来最大 30-45 秒かかっていた ACK が bridge 経由では数百 ms で確定する。bridge 無観測時は従来の DOM プロキシへ縮退（過大評価 = 安全側）。manifest 権限は不変（storage / activeTab / tabs のみ）。
- `feat(distrokid-prepare)`: DistroKid 配信成果物 `30-distrokid/` を準備する `yt-distrokid-prepare` CLI を新設した（#936）。`plan`（disc 分割計画を draft spec.json に書き出す）/ `build`（spec.json に従って mp3 コピー・metadata.md・README.md を生成する）/ `cover`（ジャケット画像を 3000×3000 JPEG に最終化する）/ `verify`（`build_release_payload` と同一コードパスで生成成果物を検証する）の 4 サブコマンドを提供する。純ロジック層は `utils/distrokid_prepare.py` に分離し、`split_tracks` / `build_draft_spec` / `validate_spec` / `render_metadata_md` / `render_readme_md` / `verify_roundtrip` / `resize_cover` / `write_release_date` を純関数として実装した。重複タイトルには `needs_unique=true` を付与して LLM が後でユニーク化すべき箇所を明示し、生成した metadata.md は `parse_album_metadata` / `parse_track_table` でのラウンドトリップ検証を自動実施する。
- `feat(distrokid-release)`: `config/channel/distrokid.json::profile.credits` を新設し、Apple Music の track credits 行（performer 行 / producer 行）の既定 role を payload に流せるようにした（#919）。`utils/config/distrokid.py` に `DistrokidProfileCredits` dataclass（`performer_role: str = "Audio"` / `producer_role: str = "Producer"`）を追加し、`DistrokidProfile.credits: DistrokidProfileCredits = field(default_factory=DistrokidProfileCredits)` として profile に組み込む。`loader.py::_build_credits` で JSON → dataclass 変換を行い、`scripts/distrokid_release.py::build_release_payload` の `asdict(distrokid.profile)` で payload に自動シリアライズされる。chrome-devtools MCP で実機観察した結果、`#track-N-performer-1-role`（86 options）には `Producer` option が無く、AI 制作 BGM の妥当な選択肢は `Audio`（オーディオ）/ `Sampler`（サンプラー）/ `Synthesizer`（シンセサイザー）/ `Instruments`（演奏）の 4 つで、運用相談の結果 `Audio` を default に採用した。`#track-N-producer-1-role`（40 options）には `Producer`（プロデューサー）option があり、これを default に。`track-N-performer-1-name` / `track-N-producer-1-name` は DistroKid native でアーティスト名（`Soulful Grooves`）が自動フィルされるため、本 dataclass は role select の既定値のみを保持し、name 欄は触らない。soulful-grooves 下流 `config/channel/distrokid.json::profile.credits` を `{"performer_role": "Audio", "producer_role": "Producer"}` で配置。後続コミットで extension `lib/distrokid-injector.ts` が 25 トラックの role select に setSelectValue で注入する
- `feat(distrokid-helper)`: フィル完了直後に「続ける」ボタン（`#doneButton`）を視界へスクロールし、有料オプション（upsell）checkbox を強制 uncheck して請求額を 0 ドル状態に保証する UX/安全策を追加した（#919）。25 トラックの長いフォームの最下部にある送信ボタンが見えず「フィル終わったが何も起きない」と人間が誤認する UX バグを防ぐため、`scrollToDoneButton(document)` を `injectAiDisclosure` 完了時に呼ぶ。要素不在は無音 skip（補助 UX のため致命ではない）。規約遵守でクリックは行わない（送信は人間が手動で押す）。upsell 強制 uncheck は `uncheckUpsells(document)` を `injectStaticFields` 末尾で呼び、`input[type="checkbox"][name="store"]`（ディスカバリーパック 24.75 ドル/年）/ `input[type="checkbox"][name="extras"]`（レガシーパック 49 ドル / ストアマキシマイザー 7.95 ドル/年 / DistroVid 8.25 ドル/月 / 音量正規化 2.99 ドル ×25 等）を全部 uncheck する。`setChecked` は目標と一致なら no-op で重複 click を避ける。将来 `profile.upsells.legacy_pack` 等で opt-in 形式の config 化を検討中だが、現状は全強制 uncheck（誤クリックからの保護優先）
- `feat(suno-helper)`: Suno Custom Mode > Advanced > More Options の Voice section にある Male / Female ボタンを `vocal_gender` 設定で自動押下できるようにした。従来は `/suno` skill が `lyrics_guidelines.vocal_gender` (male / female / neutral / auto) を持ちながら歌詞テキスト + Style 欄 (`genre_line`) の "male vocals" / "female vocals" 文字列にしか反映されておらず、Voice section のボタン自体は suno-helper 拡張が一切触れていなかったため設定が UI に乗らずブレが起きていた。`extensions/shared/api.ts::PromptEntry` に optional な `vocal_gender?: "male" | "female" | "neutral" | "auto"` を追加（文字列リテラルユニオンで配信元の typo を type 段階で弾く）。`extensions/shared/dom.ts` に SELECTORS の `vocalGenderButtons`（`button[data-selected][type="button"]` で候補を全 query → `textContent` (trim) 完全一致 "Male" / "Female" で絞り込み、aria-label / data-testid を持たない Voice section に対し Emotion class hash や親 div の role/class に依存しない方式）、`ResolvedAdvancedFields.vocalGender: { male, female }`（neutral 等の将来拡張に備えた nested 構造）、`AdvancedFieldValues.vocal_gender`、内部 helper `resolveVocalGenderButtons()` を追加し、`injectAdvancedFields` に `vocal_gender === "male" | "female"` で対応ボタンを **冪等に click**（`data-selected !== "true"` の時のみ click、既選択なら skip）するロジックを Exclude styles の次・Weirdness slider の前に挟んだ。**非対称契約**: vocal_gender 値有 + 対応ボタン null → throw（fail-loud、UI 改装検知）/ vocal_gender = "neutral" / "auto" → click しない（"Auto = Suno に任せる"解釈で既選択を解除しない）/ vocal_gender 未指定 → skip（fail-soft、後方互換）。Python 側は `generate_suno_prompts.py::_ADVANCED_JSON_KEYS` に `vocal_gender` を追加し、`_build_advanced_json_fields(override)` ヘルパへ切り出して channel override 明示時のみ JSON へ wire するロジックを保ちつつ、`vocal_gender == ""` は「未指定」として skip する（`config.default.yaml::vocal_gender: ""` の既定値が拡張型契約と矛盾しないため）。他キーの 0 / "" 境界値挙動は #900 で pin した契約を維持。Vitest（`resolveAdvancedFields` の Male/Female 解決 5 ケース・case-sensitive 絞り込み・hidden fallback / `injectAdvancedFields` の vocal_gender 注入 8 ケース・冪等 skip・neutral/auto は無操作・fail-loud throw・exclude_styles と並列）/ Python tests（`vocal_gender: "male"` → JSON 出力 / `vocal_gender: ""` → JSON 出力なし）で担保する
- `feat(distrokid-helper, collection-serve)`: DistroKid コレクション選択機能を実装した（#934）。serve（Python）側では `yt-collection-serve` の dir mode に 4 つのエンドポイントを追加する: `GET /distrokid/collections`（`30-distrokid/<disc>/` に mp3 を 1 つ以上含む disc を collection × disc 単位で列挙し、`album_title`（metadata.md または kebab→Title フォールバック）/ `track_count` / `released` を返す。released 判定は `<capture_root>/config/distrokid-releases.json` の `<collection_id>/<disc>` キー集合と照合し、capture root 未指定時は全件 false）、`GET /collections/<id>/distrokid/<disc>/release.json`（`build_release_payload` を disc 単位で呼び、`asset_path` を `/collections/<id>/distrokid/assets/` 形式の collection-scoped パスに差し替えて返す。不在 id / disc・パストラバーサルは 404）、`GET /collections/<id>/distrokid/assets/<rel>`（collection-scoped アセット配信、既存 `resolve_asset_path` を再利用）、`POST /distrokid/releases`（body: `{collection_id, disc, album_title}` を受けて `<capture_root>/config/distrokid-releases.json` に `tempfile.mkstemp`→`os.replace` の atomic write で追記。capture root 未指定は 404、Origin 未設定・不許可は 403、不正 body は 400、再 POST は上書き冪等）。`scripts/distrokid_release.py` の `build_release_payload` / `_asset_path` / `_cover_entry` / `_disc_tracks` / `_disc_cover` / `_default_release` / `_disc_source_payload` に `assets_prefix` 引数を追加し、既定値 `/distrokid/assets/` を維持して後方互換を保つ。拡張（distrokid-helper）側では popup に collection/disc 選択 select を追加し、released 済み disc を非表示、フィル完了後に `POST /distrokid/releases` を自動記録する。`tests/test_distrokid_collections_endpoint.py` に 37 件のテストを新設（純関数 unit / HTTP 統合両方）
- `feat(suno-helper, collection-serve)`: channel-agnostic な Suno playlist capture endpoint を実装した（#893）。`yt-collection-serve` に `--playlist-capture-root <PATH>` / `--playlist-capture-prefix <SLUG>`（env fallback `PLAYLIST_CAPTURE_ROOT` / `PLAYLIST_CAPTURE_PREFIX`）を追加し、両方指定時のみ POST `/suno/playlists` を有効化する（片方だけ指定は `ConfigError` で fail-loud、silent 無効化しない）。サーバー側は純関数 `normalize_suno_title(title, prefix)`（`<prefix> | <theme>` → `<prefix>-<theme-slug>`、prefix 完全一致のみ・大小無視・連続空白畳み込み、不一致は None）/ `write_suno_playlists(root, payload, *, prefix)`（`<root>/config/suno-playlists.json` へ `tempfile.mkstemp`→`os.replace` の atomic merge write、同 slug は `captured_at` 後勝ち、破損 JSON は再作成）/ `read_mapped_slugs` / `derive_collection_slug` をモジュールレベルに切り出してスペック化し、POST は 200（許可 Origin）/ 403（Origin 未設定・不許可）/ 404（capture 無効・別パス）/ 400（非 list / 不正 JSON）を返す。prefix フィルタは拡張側でやらずサーバー `normalize_suno_title` に閉じて channel-agnostic を担保する。suno-helper 拡張には overlay 下部に Capture / Send to localhost の 2 ボタンを持つ `PlaylistCaptureTab` を追加し、`shared/playlist-scrape.ts::scrapePlaylistsFromMe`（Suno `/me` の `a[href^="/playlist/"]` を aria-label 優先 + textContent fallback で抽出、空 title skip / url dedup）と `shared/api.ts::postCapturedPlaylists` を新設。連続実行の playlist 化完了時には background が bg `/me` tab を開いて scrape→POST→close する自動 capture を fail-soft で走らせる（`tabs` 権限を追加、過剰な広域権限は混入させない）。`build_collections_index` は `mapped: bool` を返すよう拡張し、拡張側は `excludeMappedCollections` で未マッピング collection のみをドロップダウンに出す（prefix 未指定の旧運用は全件表示で後方互換維持）。SSOT は `suno_artifacts.py::SUNO_PLAYLISTS_ROUTE` / `shared/constants.ts::PLAYLISTS_CAPTURE_ROUTE`。`tests/test_collection_serve_suno_playlists.py` / `extensions/suno-helper/tests/playlist-capture.test.ts` / `playlist-scrape.test.ts` / e2e `playlist-capture.spec.ts` / `manifest.test.ts` で担保。仕様は `docs/tasks/suno-playlist-capture.md`
- `feat(suno-helper)`: Suno Custom Mode > Advanced > More Options の 3 フィールド（Style Influence / Weirdness / Exclude styles）を yaml → `suno-prompts.json` → Chrome 拡張で自動注入できるようにした（#900）。従来は手動 UI セット運用で `config.default.yaml::style_influence: 85` の方針が UI に反映されず、コレクション間で値がブレる事故が再現可能だった。`extensions/shared/api.ts::PromptEntry` に optional な `style_influence?: number` / `weirdness?: number` / `exclude_styles?: string`（wire 形 snake_case 統一）を追加し、`extensions/shared/dom.ts` に SELECTORS の `excludeStyles`（`input[placeholder="Exclude styles"]`）/ `weirdness` / `styleInfluence`（`[role="slider"][aria-label="..."]`）と、radix slider へ `focus → keydown(ArrowRight/Left, bubbles:true composed:true) × |delta| → aria-valuenow 読み戻し poll（100ms × 5）で検証し不一致なら fail-loud throw` する `setSliderValue`、3 フィールドを strict visible で解決する fail-soft な `resolveAdvancedFields`、entry 値と解決結果を突き合わせて注入する `injectAdvancedFields`（注入順 Exclude styles → Weirdness → Style Influence）を新設した。**非対称契約**: entry にフィールド有り + selector 不在 → throw（fail-loud、UI 改装検知）/ entry にフィールド無し → skip（fail-soft、後方互換）。値の有無は `!== undefined` 判定で 0 や "" の有効値を脱落させない。`content.ts::injectAndGenerate` の Style/Lyrics/Title 注入後・SETTLE_MS 前に組込み、radix slider は keydown dispatch が合成イベントでも root に届くことを実機検証済みのため pointer event 合成 fallback は採用していない。Python 側は `generate_suno_prompts.py` で channel override（`config/skills/suno.yaml`）に**明示設定されたキーのみ** `load_channel_override` 経由で JSON entry へ collection スコープで載せる（`config.default.yaml` 同梱の既定値は JSON に載せず、MD 出力は従来どおり merged 値を表示）。これにより yaml に何も足さない既存 collection は `name`/`style`/`lyrics` の 3 キーちょうどで後方互換が保たれる。Vitest（`setSliderValue` の delta 計算・読み戻し失敗 throw、`resolveAdvancedFields`、`injectAdvancedFields` の非対称契約・注入順）/ Playwright e2e（MOCK_SUNO_HTML に radix slider + Exclude styles input を追加した注入スモーク）/ Python tests（subset 検証への緩和 + 3 フィールド入り / 0 値境界 / override 無し時の 3 キー後方互換）で担保する
- `docs(skills)`: suno-helper Chrome 拡張の operator 向け運用手順 skill (`/suno-helper`) を新規追加した。yt-collection-serve の dir mode / single file mode 起動コマンド、popup 操作項目（サーバー URL / collection 選択 / 範囲指定 / preset / 連続実行 / 停止）、進捗 phase 8 種（`injecting` / `generating` / `waiting-slot` / `done` / `adding-to-playlist` / `finished` / `stopped` / `error`）の読み方、resume バナーの挙動、代表的な fail-loud エラー文言の原因切り分け、`<YYYYMMDD>-<channel>-<theme>-collection` 命名規約と Custom Mode + Instrumental OFF など実機で詰まりやすい Gotchas を 1 ファイル (`.claude/skills/suno-helper/SKILL.md`) にまとめた。配置だけで `yt-skills sync --asset skills` 経由で下流チャンネルへ自動配布される（`pyproject.toml` / `_ASSET_SPECS` 改修不要）。スコープはハッピーパスの起動手順・通常運用に限定し、トラブルシュート / Suno UI 変更時の selector 更新フロー / preset 判断詳細ガイドは別 skill として後日切り出す
- `feat(suno-helper)`: suno-helper の連続生成 FINISHED 直前に、生成完了した全 clip を Suno playlist へ一括追加する phase を追加した（#854）。20 曲一気投入（#817 / #853）の後に運用者が手動で全 clip を playlist へまとめていた手間を自動化する。collection mode のとき collection id（`20260601-rjn-dawn-cloud-fold-collection` 形式）から `extractPlaylistName`（`shared/api.ts`、末尾 `-collection` 剥がし → 先頭 8 桁日付 + parts>=3 を検証し fail-loud、日付を除いた `<channel>-<theme>` を返す純パーサ）で playlist 名を導出し、popup に display only で表示する。content script は実機 DOM 検証（order.md Step 0）で確定したセレクタ・操作に基づき、`PHASE.ADDING_TO_PLAYLIST`（FINISHED 前の非終了 phase）で「完了 clip-row（`[data-testid="clip-row"][data-clip-status="complete"]`）を直近 entry数×2 件まで multi-select（`.multi-select-button > button[aria-label="Select clip"]` を click、選択済みは冪等にスキップ）→ Cmd+P（Mac=metaKey / 他=ctrlKey）で Add to Playlist dialog を開く（OneTrust cookie consent dialog は id^="ot-" / aria-label の /privacy/i で除外、判定は React Aria auto-generated ID に依らず "Add to Playlist" テキスト）→ `input[placeholder="Playlist Name"]` に #807 の `setNativeValue` で名前注入 → Create Playlist click → dialog 消滅で完了検知」を実行する。DOM 操作は `shared/playlist-dom.ts`（`selectRecentCompletedClips` / `multiSelectClips` / `openAddToPlaylistDialogViaCmdP` / `fillPlaylistNameAndCreate` / `waitForPlaylistDialogClose`）に集約し、各ステップ間は `abortableSleep` を挟んで停止ボタンに対応する。`run` の payload を `{entries, playlistName?}` へ後方互換拡張（旧配列形式は content 側で wrap、`stop` / `progress` / `queryProgress` のシグネチャは不変）し、`SnapshotPayload.playlistName?` を #853 の snapshot 復元へ追加して `PHASE.ADDING_TO_PLAYLIST` 中に popup を閉じ再 open しても進捗が復元される。Vitest（`extract-playlist-name` / `playlist-phase` / `dom-playlist` / `phase-to-status` 拡張）と Playwright e2e（`playlist-add.spec.ts`）で担保する
- `feat(distrokid)`: `yt-collection-serve` に `--distrokid-source` を追加し、30-distrokid 構造（disc 単位提出 + `cover_art_3000.jpg` + `metadata.md`）に対応した（#819）。`yt-collection-serve <collection> --distrokid-source 30-distrokid/disc1-coding-focus-vol1` 指定時、`/distrokid/release.json` の payload を `<collection>/<source>/` を 1 アルバムとして組み立てる: `tracks` は `<source>/*.mp3` をファイル名ソート順で、`track[].title` は `<source>/metadata.md` のトラック表から（未マッチ行は filename stem へ救済）、`cover` は `<collection>/30-distrokid/cover_art_3000.jpg` 優先（無ければ既存サムネイルへフォールバック）、`album_title` は metadata.md のアルバム情報枠（空なら disc dirname を kebab→Title 化）、`profile.language` は metadata.md の言語があれば override（無ければ profile 値）で解決する。release.json の schema（#815 で確定した拡張側契約）は不変で、サーバ側の payload 値だけが変わる。新規パーサ `youtube_automation.utils.distrokid_metadata`（`parse_album_metadata` / `parse_track_table`、HTML コメント枠 `<!-- ... -->` と空セルは None、ファイル名のバッククォート除去、md 不在は `ConfigError` で fail-loud）に切り出し、payload 組立は `distrokid_release.py::build_release_payload(..., distrokid_source=...)` に集約。指定 source の不在・metadata.md 欠落・コレクション外への `..` トラバーサルは `ConfigError`（明示指定は 30-distrokid 構造前提で degrade しない）。`distrokid_source` 未指定/`None` は従来の `02-Individual-music/` 経路で不変（後方互換）。`distrokid_source` は CLI → `create_server` → `_serve_distrokid_release` → `build_release_payload` まで keyword で伝搬する。新規テスト `tests/test_distrokid_metadata.py`（パーサ unit）/ `tests/test_distrokid_disc_source.py`（disc-source payload + エンドポイント結合）で担保する
- `feat(suno-helper)`: suno-helper が Suno Custom Mode の Song Title 欄へ `entry.title ?? entry.name` を注入するようにした（#844）。従来は Style / Lyrics のみ注入していたため Custom Mode で連続生成すると全曲が Suno のデフォルト命名になり後段の Library での識別が困難だった。`PromptEntry` に optional な `title` を追加（後方互換: 無ければ `name` で代替）し、`extensions/shared/dom.ts` の `SELECTORS.title`（`input[placeholder*="Song Title" i]` の弱い case-insensitive substring match。Suno の Song Title 欄は testid / aria / label を持たず placeholder のみ安定なため、`(Optional)` 表記変更にも耐えるよう弱マッチ採用）と strict `isVisible()` で Title 欄を解決して `ResolvedFields.title` へ返す。title 欄が見つからない場合は style / lyrics の fail-loud とは非対称に `console.warn` のみで処理続行する fail-soft（Suno 側 UI 改装耐性）。既存の style / lyrics 注入挙動（#814 instrumental 上書き含む）は不変。Vitest（`dom.test.ts` の title selector resolve / fail-soft、`api.test.ts` の optional title 契約）と Playwright e2e（`suno-inject.spec.ts` の title 注入・name fallback・title 欄不在 fail-soft スモーク）で担保する
- `feat(suno-helper)`: `yt-collection-serve` に collection 列挙 dir mode を追加し、suno-helper popup に collection 選択ドロップダウンと Suno 同時生成キュー監視を実装した（#816）。サーバーは引数パスが `*-collection/` を並べたディレクトリのとき dir mode に切り替わり、`GET /collections`（`[{id, name, has_prompts, pattern_count}]`）と `GET /collections/<id>/suno/prompts.json`（該当 collection の prompts 配列、未知 id / prompts 無しは 404）を配信する。未知 id・パストラバーサル文字列は `find_collection_dirs` のホワイトリストで弾く。既存の単一ファイル mode（`/suno/prompts.json` + `/distrokid/*`）は引数がコレクション dir でないとき従来どおり生き、dir mode では `/suno/prompts.json` を配信しない（純データロジックは `collection_serve.py::find_collection_dirs` / `build_collections_index` / `resolve_collection_prompts_path`、契約サブパスは `suno_artifacts.py::COLLECTIONS_ROUTE`）。拡張側は `extensions/shared/constants.ts` に `COLLECTIONS_ROUTE` / `collectionPromptsRoute(id)` / `MAX_INFLIGHT_REQUESTS=10` / `CLIPS_PER_REQUEST=2` / `PHASE.WAITING_SLOT` を、`api.ts` に `fetchCollections` / `fetchCollectionPrompts` / `pickInitialCollectionId` を追加。popup はマウント時に `/collections` を取得してドロップダウンを populate し（`has_prompts=false` は disabled、初期値は最初の有効 entry）、一覧取得が空 / 404 のときは URL 入力の単一ファイル mode へ fallback する。content script は実 DOM 検証（`suno.com/create` で確定）に基づき clip 行を `[data-testid="clip-row"]` で識別し、`svg.animate-spin` を strict `isVisible()` でフィルタして in-flight 数を数える（`shared/dom.ts::CLIP_ROW_SELECTOR` / `isClipGenerating` / `getInFlightClipCount` / `waitForQueueSlot`）。各リクエスト投入前に同時 20 clip（= 10 リクエスト）の上限が空くまで待機し、超過分の silent fail を防ぐ。pytest（dir mode 列挙・個別配信・404・CORS・単一 mode 非干渉）、Vitest（constants / api / queue 時系列モック）、Playwright e2e（「11 件目は queue 待ちで停止 → 1 完了で投入」/ collection ドロップダウンのスモーク）で担保する
- `feat(distrokid)`: DistroKid 登録フォーム自動入力の Chrome 拡張 `extensions/distrokid-helper/` を WXT (React + TypeScript + Tailwind CSS + @webext-core/messaging + @wxt-dev/storage + Vitest + Playwright) で実装した（#699、`feat/ts-rewrite` branch で完成した実装を cherry-pick して main へ移植）。`#698` で確定した `yt-collection-serve` の `GET /distrokid/release.json`（`{profile, release}` envelope）と `GET /distrokid/assets/<path>` を fetch し、popup（サーバー URL 入力・データ取得・レビュー表示・フォーム一括入力・停止・進捗/エラー）から content script へ `@webext-core/messaging` の型付き channel で注入を指示する。静的プロファイル 6 項目（artist_name / language / main_genre / songwriter / apple_music_credit / track_type）とアルバム名・リリース日は React 互換のネイティブ value setter + bubbling イベントで注入し、曲・ジャケットは `DataTransfer` 経由で `<input type=file>` に `File` をセットして `change` を発火する。注入先が 1 つでも欠ければ `FieldNotFoundError` で fail-loud（silent skip しない）。「続ける」等の送信系操作は拡張から一切行わない（規約遵守）。`distrokid.enabled=false` / 未配置チャンネルは `/distrokid/*` が 404 を返すため `ReleaseUnavailableError` を専用ハンドリングし popup でガイダンス表示する（要件 #16）。Manifest V3・最小権限（`permissions: ["storage", "activeTab"]` / `host_permissions: distrokid.com` 限定）。Vitest で API client / DOM 注入 / messaging schema / storage 既定値の unit テスト、Playwright で `distrokid.com/new` モックに対する注入スモークを担保する。`.github/workflows/extensions.yml` に `distrokid-helper` job を追加し build / typecheck / test / e2e を CI 化する。本拡張は `extensions/shared/`（#697）を介さない自己完結構成で実装した
- `feat(suno)`: Chrome 拡張 + ローカル HTTP サーバーで Suno UI への Style/Lyrics 連続投入を自動化した（#692）。`yt-generate-suno` が従来の `suno-prompts.md` に加え `suno-prompts.json`（`[{name, style, lyrics}]` の配列。md の Styles 行と同一部品から派生）を併出する。配信は #698 で一般化した `yt-collection-serve <collection-dir-or-json-path> [--port 7873] [--allow-origin chrome-extension://<id>]` が `http://localhost:<PORT>/suno/prompts.json` で行い、CORS は `chrome-extension://` オリジンのみ許可する。`extensions/suno-helper/`（Manifest V3 / unpacked）を新規追加し、ポップアップから取得 → 連続実行で各パターンを Style/Lyrics 注入（React 互換のネイティブイベント発火）→ Generate 押下 → 生成完了検知 → 次へ、を順次実行する。reCAPTCHA / エラー検知時は自動停止して警告し手動継続できる。共有パス契約は `youtube_automation.scripts.suno_artifacts` に集約。新規テスト `tests/test_collection_serve.py`、`tests/test_generate_suno_prompts.py` に JSON 併出ケースを追加。Chrome 拡張は手動テスト（Suno 実環境）で確認する
- `feat(serve,config)`: `config/channel/distrokid.json` を新規責務として追加し、`yt-collection-serve` に DistroKid 配信エンドポイントを追加した（#698）。`distrokid` セクションは `enabled: bool`（既定 `false`・opt-in）+ `profile: {artist_name, language, main_genre, songwriter, apple_music_credit, track_type}` を宣言でき、`load_config().distrokid.enabled / profile.*` でアクセスする（`youtube_automation.utils.config.distrokid`、未配置/`enabled=false` は profile 検証を skip、`enabled=true` 時のみ profile 必須 6 フィールドを Fail Fast 検証）。`yt-collection-serve` に `GET /distrokid/release.json`（`distrokid.profile` 静的データと `collections/planning/<theme>/` 動的データ＝アルバム名 / トラック / ジャケット / リリース日のマージ）と `GET /distrokid/assets/<path>`（曲・ジャケットの binary 配信、トラバーサルガード付き）を追加。`distrokid` 未配置/`enabled=false` のチャンネルでは `/distrokid/*` が 404 を返し、`/suno/prompts.json` は引き続き応答する。純データロジックは `youtube_automation.scripts.distrokid_release`（`build_release_payload` / `resolve_asset_path` / `DISTROKID_RELEASE_ROUTE` / `DISTROKID_ASSETS_PREFIX`）に分離。`examples/channel_config.example/distrokid.json` を追加。新規テスト `tests/test_collection_serve.py` / `tests/test_distrokid_release_endpoint.py`、`tests/test_config_loader.py` に distrokid セクションのケースを追加

### Changed

- `feat(suno)`: 1 pattern = 1 scene 原則を SKILL.md に追加し、`(Variation N)` 機械的接尾辞による曲タイトル生成を回避。各曲が固有の `name_jp` / `name_en` を持つ YAML 設計を強制する NG/OK 例付き。
- `feat(video-description)`: Benchmark 概要欄 TTP セクションを構造転写テーブル（7 項目）に拡充し、テンプレ使い回し禁止ルール・冒頭フックのコレクション固有化を追加。
- `docs(license)`: ライセンスを MIT から source-available custom license に変更した（#885）。転職活動のポートフォリオとして public 公開を維持しつつ、無断転載・再配布・商用利用・クレジット削除を抑止する。閲覧・学習・個人利用は許可、再配布・商用利用・改変・サブライセンスは書面許可なしに禁止。`README.md` の License 章と `pyproject.toml::license` も整合更新。
- `perf(videoup)`: 映像エフェクト (#648) をループ・ベイク方式へ刷新し、エフェクト有効時の動画書き出しを高速化した（generate_videos.sh v14）。従来はエフェクト ON でモード C（loop.mp4 + effect）/ モード D（静止画 + effect）ともに 2 時間尺を libx264 で全フレーム再エンコードしており 8〜15 分かかっていたが、エフェクト込みで 1 周期分だけ `10-assets/fx_baked.mp4` に焼き、あとは `-stream_loop -1 -c:v copy` で連結する方式へ変更して約 1〜2 分に短縮した（継ぎ目は closed GOP の stream copy で原理的に無損失）。これに伴いエフェクトの周期を整数固定にした: particles=36s（既存の `mod(t*30,1080)` のまま）/ bokeh=60s（overlay の揺れを `40*sin(2*PI*t/60)` / `30*cos(2*PI*t/60)` に整数周期化）/ gradient=72s（`gradients` を `speed=0` で静的化し、`crop` の `mod(t*15,1080)`=72s 周期だけに motion を限定）。背景が loop.mp4 のときは `lcm(round(loop 尺), 周期)` の長さを焼いて背景・エフェクト双方の継ぎ目を揃える。ベイク尺 ≥ 動画尺、または上限 `BAKE_MAX_LEN=900s` 超のときは従来の全尺再エンコードへ自動フォールバックし、短尺動画でも破綻しない。`fx_baked.params`（effect / intensity / 周期 / 元画像 mtime / maxrate）でキャッシュし、サムネ差し替え時のみ再ベイク（10〜40 秒）するためサムネ試行錯誤が軽い。あわせて静止画の fps/CRF/GOP・loop のビットレート上限/bufsize・effect の種別/強度・生成後の容量最適化（shrink）を **`config/skills/videoup.yaml` から取得する config 駆動**へ統一した（新規 env override は追加せず、`yaml_get` の 2-level flat YAML reader で読み、キー欠落時は現行固定値へフォールバック=無回帰。既存 `VIDEOUP_EFFECT` / `VIDEOUP_EFFECT_INTENSITY` env と `VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN` env は legacy fallback として存置）。新設の `shrink.enabled` + `maxrate`/`crf` を指定すると生成済み出力を 2 パス目で再エンコードして容量を絞れるが、全尺再エンコードのため stream copy の速度メリットは相殺される（最終版向け。上流の `loop_maxrate` 低減での容量制御を推奨、ファイル削除は `/live-clean` が担当）。SKILL.md に videoup.yaml スキーマ・所要時間目安・shrink/`/live-clean` 相互参照を追記。
- `perf(suno-helper)`: Balanced プリセットを増速した（#970、#948 後追い）。`maxInflightRequests` 5 → 10（`MAX_INFLIGHT_REQUESTS` 参照、#816 実機検証の Suno 実上限）、`interCreateDelayMs` 10000 → 6000（jitter ±3000 は維持し bot 検知の固定間隔シグナルを避ける）。従来の保守値は「Remix disabled プロキシによる in-flight 過大カウント + 1 失敗で全停止」時代のリスク対策であり、#948 で API status ベースの正確な計数と自動リトライ / スキップ継続が入った後は失敗 1 回のコストが小さく、定常速度（キュー容量 × 排出速度）を律速する cap を実上限まで開放するのがリスク対効果で最良。キュー飽和後の定常スループットはほぼ 2 倍になる見込み。suno-helper skill のプリセット表も更新。
- `refactor(distrokid)`: `30-distrokid/spec.json` を serve の SSOT とし、`metadata.md` を人間向け転記ドキュメントへ格下げした（#941）。`yt-distrokid-prepare build` 実行時に検証済み spec dict を `tempfile.mkstemp`→`os.replace` の atomic write で `30-distrokid/spec.json`（canonical パス）へ書き込む。`yt-collection-serve` の `GET /distrokid/collections` / `GET /collections/<id>/distrokid/<disc>/release.json` は spec.json を優先的に参照し、spec 不在または対象 disc のエントリが無い場合のみ従来の metadata.md 経路へフォールバックする（後方互換）。spec.json 破損（不正 JSON / トップレベル非 dict）は fail-loud で ConfigError を伝播させ、黙った metadata.md フォールバックによる古いデータ配信を防ぐ。共有読み書きロジックは `utils/distrokid_spec.py`（`read_collection_spec` / `find_disc_entry` / `title_map_from_entry` / `write_collection_spec`）に集約した。`utils/distrokid_prepare.py` の `SPEC_FILENAME` 定数は `distrokid_spec` からの re-export に変更し既存 import 元の後方互換を維持する。`tests/test_distrokid_spec.py` を新設（20 件）、既存 3 テストファイルに spec 優先経路と破損 fail-soft / canonical 書き込みのテストを追加（33 件）。
- `docs(skills)`: `/wf-new` Phase 2c の Suno 分岐と Phase 2d 完了ガイダンスを `/suno-helper` 連携に書き換えた。Phase 2c で `/suno` の役割を「プロンプト生成のみ。実際の楽曲生成は `/suno-helper` で連続実行」と明示し、Phase 2d 完了ガイダンスの Suno 分岐を従来の「`suno-prompts.md` のプロンプトを SunoAI に投入 → プレイリスト作成後 `/wf-next`」から「`/suno-helper` を実行 → `yt-collection-serve` で `suno-prompts.json` を配信 → suno-helper Chrome 拡張で連続注入 → 全件完了で playlist 一括追加まで自動。完了後に `/wf-next`」に置き換えた。Cross References にも `/suno-helper` を追記。自動 invoke は引き続き行わない（Chrome + Suno ログイン + 拡張ロードの physical 準備が user 側にあり、`/wf-next` への自動接続を入れていない既存方針と整合）。Lyria 分岐は不変
- `docs(skills)`: `/suno-helper` skill の起動モードを dir mode の無条件デフォルトに改めた。従来は「複数 collection を切り替える可能性があれば dir mode、1 件なら single file mode」の条件付き案内だったが、single file mode は playlist phase（全件完了後の clip 一括 playlist 化）がスキップされるため運用上常に dir mode 一択であり、Quick Reference / Step 1 / Step 2 の「Collection 選択」必須化 / Gotchas / Rules から single file mode の起動コマンドと条件分岐を撤去し、「必ず dir mode で起動する」「`curl /collections` が JSON array を返せば dir mode で起動できている」と一本化した。手順本体（preset / 進捗 phase / 中断時の resume 経路）は不変
- `docs(skills)`: `/suno` skill 内に分散していた suno-helper への次工程動線を skill 名参照で揃えた。`Step 2.5` という挿入番号を撤去して `Step 2.5` → `Step 3` / `Step 2.5 fallback` → `Step 3 の fallback` / 旧 `Step 3` → `Step 4` の整数並びへ採番し直し、Step 3 タイトルに `/suno-helper` を露出させた。description / 障害時ガイダンス / Next Step（インスト・ボーカル両分岐）の「楽曲生成は人手で Suno UI」「Step 2.5 の拡張自動投入」表現を `/suno-helper` 呼び出しへ置換し、Next Step の「ダウンロード対象のプレイリストを作成」行は `/suno-helper` が playlist 一括化を担うため削除（`/masterup` 直前に統合）。末尾に Cross References を新設して `/wf-new` ↔ `/suno` ↔ `/suno-helper` ↔ `/masterup` の双方向リンクを明示した。手順本体（パターン設計・歌詞設計・hard gate・Chrome 拡張の operator 手順）は不変
- `refactor(suno)`: `yt-generate-suno` に全曲ユニークタイトル検証 (`_validate_unique_titles`) を追加し、Suno UI Song Title 欄に注入される最終 `entry.name`（= `{name_jp} — {name_en}`、複数 scene の pattern は `(Variation N)` 付与後）が他 entry と重複していると `ConfigError` で fail-loud する。重複は (1) Suno Library で同名 clip が並んで識別不能になる、(2) `/suno-helper` の進捗 phase でどの entry の clip か追跡しにくくなる、(3) `/masterup` のリネーム時に衝突する、といった運用問題を起こすため yaml レベルで弾く。検証はインスト・ボーカル両モード一律（複数 scene の `(Variation N)` 付与済み後の name が比較対象なので、既存の multi-scene pattern は影響なし）。`_entry_names_from_resolved` ヘルパを切り出して `build_prompt_entries` と SSOT を共有し、`.claude/skills/suno/SKILL.md` の `## 曲数ベース設計（インストモード）` 手順 3 と Step 1 注意リストに「全 entry の `name_jp` / `name_en` の組はユニーク必須」と明記した（インスト/ボーカル両モード共通制約として）。tests に「全 entry ユニーク → 通る / 同一 name_jp+name_en の重複 → fail-loud + メッセージ assert / name_jp 同じでも name_en 違えば別物 / multi-scene の `(Variation N)` 付与で自動ユニーク化 → 通る」の 4 ケース追加
- `refactor(suno)`: `/suno` インストモードの設計モデルを「pattern × tracks_per_pattern」入れ子から「`tracks_per_collection` で曲数指定 → `ceil(N/2)` 個の独立 entry をフラットに並べる」モデルへ刷新した（**Breaking change**）。`/suno-helper` の登場で連続生成 + playlist 一括化が自動化された結果、AI / operator が pattern の意味（A〜D の感情起伏 / 同一 prompt の N 回再生成）を毎回設計し直す入れ子モデルが冗長になっていた。`.claude/skills/suno/config.default.yaml` に既定値 `tracks_per_collection: 20`（インストモード専用、`yaml` の top-level `tracks:` でコレクション単位に上書き可能）を追加し、未参照だった旧 documentation-only キー `patterns_per_collection: 4` を撤去（ボーカル用 `pattern_strategy` / `tracks_per_pattern` / `pattern_strategy_note` / `style_strategy` はコメントで「ボーカルモード専用」と明記して残置）。`src/youtube_automation/scripts/generate_suno_prompts.py::_resolve_prompts` の末尾にインストモード時のみ走る fail-loud 検証 `_validate_instrumental_track_count` を新設し、`yaml.tracks` (コレクション上書き) > `config.tracks_per_collection` の順で曲数を解決して `ceil(N/2)` と yaml `patterns:` 配列の scene 行数合計が一致しないと `ConfigError` で停止する（ボーカルモードは曲数定義が「1 prompt = 1 ベスト選曲」で異なるため検証対象外、未指定の旧運用は silent skip で後方互換）。`.claude/skills/suno/SKILL.md` の「パターンベース設計」セクションを `## 曲数ベース設計（インストモード）`（`ceil(N/2)` 算出式と新キー一覧）と `## パターンベース設計（ボーカルモード）`（旧 `pattern_strategy: mixed/single` 説明をそのまま温存）の 2 つに分割し、description / モード判定の表 / スタイルバリアント節 / ベンチマーク参照節 / Step 1 YAML 例 / Step 4 mood 蒸留ガイドからインスト文脈の `patterns_per_collection` 表現を全撤去した（ボーカル文脈の `patterns_per_collection` 表現は意図的に残置）。Vitest 同等の `tests/test_generate_suno_prompts.py` に「config 既定 20 + yaml 10 entry の整合」「不一致時の fail-loud メッセージ」「`tracks:` top-level 上書き」「ボーカルモードで検証スキップ」「旧 `patterns_per_collection` キー残存で無害」の 6 ケース追加と、`tests/test_suno_skill_doc.py` に新節タイトル + `tracks_per_collection` + `ceil` 言及の機械担保 assert を追加。yaml schema は `patterns:` 配列のまま維持し、`extensions/shared/api.ts::PromptEntry` 契約も変えていないため `/suno-helper` 側は不変
- `feat(suno-helper)`: `extractPlaylistName` (`shared/api.ts`) の命名規則を `<channel>-<theme>` から `<channel> | <theme>` (`|` の前後にスペース) へ変更し、シグネチャを `(collectionId, theme)` の 2 引数に変えた。channel 部分自体がハイフン区切り (例: `soulful-grooves`) になるチャンネルがあり、id 単体では channel と theme の境界を機械的に判定できなかったため、`/collections` レスポンスの `name` field (= 既に server 側で抽出済みの theme slug) を渡して逆向きに境界を確定する。検証ロジックは「末尾 `-collection` 剥がし → 末尾 `-<theme>` 照合 (不整合は fail-loud) → 残りを `-` 分割し parts[0] が 8 桁日付 + parts>=2 → channel = `parts.slice(1).join("-")` (空ならエラー) → `<channel> | <theme>` を返す」。例: `("20260601-rjn-dawn-cloud-fold-collection", "dawn-cloud-fold")` -> `"rjn | dawn-cloud-fold"`、`("20260520-soulful-grooves-midnight-mood-collection", "midnight-mood")` -> `"soulful-grooves | midnight-mood"`。popup の display only 表示と content script の Suno playlist 名注入はこの新形式をそのまま使う。呼び出し元 (`useSunoRunner.ts`) は collection summary から id + name の両方を渡すように更新。Vitest の `extract-playlist-name.test.ts` を新シグネチャ・新形式の expected に全面更新し、theme 空文字 / id-theme 不整合 / channel 空の新たな fail-loud 経路もカバーする
- `feat(suno-helper)`: popup を閉じて再 open しても連続実行の進捗（itemStates / phase / status / isRunning）が即時復元されるようにした（#852）。従来は popup の進捗が React.useState のみで永続化されず、20 曲一気投入の途中で popup を閉じると content の `runAll()` ループは継続するのに `progress` broadcast の listener が unmount で解除され、再 open で進捗を取りこぼしていた。content script を SSOT とし、各 progress 送出点で `sendMessage("progress")` の前に `currentSnapshot: SnapshotPayload` を同期更新（queryProgress との race 防止）、終了（FINISHED / STOPPED / ERROR）後も snapshot を保持して `isRunning=false` のみ更新する。popup → content の `queryProgress(): SnapshotPayload | null` メッセージを `lib/messaging.ts` の ProtocolMap に追加（既存 `run` / `stop` / `progress` のシグネチャは不変）し、popup は mount 時に `queryProgress` を試行して `buildRestoreState` で state を復元する（Suno タブでない / content 未注入は null / 失敗で従来表示へ silent fallback）。itemStates 遷移ロジックと status 文言は content（snapshot 構築）と popup（live 表示 / restore）で二重定義しないよう純関数へ SSOT 化した（`lib/snapshot.ts` の `initSnapshot` / `nextItemStates` / `applyProgress` / `isTerminalPhase`、`components/runner-errors.ts` の `phaseToStatus` / `buildRestoreState`）。`ItemState` / `SnapshotPayload` 型は `extensions/shared/constants.ts` へ集約。Vitest 3 本（`query-progress` / `use-suno-runner-restore` / `phase-to-status`）と Playwright e2e 1 本（`popup-reopen-progress`）で担保する。Suno タブごと閉じた場合の永続化（chrome.storage 併用）は scope 外（別 issue）
- `perf(suno-helper)`: `POLL_INTERVAL_MS` を 1000ms → 500ms に短縮した。`waitForGeneration` / `waitForQueueSlot` の poll 間隔が半分になり、Generate ボタン再 enable 検知と停止押下後の反応性が向上する。API 呼び出しレート (Suno 同時 20 clip = 10 リクエスト) には影響しないため CAPTCHA リスクは増えない。20 entries 連続実行で体感の「待ち時間」が緩和される。`wait-for-generation.test.ts` の定数ガードを 500 に追随
- `refactor(serve)!`: **破壊的変更** — `yt-suno-serve` CLI を `yt-collection-serve` に rename し、エンドポイントをサブパス分離した（#698）。配信ルートは `/prompts.json` → `/suno/prompts.json` に変更（#692 の JSON 契約 `[{name, style, lyrics}]` 自体は不変）。サーバー実装は `youtube_automation.scripts.suno_serve` → `youtube_automation.scripts.collection_serve` へ移動し、`pyproject.toml::[project.scripts]` の `yt-suno-serve` を**削除**して `yt-collection-serve` を追加（deprecated alias は残さない）。`extensions/suno-helper/`（素 JS）の fetch URL を `/suno/prompts.json` に追従、`.claude/skills/suno/SKILL.md` Step 2.5 の起動コマンドを `yt-collection-serve` に更新
- `refactor(extensions)`: `extensions/` の Chrome 拡張開発基盤を素 JS（手書き Manifest V3）から **WXT + React + TypeScript + Tailwind CSS + @webext-core/messaging + @wxt-dev/storage + Vitest + Playwright** に移行し、`extensions/suno-helper/` をリファレンス実装として全面書き直しした（#697）。manifest は `wxt.config.ts` から自動生成し、最小権限 `["storage","activeTab"]` を `lib/manifest.ts` の単一定数 `MANIFEST_PERMISSIONS` で宣言（`tabs` 等の過剰権限混入を Vitest `tests/manifest.test.ts` で機械担保）。複数拡張で再利用する共通コード（契約定数 / API client / origin allowlist / DOM 注入ヘルパ）を `extensions/shared/` に抽出。popup を React + Tailwind の SPA に、content script の Suno UI 注入（React 互換ネイティブイベント発火 / Generate 押下 / 完了検知 / reCAPTCHA 検知 / エラー停止）を振る舞いを保ったまま TS 化。`pnpm install && pnpm build` で `.output/chrome-mv3/` に MV3 拡張を生成し unpacked ロードする運用に変更。Vitest（unit）+ Playwright（Suno UI mock への DOM 注入 e2e スモーク）を整備し、`.github/workflows/extensions.yml` が PR で lint / 型チェック / Vitest / Playwright を実行、`.github/workflows/release-extensions.yml` が tag push 時に `pnpm zip` で拡張 zip を GitHub Release に添付する。旧 `tests/test_suno_extension_manifest.py`（最小権限ガード）は Vitest の manifest テストへ intent を移管し削除。`.gitignore` に `node_modules/` / `extensions/*/{dist,.wxt,.output}/` を追記しビルド成果物は commit しない

### Fixed

- `fix(suno-helper)`: auto-capture が Suno の URL 構造変更（`/me` → `/me/playlists`）に追従していなかったため、playlist mapping が `suno-playlists.json` に書き込まれず処理済みコレクションがドロップダウンに残り続けていた問題を修正した。併せて `captureFromTab` で SPA 未描画の空結果もリトライ対象にした。
- `fix(suno-helper)`: overlay パネルのコンテンツが画面外にはみ出してスクロールできなかった問題を修正した。`max-height: calc(100vh - 120px)` + `overflow-y: auto` を追加。
- `fix(suno-helper)`: マルチワード prefix（例: `soulful-grooves`）のチャンネルで playlist 名の境界分割が壊れ、Suno に `soulful | grooves-wah-groove` のような誤った playlist 名で作成されていた問題を修正した。サーバー側で `derive_playlist_name` を使って正しい `<prefix> | <theme>` を算出し、`/collections` API の `playlist_name` フィールドとして返すようにした。拡張はサーバーの値を優先使用し、旧サーバーでは `extractPlaylistName` fallback で後方互換を維持する。
- `docs(suno-helper)`: SKILL.md にサーバー起動後の 3 点確認（mapped / playlist_name / dir mode）、下流 venv 更新手順、Suno URL/DOM 変更時のトラブルシュート手順を追加した。
- `fix(suno-helper)`: SKILL.md のサーバー起動コマンドに `--playlist-capture-root` / `--playlist-capture-prefix` フラグが欠落しており、auto-mapping（mapped 全件 false）と手動 playlist sync（POST 404）が機能しなかった問題を修正した。
- `fix(benchmark)`: ベンチマーク収集のサムネイル分析で Gemini 2.5 Pro（Vertex AI）をデフォルトで全動画に呼び出しており、2チャンネル分の初回収集で ¥6,000 の課金が発生していた問題を修正した。サムネイル分析の実行主体を Gemini API からエージェントの画像読み取り機能（Read ツール）に移行した（追加課金なし）。設定キーを `analyze_thumbnails` → `gemini_thumbnail_analysis`（既定 `false`）にリネームし、明示的に Gemini を使う場合もデフォルトモデルを Pro → Flash に変更（コスト 1/10〜1/20）。あわせて実行前のコストプレビュー表示、Gemini 呼び出しの cost_tracker 記録（`"analysis"` カテゴリ新設）、`-y` 確認スキップフラグを追加した。
- `fix(suno-helper)`: Weirdness / Style Influence slider 注入が target に届かず skip される問題を修正した（#979）。#973 の bridge 経路（React onKeyDown 直接呼び出し）は最初に 1 回だけ `__reactProps$*` からハンドラを取得して使い回していたが、React は setState → 再レンダーのたびに onKeyDown を新しい closure に差し替えるため、取得済みハンドラは **1 step 動いた時点で stale** になり、捕捉済みの古い値を再セットするだけの空振りで「変化なし」→ false → fallback 縮退していた（実機検証: 使い回しは 1 step で停止、毎 step 再取得で完走）。`lib/slider-bridge.ts::setSliderValueViaReact` をループ内で毎 step `findReactKeyDownTarget` を解決し直す方式へ変更。fallback の `shared/dom.ts::setSliderValue` も「全 diff 分の keydown を同期一括 dispatch」が React の自動バッチングで stale 値に収束し net 1 step しか動かないことが実機で判明したため、1 step dispatch → aria-valuenow の変化を poll → 次 step の逐次方式へ刷新した（上限 `SLIDER_MAX_STEPS`=150）。あわせて #900/#973 の「Suno が isTrusted で合成イベントを弾く」診断は誤りと実機で確認（素の dispatchEvent も 1 step ずつ反映を待てば完走する）し、fail-loud エラーメッセージの誤診文言「Suno が合成イベントを弾いている可能性が高いです」を「keydown 後も aria-valuenow が変化しませんでした。Suno の UI 変更の可能性があります」へ修正した。ユーザー報告の `target=10, actual=48`（初期値 50）は bridge 1 step + fallback net 1 step の痕跡と整合する。Vitest に「再レンダーで handler が差し替わる React 模倣 slider」での stale 再現 + 完走 3 ケースと、「値の反映が非同期（再レンダー相当）の slider で 1 step ずつ待って完走」の回帰 1 ケースを追加
- `fix(collection-serve)`: suno-playlists.json のスキーマ不一致と prefix / slug 突合バグで playlist マッピング（mapped 判定）が全チャンネルで機能していなかったのを修正した（#976）。(1) 下流チャンネルに残る旧 wf-batch list スキーマ `[{slug, suno_url, suno_title, captured_at}]` を `_read_playlists_json` が「破損 → 空 dict」扱いし全件未マッピング判定 + capture 実行時に既存マッピングを上書き消失させていたため、list を dict スキーマ `{slug: {title, url, captured_at}}` へ写像して読む互換を追加（`_playlists_list_to_dict`、正準スキーマは dict のまま）。(2) `normalize_suno_title` の prefix 比較が `soulful-grooves` と playlist title 側の `Soulful Grooves` を不一致にしていたため、prefix をセグメント分割して `[\s-]+` 連結する `_prefix_pattern` で空白 / ハイフンを同一視（出力 slug は従来どおり `prefix.lower()` のハイフン正準形）。(3) `derive_collection_slug` が「date + 1 トークン」剥がしのため複数トークンチャンネル名（`20260611-soulful-grooves-<theme>-collection`）で 2 トークン目が theme に混入し playlist 側 slug と永遠に不一致だったのを、date 剥がし後に prefix と前方一致（大小無視・空白 / ハイフン無差別）すれば prefix 全体を剥がす方式へ変更（不一致時は従来の 1 トークン剥がしに fallback し、dir のチャンネル表記と prefix が異なる運用 — 例: dir `df365-...` + prefix `DF` — の後方互換を維持）。
- `fix(suno-helper)`: Style Influence / Weirdness slider 注入が Suno の isTrusted チェックで弾かれ warn + skip され、指定値が反映されないまま生成される問題を修正した（#973）。Suno の slider は onKeyDown 内で `isTrusted` を検証するため `dispatchEvent` による合成 KeyboardEvent は原理的に動かない（#900 実機検証の既知問題。従来案は chrome.debugger API だったが permission 追加 + 「デバッグ中」警告バナー常時表示のコストが大きい）。代わりに #948 で導入済みの MAIN world fetch bridge に slider 注入 RPC（`BRIDGE_MSG.SLIDER_SET_REQUEST` / `SLIDER_SET_RESPONSE`）を追加し、MAIN world からのみアクセスできる React の `__reactProps$*` expando から onKeyDown ハンドラを取得して `isTrusted: true` を持つ疑似イベントオブジェクトで直接呼び出すことでチェックを通過させる（新設 `lib/slider-bridge.ts`: 祖先 5 段までの props 探索 / step ごとの aria-valuenow 読み戻しで過走なく収束 / 値が動かなければ即 false）。`injectAdvancedFields` は `options.bridgeSetSlider` DI で bridge 経路を優先し、bridge 失敗（plain DOM の e2e mock 等）は従来の合成 dispatchEvent へ、両方失敗は従来どおり warn + skip へ縮退する（後退なし）。manifest 権限は不変。
- `fix(collection-serve)`: 破損 spec.json（存在するが不正 JSON）に対する `read_collection_spec` の `ConfigError`（#941 fail-loud）が `GET /distrokid/release.json`（単一 mode）/ `GET /collections/<id>/distrokid/<disc>/release.json`（dir mode）の handler で未捕捉のままスレッドを落とし、HTTP レスポンスなしの接続切断（curl では HTTP 000）になっていたのを修正した（#944）。distrokid-helper 拡張はメッセージなしのネットワークエラーしか受け取れず原因が分からなかった。`_Handler` に `_send_json_error(status, message)` ヘルパを追加し（`send_error` と異なり CORS ヘッダ付き + JSON ボディ `{"error": ...}` で返すため、コンテキストを問わず fetch がステータスを読める）、両 route の `build_release_payload` 呼び出しを `try/except ConfigError` で囲って 500 + エラーメッセージを返すようにした。破損 spec で古いデータを配信しない fail-loud の設計意図は維持する。回帰テストを `tests/test_distrokid_release_endpoint.py`（単一 mode、`serve` fixture に `distrokid_source` 引数を追加）と `tests/test_distrokid_collections_endpoint.py`（dir mode、CORS ヘッダ検証込み）に追加
- `fix(suno-helper)`: captcha 検知時の挙動を「即 fail-loud 停止」から「`waiting-captcha` 待機 → 解消後に自動続行」へ変更した（#946）。Suno の hCaptcha は Generate click に反応して challenge を起動するが、多くは passive 検証で数秒以内に自動 verify されて閉じる（console: `captcha required, awaiting verification` → `captcha verified`）ため、従来の即 throw だと「画面に challenge が表示されていないのに中断: reCAPTCHA を検知しました」が entry ごとに発生し、大規模 collection の連続実行が手動再開なしでは完走できなかった。対応: (1) `shared/dom.ts` に `waitForCaptchaClear(options)` を新設し、challenge 解消（自動 verify or 手動解決）まで poll で待機、`CAPTCHA_WAIT_TIMEOUT_MS`（10 分）超過時のみ fail-loud throw、中断 (isAborted) は即 return。(2) `waitForGeneration` は captcha 検知で throw する代わりに `waitForCaptchaClear` へ移行し、待機分だけ deadline を延長する（生成タイムアウト `GENERATE_TIMEOUT_MS` を消費しない）。(3) `content.ts` の Generate click 前チェックも同様に待機化し、新 phase `PHASE.WAITING_CAPTCHA`（`waiting-captcha`）で popup に「captcha 解消待ち…（多くは自動で解消します）」を表示する。(4) `detectRecaptcha` は検証完了後に title と bbox を保持したまま画面外（`y:-9999`、wrapper `opacity:0` + `z-index:-2147483648`）へ駐機する challenge iframe を `rect.bottom <= 0` で除外する — #875 の title 非空ヒューリスティックが verify 後の駐機 iframe を恒久誤検知し、再開しても即 ERROR で停止し続ける問題の修正。captcha に Generate click が握り潰されたケースは既存 `injectWithVerification` の ack 検証 (#864) がそのまま retry で救済する。Vitest に waitForCaptchaClear 4 ケース / waitForGeneration の captcha 待機 3 ケース（自動 verify 続行・deadline 延長・残留 timeout throw）/ detectRecaptcha 駐機除外 1 ケース / phase 表示 1 ケースを追加
- `fix(suno-helper)`: background service worker の fire-and-forget 中継 2 箇所（action クリック時の `toggleOverlay` / runner → overlay の `progress`）が `void sendMessage(...)` で Promise を投げ捨てており、content script 未注入のタブで reject すると `Uncaught (in promise) Error: Could not establish connection. Receiving end does not exist.` が未処理 rejection として chrome://extensions のエラーバッジに蓄積されるバグを修正した（#937）。`toggleOverlay` は suno.com 以外のタブでアイコンをクリックすると必ず reject し（content script は `manifest.matches` の suno.com にしか注入されない）、拡張リロード後にハードリロードしていない stale な Suno タブでも同様に発生する。`progress` はページ遷移・タブ閉鎖のレースで overlay 側リスナーが消えていると reject する。run / stop / queryProgress / capturePlaylists の中継は Promise を `onMessage` ハンドラに return しており @webext-core/messaging がエラーを呼び出し元へシリアライズして返すため対象外（捨てる場所だけが未処理になる）。対応: `components/runner-errors.ts` に純関数 `describeRelayFailure(action, message)` を追加し（既存 `isContentScriptMissingError` を再利用、missing-receiver → `level: "info"` + ハードリロード案内、それ以外 → `level: "warn"`）、`toggleOverlay` の catch でその結果を `console.info` / `console.warn` に出す。高頻度な `progress` は `console.debug` のみで握りつぶす（spam 防止、取りこぼしても次の通知で追いつく）。機能挙動の変更はなし（中継先がない時に静かに失敗する点は同じで、未処理 rejection をログ消費に変えただけ）。Vitest `tests/relay-failure.test.ts` に `describeRelayFailure` の回帰 6 ケース（missing-receiver → info + ハードリロード案内 / 大文字小文字ゆらぎ 3 種 / 一般エラー → warn / 空メッセージ → warn）を追加`scripts/distrokid_release.py::_read_release_date` が `workflow-state.json::planning.publish_target_at` を素通しで payload に載せていたため、ISO datetime（例 `"2026-03-22T08:00:00+09:00"`）をそのまま `<input type="date">` に渡しても空値になっていた。`_normalize_release_date` ヘルパを追加し `datetime.fromisoformat(raw).date().isoformat()` で `YYYY-MM-DD` へ正規化する（date のみ形式も full ISO datetime も 1 本で処理、parse 不能 / 非文字列は `ConfigError` で fail-loud）。拡張側 `injectReleaseDate` は `requireInput` 経由で要素不在だと `FieldNotFoundError` を throw しフィル全体が停止していたが、`#release-date-dp` は DistroKid の契約プランによって UI 自体が出ない場合があるため `querySelector` へ変更し、要素不在時は `console.warn` + skip でフィルを続行するよう変更した
- `fix(distrokid)`: `DistrokidProfileCredits.performer_role` の既定値を実在しない `"Audio"` から `"Synthesizer"` に修正した（#930）。実機 DOM 検証（2026-06-11）で `#track-N-performer-1-role` の option は 84 件・楽器名のみで `"Audio"` は存在しないことが判明。`"Audio"` を指定すると `setSelectValue` が `OptionNotFoundError` で fail-loud していた。AI 制作 BGM の実態に最も近い実在 option として `"Synthesizer"` を採用した。変更箇所は `utils/config/distrokid.py::DistrokidProfileCredits` フィールド既定値・docstring、`utils/config/loader.py::_build_credits` の JSON fallback 値、`extensions/distrokid-helper/lib/distrokid-injector.ts` の doc コメント（ロジック変更なし）の 3 箇所
- `fix(suno-helper)`: entry 数 × 2 clip が初期ロード 40 件を超えるコレクションで playlist 追加が漏れるバグを修正した（#924 Fix 3）。原因は Suno の clip list（`.clip-browser-list-scroller`）が**遅延ロード（無限スクロール）**実装であること。実機確認: 初期ロードは 40 row のみ（scrollHeight 3031 / clientHeight 650）で、`scroller.scrollTop = scroller.scrollHeight` + `scroller.dispatchEvent(new Event("scroll"))` で +20 row ずつ追加ロードされる（40→60→80→100 を実測）。ロード済み row は unmount されない（仮想化ではない）ため、画面外の row も DOM に存在して click 可能。旧実装 `selectRecentClips(count)` はロード済み row しか拾えず、不足しても `rows.slice(0, count)` で**黙って少なく返す（silent slice）**ため、再開後に「作った曲しか追加されない」症状を引き起こしていた。対応: `selectRecentClips` を撤去し `ensureClipRowsLoaded(count, opts)` を新設。この関数は scroller を底方向へスクロールし、count 件の row が DOM にロードされるまで poll で待機する（`pollIntervalMs` 間隔、`loadSettleTimeoutMs` 上限）。`isAborted()` が true なら打ち切り即 return（throw しない）。リスト末尾（追加ロードが止まる）まで到達しても不足する場合は「X/Y 件しかロードできませんでした」の実件数/要求件数を含むメッセージで **fail-loud throw**（silent slice を廃止）。成功時は `scrollTop = 0` に戻してから先頭 count 件を返す（選択・Cmd+P 操作を初期表示位置で行うため）。また `multiSelectClips` の verify deadline を `Math.max(CLIP_SELECT_VERIFY_TIMEOUT_MS, rows.length * 50)` でスケールし、60-80 件など大規模コレクションで 1 秒に収まらないリスクに対応した（50ms/row は `CLIP_SELECT_VERIFY_MS_PER_ROW` 定数化）。`entrypoints/content.ts` の `addClipsToPlaylist` を `ensureClipRowsLoaded` ベースに置き換え、ロード走査後の `aborted` 再チェックで部分状態のまま Cmd+P に進まない経路を確保した。Vitest に 9 ケース追加（初期ロード十分・1 回追加ロード・複数回追加ロード・末尾不足の fail-loud throw・isAborted 打ち切り・scrollTop 0 復帰・scroller 不在・row 0 件・中間ラッパ collapse なし）。Playwright e2e に「初期 4 row → scroll で +4 row → 8 件選択 → Cmd+P → Create → dialog 消滅」スモークケースを追加（実 overflow scroller + scroll イベント遅延ロード mock）。
- `fix(suno-helper)`: 連続生成が中断（stop / waitForGeneration 内の captcha・timeout エラー）した後に再開すると、直前に投入した entry がもう一度生成されて **n+1 重複** が発生するバグを修正した（#924 Fix 2）。原因は `persistInterruptState(i)` が常に現在の entry index を永続化していたため、再開時に `resumeRunRange` が `failedIndex` から始まる range を構築し、既に Generate を click した entry も再実行していたこと。加えて `injectAndGenerate` 内の `abortableSleep(SETTLE_MS)` 後に abort チェックが無く、停止押下後でも Generate ボタンを click してしまう経路があった。対応: (1) `lib/inject-retry.ts` に専用エラークラス `InjectNotAcknowledgedError`（全 attempt で in-flight 増加が確認できなかった終端エラー）を追加し、終端 throw を `Error` → `InjectNotAcknowledgedError` に置き換えた（メッセージ不変）。(2) `lib/resume-state.ts` に純関数 `resolveInterruptIndex(currentIndex, submitted, isNotAcknowledged)` を追加: Generate click 済み（submitted=true）かつ silent drop 確定でない → currentIndex + 1（再生成しない）、それ以外（click 前の中断・InjectNotAcknowledgedError）→ currentIndex（再生成する）。(3) `entrypoints/content.ts` の `injectAndGenerate` に「関数冒頭で `lastSubmittedEntryIndex = -1` にリセット（前 attempt の click を次 attempt に誤引き継ぎする欠落バグを防ぐ）」「`abortableSleep` 後に `if (aborted) return;`（停止押下後に Generate を押さない）」「`button.click()` 直後に `lastSubmittedEntryIndex = index`」を追加。`runAll` の STOPPED（injectWithVerification 後）/ ERROR catch を `resolveInterruptIndex` ベースに変更し、ループ先頭・waitForQueueSlot 後の STOPPED は従来どおり `i`（この時点では未 click）のままコメントを明記。(4) `applyProgress` の failedIndex doc コメントを新 semantics（「次に実行する index」）へ更新。(5) `components/App.tsx` の再開バナー文言を新 semantics に整合: `failedIndex < total` なら「前回の実行が中断されました。entry N から再開しますか？」、`failedIndex >= total` なら「全 entry 投入済みです。playlist 追加から再開しますか？」。**トレードオフ**: ack 待ち中に abort された場合は受理未確認のまま i+1 となり、稀に未受理 entry を skip し得る（重複より欠落を許容する方針。range 手動指定で救済可能）。旧 `ResumeState` が残っていた場合は旧挙動どおり（劣化なし、マイグレーション不要）。Vitest に `resolveInterruptIndex` の 4 ケース（submitted=false / submitted=true+受理済み / submitted=true+NotAcknowledged / i=total-1 の round-trip）と `InjectNotAcknowledgedError` の 3 ケース（instanceof / name / メッセージ不変）を追加。
- `fix(suno-helper)`: `detectRecaptcha()` が reCAPTCHA anchor / hCaptcha checkbox widget などの**常駐 widget iframe** を誤検知し、captcha が表示されていないのに連続生成が中断するバグを修正した（#924）。原因は #875 で導入した「bbox>0 かつ title 非空なら visibility:hidden でも検知する」ヒューリスティックが challenge 系以外の iframe にも適用されていたこと。reCAPTCHA anchor は title="reCAPTCHA" を常時保持し、hCaptcha checkbox widget も常時 title を持つため、それらが `SELECTORS.recaptcha` にマッチすると title 非空 → true で誤検知していた。対応として内部ヘルパ `isChallengeFrame(src)` を追加し、title 非空ヒューリスティックを **challenge 系 iframe（hCaptcha は `#frame=challenge`、reCAPTCHA は `/bframe` を含む src）に限定** した。challenge 系以外の iframe は従来通り strict `isVisible()` のみで判定する（#875 のヒューリスティック自体は challenge 系において維持）。誤検知の対象 iframe は動的挿入のため静的確認が困難なため、true を返す際に src / title / bbox / visibility を `console.debug("[suno-helper] captcha challenge iframe detected", {...})` で出力し、次回発生時に真因確定できるよう診断ログを追加した。Vitest に「hidden hCaptcha checkbox widget → false」「hidden reCAPTCHA anchor → false」「hidden reCAPTCHA bframe → true」「hidden hCaptcha challenge (#frame=challenge) → true（#875 回帰ガード）」「可視 anchor widget → true（isVisible 経路維持）」の 5 ケースを `describe("title 判定は challenge 系 iframe に限定 (#924)")` として追加。既存の `title 判定の 4 組合せ (#875)` describe は challenge 系 src（`#frame=challenge` 付き）を使うよう fixture を更新した
- `fix(distrokid-helper)`: 25 tracks album のフィル時に「アルバム名 / リリース日 / Apple Music 担当（クレジット role） / 利用規約同意」が未入力で残り、送信できないバグを修正した（#919）。chrome-devtools MCP で実機観察した結果、以下 4 点を一度に潰す必要があったため 1 コミットでまとめた: (1) `injectAlbumTitle` / `injectReleaseDate` が `findVisibleField` の `isVisible` filter で silent skip していた。`#albumTitleInput` / `#release-date-dp` は `<input type=text|date>` で id 一意のため type=hidden 排除は不要だが、`setTrackCount(25)` 直後の DistroKid 内部 re-layout で `getBoundingClientRect` が一時的に 0×0 になる瞬間があり、`isVisible` が false 判定して `findVisibleField` が null を返す → 値注入を skip するレースが retest で観測された。`requireInput` ベース（id 直接取得・bbox 非依存）に変更し、fail-loud にして UI 変更や race を即座に検知する。(2) Apple Music クレジット行の role 欄（`#track-N-performer-1-role` 86 options / `#track-N-producer-1-role` 40 options）が未注入。実機 DOM はネイティブ `<select>` に `dk-searchable-select__native` クラスをつけて `display:none` で隠し、上に DistroKid 独自の searchable dropdown UI（`.dk-searchable-select__input`）が乗る設計だが、ネイティブ側の `selectedIndex` 変更 + `change` event dispatch で独自 UI 側の表示テキストも同期されることを実機検証で確認したため、`injectAppleMusicCredits` を `(root, trackCount)` から `(root, trackCount, credits)` にシグネチャ拡張し、PR #911 で導入した `setSelectValue`（option.value 完全一致 → option.text 完全一致 → 部分一致 fallback）で `profile.credits.performer_role` / `producer_role` をネイティブ select に流す。一致無しは `OptionNotFoundError` で fail-loud。(3) DistroKid 利用規約同意 checkbox `#areyousuretandc` が unchecked のままだと送信時に validation で止まるため、`acceptTermsAgreement(document)` を新設し `injectStaticFields` 末尾で `setChecked(true)`（既に check 済みなら no-op）。要素不在は `FieldNotFoundError` で fail-loud。(4) `APPLE_CREDIT_SELECTORS` の API を `performerByTrack` / `producerByTrack` から `performerNameByTrack` / `performerRoleByTrack` / `producerNameByTrack` / `producerRoleByTrack` の 4 分割に再設計し、name 欄と role 欄を別々に injection 可能にした。Vitest を 91→123 ケースへ拡張（race 回避の bbox=0 ケース・role の change dispatch 観測・OptionNotFoundError 経路・利用規約 fail-loud・upsell 強制 uncheck・name=store/extras 以外を触らない不変・doneButton scrollIntoView 引数（smooth + center）の機械担保）。Playwright e2e fixture（`tests/e2e/fixtures/distrokid-new.html`）も role select / 利用規約 / upsell / doneButton を追加して実 DOM 準拠で組み直し。`.output/chrome-mv3/content-scripts/content.js` を再ビルド済み（28.26 kB）。規約遵守で `#doneButton` の自動 click は引き続き行わない
- `fix(distrokid-release)`: `yt-collection-serve --distrokid-source 30-distrokid/disc{N}-...` の `/distrokid/release.json` payload で、`<collection>/30-distrokid/disc{N}-.../metadata.md` の「| 言語 | ... |」セルが `profile.language` を上書きしていた挙動を撤廃し、`profile.language` を権威にした（#888 第2回 retest 後の続報）。実機 BGM チャンネル運用で metadata.md の「言語」セルに楽曲属性表記の `Instrumental`（全曲インスト宣言）が書かれているケースを再現確認し、その値が serve → distrokid-helper 拡張 → `<select id="language">` まで伝搬した結果、DistroKid `#language` の 45 言語 option（`Arabic` / `English` / `Japanese` 等）には `Instrumental` が無いため、上で追加した `OptionNotFoundError` が fail-loud で発火していた。原因は `distrokid_release.py::_disc_source_payload` の `language = album_meta["language"] or profile["language"]` で metadata.md の値を優先していたこと。metadata.md の「言語」は人間が読む転記用テンプレで、DistroKid form 言語 option（歌詞の言語）と意味が異なる値（楽曲属性等）が書かれうるため、payload には反映しない方針へ統一し、`{"profile": profile, ...}` をそのまま返すように単純化した（spread での language 上書きを撤廃）。`config/channel/distrokid.json::profile.language` が単一情報源になる。`parse_album_metadata` の language キー抽出は破壊しない（将来 form 互換値が来た場合に備えて残置、現状未使用）。pytest `tests/test_distrokid_disc_source.py` を新方針に追従させ、`test_disc_source_language_overridden_by_metadata`（旧）を `test_disc_source_language_uses_profile_ignoring_metadata` に置き換え（metadata.md=`Instrumental` でも profile=`ja` を維持することを assert）、`test_release_endpoint_serves_disc_source_payload` の統合検証も `profile.language == "ja"` に揃えた。下流チャンネルリポの metadata.md（`| 言語 | Instrumental |`）は手動で `| 言語 | English |` に書き直してリリースを進める運用とする（テンプレ生成スクリプトは automation 本流に存在しないため）
- `fix(distrokid-helper)`: 25 tracks album を全フィルした直後に DistroKid 本体の `distroSubmitNewAlbumForm` が `Uncaught TypeError: Cannot read properties of null (reading 'trim')` で crash し、送信ボタン `#doneButton` が「確認しています…」(`distroDoneButtonWithAPI .disabled`) で stuck したまま `resetUploadDoneButton()` まで到達せず、ページ reload しないとリリースを進められないバグを修正した（#888 第2回 retest）。chrome-devtools MCP で trap (try-catch ラッパ) を仕掛けて取った stack trace から実機 line 6507 col 35 (`else if ($j('#genrePrimary').val().trim() == '')`) が crash 点と特定し、`<select id="genrePrimary">` がフィル後も `selectedIndex === -1` のままで jQuery `.val()` が `null` を返している（DistroKid 本体側に `(.val() || '').trim()` のガードが無い）状態を再現確認した。原因は拡張側 `setNativeValue` が `HTMLSelectElement.prototype.value` の native setter を直接叩いていた点: 実機 DistroKid (JA UI) では `<option value="25">R&B／ソウル</option>` のように value が数値で text が日本語ラベルだが、payload は `"Electronic"` のような英語キーで送っていたため、`select.value = "Electronic"` を実行しても対応 option が無く selectedIndex が -1 のまま放置され、その後の DistroKid validation で `.val()` が null → crash 連鎖していた。`lib/distrokid-injector.ts::setNativeValue` を `<select>` 検出時に新ヘルパー `setSelectValue` へ委譲する分岐を入れ、優先順「option.value 完全一致 → option.text 完全一致（normalize: NFKC + ／→/ + lowercase + trim）→ option.text 部分一致（placeholder `value=""` は除外）」で option を解決し `selectedIndex` を明示更新する。一致無しは新エラー `OptionNotFoundError` で fail-loud し、config と実機 UI の不整合を即座に検知する（silent skip しない）。設計上の意味: payload を実機 UI 言語の label (例 `"R&B／ソウル"`) または option.value (例 `"25"`) に揃える運用に振り、normalize fallback は ASCII 微妙差 (`／` vs `/`、大文字小文字、`"Electronic"` ↔ `"Electronic Dance"`) を吸収する safety net とする。Vitest に 8 ケース追加（value 完全一致 / text 完全一致 / normalize ／→/ / 部分一致 fallback / placeholder skip / 一致無しの fail-loud / input/change の bubbles 発火 / `OptionNotFoundError` メッセージ機械担保）し、`tests/distrokid-injector.test.ts` の `mountSelectWithOptions(id, [{value, text}])` ヘルパで実機準拠の数値 value + 日本語 text を再現。`.output/chrome-mv3/content-scripts/content.js` を再ビルドし、規約遵守で `#doneButton` 自動 click は引き続き行わない
- `fix(suno-helper)`: `yt-collection-serve` をデフォルト（`--allow-origin` 未指定）で起動すると、overlay 化（#892 / PR #895）後に suno.com の content script から発火する fetch が CORS preflight で block されて `Failed to fetch` になっていた回帰を修正した（#896）。MV3 では content script の fetch が page origin（`https://suno.com`）として扱われるため、`chrome-extension://` scheme のみをデフォルト許可していた `is_origin_allowed` が `Access-Control-Allow-Origin` を echo できなかったのが原因。`collection_serve.py` に `_DEFAULT_ALLOWED_WEB_ORIGINS`（`https://suno.com` / `https://www.suno.com` / `https://distrokid.com` / `https://www.distrokid.com`、完全一致）を新設し、`allow_origin=None` のとき extension scheme に加えてこの集合を許可するよう変更した。distrokid.com 系は同根原因の予防的追加（#896 要件3）。`--allow-origin <origin>` 明示時の完全一致ロック挙動は不変（デフォルト許可リストは効かない）。前方一致偽装（`https://suno.com.evil.com`）/ scheme 差異（`http://suno.com`）/ 末尾スラッシュは通さない。`tests/test_collection_serve.py` に `is_origin_allowed` の parametrize ケースと suno.com origin の GET / OPTIONS preflight / lock 回帰テストを追加。suno-helper / distrokid-helper README の CORS 案内も「デフォルトで suno.com / distrokid.com も通る」に更新した
- `fix(distrokid-helper)`: 25 tracks album で「フォーム一括入力」を実行すると AI 開示注入の最終段で `FieldNotFoundError: [name="ai_partial_audio_type_<uuid>"][value="undefined"]` で停止していたバグを修正し、AI 開示フローを SweetAlert2 modal に対応させた（#877）。直接原因は `injectAiDisclosureForTrack` の `partial_audio_type !== null` 判定が `undefined !== null` を通して selector に文字列 `undefined` を埋め込んでいたこと（`!= null` の loose equality へ修正）。実機 DOM を chrome-devtools MCP で再観察した結果、AI 開示は inline 展開ではなく SweetAlert2 ベースの modal（`.ai-credits-swal-modal`）で開き、modal 内の「Apply these selections to all songs on this release」（`#ai-apply-all-1`）checkbox を入れて保存すると全 track に伝播する設計と判明したため、track ごとの inline 一括注入を破棄し「1st track の `ai_gate`「はい」click → `MutationObserver` で modal mount を待つ → modal 内で歌詞 / 作曲 / 録音範囲（`.distroAiRecordingScope`）/ partial 種別 / アーティスト種別（`.distroAiArtistPersona`）/ apply-all を設定 → 保存 button → modal unmount を待つ」async フロー（`injectAiDisclosure` / `waitForElement` / `waitForRemoval`、modal が出現/消失しなければ `ModalTimeoutError` で fail-loud）へ刷新した。Python `utils.config.distrokid.AiDisclosure` と TS `lib/types.ts::AiDisclosure` に新フィールド `recording_scope`（"full"/"partial"）/ `artist_persona`（AI ペルソナ=true）/ `apply_to_all` を追加し、`composition` を `music` にリネーム（loader で recording_scope と partial_audio_type をクロスバリデーション、`yt-distrokid-migrate` が旧 `composition` → `music` 変換・新フィールド default 補完・`recording_scope` 未指定かつ `partial_audio_type` 非 null のときの `recording_scope="partial"` 導出を担当）。`InjectSession.finish` / `Injector.injectAiDisclosure` を async 化。Vitest（modal mount/unmount 待ち・apply-all 伝播・loose equality 回帰）/ Playwright e2e（1 click → modal → 保存 → 全 track 反映）/ Python tests を新仕様へ追従し、fixture HTML も swal2 modal mount script へ書き換え、`.output/chrome-mv3/content-scripts/content.js` を再ビルドした
- `fix(distrokid-helper)`: 実機 DistroKid `/new` で popup から「フォーム一括入力」を実行すると `注入先フィールドが見つかりません: [name="artist_name"]` で停止していたバグを修正した（#874）。直接原因は `.output/chrome-mv3/` の build artifact が PR #815 撤廃前のままで旧フラット selector マップ（`var f={artist_name: '[name="artist_name"]', ...}`）が残っていたこと（再ビルドで解消）。実機 DOM 検証（chrome-devtools MCP）でさらに `AI_DISCLOSURE_SELECTORS`（`#ai-yes` / `#ai-modal` / `[name^="ai_lyrics_"]` / `#ai-apply-all-1` / `#ai-save`）が fixture-driven で実 DOM と完全に乖離していることが判明したため、uuid-driven 関数群（`gateByUuid` / `lyricsByUuid` / `compositionByUuid` / `partialAudioTypeByUuid`）に刷新し、`injectAiDisclosure` を「全 track の uuid を `resolveTrackUuids` で解決して各 track にループで一括注入する sync 関数」に再設計した（実 DOM の `ai_lyrics_<uuid>` / `ai_music_<uuid>` checkbox は `display:none` の親に隠れているが `el.click()` 自体は React 制御に届くため `MutationObserver` の展開待ちは不要、apply_to_all checkbox は実 DOM に存在しないためループによる一括適用で代替）。Python `utils.config.distrokid.AiDisclosure` と TS `lib/types.ts::AiDisclosure` も実 DOM 準拠で再設計し、`full_audio` / `partial_audio` / `apply_to_all` の 3 boolean を撤廃して `partial_audio_type: "vocals" | "instruments" | null` を追加（loader は旧 keys を silent に無視するため下流チャンネルの `distrokid.json` 書き換えは不要）。Vitest / Playwright / Python tests を新仕様に追従し、fixture HTML も実 DOM 準拠に書き換え
- `fix(suno-helper)`: 20 entries 投入時に entry 11 付近で runner が ERROR 落ちして残り entries が injection されないバグと、生成完了 entry でも 2 clip 揃わず 1 clip しか出ないバグを根本修正した（#864）。原因 3 つを同時に潰した: (1) `waitForQueueSlot` が single clip 完了待ち用の 3 分 timeout を流用していた → `QUEUE_SLOT_WAIT_TIMEOUT_MS = 5 分` を独立定数として新設、(2) `INTER_CREATE_DELAY_MS` が 1 秒で短く clip-row DOM 反映ラグの間に次 inject が走り silent drop されていた → 3 秒に延長、(3) `injectAndGenerate` が Generate ボタン再 enabled だけを成功判定とし silent drop に気付かず次 entry に進んでいた → inject 前後で `getInFlightClipCount()` を測定し `CLIPS_PER_REQUEST = 2` 増えるまで poll wait（`shared/dom.ts::waitForInFlightIncrease`、timeout で throw せず false 返し中断時は true）、達しなければ同じ entry を最大 2 回 retry（`MAX_INJECT_RETRY`）、それでも増えなければ fail-loud で ERROR。retry ループは unit test 到達性のため依存 DI した `suno-helper/lib/inject-retry.ts::injectWithVerification` に抽出した。Vitest 新規（`waitForInFlightIncrease` の resolve / timeout / abort 挙動、`injectWithVerification` の retry / fail-loud 挙動、定数値）で担保。
- `fix(suno-helper)`: #860 の playlist 追加フローで dialog 内 row 検出に失敗して `Playlist "..." 行が dialog 内 list に出現しませんでした` で中断していたバグを修正した。原因は実機 Suno dialog の playlist row wrapper が `<button>` でも `[role="button"]` でもなく **role/aria 不可視の素の `<div>` (React onClick handler のみ)** だったため、親方向 walk で button / role=button だけを探していた `findPlaylistRowsByName` が常に空配列を返していた。対応として `PLAYLIST_ROW_LABEL_SELECTOR = "div.ml-4.font-sans"`（実機 snippet で確定した row 内 label の Tailwind class）を導入し、name と text 完全一致した label を直接 click する方針へシンプル化した（label click は bubbling で wrapper の React onClick へ届く想定）。row wrapper 解決のための階層 walk ロジック自体を削除し、Suno 側 DOM 変化への脆弱性を減らした。Vitest `dom-playlist.test.ts` の row テストを「label click が bubbling で wrapper handler を発火する」観点へ書き換え、wrapper は実機どおり素の `<div>` で構築する。`event.target` が label であることも明示的に観測してアサート
- `fix(suno-helper)`: 上記と同じ #860 フローで 3 件しか生成していない場合や全 entries 投入直後で **0 件しか multi-select されない** バグを修正した。原因は `selectRecentCompletedClips` が `data-clip-status="complete"` で完了 row のみを拾っており、Suno の clip-row には生成完了マーク反映ラグがあるため `addClipsToPlaylist` フェーズへ進んだ時点で完了マーク未付与だと 0 件選択になっていた。対応として `CLIP_ROW_COMPLETED_SELECTOR` を撤去し `CLIP_ROW_SELECTOR = '[data-testid="clip-row"]'` (status フィルタなし) を `selectRecentClips` で使うよう変更した。Suno の playlist 追加は生成中 clip でも実行でき、未完了分は生成完了時に playlist へ自動反映されるため運用上問題ない。content.ts の呼び出しコメントも「生成完了マーク反映ラグ対策で生成中も含めて拾う」旨を明文化し、Vitest に「全 row streaming のみで 0 件にならず全件返す」「complete と streaming 混在で 5 件返す」ケースを追加
- `fix(suno-helper)`: 全 entries 生成完了後の playlist 自動追加フローで、Suno の Cmd+P dialog 「Create Playlist」ボタンが新規 playlist を **空で作成するのみ** で選択中 clip は追加されない仕様（実機確認）に対応していなかったバグを修正した。従来の `addClipsToPlaylist` は multi-select → Cmd+P → 名前注入 → Create Playlist click → dialog close 待ち、で終わっていたため、playlist 自体は作られても 40 clip が紐付かない空 playlist が出来上がっていた。Create Playlist click 直後に dialog 内 list に出現する該当 playlist row を改めて click して clip を紐付ける step (`shared/playlist-dom.ts::clickPlaylistRowByName`) を追加し、`content.ts::addClipsToPlaylist` の `fillPlaylistNameAndCreate` と `waitForPlaylistDialogClose` の間に `abortableSleep(SETTLE_MS)` + `clickPlaylistRowByName(dialog, playlistName)` を挿入した。row の特定は dialog 内 `<div>` で children=0 かつ `textContent.trim()` が name と **完全一致** する leaf を起点に親方向に walk して `button` / `[role="button"]` の clickable wrapper を掴む（前方一致だと `DF | X` と `DF | X2` を取り違える）。Suno は同名 playlist の重複作成を許容するため、複数 row が並ぶ場合は **DOM 順で最後 (= 直前に作成した最新)** を click し、前回テスト等で残っていた古い同名 playlist には触らない。期限 5s 内に row が出現しなければ throw（silent skip しない）。Vitest `dom-playlist.test.ts` に 7 ケース追加（単一一致 click / 同名複数の最新 row 選択 / 前方一致誤検知防止 / poll で待って出現後 click / timeout throw / dialog 外無視 / `role="button"` div 親 wrapper 対応）
- `fix(suno-helper)`: popup 起動時に `/collections` レスポンスの `name` field 値（server 側で末尾 `-collection` が剥がされておらず例えば `dawn-cloud-fold-collection` 形式で返ってくる）をそのまま theme として `extractPlaylistName(id, theme)` に渡していたため、id 末尾 `-<theme>` 照合が常に失敗して fail-loud で throw → useMemo で React component が crash し popup が起動しないバグを修正した。`components/useSunoRunner.ts` の derivedPlaylistName 計算で `selected.name.replace(/-collection$/, "")` を挟んで theme から末尾 `-collection` を剥がしてから渡す。`extractPlaylistName` 側の契約 (theme は接尾辞なしの slug) は維持しスペックを通す位置だけ修正。サーバ側 (`utils.collection_paths.CollectionPaths.collection_name`) が将来 suffix を剥がして返すよう修正されても剥がし処理は冪等で無害
- `fix(suno-helper)`: popup の「開始失敗」「停止リクエスト失敗」エラーで Chrome の `Could not establish connection. Receiving end does not exist.`（拡張リロード後に Suno タブが古い content script のままで残っているときに出る）を検知し、対処法「Suno タブをハードリロード (⌘+Shift+R / Ctrl+Shift+R)」を案内に追記するようにした。従来は汎用の「Custom Mode 画面を開いた状態で実行してください」のみで、実際の原因と異なる対処を案内していた。検知は case-insensitive substring match、整形は `components/runner-errors.ts` の純関数 (`isContentScriptMissingError` / `formatRunError` / `formatStopError`) に分離して `wxt/browser` 非依存とし、Vitest（`tests/content-script-missing-hint.test.ts`）で 11 ケース担保する
- `fix(suno-helper)`: suno-helper の連続実行で Suno の queue 上限エラー toast を検知して自動回復するようにし、投入間に待機を入れ、停止反応性を高めた（#847）。実機で 12 entries を連続実行すると、Create クリック→Suno API→`clip-row` DOM 反映のラグで `waitForQueueSlot(20)` が「19 件」と誤判定して投入し、Suno が 21 件目として reject → 「Generation in progress（他の曲の生成が完了するまでお待ちいただき…）」toast が出ても extension が気付かず投入し続ける問題があった。`extensions/shared/dom.ts` に `isQueueLimitErrorVisible()`（可視な `[role="dialog"]` のうち英語見出し "generation in progress" を case-insensitive substring match で検知。testid/aria を持たない toast 構造に対し `detectRecaptcha` と同じ strict `isVisible()` で非表示残骸を弾く。多言語耐性のため日本語並列テキストには依存しない）と `QUEUE_LIMIT_ERROR_SELECTOR` を追加し、`waitForQueueSlot` を toast 表示中は空きスロットがあっても投入せず待機継続、toast 消失後に `queueErrorWaitMs`（= `QUEUE_ERROR_WAIT_MS=30000`）の安全マージンを取ってから再開するよう拡張した。併せて Create→DOM 反映ラグ由来の過剰投入を吸収するため各投入後に `INTER_CREATE_DELAY_MS=1000` 待機し、固定 `sleep(SETTLE_MS)` を中断可能な `abortableSleep(ms, isAborted)` へ置換して停止押下後 3 秒以内にフローが止まるようにした（`extensions/shared/constants.ts` / `extensions/suno-helper/entrypoints/content.ts`）。Vitest（`isQueueLimitErrorVisible` の検知/非検知、`abortableSleep` の abort/timeout/通常 resolve、`waitForQueueSlot` の toast 検知 wait→消失 buffer wait の時系列モック、契約定数）と Playwright e2e（toast 検知中は待機し消失で再開、`abortableSleep` が長い待機の途中でも 3 秒以内に抜ける）で担保する。既存 #817 queue 待ち / #844 title 注入の挙動は不変
- `fix(distrokid)`: distrokid-helper のセレクタを実 DOM 検証（`distrokid.com/new` ログイン状態）に基づき修正し、AI 開示モーダルへ対応、`DistrokidProfile` schema を再設計した（#813）。PR #803 は実 DOM 未検証の想像セレクタ（`name="artist_name"` 等）だったため大半が実 DOM と不一致だった。セレクタを id ベース（`#language` / `#genrePrimary` / `#genreSecondary` / `#albumTitleInput` / `#release-date-dp` / `#artwork`）と track 別の index/uuid 生成（タイトル `[name="title_<uuid>"]` を DOM order で解決、songwriter は `songwriter_real_name_{first,middle,last}<N>` の 3 分割、曲は `#js-track-upload-<N>`）へ刷新し、全 track を index 順に注入する（「先頭のみ」を撤廃）。`album_title` はアルバム時のみ存在するためシングルモードでは skip（要素不在で throw しない）。AI 開示は「はい」radio 選択後に `MutationObserver` でモーダル展開を待ってから checkbox（歌詞 `ai_lyrics_` / 作曲 `ai_music_` / 音声すべて・音声の一部は DOM order / apply-all `ai-apply-all-`）を注入し「保存する」で commit する。テキスト/SELECT 解決時は `extensions/shared/visibility.ts::isVisible`（`shared/dom.ts` から切り出して export 化）で type=hidden の `#artistName` 等を排除し、未検出は `FieldNotFoundError` で fail-loud（silent skip しない）。schema は Python（`utils.config.distrokid` の `SongwriterName` / `AiDisclosure` / `DistrokidProfile`、必須は `language` / `main_genre` のみ）と TS（`lib/types.ts`）を 1:1 で再設計し、旧フラットフィールド（`artist_name` / `apple_music_credit` / `track_type`）を撤廃。旧 `config/channel/distrokid.json` を新 schema へ in-place 変換する `yt-distrokid-migrate`（dry-run / `--apply` / `--backup`、songwriter 文字列の氏名分割・ai_disclosure default 付与）を追加。Vitest unit + Playwright e2e mock（実 DOM 構造ミラー）を新 schema・新セレクタで更新。「続ける」等の送信系操作は引き続き行わない（規約遵守）
- `fix(suno)`: Suno Custom Mode の Style/Lyrics 識別を data-testid ベースに変更し、日本語 UI 破損を修正した（#807）。実 DOM（`suno.com/create`・日本語 UI）検証で、`SELECTORS.stylePlaceholder` の placeholder 正規表現が日本語ロケールの Style 欄（ジャンル語彙の例）にヒットせず、fallback の `areas[0]=Lyrics` を Style に返して Lyrics 欄を上書きする致命バグが判明していた。`extensions/shared/dom.ts` で Lyrics を `data-testid="lyrics-textarea"`（UI 言語非依存）で最優先識別し、Style は「Lyrics 以外の strict visible textarea」として解決、Style 解決不能または Style==Lyrics の衝突時は throw（silent な上書きを禁ずる）。`isVisible` を `offsetParent !== null` から bbox 0 除外 + 親要素 walk（display:none / visibility:hidden / opacity:0 排除）の strict 版に強化し、Simple Mode の隠し textarea を拾わないようにした。Vitest unit テスト（`tests/dom.test.ts`）と Playwright e2e mock（`data-testid="lyrics-textarea"` を含む）で担保する
- `fix(suno)`: hCaptcha プリロード iframe の誤検知で連続実行が Create 直後に中断する問題を修正した（#810）。Suno は hCaptcha challenge UI を非表示プリロード iframe（`display:none` / `visibility:hidden`）として常駐させるため、`extensions/shared/dom.ts::detectRecaptcha` が `querySelector` の hit だけで判定すると常に true になり、`waitForGeneration` の poll が最初の Create 押下直後に「reCAPTCHA を検知しました」で必ず中断していた。判定を #807 で strict 化済みの `isVisible`（bbox 非ゼロ + 親 walk で `display:none`/`visibility:hidden`/`opacity:0` を排除）に統一し、実 challenge UI が表示された時のみ検知する。selector は不変（hCaptcha は `src*="hcaptcha"` で既にカバー済み）。回帰ガードとして `extensions/suno-helper/tests/dom.test.ts` に非表示プリロード iframe で false / 可視 challenge で true を検証する Vitest を追加し、Playwright e2e（`tests/e2e/suno-inject.spec.ts`）の Suno mock に常駐 hCaptcha iframe を含めた
- `fix(suno)`: instrumental パターン（`lyrics === ""`）で前パターンの歌詞が Lyrics 欄に残り続ける問題を修正した。`extensions/suno-helper/entrypoints/content.ts::injectAndGenerate` の `if (entry.lyrics)` truthy ガードが空文字を skip するため、`/suno` で生成された連続パターンの中に instrumental が混ざると Lyrics 欄が前パターンのまま生成されていた。`if (lyrics)`（DOM 要素の存在判定）に変えて空文字でも `setNativeValue(lyrics, "")` で上書きするよう変更し、要素が無くて歌詞がある場合のみ fail-loud で throw するロジックに整理した。Playwright e2e（`tests/e2e/suno-inject.spec.ts`）に「instrumental パターン投入後に Lyrics 欄が空になる」シナリオを追加し回帰ガードとした

### Removed

- `refactor(serve)!`: `yt-suno-serve` CLI と `youtube_automation.scripts.suno_serve` モジュールを削除した（#698、後継は `yt-collection-serve` / `youtube_automation.scripts.collection_serve`）

### Migration

- `#698`: `yt-suno-serve` を実行しているスクリプト・運用手順は `yt-collection-serve` に置き換える。配信 URL は `http://localhost:<PORT>/prompts.json` → `http://localhost:<PORT>/suno/prompts.json` に変わる（suno-helper 拡張は本リリースで追従済み）

## [5.5.7] - 2026-06-02

### Added

- `feat(community-draft)`: `data/community/weekly-vote-log.json` の loader / append / weight hook を upstream で正式化した（#509、#446 / #445 / #339 統合）。`youtube_automation.utils.weekly_vote_log` モジュールに `AxisVote` / `WeeklyVoteEntry` / `WeeklyVoteLog` の dataclass、`load_weekly_vote_log()` / `save_weekly_vote_log()` / `append_weekly_vote_entry()` の loader-writer、JSON Schema (`youtube_automation/utils/schemas/weekly_vote_log.schema.json`, `schema_version: 1`) と整合する手書きバリデータ、`/collection-ideate` 向け hook `compute_vote_log_weights(log, recent_weeks=N, decay=0.7)` を追加した。hook は最新週ほど重い `decay^i` の重みづけ平均 (`weights`) と「連続 2 週以上で同 `top_axis`」の強制採用判定 (`forced_axis` / `forced_streak`) を返す。新 CLI `yt-vote-log {append, show, weights, validate}` を `youtube_automation.scripts.vote_log:main` に登録（`pyproject.toml::[project.scripts]`）。あわせて `community-draft` SKILL.md / `config.default.yaml` に `behind_the_scenes` の一人称 4 文構造（`scene_hook` / `mood_anchor` / `signature_element` / `listening_invitation`）と `scene_phrase` / `personal_mood` / `drink_signature` / `animal_object` / `music_style` の変数解決順序、`next_teaser` の `collections/planning/*/workflow-state.json::planning.publish_target_at` 探索ロジックを upstream 化し、`poll` type は DEPRECATED として正式 retire（`utils.weekly_vote_log.warn_poll_deprecated()` が warning ログ）。`collection-ideate` SKILL.md には vote-log hook 連携節と `yt-vote-log weights` CLI 例を追記。新規テストは `tests/test_weekly_vote_log.py`（30 ケース・schema バリデーション / load-save / append / `compute_vote_log_weights` の境界）と `tests/test_vote_log_cli.py`（8 ケース・`append` → `show` → `weights` の roundtrip + 衝突検出 + label に `:` を含むケース）

- `feat(wf-next)`: `/wf-next` の承認ゲートを `config/channel/workflow.json` から宣言できるようにした（#508）。`Workflow` dataclass に `wf_next.approval_gates.{audio, upload}` を追加し、loader が `workflow.wf_next.approval_gates` をロードする（既定値は両方 `False` で従来通り全自動進行・後方互換）。`audio: true` のとき `prepared` 2-B（音源承認）、`upload: true` のとき `mastered` 3-B（アップロード承認）の前段で AskUserQuestion を取りに行く運用に切り替わる。SKILL.md は本リポジトリ側の単一定義に config 駆動の挙動を集約したため、各チャンネル側 SKILL.md を書き換える運用は不要（`yt-skills sync` の衝突を避けるためにも本ファイルは編集しないこと）。`examples/channel_config.example/workflow.json` に `wf_next.approval_gates` の例を追記

- `feat(collection-ideate, thumbnail)`: `differentiation_axes` による TTP 構図逸脱を防ぐ `composition_lock` フラグと、生成後セルフチェック CLI `yt-thumbnail-check` を追加した（#489）。`config/skills/collection-ideate.yaml` のトップレベル `composition_lock: true`（デフォルト）が有効なとき、`differentiation_axes` は「企画コンセプトの内部メタデータ」（音楽プロンプト・概要欄・タイトルバリエーション）として扱い、サムネ構図には反映しない（差別化は `objects.swappable` の slot 値のみ）。DF365 / 2026-05-20 で発生した「`location` を `mountain airstrip` / `urban tunnel exit` / `desert airstrip` と変えた結果 TTP 参照画像のスタイルアンカーが効かなくなる」事象への対処。新規ヘルパー `youtube_automation.utils.composition_lock` に `is_composition_locked()` / `expand_fixed_objects()`（既知 TTP キー `wet_runway` / `matte_black_car` / `aircraft_mid_distance` / `blue_hour` / `low_three_quarter_angle` / `rain_window` / `turntable` / `campfire` / `character` 等を定型節へ辞書展開、未知キーは passthrough）/ `axes_in_thumbnail_prompt()`（生成プロンプトに axes 値がドリフトしていないか軽量検出）/ `build_self_check_prompt()`（`objects.fixed` + `no_logo_guard` から Gemini Vision 用 YES/NO チェックリスト prompt を組み立て）を実装。新規 CLI `yt-thumbnail-check <image>...` は Gemini Vision でチェックリストの合否を JSON 形式で取得し、終了コード 0/1 で全体合否を返す（`--json` / `--quiet` / `--print-prompt` / `--check 'extra question?'` / `--model` をサポート）。`collection-ideate.yaml` に `self_check`（`enabled` / `verify_fixed_objects` / `no_logo_guard.{detect_text,detect_logo,detect_watermark}` / `max_regeneration_attempts` / `model`）を追加し、`/collection-ideate` Phase 4 に「4-4-check: 生成後セルフチェック」節を新設して 4-5 のユーザー提示前にロゴ・テキスト混入・wet_runway 不在等を機械検出するフローを案内。`/thumbnail` SKILL.md の「品質チェック」節にも `yt-thumbnail-check` を前段スクリーニングとして追記。`composition_lock: false` に設定すれば従来挙動（差別化軸をサムネ構図にも反映）に戻る非破壊変更


- `feat(veo,videoup)`: 動画生成中の進捗表示を改善した（#641）。Veo ループ動画生成（`veo_generator._wait_for_operation`）はドット列のままだったポーリング表示を「スピナー + 経過時間 + 推定進捗率 / ETA」の 1 行更新表示に置き換え、Veo API が真の進捗を返さない制約下で典型生成時間ベースの推定値であることを `≈` prefix で明示する。生成フロー全体を `[Step 1/3] 生成中` → `[Step 2/3] 保存中` → `[Step 3/3] 後処理` の 3 ステップで明示し、`generate_videos.sh` 側も `[Step N/M]` のステップ行と既存スピナーに加え ETA 表示を追加した。進捗フォーマット（経過時間 / ETA / スピナー / 1 行レンダラー）は `utils/progress.py` の純粋関数として切り出し `tests/test_progress.py` で 39 ケースを担保。非 TTY 環境（CI / log redirect）では `\r` アニメを抑止し定期的な行ごとの出力にフォールバックする（Python 側は `progress.is_tty(sys.stdout)`、bash 側は `[[ -t 1 ]]` で判定）


- `feat(videoup)`: `generate_videos.sh` に短尺 master を音声側 `-stream_loop -1` で動画長まで伸ばす opt-in 経路を追加した（#545）。`.claude/skills/videoup/config.default.yaml` に新キー `audio.target_video_duration_min` (分) を導入し、設定時は ffmpeg の音声入力にも `-stream_loop -1` を適用して `-t <target_video_duration_sec>` で動画長を強制する。例えば `audio.target_duration_min: 30` の master を `target_video_duration_min: 120` で動画化すると 4 ループ相当の 2h 動画を生成し、下流チャンネル (rain-jazz-night 等) の finalize 工程 (loudnorm + 雨音レイヤー encode) を短縮できる。未設定時は従来動作 (音声尺 = 動画尺、後方互換)、master 尺 ≥ target のときは無視されて master 尺が支配する。環境変数 `VIDEOUP_AUDIO_TARGET_VIDEO_DURATION_MIN` でも上書きでき、優先順位は env > `config/skills/videoup.yaml` の channel override > 未設定。音声 loop seam の crossfade は本キーのスコープ外 (将来拡張)

- `feat(yt-generate-master)`: 先頭固定オプション `--pin-first <files...>` / `--pin-first-count N` を追加した（#549）。Suno V5 の類似イントロ群が後半で連続クラスタ化するのを避けつつ retention に強いフック曲を冒頭に置く運用要請に応える。`--pin-first` は指定ファイル名を引数順で先頭に固定（未存在は fail-loud）、`--pin-first-count` はソート済み先頭 N 件を固定。両者は mutually exclusive（argparse レベルでエラー）。`--shuffle` / `--shuffle-seed` 併用時は pinned 部分は順序固定のまま、残りのみシャッフルされる（`--target-duration` / `--loop` 併用時はループ展開の前段で先頭固定を適用）。skill-config `.claude/skills/masterup/config.default.yaml::audio.pin_first_count`（既定 `0` = 固定なし）を追加し、CLI フラグ未指定時のチャンネル単位デフォルトとして採用される（既存 `audio.shuffle` と同じ優先順位ルール）。互換: pin オプション未指定 / `pin_first_count: 0` のとき現行と完全に同一の動作。実装は `_apply_pin_first()` に集約し、stdout に `[Pin] first N track(s) fixed: [...]` 再現性ログを `--quiet` 指定時も出力する

- `feat(masterup)`: `yt-apply-rain-layers` CLI と masterup skill の `post_processing.rain_layers` namespace を追加し、raw master (`01-master/master.mp3`) と `branding/rain_layers/*.wav` を amix で合成した別ファイル出力 (既定 `master-rain.wav` / PCM 16-bit / 44.1kHz / stereo) を opt-in で生成できるようにした（#510）。`yt-finalize-master` の loudnorm 二段 in-place 上書きとは独立した namespace / 別 CLI で、各レイヤーを ffmpeg `-stream_loop -1` で master 尺までループ → `volume={dB}dB` で減衰 → `amix=duration=first:normalize=0` で合成する。`enabled: false`（既定）で完全 no-op、`enabled: true` だが WAV 0 件なら fail-loud (rc=1)。`--dry-run` で ffmpeg コマンドを stdout 表示。成功時は `workflow-state.json::assets.raw_master` を `output_name` に書き換えて後段ステップ (`/wf-next` 等) が新出力を参照できるようにする。SKILL.md に Step 5.6 と config 表 4 行を追記

- `docs(skills)`: 外部サービス障害時 / rate limit / 未認証時のガイダンスが欠落していた 27 件の SKILL.md に統一見出し `## 障害時ガイダンス` と 3 列表（状況／兆候／対処）を追加した（#411、監査 `data-dependencies-compat.md §7.1`）。YouTube Data / Analytics 系（`analytics-collect` / `channel-status` / `playlist` / `video-upload` / `viewer-voice` / `metadata-audit` / `channel-import` / `channel-new`）は OAuth 未認証（`auth.oauth_handler` の `FileNotFoundError` / HTTP 403 → `auth/token.json` 削除して再認証）・YouTube quota（HTTP 429 / 403 `quotaExceeded`、日次 10,000 units リセット待ち）・API 障害（HTTP 503）を、Vertex AI 系（`loop-video` / `thumbnail` / `wf-new`）は ADC 未取得（`gcloud auth application-default login`）・rate（HTTP 429）・課金済み途中失敗・画像 provider 切替を記載。`gh` / `op` / `terraform` / `ffmpeg` など CLI 依存（`channel-import` / `channel-new` / `streaming` / `videoup`）の不在・未認証も補い、外部サービス非依存の skill には API 障害行を捏造せず入力データ/設定不在に限る旨を明記した。各記述は `auth/oauth_handler.py` / `image_generation.provider` / `gcloud` ADC など実コード・実 SKILL.md と突合。非実行資産（プロンプト本文）への追記のため、見出し・本文構成を固定する自動テストは追加しない（テストポリシー「非実行資産のテスト」に準拠）

- `feat(doctor)`: `yt-doctor` の診断範囲を api/channel/data/upload のカテゴリ 4 段階に拡張した（#565）。`CheckResult` に `category` フィールドを追加し `render_table` でカテゴリ別に段階表示する。新 check として `channel_config`（config/channel/ ロード可能性）・`analytics_report`（reports/analysis_*.md 存在確認）・`benchmark_data`（docs/benchmarks/*.md 存在確認）・`upload_ready`（upload 必須 scope 充足・channel_id 紐付け）を追加し、api check 通過後に `/wf-new` 起動前提とアップロード可能性まで連続診断できるようにした。`onboard` SKILL.md を新カテゴリ Steps・ハイブリッド方針（analytics=案内/benchmark=ai-exec/scope=HUMAN STEP）・完了メッセージ（wf-new 起動 + アップロード可能）へ更新し、`channel-setup` SKILL.md の skip 条件を api カテゴリ限定へ整合した

- `feat(image_provider)`: gemini CLI 経由のサブスク認証で画像生成する新 provider `gemini_cli` を追加した（#474）。Google AI Pro/Ultra サブスクで認証済みの `gemini` CLI（`@google/gemini-cli`）を subprocess で非対話起動（`gemini --yolo -m <model> -p <prompt>`）し、出力パスをプロンプトに埋め込んで画像を書き出させる。GCP 従量課金（ADC 経由の既存 `gemini` provider）を発生させずに枚数の多いサムネ生成のコストを抑えられる。`image_generation.provider: gemini_cli` + `image_generation.gemini_cli.{model,image_size,timeout_seconds}` で設定。CLI 未導入時は `ConfigError`、生成後は出力ファイルの存在と PNG 妥当性を検証し指数バックオフでリトライする。既存 ADC 経由 `gemini` provider はそのまま温存（非破壊）。skill デフォルトの provider は `gemini` のまま（切り替えはスコープ外）

- `feat(comments-reply)`: `CommentRule` に `scope: "top_level" | "reply" | "any"` を追加した（#524）。#365 で reply も返信対象に含まれるようになり keyword/pattern ルールが top-level / reply の区別なく当たっていたため、ルール単位でマッチ対象の階層を絞れるようにした。`rule_engine` が `FetchedComment.parent_id`（reply 判定）と scope を突合し、`top_level` は top-level のみ・`reply` は reply のみ・`any`（既定）は両方にマッチする。`scope` 未指定の既存ルールは `"any"` として #365 以前と等価のマッチ挙動を維持する。`config/channel/comments.json` の rules に任意指定でき、無効値は `ConfigError`。`examples/channel_config.example/comments.json` に指定例を追加

- `feat(yt-channel-settings)`: `push` に channel_id mismatch 時の safety check を追加した（#561）。`config/channel/meta.json` の `channel.channel_id` が設定済みの場合、`channels().list(mine=True).id` と照合し、不一致なら別チャンネルの OAuth トークンで設定を上書きする取り違え事故として `push` を refuse する（`channel_settings.verify_channel_id()`）。`channel_id` 未設定のチャンネルは後方互換でスキップしつつ、初回 push 時に取得した id を `meta.json` へ追記するよう警告する。`ChannelMeta` に `channel_id` フィールドを追加（任意キー）

- `feat(agents)`: `short_uploader` の `_check_upload_interval` / `_calculate_short_publish_at` が `workflow-state.json` / `upload_tracking.json` から読んだ datetime を TZ-naive と判定して backfill する直前に、どのファイル・どのフィールドが TZ-naive かを `logger.warning` で記録するようにした（#532）。#359 で書き込み側は TZ-aware ISO 8601 に統一済みのため、ここを踏むのは既存 live/ 配下のレガシーデータのみ。将来 backfill 補正自体を撤去するタイミングの判断材料（warning ゼロ観測）になる。2 箇所の backfill ロジックは共通ヘルパー `_backfill_naive_datetime()` に集約した

- `feat(agents)`: 永続化用 timestamp の TZ-naive 混入を書き込み時点で検出する防御コードを追加した（#533）。`utils/schedule.py` に `now_in_schedule_tz(schedule_config)`（schedule.timezone の現在時刻を TZ-aware datetime として返し生成を一点集約）と `ensure_tz_aware(dt, *, context)`（TZ-naive なら `ValidationError` を送出する防御ヘルパ）を追加し、`short_uploader._update_workflow_state`（`workflow-state.json::uploaded_at`）と `collection_uploader._completed_tracking_record`（`upload_tracking.json::upload_time`）/ `_update_workflow_upload`（`workflow-state.json::updated_at`）の書き込み点を `now_in_schedule_tz()` 経由に統一した。#359 で書き込み側を TZ-aware に統一した後の再リグレッションを、読み手側 backfill で吸収される前に書き込み時点で検知できる

- `feat(yt-channel-settings)`: `keywords` の合計 500 文字制限を push 前に事前バリデーションするようにした（#563）。`build_update_body` で `_keywords_to_api()` の結果長を検証し、500 文字を超える場合は `channels().update()` の汎用的な 400（`Request contains an invalid argument.`）を待たずに `YouTubeAPIError` で停止する。エラーメッセージに現在の文字数・超過分・長い順の短縮候補タグを含め、原因が keywords 長であることを即座に判別できるようにした

- `feat(video-upload)`: アップロード preflight に公開タイトルの TTP 鋳型準拠チェックを追加した（#602）。`preflight_checks.check_title_template_compliance()` が「鋳型逸脱（` | ` で LHS/RHS に分割でき RHS が `N Hours of ...` 系に一致）」「巻数表記（`Vol.` / `Vol N` / `Part N` / 末尾ローマ数字 / `#N`）」「既存 live タイトルとの RHS 完全重複」「核語彙欠落（任意）」を機械検出し、`youtube_auto_uploader._preflight_check` で違反時にアップロードを block する。soulful-grooves で発生した `Funky Spirit Vol.2 | 3 Hours of Soulful Retro Funk Grooves`（コレクション内部名の公開タイトル流用）を巻数表記 + RHS 重複で停止できる。鋳型語彙・パターン・セパレータは `content.json::title.template_check` から導出し、`title.template` に ` | ` を含まないチャンネルは自動スキップ（既定値はフォールバック、ハードコードなし）。既存 live タイトルは `collections/live/*/20-documentation/descriptions.md` の `## タイトル案` から収集する

- `feat(comment-reply)`: `yt-comments-reply` にメインループ先頭で動く video status preflight を追加した（#576）。`commentThreads.list` の前に対象 video の `status` を `videos.list`（50 件単位で chunk 化）で一括取得し、API 応答に存在しない（削除済み）video は `plan.skipped` に `reason="video_not_found"`、`privacyStatus="private"` の video は `reason="video_private"` で積んで除外する。これまで apply 段階でしか出なかった 404 / 403 を dry-run プレビューで事前可視化し、無駄な `comments.insert` の quota 消費を避ける。unlisted はオーナーがコメント可能なため通過、quota 節約のため history に返信実績がある video は status check 対象外。dry-run / apply 共通で動作（`utils/comments/replier.py::fetch_video_status` / `_preflight_video_status`、`ReplyHistory.replied_video_ids`）


### Changed

- `docs(loop-video)`: `.claude/skills/loop-video/SKILL.md` に「中断 (Ctrl+C) 時の挙動」セクションを追加した（#454）。Veo 3.1 API は現状 `operations.cancel` 相当を提供しておらず、本スキルの `utils/veo_generator.py` も `KeyboardInterrupt` 捕捉時に state 保存とメッセージ表示のみ行い cancel API を呼んでいないため、**submit 成功後の Ctrl+C はローカルプロセスを止めるだけで API 側 operation とクレジット消費は止まらない**ことを表形式で明記。中断 = 無料化ではなく「次回 resume の予約」であり、再開には `<CHANNEL_DIR>/tmp/veo-operations/<output-hash>.json` に保存された operation_name が使われ再課金は発生しない点、ループ動画化そのものを停止したいチャンネルは `enabled: false` で CLI ごと無効化すべき点、将来 Veo API が cancel に対応したら本セクションを書き換える前提である点を運用ガイドラインとして併記。skill ドキュメントのみの追記で `src/` は不変

- `chore(release)`: `/automation-release` skill の prepare フェーズに `uv lock` 実行 step（Phase 1-5）を新設し、`pyproject.toml::version` bump と同 commit で `uv.lock` を同期するように手順を改めた（#515）。`v5.5.2` 時点で `pyproject.toml` だけが bump され `uv.lock` が `5.5.1` のまま取り残されたドリフトの再発防止策。`references/prepare-checklist.md` に「uv が利用可能」prerequisite と既存ドリフト用のエッジケースを追記、`references/publish-checklist.md` に lock 一致検証を追加。本リリース時点で main 上の `uv.lock` は `5.5.6` に同期済みのためデータ修正は不要、skill 手順とドキュメントのみの更新

- `chore(deps)`: 2026-10-16 に shutdown が確定している `gemini-2.5-flash` / `gemini-2.5-flash-lite` を後継の `gemini-2.5-pro` に一括置換した（#505）。skill 側は `.claude/skills/benchmark/config.default.yaml`（`thumbnail_analysis.model`）/ `.claude/skills/video-analyze/config.default.yaml`（`model`）の既定値、ドキュメント側は `benchmark/SKILL.md` / `video-analyze/SKILL.md` / `wf-new/references/scene_phrases.md`、src 側は `benchmark_collector.py::BenchmarkThumbnailAnalyzer` のフォールバック値・`populate_scene_phrases.py::DEFAULT_GEMINI_MODEL`・`utils/config/comments.py::GEMINI_MODEL_DEFAULT` を更新し、関連テスト（`test_config_loader` / `test_comments_*` / `test_video_analyzer` / `tests/fixtures/skill_config_verify/...`）のリテラルも追従。`gemini-2.5-flash-image-preview`（画像生成プロダクト）と `docs/audits/**` の歴史記録は scope 外として温存

- `feat(channel-setup)`: `/channel-setup` Step 2 に競合 `brandingSettings` / `localizations` の TTP 転写ステップを追加した（#560）。Step 2 を 3 サブステップ（2.1 競合スナップショット取得 → 2.2 config 案生成 → 2.3 TTP self-check）に再構成し、`config/channel/analytics.json::benchmark.channels[0]` が指定されているチャンネルでは `channels().list(part='snippet,brandingSettings,localizations', id=<benchmark>)` を AI のコンテキストに必ず載せてから config 案を作るルートに統一する。TTP 対象面を `snippet.description` / `brandingSettings.channel.description` / `brandingSettings.channel.keywords`（数・順序・クォート形式まで）/ `country` / `defaultLanguage` / `localizations` 全エントリのチェックリストとして明文化し、`config-generation-rules.md` の `tags.base` / `descriptions` / `localization` 各節に「TTP 路線時の転写ルール」を追記。Step 2.3 では Claude が章立て対応・語彙整合・言語セット整合・差別化箇所の説明可能性を self-check し、ユーザー承認前に提示する。`Soulful Grooves` 立ち上げで Amber の概要欄を一度も見ずに独自文言を書いて push した事故（issue 本文）を skill 手順側で防ぐ

- `docs(loop-video)`: `.claude/skills/loop-video/SKILL.md` に「再実行時のコスト警告」セクションと挙動マトリクス、`--skip-existing` / `--smooth` 単独 mode の使い方を追記した（#452）。Veo 3.1 は課金 API で、デフォルト経路は既存 `loop.mp4` を `loop-v{n}.mp4` に退避してから Veo を再度叩く（フル再課金）ため、冪等再実行は `--skip-existing`（既存があれば early exit 0、0 円 no-op）、継ぎ目補正は `--smooth` 単独 mode（FFmpeg post-process 専用で Veo を叩かない、0 円）、本気の作り直しのみ素の `yt-generate-loop-video` を意図的に再実行する三層運用を明文化。Quick Reference に両フラグを追記し、Instructions の step 3/5 を `--skip-existing` / `--smooth` 単独 mode 前提に書き直した（「再生成 + post-process」を 1 コマンドで束ねる API は再生成を明示的なフル再課金イベントとして扱うため意図的に未提供である旨も併記）。skill ドキュメントのみの追記で `src/` は不変（CLI 側のフラグは元 issue #378 の code 子で実装済み、本 PR は SKILL.md の追従のみ）

- `refactor(skills)`: 全 44 個の `.claude/skills/*/SKILL.md` frontmatter の `description:` を strict PyYAML（`yaml.safe_load`）安全な double-quoted string に統一した（#652、PR #651 / #650 follow-up）。値内の `: `（コロン+スペース）が strict YAML でマッピング区切りと誤解釈されパースが破綻する将来負債を解消（現状実際に失敗していたのは masterup / thumbnail の 2 ファイル）。値テキスト（意味・トリガー語彙・参照リンク）は 1 文字も変更せずクオートで囲むだけの機械的変換で、skill ルーター（Claude Code / Codex）の trigger 動作・`yt-skills sync` / wheel 配布経路は不変。新規 skill 用に「`description:` は double-quoted string で書く」ガイドを `AGENTS.md` の skill 編集規約節に 1 行追記。回帰担保として全 SKILL.md frontmatter が `safe_load` で name/description を持つ dict として解釈できる構造契約テスト `tests/test_skill_frontmatter_yaml.py`（文言は固定しない）を追加

- `feat(masterup)`: `yt-finalize-master` の音響パイプライン全項目を skill-config から注入できるようにした（#512）。`audio.finalize.*` namespace を新設し、`ambient_layers.{dirname,glob,volume_db,fadein_s,fadein_curve,layers.<filename>}` / `loudnorm.{enabled,mode,I,LRA,TP}` / `mix.{duration,normalize}` / `bitrate` / `codec` / `sample_rate` を全て注入可能化した。`loudnorm.enabled: false` で pass1/pass2 を skip して `amix` 単発で encode する 1-pass モードを追加し、`loudnorm.mode: dynamic` 指定時は `NotImplementedError` で fail-loud する。`find_rain_layers` を `find_ambient_layers(channel, *, layers_dirname, glob_pattern)` に汎用化し、`_resolve_rain_config` を `_resolve_finalize_config` にリネームして `FinalizeConfig` 値オブジェクトを返す。`build_filter` に `fadein_curve` / `mix_duration` / `mix_normalize` / `layer_overrides` / `apply_loudnorm` を追加し per-file layer 上書きを織り込む。`_build_pass2_cmd` に `-c:a {codec}` / `-ar {sample_rate}` を反映。旧 `rain_layer` namespace は後方互換 alias として読み続けるが `DeprecationWarning` を出す（新旧併設時は新を優先）。既存 v5.5.0 挙動は組み込みデフォルトで完全再現（既存 29 件 + 新規 24 件のテスト green で担保）

- `refactor(thumbnail)`: imagegen 14 項目 Shared prompt schema の bridge 層を試験導入した（#654、PR #651 / #650 follow-up・差分レポート提案 5 / E-2）。`src/youtube_automation/utils/image_provider/prompt_schema.py` に 14 項目 `PromptSchema` dataclass（`use_case` / `asset_type` / `primary_request` / `input_images` / `scene` / `subject` / `style` / `composition` / `lighting` / `color` / `materials` / `text` / `constraints` / `avoid`）と既存 `image_generation.gemini.*` キーから 14 項目へ機械マッピングする `from_skill_config()` / imagegen 形式 `Label: value` を出力する `render()` を追加し、`image_provider.__init__` の `__all__` に `PromptSchema` / `prompt_schema` を export した。対応マッピング表は `.claude/skills/thumbnail/references/prompt-schema.md`、設計判断と段階移行パスは `docs/skill-design/ADR-001-thumbnail-prompt-schema.md` に明文化（試験導入のみ・実本番フロー未接続）。`composition.py` / `scripts/generate_image.py` / `diff_prompt_template` / TTP / Two-Phase / 視認性検証 / 固定キャラ / stock 退避 / 複数プロバイダー切替の挙動は完全に温存（既存 `tests/test_thumbnail_skill_assets.py` 4 件 + 新規 `tests/test_prompt_schema.py` 8 件 green で担保）。SKILL.md は「## プロンプト構築」節末尾に bridge への参照リンクを 1 行追記したのみで既存セクション順序・固定化テストの対象テキストには触れていない。次フェーズ（opt-in feature flag）は skill-config 管理見直し epic 発火後に別 issue として `takt:default` で再起票する

- `refactor(thumbnail)`: `.claude/skills/thumbnail/SKILL.md` を OpenAI codex 公式 imagegen SKILL.md の構造へ部分準拠させた（#650）。description 末尾に「Do not use when: SVG・ベクター画像の生成/編集、コード生成、YouTube サムネイル以外の汎用画像生成」相当の除外条件を追記して AI スキルルーターの誤起動を防ぎ、Overview 近辺に `Use case: product-mockup (YouTube thumbnail variant)` の 1 行で imagegen taxonomy との対応を明示。「プロバイダー切り替え」節に未設定時のデフォルト（`gemini`）と channel-config 優先順位を明文化。肥大化していた「プロンプト構築」節と散在していたプロンプト例を `.claude/skills/thumbnail/references/prompting.md` / `references/sample-prompts.md` へ逐語移植（改変なし・移動のみ・SKILL.md 側は参照リンクへ置換）。あわせて phase-1 差分レポートを `docs/skill-design/thumbnail-codex-imagegen-diff-report.md` に救出（byte-identical, 388 行/30873B）。挙動・出力命名・skill-config 機構・TTP / コレクション連携 / 複数プロバイダー切替本体は不変（`tests/test_thumbnail_skill_assets.py` 4 件 green で担保）

- `refactor(agents)`: 600 行超で責務肥大していた `youtube_auto_uploader.py`（602 行）を責務別 mixin モジュールへ分割した（#465）。preflight 検証（`_preflight.py::PreflightMixin`）/ descriptions.md 解析（`_descriptions_md.py`）/ 重複検索（`_dedup_search.py`）/ Complete Collection 戦略（`_complete_collection_strategy.py`）/ 定数（`_uploader_constants.py`）に切り出し、`YouTubeAutoUploader` は各 mixin を合成する形に整理して本体を 356 行へ縮小した。機能・公開 API・挙動はすべて不変（既存 upload 系テスト 68 件 green で担保）。`_preflight_check` の移動に伴いテストの `load_config` パッチ対象を `_preflight` モジュールへ追従。`collection_uploader.py` の分割は follow-up


- `fix(channel-setup)`: `/channel-direction` で確定した方向性が `config/skills/*.yaml` / `config/channel/*.json` に転記されず下流 skill が空 config で破綻する根本原因を是正した（#567）。`channel-setup/SKILL.md` に **Step 3.5「config/skills/*.yaml への転記」** と Step 3 の必須転記表を追加し、`audio.target_duration_min` / `title.theme_scenes` / Suno `genre_line` ・ `exclude_styles` / Thumbnail `reference_images.default` ・ `brand_background` ・ `composition_rules.*` を空のまま終了しない手順を明文化。雛形として `references/config-template/audio.json` と `references/config-template/skills/{suno,thumbnail}.yaml` を新設し、`config-generation-rules.md` に「channel-direction.md の決定を必ず転記する skill-config」節と `audio` セクションの記載を追加。TTP 参照画像は `/benchmark` が `data/thumbnail_compare/benchmark/` に download した競合サムネを参照することで手動 download を解消する導線も明記。`channel-direction/SKILL.md` には引き継ぎ項目表と方向性ドキュメント雛形に「音楽設定」「TTP 対象サムネ」「ブランド背景色」を追加し、上流の決定漏れを setup 前に発見できるようにした。あわせて `.claude/CLAUDE.template.md` の upstream 名表記を pypi パッケージ名 `youtube-channels-automation` と GitHub リポジトリ名 `daiki-beppu/youtube-automation` で区別して統一（CLI 配布名と PR 提出先の食い違いを解消）

- `refactor(agents)`: 600 行超で責務肥大していた `youtube_auto_uploader.py`（602 行）を責務別 mixin モジュールへ分割した（#465）。preflight 検証（`_preflight.py::PreflightMixin`）/ descriptions.md 解析（`_descriptions_md.py`）/ 重複検索（`_dedup_search.py`）/ Complete Collection 戦略（`_complete_collection_strategy.py`）/ 定数（`_uploader_constants.py`）に切り出し、`YouTubeAutoUploader` は各 mixin を合成する形に整理して本体を 356 行へ縮小した。機能・公開 API・挙動はすべて不変（既存 upload 系テスト 68 件 green で担保）。`_preflight_check` の移動に伴いテストの `load_config` パッチ対象を `_preflight` モジュールへ追従。`collection_uploader.py` の分割は follow-up

- `refactor(agents)`: 600 行超で責務肥大していた `collection_uploader.py`（613 行）を責務別 mixin モジュールへ分割した（#465 follow-up）。tracking / workflow-state JSON I/O（`_tracking_io.py::TrackingIOMixin`）/ 公開日一覧取得 + publishAt 計算（`_published_dates.py::PublishedDatesMixin`）/ プレイリスト自動割り当て（`_playlist_assignment.py::PlaylistAssignmentMixin`）/ Complete Collection 実行ループ（`_complete_collection_executor.py::CompleteCollectionExecutorMixin`）/ 定数（`_collection_uploader_constants.py`）に切り出し、`CollectionUploader` は各 mixin を合成する形に整理して本体を 355 行へ縮小した。機能・公開 API・挙動はすべて不変で、`patch("youtube_automation.agents.collection_uploader.PlaylistManager")` 等の既存テスト patch ポイントは本モジュールでの再エクスポートで温存している（既存 collection_uploader / collection_paths / schedule_cadence 系 119 件 green で担保）。`tests/test_collection_paths.py::_MIGRATED_FILES` の literal Path 回帰リストに新 mixin 4 ファイルを追加して制約を継承


- `docs(masterup)`: `.claude/skills/masterup/SKILL.md` に「Suno 依存の脆弱性と復旧手段」セクションを新設し、本スキルが Suno UI HTML スクレイピング（Step 2 / WebFetch）と CDN URL パターン（Step 3 / `https://cdn1.suno.ai/{song_id}.mp3`）という非公式・非サポート経路に依存していること、UI / CDN 仕様変更で壊れうる箇所（プレイリスト HTML / `song_count` メタ / CDN URL / 公開可否）と症状、壊れた時の判定フロー（silent 続行禁止・ユーザーへ明示報告し停止）、フォールバック運用（Suno UI から手動 DL → `02-Individual-music/` へ配置 → `yt-generate-master` 直叩き → `yt-finalize-master` / `yt-fix-timestamps` / Step 6 rsync を手動順次実行 → `workflow-state.json` 手動更新）、Suno 公式 API 公開時の移行プラン（新規 `yt-suno-fetch` CLI 追加 → Step 2/3 を CLI 呼び出しへ置換 → 非公式経路を `/masterup-legacy` へ退避 or mode 切替 → 安定後に破壊的変更で削除）を明文化した（#409）。Quick Reference の直後に挿入し既存 Instructions 順序・挙動には未影響。`/masterup` 経路が壊れた時にユーザーが復旧手段ゼロで詰む状況を避けるための運用ドキュメント追加

- `fix(lyria)`: Lyria の Ctrl+C 中断で支払い済みオーディオ応答が失われる問題を修正した（#481）。Lyria は単一同期リクエストで billing が確定するため、`requests.post` の戻り後（課金確定後）に Ctrl+C を受けると支払い済み bytes を取りこぼしていた。`generate_music()` が response 受信後の `KeyboardInterrupt` を捕捉し、bytes を `<CHANNEL_DIR>/tmp/lyria-recovered/<sha1>.mp3`（内容ハッシュ命名・冪等）へ退避してから中断を再送出する。`requests.post` 処理中の中断は response 未受信のため救済不能として明示。呼び出し側 `generate_lyria_master.py` の WAV 保存（ffmpeg）中の中断も同じ退避経路（`persist_recovered_audio`）で救済する。退避ファイルは手動で WAV 化して `02-Individual-music/` に置けば再課金なしで再利用できる

- `chore(config)`: `_build_playlists` の per-key 想定外型（list / int / null / float / bool 等）に対する `ConfigError` メッセージへ実際の型名（`got <type>`）を含め、トップレベル shape チェックと文言を揃えた（#419）。`Playlists.items: dict[str, dict]` 型注釈とランタイム挙動の乖離を Fail Fast で防ぐ既存ガードの actionable 化。list / null / float / bool での `ConfigError` 発生をパラメトライズドテストで担保

- `refactor(streaming)`: `utils/streaming/archive_counter.py` を `monthly_archive.py` にリネームし、日単位の `daily_archive.py` との命名対称性を取り戻した（#423、#156 の move only refactor 追従）。`cli/stream_bandwidth.py` の import とテスト（`test_stream_archive_counter.py` → `test_stream_monthly_archive.py`）を追従。公開関数 `count_archives` と `utils/streaming/__init__.py` の公開 API は不変、ロジック変更なし

- `fix(channel-settings)`: `yt-channel-settings push --apply` 直後の `diff` に旧 localizations が表示される問題を修正した（#564）。`fetch_channel()` が `channels.list(part="brandingSettings,localizations,status,snippet")` で一括取得していたが、`localizations` を他 part と同じ呼び出しに混ぜると YouTube Data API のキャッシュ層に当たり push 直後に旧版が返る。combined fetch は `brandingSettings,status,snippet` に絞り、`localizations` は単独 part で取り直してマージする二段 fetch に変更した（push 反映済みの新版が安定して返る）。`diff` / `push` / `pull` はいずれも `fetch_channel()` 経由のため自動的に最新化される

- `perf(scripts)`: `yt-generate-image` の attempt ループ（`--max-attempts N`）を `concurrent.futures.ThreadPoolExecutor` で並列化し、複数バリエーション生成の総実行時間を短縮した（#584）。出力パス（`-vN`）と参照画像のローテーション割り当てをループ前に全 attempt ぶん確定（`plan_output_paths` / `plan_reference_assignments`）して `resolve_unique_path` の直列依存を排除し、逐次実行と同一の採番・参照割り当てを保つ。失敗（`ConfigError`）は future の例外として回収して `sys.exit(1)` をループ外に集約（1 件でも失敗ならプロセスを落とす従来挙動を維持）。並列度は CLI `--max-workers`（未指定時はレート制限を考慮した控えめな固定値 3）で制御し、`--max-attempts 1`（単発）の挙動・出力は従来どおり。`cost_tracker.log_generation` は既存の `fcntl.flock` でスレッド間も直列化されるためコスト記録の取りこぼし・重複は起きない

- `fix(metadata-generator)`: `title.template` / `localizations.json::title_template` に metadata_generator が提供しない未知プレースホルダ（例 `{adjective}`）が含まれていても、Complete Collection アップロード全体が `KeyError` でクラッシュしないようにした（#574）。(1) `descriptions.md` の `## タイトル案` が最終タイトルを供給する経路では `generate_complete_collection_metadata(title_override=...)` で本来捨てられる中間タイトル生成（`_generate_title`）をスキップし完走させる。(2) 中間タイトル生成や localizations タイトル整形では新ヘルパー `format_title_template()` を経由し、未知プレースホルダを opaque な `KeyError` ではなく「不正プレースホルダ名 + 許可キー一覧」を含む actionable な `ValidationError` に変換して fail-loud する。`youtube_auto_uploader._upload_complete_collection()` は `descriptions.md` を先に読み込み `title_override` として渡す

- `fix(benchmark)`: ベンチマーク未取得・空・取得失敗時に空データ/デフォルト値（`[]` / `{}` / `avg_views=0`）のまま黙って完走する fallback を是正した（#619）。`load_benchmark_videos()` は JSON 未検出 / フィルタ後 0 件で `ConfigError`、`collect_channel()` はチャンネル欠落で `YouTubeAPIError`・API 失敗（`HttpError`）を `YouTubeAPIError.from_http_error` でドメイン例外化、`collect_all()` は欠落チャンネルを `if data:` で暗黙スキップせず明示検知して `YouTubeAPIError`、`ensure_benchmark_fresh()` は取得失敗・`benchmark.channels` 未設定で黙って `return` せずドメイン例外で通知する。いずれも原因と次アクション（`/benchmark` 再実行・設定確認）をメッセージに含め、下流（サムネ比較・分析）が無効データに基づいて成功扱いされる経路を塞ぐ

- `refactor(video-upload)`: 動画アップロード時の AI 開示フラグ `status.containsSyntheticMedia` と子供向け申告 `status.selfDeclaredMadeForKids` を `youtube_auto_uploader.py` のハードコードから config 解決へ外出しした（#605、audit R-5）。`config/channel/youtube.json` の `youtube.contains_synthetic_media` / `youtube.self_declared_made_for_kids` で上書きでき、`YoutubeApi` dataclass の任意フィールド（デフォルト `True` / `False`）として `channel_settings.build_upload_status_flags()` 経由で解決する。未設定時は現行の振る舞い（`containsSyntheticMedia: True` / `selfDeclaredMadeForKids: False`）を維持するため挙動は不変。YouTube 側ポリシー変更や下流チャンネルごとの開示要否差異への追従が容易になる


### Deprecated

- `docs(deps)`: `google-auth-httplib2`（PyPI 0.4.0 / 2026-05-07 で deprecated 表明）を依存ポリシーとして明文化した（#475、#408 follow-up・監査 R-04）。CLAUDE.md「依存ポリシー: deprecated 表明済み依存の取り扱い」節で `src/youtube_automation/` への直 import 新規追加を禁止し（現状 0 件）、回帰テスト `tests/test_no_google_auth_httplib2_direct_import.py` で `ast` ベースに機械担保する。既存の transitive 依存は `googleapiclient.discovery.build(..., credentials=...)` 経由で残置し、上流が non-httplib2 transport をサポートした際の移行手順は `docs/migration/google-auth-httplib2.md` を参照。`pyproject.toml::dependencies` の直接宣言撤去は transport 切替完了後に別 issue で再検証（外部依存待ち）。リリース時は `/automation-release` が `[Unreleased]` を整える流れで本節をそのまま `Deprecated` として転記する


### Fixed

- `fix(videoup)`: `generate_videos.sh` のマスター音源検出パターンを拡張し、`/lyria` / `/masterup`（`yt-generate-master`）の自動生成出力である `master.{wav,m4a,aac,mp3,flac}` も検出対象に追加した（#507）。従来は `master-mix.{wav,m4a,aac,mp3,flac}` のみだったため、`/lyria` で `master.wav` を出力した直後に `/videoup` を起動すると `ERROR: master-mix.{wav,m4a,aac,mp3,flac} not found` で停止していた問題を解消（採用方針 (a) — skill 単体完結、`src/` 側のファイル名は据え置き）。検出順は `master-mix.*`（DAW バウンス・手動配置を優先）→ `master.*`（自動生成）、拡張子は wav / m4a / aac / mp3 / flac の順。両方存在する場合は `master-mix.*` を優先（テスト `test_master_mix_takes_precedence_over_master` で固定化）。`.claude/skills/videoup/SKILL.md` のステップ・自動検出記述と `src/youtube_automation/utils/audio_formats.py` の docstring も新パターンに合わせて更新

- `feat(videoup)`: `generate_videos.sh` に映像エフェクトプリセット 3 種（光の粒子 / ボケ / グラデーション流れ）を追加した（#648 / feedback by あおいさん）。環境変数 `VIDEOUP_EFFECT=none|particles|bokeh|gradient` と `VIDEOUP_EFFECT_INTENSITY=subtle|medium|strong` で選択でき、デフォルトは `none` で従来挙動を完全に温存する（ループは stream copy のまま、静止画は 1fps libx264 のまま）。エフェクト有効時はループモードでも libx264 再エンコード（CRF 22 / `LOOP_MAX_BITRATE` ガード継続）に自動で切り替わり、静止画モードも 24fps 出力に切り替わる。filtergraph は ffmpeg 単体で完結（外部依存なし）、不正な値は ffmpeg 起動前に fail-loud で停止する。詳細・使い方・注意点は `.claude/skills/videoup/SKILL.md` 「映像エフェクト」節、テストは `tests/test_generate_videos_script.py` の `test_*_effect_*` を参照。skill-config 化（チャンネル既定値のファイル設定化）は follow-up

- `feat(videoup)`: `generate_videos.sh` を v13 へ更新し config-driven overlay（visualizer + subscribe popup）合成を追加した（#511）。`config/channel/youtube.json::overlays.enabled: true` のとき `jq` で `overlays` を読み x264 再エンコード経路で `filter_complex` を構築し、`showfreqs=mode=bar` + `gblur` glow で audio visualizer を、静止 PNG + `fade` / `enable='between(t,start,end)'` で subscribe popup を背景の上に合成する。`enabled: false`（既定）/ `overlays` キー欠落 / `jq` 未導入時は v12.1 の stream copy（loop）/ 1fps 静止画経路を完全に維持して後方互換を保つ。あわせて `COLLECTION_NAME` 抽出 regex を `^[0-9]+-[a-z]+-` → `^[0-9]+-[a-z0-9]+-` へ緩め、数字を含む slug（例 `20260101-r2d2-foo-collection`）を正しく剥がせるよう修正。`YoutubeConfig` に `Overlays` / `OverlayAudioVisualizer` / `OverlaySubscribePopup` / `OverlayEncoder` dataclass を追加し、`loader._build_overlays` で `overlays` JSON を全フィールド組み立てる（型不正は `ConfigError`）。`examples/channel_config.example/youtube.json` に `overlays` セクションのサンプル（既定 `enabled: false`）を追記し、`.claude/skills/videoup/SKILL.md` に Overlays セクション（設定例・popup 画像探索順・DeepFocus365 実証メモ）を追加した


- `fix(skills-sync)`: `yt-skills sync --asset skills` の `.agents/skills` symlink 作成が権限エラーで失敗したときに silent に握りつぶしていた挙動を是正した（#644、#617 の follow-up）。これまでは `OSError` をまとめて `'unsupported'` 扱いにし stderr 警告のみで rc=0 を返していたため、Codex CLI が同期済みスキルを発見できない原因の切り分けに時間がかかっていた。`PermissionError` を `OSError` から分離して `'permission-denied'` を返し、sync 全体の rc を非ゼロにし、`mkdir -p .agents` + `ln -s ../.claude/skills .agents/skills` の手動復旧手順と `sudo` / 適切権限での `yt-skills sync --asset skills --force` 再実行を案内する actionable な error メッセージを stderr に出す。FS が symlink を本当にサポートしていない環境（Windows 非特権ユーザー等）は従来どおり `'unsupported'` で警告のみ（rc=0）を維持し、復旧可能な権限エラーとだけ扱いを分ける。テストで permission-denied 経路（rc!=0・手動復旧文・skills 本体は配布完了）と unsupported 経路（rc=0 のまま）の両方を担保する

- `fix(thumbnail)`: キャラサムネの解剖学（手・指）品質ゲートを敷き、`single_step` プレビュー = 最終 thumbnail 経路が QA をスキップする穴を塞いだ（#570）。`.claude/skills/thumbnail/config.default.yaml` の `single_step` に新 clause `anatomy_clause`（`hands anatomically correct, five fingers each, no fused/extra/melted fingers` を骨格）を追加し、`diff_prompt_template` から `${anatomy_clause}` として opt-in 展開できる。`.claude/skills/thumbnail/SKILL.md` の品質チェック節に手・指 5 本指 / 分離 / 楽器持ちポーズ警告を含む解剖学チェック項目を追加し、プロンプト構築 step 3 で `anatomy_clause` の必須挿入条件（キャラ + 手構図）を明文化。`.claude/skills/wf-new/SKILL.md` Phase 2c の `single_step` / `codex` 経路で `cp main.png thumbnail.jpg` の直前に必須 QA（手・指解剖 / テキスト破綻 / 署名透かし）を Read プレビューで通すよう手順を分割し、NG 時は `${anatomy_clause}` 強調 + Phase 4 から再生成または codex プロバイダー切替の戻り経路を提示。`.claude/skills/collection-ideate/SKILL.md` Phase 4-1 / 4-4 に「キャラ + 手構図では全企画プロンプトに `anatomy_clause` を含める」要件を追加し、`single_step` プレビューが最終 thumbnail に流用される経路で Gemini の指融合・本数異常・溶融が公開サムネに混入する経路を塞ぐ。`tests/test_thumbnail_skill_assets.py` に `anatomy_clause` の同梱 / 品質チェック項目の解剖学カバレッジを検証する 2 件を追加（既存 4 件 + 新 2 件 = 計 6 件 green）

- `fix(channel-new,channel-import)`: `channel-new` / `channel-import` の `uv add git+https://...` の URL を `youtube-channels-automation.git`（PyPI 配布名・GitHub には存在せず HTTP 404）から正しい `youtube-automation.git`（GitHub リポジトリ名）に修正した（#642）。あわせて `channel-setup/references/claude-md-template.md` と `channel-setup/references/gcp-bootstrap.md` の GitHub リポジトリ参照も `daiki-beppu/youtube-automation` に直し、テンプレート経由で全下流チャンネルの `CLAUDE.md` に誤名が伝播していたドキュメントバグを止める。再発防止のため両ファイルに「GitHub repo 名 = `youtube-automation` / PyPI 配布名 = `youtube-channels-automation` / import 名 = `youtube_automation` で 3 つは別物」と明記

- `fix(yt-channel-settings)`: localizations のロケールコードを CLI 側で双方向に正規化し、`["ja", "en", "de"]` のような短縮 BCP-47 が部分失敗する問題を解消した（#562）。`channel_settings.build_update_body` は短縮形 / ハイフン形 / アンダースコア形のいずれを受け取っても YouTube 内部形 `xx_YY`（例 `ja_JP` / `en_US` / `de_DE`）に正規化して `localizations` のキーと `brandingSettings.channel.defaultLanguage` を送信する。これにより `defaultLanguage` と一致した言語だけが受理され他言語が silent skip される YouTube API の挙動を踏まずに済む。`parse_api_response` 側は逆向き正規化で短縮形 `xx`（region 必須は `xx-YY`、例 `pt-BR` / `zh-TW`）へ寄せてローカル persistence に書き出し、`diff_settings` も `default_language` と `localizations` のキー揺れを吸収してから比較するため `pull` 後の永続 diff がゼロになる。`config-generation-rules.md` の推奨形式 `["ja", "en", "de"]` のまま運用可能（`normalize_locale_to_api` / `normalize_locale_to_short`）

- `fix(masterup)`: `/masterup` Step 2 の WebFetch ベースのプレイリスト取得が 50 曲超のプレイリストで超過分を silent に取りこぼす問題を是正した（#645）。`.claude/skills/masterup/SKILL.md` の Step 2 に「プレイリスト総曲数（`song_count` 等のメタ表記）の必須取得」と「取得件数との突合チェック（不一致なら中断・ユーザー報告）」を明文化し、suno.com のサーバー描画上限（50 件）で 51 曲目以降が遅延読み込みのため取れないことを前提運用化した。総曲数のメタが取れない場合も silent 続行を禁止し中断する。フォールバック方針として「50 曲以下に分割して再実行」または「`02-Individual-music/` に手動で MP3 を揃えて `yt-generate-master` を直接実行」を SKILL.md に明記。内部 API / 公式 API への移行は別 issue（スコープ外）

- `fix(suno)`: `/suno` SKILL.md がパターン数を「4」固定で生成していた問題を修正した（#608）。「## パターンベース設計」「### 生成計画」を `config/skills/suno.yaml` の `patterns_per_collection` / `pattern_strategy` / `tracks_per_pattern` / `pattern_strategy_note` 参照ベースに書き換え、`patterns_per_collection: 1`（= `pattern_strategy: single`）宣言時は複数シーンを 1 つの統合情景フレーズに集約して同一プロンプトを `tracks_per_pattern` 回生成する手順を明示した。総トラック数も `patterns_per_collection × tracks_per_pattern × 2` 式へ一般化（1×3×2=6 / 4×3×2=24 の対比表を併記）。skill-config に該当キーが無い場合は後方互換で従来の 4 パターンへフォールバックするため、既存 DeepFocus365 以外のチャンネルへの影響は無い。あわせて `config.default.yaml` に `patterns_per_collection: 4` / `pattern_strategy: mixed` / `tracks_per_pattern: 3` / `pattern_strategy_note: ""` を default として明示

- `fix(suno)`: `/suno` skill と `/wf-new` Phase 2c に `genre_line` 空時の hard gate を導入し、AI がジャンル方向性を手書きで埋めかねない問題を塞いだ（#571、root cause #567）。`config/skills/suno.yaml::genre_line` が空 + `data/video_analysis/<slug>/*.json` が全 benchmark slug で不在のときは、`/suno` の Instructions 冒頭「前提条件チェック（hard gate）」と `/wf-new` Phase 2c の `/suno` 呼び出し前段の両方で実行を中断し、`uv run yt-video-analyze --source benchmark --channel <slug> --top 5`（必要なら先に `/benchmark`）を先行するようユーザーに案内する。「Suno プリセット推奨（suno_preset fallback）」節と「ベンチマーク BGM 構造の参照」節の `AskUserQuestion` 提案にも「genre_line 空のとき拒否は中断扱い、AI 手書き fallback 禁止」を明記して提案止まりだった経路を塞いだ。`genre_line` 充足済み（あるいは fallback で `suno_preset.genre_line` が取れる）チャンネルの挙動は不変

- `docs(videoup,suno,lyria,masterup)`: オーディオビジュアライザー / オーバーレイ機能が未実装である旨を `videoup` SKILL.md に明文化し、関連する音源生成系スキル（`suno` / `lyria` / `masterup`）にも警告セクションを追加した（#646 feedback）。ユーザーが Suno 取り込み等の音源工程でビジュアライザー指示を出しても最終 MP4 に反映されない根本原因が「`generate_videos.sh` 側に overlay 合成経路が存在しない」ことであることを記載し、機能本体の実装は #511（`overlays.enabled` config-driven 合成）で追跡されていること、実装が落ちるまでは外部ツール（DaVinci / AfterEffects / 手書き ffmpeg）で別途合成する暫定運用とすべきことを明示した。誤指示を受けたときに Claude が即座に制約を伝える行動指針も追記。コード本体（`generate_videos.sh` v12.1）は変更なし

- `fix(lyria)`: Lyria 3 の新 schema 検出パスを公式仕様 `steps[*].content[*]` ベースに再実装した（#679、#377 defensive 実装の再検証）。従来は Gemini text-generation API の構造 `candidates[*].content.parts[*].inline_data` を走査していたが、これは Lyria 3 `interactions` API の新 schema（[May 2026 breaking change](https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026)）と乖離しており、Vertex AI 側で新 schema に切り替わると `candidates` 不在で `None` を返し生成がサイレント停止する恐れがあった。公式の新 schema は flat な `outputs` 配列を `steps` 配列に置き換え、各 step の `content` 配列要素は legacy `outputs` と同一形状（`type` / `mime_type` / `data`）を持つ。両経路の audio 抽出を共通ヘルパー `_audio_data_from_entries` に集約し、`_new_schema_audio_data` を `steps[*].content[*]` 走査へ書き換えた。誤った旧経路向けヘルパー `_audio_data_from_part`（`inline_data` / camelCase 対応）は削除。legacy `outputs` 経路は不変で後方互換を維持し（撤去は Vertex 切替日確定後の #461 スコープ）、想定外のレスポンス形状では例外を投げず `None` を返す defensive 挙動も維持する（`tests/test_lyria_client.py` の新 schema / legacy / 不正形状ケースで担保）

- `fix(thumbnail)`: TTP / single_step モードでベンチマーク参照画像の署名・透かし・ロゴが転写されて IP / 版権リスクを生む経路を塞いだ（#569）。`config/skills/thumbnail.yaml`（`config.default.yaml`）の `image_generation.gemini.single_step` に新 clause `ip_safety_clause`（`no signature, no autograph, no watermark, no logo, no brand mark, clean corners`）を追加し、`.claude/skills/thumbnail/SKILL.md` の TTP 章冒頭・プロンプト構築 step 3・プリフライト・チェックリストに「参照元の識別マークはコピーしない — 版権/IP リスク」の警告と差分プロンプトへの常時挿入要件を明文化した。`.claude/skills/collection-ideate/SKILL.md` の Phase 4-1（テキスト案提示）/ Phase 4-4（single_step プロンプト構築）にも同 clause を全企画プロンプトの末尾に含めるよう追記し、テキスト案レビュー段階で抜けに気付けるようにした。skill ドキュメント / config テンプレートの追加のみで実コード変更は伴わず、既存 `diff_prompt_template` は破壊しない（既存テンプレートは新 clause を `${ip_safety_clause}` として opt-in 展開する形）

- `fix(video-upload)`: 予約投稿の設定をしたつもりが即時公開されてしまう FB を是正した（#647）。`collection_uploader._calculate_publish_at` が `schedule.auto_schedule_enabled: true` の明示設定だけを有効化条件にしていたため、`cadence` / `publish_time` だけを書いて `auto_schedule_enabled` を入れ忘れた `schedule_config.json` は黙って即時公開経路に落ちていた。`_scheduling_enabled()` ヘルパーを切り出して (1) `auto_schedule_enabled` 明示優先 (2) 未設定でも `cadence`（非空）または `publish_time` 明示なら有効扱いとする暗黙オプトインを追加（`auto_schedule_enabled: false` 明示は即時公開を強制する後方互換は維持）。あわせて `youtube_auto_uploader._normalize_publish_at()` を新設し、`+09:00` 等の timezone offset 付き値を UTC（Z 終端）に正規化してから `status.publishAt` に渡す（API 受理形式の取りこぼし防止）。`show_plan()` は `auto_schedule_enabled: false` が明示されているのに `cadence` / `publish_time` / `day1_time` が設定されている矛盾構成を ⚠️ で警告。`.claude/skills/video-upload/references/scheduled-publish.md` を新設し、有効化方法・検証手順（`--plan` / YouTube Data API での `status.publishAt` 確認）・即時公開された場合のトラブルシュートを明文化、`channel-setup/references/schedule-template.json` を `publish_time` + `cadence` 構成に更新

- `fix(short-upload)`: `ShortUploader.upload_short` に resumable upload session URI 永続化を適用し、Shorts 投稿の中断→再実行時の video_id 重複（二重 publish）の余地を解消した（#466、CC 経路 #381 と同等）。これまで `upload_video` を `resume_session_uri=None` のまま呼んでいたが、`workflow-state.json` の `post_upload.shorts[].resume_session_uri` に session URI を読み書きするクロージャ（`on_session_uri_changed` / `on_upload_complete`）を配線。開始前に保存済み URI を読んで再開し、成功時はクリア、中断時は残して次回再開する。tracking 媒体は CC の `upload_tracking.json` ではなく Shorts 専用の `workflow-state.json`（既存 entry には key を増やさず書込み時のみ append する schema 互換）。再開不要な単発投稿は従来どおり `resume_session_uri=None` で挙動不変

- `fix(uploader)`: サムネ候補の優先順を `CollectionPaths.find_thumbnail()` に集約して統一した（#535）。従来 `find_thumbnail()`（`thumbnail.jpg > main.png > main.jpg`）と `_upload_complete_collection` のインライン候補（`thumbnail.jpg > thumbnail.png > main.jpg > main.png`）で順序が食い違っており、将来 `find_thumbnail()` へ統一する際に拾われる画像が変わるリスクがあった。実際にアップロードで使われていた後者の順を正とし、`find_thumbnail()` を `thumbnail.jpg > thumbnail.png > main.jpg > main.png`（`_THUMBNAIL_CANDIDATES`）に揃え、`_upload_complete_collection` は `find_thumbnail()` へ委譲。全候補組み合わせで統一前のアップロード経路と同一ファイルを指すことを回帰テストで担保（既存コレクションのサムネ選択は不変）


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
  - `youtube_automation.utils.config.channel_dir()`: `config/channel/` を含むプロジェクトルート path 解決のみ
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

[5.5.17]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.17
[5.5.16]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.16
[5.5.15]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.15
[5.5.14]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.14
[5.5.13]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.13
[5.5.12]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.12
[5.5.11]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.11
[5.5.10]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.10
[5.5.9]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.9
[5.5.8]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.8
[5.5.7]: https://github.com/daiki-beppu/youtube-automation/releases/tag/v5.5.7
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
