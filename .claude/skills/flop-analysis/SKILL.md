---
name: flop-analysis
description: "Use when 公開済み動画が伸びなかった原因を video_id、collection、または --since で切り分け、postmortem.md に出力するとき。「伸びなかった」「flop 分析」で発動。横断戦略は /analytics-analyze、事前監査は /alignment-check"
---

## 前後工程

- `前工程`: `/analytics-analyze`, `/alignment-check`
- `後工程`: `/collection-ideate`

## Overview

公開後「思ったより伸びなかった」動画について、Analytics（CTR / 平均視聴時間 / インプレッション）を
過去自チャンネル平均 + 競合ベンチマークと突き合わせ、症状から仮説を立て、対応する既存スキル / CLI / API で検証する。
最終出力は `collections/live/<collection>/20-documentation/postmortem.md`。

責務は **症状の定量化 + 仮説リスト生成 + 検証の自律実行 + 結論の記入** まで。Gemini 等の API コストが発生する `/video-analyze` を含め、仮説検証はユーザーの承認プロンプトを挟まず実行する。改善策の適用は本スキルの責務に含めない。

## 完了条件

`collections/live/<collection>/20-documentation/postmortem.md` に、Phase 4 の検証の実行結果と「結論 / 反証 / 学び」をすべて記入して保存し、Phase 6 の insights 還元（還元対象なしの場合はその明示）まで実行した時点で完了。検証手段の案内だけ、または結論欄が空の状態では完了としない。

## 設定読み込みゲート

前提確認や Phase 1 に入る前に、以下を必ず Read（Codex では同等のファイル閲覧）で開く。SKILL.md の説明や記憶から設定値を推測しない。

1. `.claude/skills/flop-analysis/config.default.yaml`
2. `config/skills/flop-analysis.yaml`（存在する場合）

新 override を正規経路として優先する。新 override がなく `config/skills/postmortem.yaml` だけが存在する場合は、移行 fallback として旧 override を読み込み、`config/skills/flop-analysis.yaml` へのリネームを案内する。読み込み後は `youtube_automation.utils.skill_config.load_skill_config("postmortem")` と同じ deep-merge 前提で、チャンネル上書きを優先して扱う。存在しない override は未設定として扱い、勝手に作成しない。Phase 2 の症状判定は `thresholds.*`、Phase 3 の仮説マッピングは `hypothesis_ratios.*` を参照する。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合、ユーザーに確認:
- **新規チャンネル** → `/channel-new` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/channel-new`（既存チャンネル取り込みモード）を案内

加えて、対象動画について以下が揃っていること:
- `data/analytics_data_*.json` の `video_analytics[<video_id>]` に当該動画が含まれている（含まれていない場合は `/analytics-collect` を先に案内）
- CTR / インプレッションを参照する場合は同 JSON に `reporting_api.impressions_summary.per_video[]` が含まれていること（取得元は `utils/reporting_api.py`。未取得の場合は CTR / インプレッション欄を「データなし」と明示し、`/analytics-collect` の再実行を案内する）
- コレクション指定の場合は `collections/live/<collection>/20-documentation/upload_tracking.json` が存在する

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| `<video_id>` | YouTube 動画 ID を直接指定 | `/flop-analysis dQw4w9WgXcQ` |
| `<collection>` | コレクション名を指定（`upload_tracking.json` の `complete_collection.video_id` を解決） | `/flop-analysis rain-jazz-night` |
| `--since <N>` | 公開後 N 日以内に公開された動画から候補を提示 | `/flop-analysis --since 14` |

複数候補がある場合は AskUserQuestion で対象を選ばせる。

## 想定 API call 数

| API | call 数 / 実行 | 変動要因 |
|---|---|---|
| 直接実行 CLI（yt-launch-curve / yt-theme-compare / yt-thumbnail-correlate） | 0 call（ローカル処理のみ） | — |
| Vertex AI Gemini（Phase 4 で /video-analyze を自律実行する場合） | 対象 1 動画 = 1 call | 仮説検証で /video-analyze を実行するかどうか |

- 上限 / 承認: /video-analyze は承認プロンプトなしで自律実行されうるが、対象は当該 video_id 1 本に限定される。見積もりの詳細は /video-analyze の「想定 API call 数」を参照。

## 実行フロー

### Phase 1: 対象動画の解決

入力種別ごとに `video_id` を確定する:

| 入力 | 解決ロジック |
|------|-------------|
| `<video_id>`（11 文字英数 + `-_`） | そのまま採用 |
| `<collection>` | `collections/live/<collection>/20-documentation/upload_tracking.json` の `complete_collection.video_id` を採用（`agents/_tracking_io.py`（`collection_uploader.py` から分離）の schema_version=3 で生成される唯一のフィールド） |
| `--since <N>` | `data/analytics_data_*.json` の `video_analytics[*].published_at` を走査し、現在日付から N 日以内に公開された動画を候補化 → AskUserQuestion |

確定した `video_id` から、所属コレクション名（`upload_tracking.json` を逆引き）と公開日（`video_analytics[<id>].published_at`）を取得する。コレクションが解決できない場合は **エラーで停止** し、利用者に `<collection>` 引数か対応する `upload_tracking.json` の整備を促す（新規ディレクトリ規約は作らない）。

所属コレクションの `20-documentation/thumbnail-test-history.json` が存在する場合は、`.claude/skills/thumbnail-test/references/history-schema.md` の `### Completed history` にある履歴構造検証コマンドだけを実行する。検証が非0なら履歴を根拠に使わず、ファイルパスとエラーを postmortem のデータ不足として記録する。検証済みなら `video_id` が一致する全 entry を Phase 2 へ渡す。履歴が存在しない場合は「A/B テスト履歴なし」と明示し、従来の Analytics 根拠だけで続行する。

