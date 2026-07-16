---
name: flop-analysis
description: "Use when 公開済み動画が伸びなかった原因を video_id、collection、または --since で切り分け、postmortem.md に出力するとき。「伸びなかった」「flop 分析」で発動。横断戦略は /analytics-analyze、事前監査は /alignment-check"
---

## Overview

公開後「思ったより伸びなかった」動画について、Analytics（CTR / 平均視聴時間 / インプレッション）を
過去自チャンネル平均 + 競合ベンチマークと突き合わせ、症状から仮説を立て、検証ステップ（既存スキル）を案内する。
最終出力は `collections/live/<collection>/20-documentation/postmortem.md`。

責務は **症状の定量化 + 仮説リスト生成 + 検証スキル案内** までで、実検証（サムネ比較・タイトル評価・コメント分析等）は既存スキルへバトンする。

## 完了条件

`collections/live/<collection>/20-documentation/postmortem.md` を保存（「結論 / 反証 / 学び」欄は空のまま）し、Phase 4 の検証ステップ一覧をユーザーに提示した時点で完了。実検証の実行は完了条件に含まない。

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
| `ctr_percentage` が自チャンネル `aggregated_ctr_percentage` の `ctr_low` 倍未満 | `impressions` は過去平均同等以上 | サムネ訴求弱 | タイトル訴求弱 / ターゲット層ミスマッチ / 差別化不足 |
| `ctr_percentage` が自チャンネル `aggregated_ctr_percentage` の `ctr_healthy` 倍以上 | `average_view_duration` が自チャンネル中央値の `avd_low` 倍未満 | 中身の弱さ（音源 / 編集 / テーマ） | サムネと中身の不一致 |
| `impressions` が過去平均の `impressions_low` 倍未満 | — | タイトル / タグ SEO 弱 / 初動エンゲージメント低 | 公開時刻ミス / 再生リスト未登録 |
| 全指標が中央値前後（±`neutral_band_pct` %）で `ratio_vs_median < mild` | — | テーマ自体の市場性不足 | 競合過密ジャンル |

閾値は skill-config の恒久上書きとは別に **チャンネル特性に応じて文脈調整可** とする。ただし一時調整して良いのは以下の 3 ケースに限る:

| ケース | 調整内容 |
|--------|---------|
| 新チャンネル（公開 10 本未満 or 開設 30 日未満） | 平均比閾値を ±0.1 まで緩和可 |
| 直近テーマ転換 | 過去平均比較は参考値とし `ratio_vs_median` 系を優先 |
| 外部要因の明確な痕跡 | 該当指標の判定を保留し外部要因を先に記録 |

該当ケースがなければ表の係数をそのまま使う（自由裁量での調整は不可）。調整した場合は、変更前後の閾値と適用したケース名を postmortem.md の「症状サマリー」欄に必ず明示する。

per-video 流入経路シェア（`YT_SEARCH` / `YT_BROWSE` 等）に基づく「YouTube 内露出不足」仮説は、既存データには per-video の `insightTrafficSourceType` が含まれないため Phase 3 では仮説化しない。`impressions` が過去平均の `impressions_low` 倍未満（上表 3 行目）と判定された場合のみ、Phase 4 の検証ステップで per-video の流入経路を YouTube Analytics API に直接問い合わせて切り分ける。

### Phase 4: 検証ステップの案内

仮説ごとに使うべき既存スキル / データを提示する（実検証は本スキルでは行わない）:

| 仮説 | 検証手段 |
|------|---------|
| サムネ訴求弱 | `/thumbnail-compare`（ベンチ並列比較）/ `yt-thumbnail-correlate --metric views`（特徴量と views の相関） |
| サムネ訴求弱（A/B 履歴あり） | `/thumbnail-test` 履歴で `winner` なら候補間差が観測された根拠、`performed_same` / `inconclusive` ならテストした候補間で明確な差を確認できなかった反証として併記。履歴だけで flop 原因を確定しない |
| タイトル訴求弱 | `/alignment-check`（タイトル × サムネ × 音楽の整合性）/ `data/benchmark_*.json` の競合タイトル語彙比較 |
| ターゲット層ミスマッチ | `/viewer-voice` で視聴者コメントの実態確認 → `/audience-persona-design` でペルソナ再評価 → `/viewing-scene` で利用シーン検証 |
| 差別化不足 | `/discover-competitors` で同ジャンル競合棚卸し → `/channel-new`（方向性検討モード）で差別化軸の再定義 |
| 中身の弱さ（音源 / 編集 / テーマ） | `/video-analyze` の `hook_structure` / `bgm_arc` / `scene_timeline` / `editing_metrics` |
| サムネと中身の不一致 | `/video-analyze` の `thumbnail_alignment` / `/alignment-check` |
| SEO / 流入低（per-video 流入経路の確認） | YouTube Analytics API に `ids=channel==<channel_id>`, `filters=video==<video_id>`, `dimensions=insightTrafficSourceType`, `metrics=views,estimatedMinutesWatched` で直接クエリ（既存ヘルパー `get_traffic_source_analytics` はチャンネル全体集計のため使わない）。`YT_SEARCH` の検索キーワード詳細は `utils/traffic_source_analytics.py::get_traffic_source_detail`（チャンネル全体集計だが検索語の傾向把握には使える）/ `data/benchmark_*.json` のタグ語彙 |
| 初動エンゲージメント低 | `/comments-reply` で初動コメント返信 / 公開時刻の見直し（`data/analytics_data_*.json` の `daily_views` トレース） |
| テーマ市場性不足 | `yt-theme-compare` でテーマ別 launch curve 比較 / `/discover-competitors` で隣接ジャンル探索 |
| YouTube 内露出不足 | `yt-channel-trend` で直近のチャンネル全体トレンド確認 / 再生リスト登録状況の確認 |

`/video-analyze` の各出力は動画全尺ではなく冒頭クリップ窓（既定 900 秒、JSON の
`analysis_window_sec`）内の分析結果として扱う。`bgm_arc.outro` や `editing_metrics`
を動画全体の終盤・全尺平均として読まない。

### Phase 5: postmortem.md の生成

出力先は `collections/live/<collection>/20-documentation/postmortem.md`。コレクションを逆引きできない `video_id` は **エラーで停止** し、`<collection>` 引数の指定か `upload_tracking.json` の整備を促す（フォールバック用の新規ディレクトリ規約は作らない）。

既存ファイルがある場合は **追記** する（同コレクション内の別動画は `## Postmortem: <タイトル> (<video_id>)` セクションで分割）。

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

※ per-video 流入経路シェアは既存データに含まれないため症状サマリーには載せない。必要な場合は Phase 4 の検証ステップ欄に「YouTube Analytics API で `filters=video==<id>; dimensions=insightTrafficSourceType` を直接実行」と書く。

## サムネ A/B テスト履歴
| completed_at | result.status | A〜C watch_time_share | 解釈 |
|---|---|---|---|
| … | … | … | 候補間差の根拠 / 明確な差なしの反証 |

## 立てた仮説
1. <主仮説>（根拠: <症状>）
2. <副仮説>（根拠: <症状>）

## 検証ステップ
- [ ] <仮説 1> → `<検証スキル / CLI>`
- [ ] <仮説 2> → `<検証スキル / CLI>`

## 結論 / 反証 / 学び
（検証完了後に運用で記入）
```

「結論 / 反証 / 学び」欄は空のまま出力する（運用記入欄。`TODO:` コメントを入れない）。

## 障害時ガイダンス

次工程は子スキルへ委譲する orchestration。失敗時は委譲先の障害が表面化する。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 委譲先 skill の失敗 | 子 skill がエラー終了 | 各子 skill の「障害時ガイダンス」を参照して個別に対処 |

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

postmortem.md 保存後、Phase 4 で挙がった検証スキルを順次実行する:

| 主仮説カテゴリ | 次に実行するスキル |
|---------------|-------------------|
| サムネ訴求弱 | `/thumbnail-compare` → 必要なら `/thumbnail <collection>` で再生成 |
| タイトル訴求弱 | `/alignment-check` → `config/channel/content.json` の `title.template` を更新 |
| 中身の弱さ | `/video-analyze --source own --collection <name>` |
| ターゲット層ミスマッチ | `/viewer-voice` → `/audience-persona-design` → `/viewing-scene` |
| テーマ市場性不足 | `/discover-competitors` → `/channel-new`（方向性検討モード） |

検証完了後は postmortem.md の「結論 / 反証 / 学び」を埋め、必要なら `/channel-new`（方向性検討モード）でチャンネル全体の方向性を見直す。