### Phase 2: 症状の定量化

以下のソースを突き合わせて症状テーブルを作る。**指標は実装と同じシンボル名で参照すること**:

| 指標 | ソース | 取得方法 |
|------|--------|---------|
| `cumulative_views` ベンチマーク比 | `yt-launch-curve --video <id>` | `target.ratio_vs_median` / `target.quartile_label` を引用 |
| 日別 `daily_views` / `daily_impressions` / `ctr` | `yt-launch-curve --video <id>` | `target.trace[]` を引用（`daily_views` / `daily_impressions` / `ctr` の各キーが含まれる） |
| 平均視聴時間（全期間） | `data/analytics_data_*.json` の `video_analytics[<id>].average_view_duration` | snake_case フィールド（秒）。`strategic_analytics.py::get_combined_analytics` 由来 |
| CTR（全期間集計） | `data/analytics_data_*.json` の `reporting_api.impressions_summary.per_video[]` | `video_id` 一致行の `ctr_percentage`（パーセント）。`utils/reporting_api.py::collect_impressions_summary` 由来。Reporting API v1 が未取得の場合は欠損として扱う |
| インプレッション（全期間集計） | 同上 | `video_id` 一致行の `impressions`。日次合計は `target.trace[].daily_impressions` を合算 |
| 競合中央値（補助指標） | `data/benchmark_<YYYYMMDD>.json`（最新） | `benchmark_collector.py::collect_channel` が保存する `views` / `likes` / `comments` / `duration_display` のみ参照。**CTR / 平均視聴時間は Data API では取れず競合分は欠落する** |
| サムネ A/B テスト | `20-documentation/thumbnail-test-history.json` | 対象 `video_id` の `result.status` / `candidates[].watch_time_share` / Winner 候補の構図・配色・文字量を引用 |

**per-video 流入経路シェアについて**: `data/analytics_data_*.json` の `traffic_sources`（`channel_analytics.py:163` 由来）と `utils/traffic_source_analytics.py::get_traffic_source_analytics` は **どちらもチャンネル全体集計** であり、対象動画 1 本のシェアは含まない。per-video の `insightTrafficSourceType` を取得するヘルパー関数はリポジトリ内に存在しないため、Phase 2 の症状テーブルでは流入経路を扱わない。per-video の流入経路を見たい場合は Phase 4 の検証ステップ（YouTube Analytics API への直接クエリ）に集約する。

ベンチマーク値の使い分け:

- **CTR / 平均視聴時間 / インプレッション**: 自チャンネル中央値のみで比較する（競合分は YouTube Data API では取得できないため）。基準値は `yt-launch-curve` の `target.benchmark_median` / `target.ratio_vs_median` と、`reporting_api.impressions_summary.aggregated_ctr_percentage`（チャンネル全体平均）を採用する
- **views / 動画長**: 自チャンネル中央値 + 競合中央値（`data/benchmark_*.json`）の両方を引用してよい

症状判定の閾値は skill-config `thresholds.ratio_vs_median`（既定 `strong: 0.5` / `moderate: 0.7` / `mild: 0.9`。`launch_curve_analyzer.py` の四分位ラベル p25/p50/p75 と整合）:

| 指標 | 判定 |
|------|------|
| `ratio_vs_median < strong` | 強い症状（赤） |
| `strong ≦ ratio_vs_median < moderate` | 中程度の症状（黄） |
| `moderate ≦ ratio_vs_median < mild` | 軽症（薄黄） |
| `ratio_vs_median ≧ mild` | 健常（緑） |

### Phase 3: 仮説マッピング

Phase 2 の症状から仮説を生成する。判定係数は skill-config `hypothesis_ratios`（既定 `ctr_low: 0.7` / `ctr_healthy: 0.9` / `avd_low: 0.7` / `impressions_low: 0.5`）と `thresholds.neutral_band_pct`（既定 10）を使う。複数の症状が同時に成立した場合は該当行をすべて採用し、postmortem.md には全候補を列挙する:

| 主症状 | 副症状 | 主仮説 | 副仮説 |
|--------|--------|--------|--------|
| `ctr_percentage` が自チャンネル `aggregated_ctr_percentage` の `ctr_low` 倍未満 | `impressions` は過去平均同等以上 | サムネ訴求弱 | タイトル訴求弱<br>ターゲット層ミスマッチ<br>差別化不足 |
| `ctr_percentage` が自チャンネル `aggregated_ctr_percentage` の `ctr_healthy` 倍以上 | `average_view_duration` が自チャンネル中央値の `avd_low` 倍未満 | 中身の弱さ（音源 / 編集 / テーマ） | サムネと中身の不一致 |
| `impressions` が過去平均の `impressions_low` 倍未満 | — | タイトル / タグ SEO 弱<br>初動エンゲージメント低 | 公開時刻ミス<br>再生リスト未登録 |
| 全指標が中央値前後（±`neutral_band_pct` %）で `ratio_vs_median < mild` | — | テーマ自体の市場性不足 | 競合過密ジャンル |

閾値は skill-config の恒久上書きとは別に **チャンネル特性に応じて文脈調整可** とする。ただし一時調整して良いのは以下の 3 ケースに限る:

| ケース | 調整内容 |
|--------|---------|
| 新チャンネル（公開 10 本未満 or 開設 30 日未満） | 平均比閾値を ±0.1 まで緩和可 |
| 直近テーマ転換 | 過去平均比較は参考値とし `ratio_vs_median` 系を優先 |
| 外部要因の明確な痕跡 | 該当指標の判定を保留し外部要因を先に記録 |

該当ケースがなければ表の係数をそのまま使う（自由裁量での調整は不可）。調整した場合は、変更前後の閾値と適用したケース名を postmortem.md の「症状サマリー」欄に必ず明示する。

per-video 流入経路シェア（`YT_SEARCH` / `YT_BROWSE` 等）に基づく「YouTube 内露出不足」仮説は、既存データには per-video の `insightTrafficSourceType` が含まれないため Phase 3 では仮説化しない。`impressions` が過去平均の `impressions_low` 倍未満（上表 3 行目）と判定された場合のみ、Phase 4 の検証ステップで per-video の流入経路を YouTube Analytics API に直接問い合わせて切り分ける。

### Phase 4: 検証の自律実行

Phase 3 で列挙した主仮説（全件）について、次の表から対応する検証手段を選び、ユーザーの承認プロンプトを挟まず対応する検証手段を自動実行する。`/video-analyze` 等の有料 API を使う検証も同じ扱いとする。

各検証の直後に、postmortem.md の「検証ステップ」欄へ以下を記録する:

- 対象仮説と実行したスキル / CLI / API クエリ
- 実行結果の要約と、参照した数値・成果物パス
- 判定: `支持` / `反証` / `未検証（理由: <具体的な理由>）`

主仮説は途中で支持されたものがあっても省略せず、全件を検証する。全主仮説の判定後は、`.claude/skills/flop-analysis/references/verification.py --operation secondary-transition` に全主仮説の判定を渡し、その `action` と `reason` に従う。`未検証` は反証として扱わない。

副仮説を実行しない場合も、各副仮説に該当する上記の理由を記録する。これにより、データ不足または子スキル失敗で主仮説が未検証のときに、主仮説が支持されたとは記録しない。

個別検証がデータ不足または子スキル失敗で実行不能でも全体を停止しない。当該項目へ `未検証（理由: <具体的な理由>）` と記録し、残りの検証を続行する。

**非対話・分析専用境界**

Phase 4 は改善策を適用せず、次の境界を守る:

- `/alignment-check`、`/viewer-voice`、`/audience-persona-design`、`/viewing-scene`、`/channel-new` はスキルとして起動しない。これらは AskUserQuestion、設定更新、または別成果物の保存を完了条件に含むため、既存の `docs/plans/alignment-audit.md`、`docs/plans/viewer-voice-analysis.md`、`docs/channel/personas/persona-definition.md`、`docs/plans/viewing-scene-matrix.md` がある場合だけ read-only 入力として読む。必要な成果物がなければ、その仮説を理由付きの `未検証` とする
- タイトル整合性は `/alignment-check` を起動せず、対象コレクションの `workflow-state.json`、音楽プロンプト、実動画尺、検証済み A/B 履歴の現在サムネ候補を read-only で照合する。`config/channel/content.json`、タイトル、サムネイル、音源、方向性文書は変更しない
- 差別化・市場性は `/discover-competitors` や `/channel-new` を起動せず、最新の既存 `data/benchmark_*.json` と `yt-theme-compare` の標準出力だけを使う。競合の追加、方向性決定、config 更新は行わない
- `/thumbnail-compare` と `/video-analyze` は各スキルの分析成果物生成まで実行してよいが、Next Step の再生成・設定更新には進まない

**共通の期間・比較・記録契約**

- 「公開初期」は公開日を day 0 とする day 0〜6 の 7 日間。公開後 7 日未満なら、最新 `data/analytics_data_<YYYYMMDD>.json` の日付までの同じ経過日数を対象にする
- Reporting API の D+2 ラグを考慮し、公開後 3 日未満は CTR を使う仮説を判定せず、`未検証（理由: Reporting API の D+2 ラグ）` とする。CTR を使わない検証は同じ経過日数で続行する
- 自チャンネル比較は `yt-launch-curve` が対象と同じ経過日数で返す他動画の中央値を使う。比較可能な他動画が 3 本未満なら、中央値を作らず `未検証` とする
- 競合比較は最新 `data/benchmark_<YYYYMMDD>.json` の `views` 上位 10 本を使う。該当動画が 10 本未満なら存在する全件を使い、3 本未満なら `未検証` とする
- 各判定は postmortem.md に `hypothesis`、`method`、`period`、`target_value`、`baseline_value`、`threshold`、`evidence_path`、`verdict` の 8 フィールドを記録する。必要な値が 1 つでも欠ける場合は支持・反証を推定せず `未検証` とし、欠けたフィールド名を理由に含める
- per-video 流入は Analytics API に `ids=channel==<channel_id>`、`startDate=<published_atのYYYY-MM-DD>`、`endDate=<公開初期の最終日>`、`filters=video==<video_id>`、`dimensions=insightTrafficSourceType`、`metrics=views,estimatedMinutesWatched` を指定し、同じ `ids`・期間で `filters` と `dimensions` を外した channel query と比較する

**実行可能な判定境界**

語彙の NFKC 正規化・token 化、タイトル整合性、サムネ特徴量と A/B 根拠の統合、中身の弱さ、主仮説後の状態遷移は `.claude/skills/flop-analysis/references/verification.py` を単一ソースとする。本文で判定を再実装せず、各検証結果を JSON object として標準入力へ渡す。

```bash
uv run python .claude/skills/flop-analysis/references/verification.py --operation <term-classification|title-alignment|thumbnail|content-signals|hypothesis|secondary-transition> < input.json
```

`title-alignment` の語彙候補は対象だけに限定しない。`genre_vocabulary` は `collections/live/*/workflow-state.json::theme` と各音楽プロンプトの style / genre 行、`scene_vocabulary` は同 `workflow-state.json::scene_phrases.*` から収集する。対象タイトル、対象の theme・`planning.music.mood[]`・音楽プロンプト、対象の scene phrases、検証済み A/B 履歴で `file` が `thumbnail.jpg` / `thumbnail.png` の候補の `composition.scene`、実動画尺をそれぞれ `title`、`actual_genre_texts`、`actual_scene_texts`、`thumbnail_scene_texts`、`duration_seconds` として渡す。本スキルは collection 型だけを対象とするため `actual_content_type` は `collection` とする。これにより、対象内容と一致しない `rock` や `sleep` も語彙候補に存在すれば矛盾へ到達する。必須入力が空ならスクリプトの `unverified` と `reason` をそのまま記録する。

差別化不足とタイトル / タグ SEO 弱の語彙比較は、同じ語彙候補と競合タイトルを `term-classification` に渡す。返された `genre_terms`、`scene_terms`、`subject_terms`、`content_terms`、文書頻度順の `frequent_competitor_terms` だけを使い、別の token 化を本文内で行わない。

スクリプト出力の `supported` / `refuted` / `unverified` は、それぞれ postmortem の `支持` / `反証` / `未検証` に対応する。スクリプトが非0終了した場合は成功扱いせず、stderr を理由に含む `未検証` として残りの検証を続行する。

ターゲット層ミスマッチでいう各成果物の「主対象シーン」は、`主対象` または `primary` と明記された見出し・表セル・箇条書きだけから、上記と同じ token 規則で抽出する。明記がない成果物は主対象シーンを抽出できないものとして `未検証` にする。

仮説ごとの入力を収集し、判定は reference の operation だけで行う:

| 仮説 | read-only 入力 | operation / hypothesis |
|------|----------------|------------------------|
| サムネ訴求弱 | `/thumbnail-compare` の `data/thumbnail_compare/small/` にある対象・競合320px画像、検証済み A/B 履歴、`yt-thumbnail-correlate --metric views`（補助根拠） | `thumbnail` |
| タイトル訴求弱 | 対象タイトル、全コレクション由来の語彙候補、対象の workflow-state・音楽prompt・実動画尺、現在サムネ候補の `composition.scene`。collection 型なので `actual_content_type=collection` | `title-alignment` |
| ターゲット層ミスマッチ | `viewer-voice-analysis.md`、`persona-definition.md`、`viewing-scene-matrix.md` の主対象一致件数 | `hypothesis: target-mismatch` |
| 差別化不足 | 最新 benchmark 上位10本と `term-classification` の出力 | `hypothesis: differentiation` |
| 中身の弱さ（音源 / 編集 / テーマ） | 対象と同じ冒頭クリップ窓で保存済みの `/video-analyze` 成果物: 対象の `hook_structure.intro_sec` / `bgm_arc.peak` / `scene_timeline` / `editing_metrics.avg_cut_sec`、同ジャンル競合3本以上の `editing_metrics.avg_cut_sec` 中央値 `competitor_avg_cut_median`。retention 収集済みなら `yt-retention-timeline --video <video_id>` の `reports/retention_analysis/<video_id>.md` も引用 | `content-signals` |
| サムネと中身の不一致 | `/video-analyze` の `thumbnail_alignment.signature_present` | `hypothesis: thumbnail-content-alignment` |
| タイトル / タグ SEO 弱 | 同期間の per-video / channel Analytics API 結果と `term-classification` の出力 | `hypothesis: seo` |
| 初動エンゲージメント低 | `commentThreads.list` と `yt-launch-curve` の day 0〜6 | `hypothesis: engagement` |
| 公開時刻ミス | `published_at` と他動画の公開初期 cumulative views | `hypothesis: publish-time` |
| 再生リスト未登録 | 全チャンネル所有 playlist の `playlistItems.list` | `hypothesis: playlist` |
| テーマ自体の市場性不足 | `yt-theme-compare` の day 0・3・6 と最新 benchmark | `hypothesis: marketability` |
| 競合過密ジャンル | 最新 benchmark 上位10本と `term-classification` の出力 | `hypothesis: competition` |

入力 JSON のキー・閾値・支持 / 反証 / 未検証条件は reference の各公開関数を正とする。必要な入力を収集できない場合は operation を推測値で埋めず、欠けた入力名を理由に `未検証` とする。A/B 履歴は `result.status`、`result.result_candidate_id`、`candidates[].{id,file}` をそのまま `thumbnail` に渡し、現行候補か挑戦候補かも reference で解決する。主観評価は verdict の入力にしない。

`/video-analyze` の各出力は動画全尺ではなく冒頭クリップ窓（既定 900 秒、JSON の
`analysis_window_sec`）内の分析結果として扱う。`bgm_arc.peak` は実スキーマの `M:SS` / `H:MM:SS` 文字列を reference が秒へ変換する。競合の `competitor_avg_cut_median` は対象と同じ `analysis_window_sec` の既存 `/video-analyze` 成果物が3本以上ある場合だけその `editing_metrics.avg_cut_sec` の中央値を使い、不足時は推定せず `未検証` とする。`bgm_arc.outro` や `editing_metrics`
を動画全体の終盤・全尺平均として読まない。

対象動画の retention が最新 `data/analytics_data_*.json::retention[]` にある場合は、
`yt-retention-timeline --video <video_id>` を実行し、drop 地点に対応する scene / BGM を
検証結果へ引用する。`status=skipped` で `/video-analyze 未実行` と返った場合は、既存の
Phase 4 規則どおり対象 1 動画だけ `/video-analyze` してから再実行する。retention 未収集なら
この照合だけを `未検証（理由: retention 未収集。/analytics-collect の full 収集が必要）` とし、
他の content-signals 検証は続行する。`outside_analysis_window` の scene / BGM は推測しない。

### Phase 5: postmortem.md の生成

出力先は `collections/live/<collection>/20-documentation/postmortem.md`。コレクションを逆引きできない `video_id` は **エラーで停止** し、`<collection>` 引数の指定か `upload_tracking.json` の整備を促す（フォールバック用の新規ディレクトリ規約は作らない）。

既存ファイルがある場合は **追記** する（同コレクション内の別動画は `## Postmortem: <タイトル> (<video_id>)` セクションで分割）。

「結論 / 反証 / 学び」は Phase 4 の検証結果を根拠に自動記入し、3 項目を空欄にしない。検証不能が残った場合も、確認できた事実、特定できなかった範囲、その理由、追加で必要なデータを記入する。`未検証` の仮説を支持または反証されたものとして断定しない。

```markdown
# Postmortem: <タイトル> (<video_id>)
公開日: YYYY-MM-DD / 経過日数: N 日
作成日: YYYY-MM-DD
データソース: `data/analytics_data_<YYYYMMDD>.json`, `data/benchmark_<YYYYMMDD>.json`

## 症状サマリー
| 指標 | 実測 | 自チャンネル中央値 | 比率 | 判定 |
|------|------|-------------------|------|------|
| cumulative_views (Nd) | … | … | …x | 赤/黄/緑 |
| ctr_percentage | …% | …% | …x | … |
| average_view_duration | …秒 | …秒 | …x | … |
| impressions (合計) | … | … | …x | … |

※ CTR / 平均視聴時間 / インプレッションは自チャンネル平均のみと比較する（競合分は YouTube Data API で取得不可のため欄外注記）。

※ per-video 流入経路シェアは既存データに含まれないため症状サマリーには載せない。必要な場合は Phase 4 の検証ステップ欄に「YouTube Analytics API で `ids=channel==<channel_id>; filters=video==<id>; dimensions=insightTrafficSourceType` を直接実行」と書く。

## サムネ A/B テスト履歴
| completed_at | result.status | A〜C watch_time_share | 解釈 |
|---|---|---|---|
| … | … | … | 候補間差の根拠 / 明確な差なしの反証 |

## 立てた仮説
1. <主仮説>（根拠: <症状>）
2. <副仮説>（根拠: <症状>）

## 検証ステップ
- [x] <主仮説 1> → `<実行した検証スキル / CLI / API>`
  - 記録: `hypothesis=<仮説>`, `method=<検証手段>`, `period=<対象期間>`
  - 数値: `target_value=<実測>`, `baseline_value=<比較値>`, `threshold=<判定閾値>`
  - 根拠: `evidence_path=<成果物パス>`, `verdict=<支持 / 反証 / 未検証>`
  - 判定: 支持 / 反証 / 未検証（理由: <具体的な理由>）
  - 実行結果: <数値・成果物パスを含む要約>
- [x] <実行した副仮説 1> → `<実行した検証スキル / CLI / API>`（全主仮説が反証された場合）
  - 記録: `hypothesis=<仮説>`, `method=<検証手段>`, `period=<対象期間>`
  - 数値: `target_value=<実測>`, `baseline_value=<比較値>`, `threshold=<判定閾値>`
  - 根拠: `evidence_path=<成果物パス>`, `verdict=<支持 / 反証 / 未検証と理由>`
  - 判定: 支持 / 反証 / 未検証（理由: <具体的な理由>）
  - 実行結果: <数値・成果物パスを含む要約>
- [ ] <未実行の副仮説 1> → `N/A`（主仮説に支持または未検証がある場合）
  - 記録: `hypothesis=<仮説>`, `method=<検証手段または N/A>`, `period=<対象期間または N/A>`
  - 数値: `target_value=<実測または N/A>`, `baseline_value=<比較値または N/A>`, `threshold=<判定閾値または N/A>`
  - 根拠: `evidence_path=<成果物パスまたは N/A>`, `verdict=<未検証と理由>`
  - 判定: 未検証（主仮説が支持されたため、または主仮説に未検証があるため）
  - 実行結果: <数値・成果物パスを含む要約、または未実行理由>

## 結論 / 反証 / 学び
- 結論: <支持された仮説、または現時点で原因を特定できないことと理由>
- 反証: <反証された仮説と根拠。該当なしの場合は「反証なし」と理由>
- 学び: <次回の企画・制作・公開へ反映する具体的な学び。断定できない場合は追加で必要なデータ>
```

### Phase 6: insights への還元

Phase 5 で保存した postmortem.md の「結論 / 反証 / 学び」から、次サイクルの企画・制作に効く学びを `data/insights.jsonl` へ還元する。エントリ形式は `.claude/skills/analytics-analyze/references/insights-entry.schema.json` を単一ソースとし、本文で必須キーや enum を再定義しない。

**還元ゲート**: 次をすべて満たす postmortem セクションだけを還元対象にする。満たさない場合は追記せず、「insights 還元なし（理由: <空欄 / 全主仮説が未検証>）」と明示して完了する。

- 「結論 / 反証 / 学び」の 3 項目がすべて記入済みである
- 「学び」が `支持` または `反証` の検証結果に基づいている（`未検証` の仮説だけを根拠にした学びは還元しない）

還元するエントリの規則:

- `source: "postmortem"`、`source_path` に対象 `collections/live/<collection>/20-documentation/postmortem.md`、`status: "open"` で追記する
- `lever` は支持された主仮説カテゴリから対応付ける: サムネ訴求弱 → `thumbnail` / タイトル訴求弱 → `title` / テーマ自体の市場性不足・競合過密ジャンル → `topic` / 中身の弱さ（音源 / 編集 / テーマ） → `bgm` / タイトル・タグ SEO 弱 → `metadata` / それ以外 → `other`
- `evidence` には検証ステップ欄の `target_value` / `baseline_value` / `threshold` など数値根拠を含める
- 追記は append-only とする。既存行の削除・並べ替え・書き換えをしない（`status` / `status_note` の更新は `/collection-ideate` の責務）
- 既存エントリと同旨の `finding` は重複追記しない（同じ postmortem を再実行しても二重還元しない）

追記後（追記 0 件の場合も含め）、次の検証が exit 0 になることを確認してから完了を報告する:

```bash
uv run python3 .claude/skills/analytics-analyze/references/validate_insights.py data/insights.jsonl
```

還元された学びは次サイクルで `/wf-new` が open エントリとして収集し、`/collection-ideate` の企画入力・`/thumbnail`（lever=thumbnail）の制作前参照に使われる。本スキルを `/wf-new` から自動実行することはない（公開済み動画の分析・検証は本スキルの既存責務に残る）。

## 障害時ガイダンス

Phase 4 は子スキル / CLI / API へ委譲する orchestration。個別検証の失敗は postmortem.md に残し、他の検証から切り離す。

| 状況 | 兆候 | 対処 |
|---|---|---|
| データ不足 | 必要な Analytics / benchmark / 対象成果物がない | `未検証（理由: <具体的な理由>）` と記録し、残りの検証を続行 |
| 子スキル失敗 | 子 skill / CLI / API がエラー終了 | エラー要約と成果物の有無を `未検証（理由: <具体的な理由>）` に含め、残りの検証を続行 |
| postmortem.md 保存失敗 | 検証結果を永続化できない | 完了を報告せずエラーで停止し、保存先とエラーを提示 |

## 関連ファイル

- `data/analytics_data_<YYYYMMDD>.json` — `video_analytics[<id>]`（`average_view_duration` / `published_at` / `title`）、`reporting_api.impressions_summary.per_video[]`（`ctr_percentage` / `impressions`）、`reporting_api.impressions_summary.aggregated_ctr_percentage`（チャンネル全体平均 CTR）。`traffic_sources` 欄はチャンネル全体集計のみで per-video シェアは含まない
- `data/benchmark_<YYYYMMDD>.json` — 競合ベンチマーク（`views` / `likes` / `comments` / `duration_display`。CTR / 平均視聴時間は含まれない）
- `collections/live/<collection>/20-documentation/upload_tracking.json` — `complete_collection.video_id`（コレクション → video_id 逆引きにも使用、`agents/_tracking_io.py`（`collection_uploader.py` から分離）の schema_version=3 で生成）
- `collections/live/<collection>/20-documentation/thumbnail-test-history.json` — `/thumbnail-test` が記録する Studio A/B テスト結果。存在時は `.claude/skills/thumbnail-test/references/history-schema.md` で検証してから使用
- `src/youtube_automation/scripts/launch_curve.py` — `yt-launch-curve --video <id>` の出力定義（`target.ratio_vs_median` / `target.quartile_label` / `target.trace[]` / `target.benchmark_median`）
- `src/youtube_automation/utils/launch_curve_analyzer.py` — `compute_benchmark` / `judge_video_vs_benchmark`（p25/p50/p75 四分位）
- `src/youtube_automation/utils/reporting_api.py` — `collect_impressions_summary` / `_aggregate_rows`（`per_video[].ctr_percentage` / `per_video[].impressions` を生成）
- `src/youtube_automation/utils/traffic_source_analytics.py` — `get_traffic_source_analytics`（チャンネル全体集計のみ。per-video filter 非対応）/ `get_traffic_source_detail`（`insightTrafficSourceType` を絞り込みつつチャンネル全体集計で詳細を返す）

## Next Step

postmortem.md 保存後、支持された主仮説と「学び」に基づく改善候補を提示する。以下は検証の再実行手順ではなく、分析完了後の改善候補とする:

| 支持された主仮説カテゴリ | 改善候補 |
|-------------------------|----------|
| サムネ訴求弱 | `/thumbnail-compare` → 必要なら `/thumbnail <collection>` で再生成 |
| タイトル訴求弱 | `/alignment-check` → `config/channel/content.json` の `title.template` を更新 |
| 中身の弱さ | `/video-analyze --source own --collection <name>` |
| ターゲット層ミスマッチ | `/viewer-voice` → `/audience-persona-design` → `/viewing-scene` |
| テーマ自体の市場性不足 | `/discover-competitors` → `/channel-new`（方向性検討モード） |
| 初動エンゲージメント低 | 公開直後のコメント・日次視聴を確認後、必要なら `/comments-reply` をそのスキル固有の明示承認ゲート付きで実行 |

改善策の実行は本スキルの完了条件に含めない。必要なら `/channel-new`（方向性検討モード）でチャンネル全体の方向性を見直す。
