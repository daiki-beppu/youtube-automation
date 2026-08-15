# Analytics analyze mode

## Overview

収集済みの YouTube Analytics データを詳細分析し、データドリブンな改善提案を行います。

## 完了条件

**Hard Gate**: 次のすべてを満たすまで完了としない。

1. `yt-launch-curve --latest` / `yt-channel-trend` / `yt-theme-compare` / `yt-traffic-trend` / `yt-vpd-rank` / `yt-win-pattern` / `yt-ttp-health` を `--text` なしで実行し、7 コマンドすべてが成功している。`yt-vpd-rank` と `yt-win-pattern` は各 1 回だけ実行している
2. 既存分析 4 CLI、`yt-vpd-rank`、`yt-win-pattern`、`yt-ttp-health` の JSON 出力を schema version 3 の「構造化 JSON 契約」に従って `reports/analysis_YYYYMMDD.json` に保存している
3. 「分析項目」の全項目をカバーした schema 準拠 `reports/analysis_YYYYMMDD.json` と同 basename HTML を保存している
4. JSON の evidence に、`yt-ttp-health` を除く 6 CLI **それぞれから少なくとも 1 つの数値**を JSON path と共に保存している
5. ユーザーに JSON / HTML の両パスと要約を提示している
6. `references/analysis-json-validator.md` の validator が、full 収集データに対する構造化 `retention_analysis` と視聴維持率の数値引用を含めて exit 0 になっている
7. 「学びの insights 蓄積」に従い、主要な学びを `data/insights.jsonl` へ `references/insights-entry.schema.json` 準拠で追記し（新規知見が無い場合は「追記 0 件」を明示）、`references/validate_insights.py` が exit 0 になっている

CLI 未実行、終了コード非 0、JSON のパース失敗、6 CLI のいずれかの evidence 欠落、JSON / HTML の片方のみの場合は未完了。鮮度チェックでスキップできるのも、同じ `YYYYMMDD` の schema version 3 の完了条件を満たす JSON / HTML ペアが存在する場合だけで、鮮度内でも schema version 2 は再分析する（スキップ時は insights の再追記も行わない）。

## Subagent 委譲ゲート

メインエージェントは前提確認、鮮度チェック、対象ファイルの選定、成果物存在確認、ユーザーへの短い報告だけを担当する。`data/analytics_data_*.json`、専門 CLI の JSON 出力、`data/video_analysis/` の詳細 JSON はメイン会話で直接 Read せず、分析 subagent へ入力パスとして渡す。

分析 subagent は指定された入力パスを読み、必須 7 CLI を実行し、分析結果を `analysis-report.schema.json` 準拠 candidate JSON に保存する。`summary`、主要指標、VPD/勝ち型比較、evidence 付き示唆、推奨 action を JSON の固定キーへ保存する。既存 4 CLI は `cli_outputs`、VPD 2 CLI はトップレベル `vpd_ranking` / `win_pattern`、`yt-ttp-health` は `ttp_health` へ stdout JSON object を値を変更せず埋め込む。完了報告では `status`、読んだ入力パス、実行した CLI、生成または再利用したレポートパス、主要発見の要約だけを返し、生データ本文や CLI JSON 全文を返さない。メインエージェントは common migration workflow で `reports/analysis_YYYYMMDD.{json,html}` を公開し、`references/analysis-json-validator.md` の validator が exit 0 になることを機械的に確認してから完了を報告する。

## 前提

`config/channel/` が存在すること（`load_config()` でロード可能）。

存在しない場合はここで停止し、ユーザーに確認:
- **新規チャンネル** → `/setup --channel` を案内
- **既存チャンネル**（YouTube で既に運営中）→ `/setup --import` を案内

`config/channel/` が `load_config()` でロード可能になるまで後続手順へ進まない。

## When to Use

- `/analytics --collect` でデータ収集を完了した後
- `/wf-next` 完了（動画公開）から T+7 日後の初週パフォーマンス確認（推奨タイミング）
- 戦略検討のための詳細分析が必要なとき
- CTR 改善やコンテンツ最適化の根拠データが欲しいとき

## Quick Reference

| 引数 | 説明 | 例 |
|------|------|-----|
| `$ARGUMENTS` | 分析本文の対象ファイル指定（省略可） | `/analytics --analyze data/analytics.json` |
| 未指定 | 更新時刻が最新の analytics データファイルを分析本文の対象にする | `/analytics --analyze` |

`$ARGUMENTS` は分析本文の対象だけを指定する。必須 4 CLI には入力ファイル指定オプションがないため、引数の有無にかかわらず各 CLI が実装上選択する最新スナップショットを使う。分析本文の対象と CLI 入力は混同せず、構造化 JSON の `inputs.analysis_target` と `inputs.cli_selected` に分けて記録する。

## Instructions

あなたは YouTube Analytics エキスパートです。`config/channel/content.json` の `genre` セクションからチャンネルのジャンル・コンテキストを読み取り、そのチャンネルに最適化された分析を行います。

### 鮮度チェック（並列実行対応）

しきい値は `/analytics --collect` の skill-config が単一ソース。まず以下を Read（Codex では同等のファイル閲覧）で開き、`freshness_minutes`（既定 30 分）を確定する:

1. `.claude/skills/analytics/config.default.yaml`
2. `config/skills/analytics.yaml`（存在する場合。deep-merge でチャンネル上書きを優先）

分析実行前に `reports/` 配下の最新レポートを確認する:
- `freshness_minutes` 分以内に生成された同日付の `analysis_YYYYMMDD.json` / `.html` ペアがあり、JSON schema と `references/analysis-json-validator.md` の validator が exit 0 の場合だけ分析をスキップし、AI入力には JSON だけを使用
- スキップ時: 「既存レポートが十分新しいため分析をスキップしました（`<filename>`、`<N>`分前に生成）」と表示

### 対象データ

```
$ARGUMENTS
```

引数が指定されている場合はそのファイルを、未指定の場合は `data/analytics_data_*.json` のうち更新時刻が最新のファイル（`ls -t data/analytics_data_*.json | head -1` で取得できるもの）を分析本文の対象として subagent に渡す。

これとは別に、必須 4 CLI が実際に読むファイルを、各 CLI の実装と同じ辞書順で実行前に確定する。

- `data/analytics_data_*.json` の辞書順末尾: 4 CLI 共通の入力（`yt-traffic-trend` はシェア推移のため過去スナップショット群も読むが、`cli_selected` に記録するのは辞書順末尾の 1 件だけ）
- `data/analytics/daily_per_video/*.json` の辞書順末尾: `yt-launch-curve` / `yt-theme-compare` の入力
- `config/channel/content.json`: `yt-theme-compare` のテーマ定義

分析本文の対象または CLI の必須入力が存在しない場合は未完了として中断する。`$ARGUMENTS` で指定した分析対象が CLI 入力と異なる場合も許容するが、同じ入力から得た数値であるかのように記述しない。メインエージェントは対象ファイルの中身を直接 Read せず、確定した各パスを subagent に渡す。

### 分析委譲プロンプト要件

subagent へは次を具体値で渡す:

- 入力パス: 分析本文の対象、CLI が選択する `data/analytics_data_*.json` と `data/analytics/daily_per_video/*.json`、`config/channel/content.json`、存在する場合は `data/video_analysis/<slug>/<video_id>.json`
- 実行する作業: 「分析項目」の全項目をカバーする分析と、必須の `yt-launch-curve --latest` / `yt-channel-trend` / `yt-theme-compare` / `yt-traffic-trend` / `yt-vpd-rank` / `yt-win-pattern` / `yt-ttp-health`
- VPD 中間成果物: `reports/analysis_YYYYMMDD.vpd-ranking.json` / `.visual-annotations.json` / `.win-pattern.json`。最初の JSON は `yt-vpd-rank` stdout、最後は `yt-win-pattern` stdout を直接 capture する
- 目視分類: captured ranking の top / bottom 全動画を `/channel-research --thumbnail` と同じ構図 / 配色 / テキスト配置 / 視線誘導 / キャラ・被写体の 5 軸で分類する。同じ captured JSON の `video_id` だけを使い、観測不能は推測せず JSON `null` にする
- 期待成果物: 同じ日付の `reports/analysis_YYYYMMDD.json` と `reports/analysis_YYYYMMDD.html`
- 完了報告: `status: success | failure`、`inputs`、`commands`、`artifacts`、`summary`、`errors`

#### VPD snapshot と目視 annotation の固定手順

分析 subagent は同じ `YYYYMMDD` を使い、次の順序を変えない。各 CLI 行は再試行を含めて **成功した 1 回だけ**を採用し、失敗時は途中成果物をレポートへ埋め込まず未完了にする。

```bash
vpd_ranking_path="reports/analysis_YYYYMMDD.vpd-ranking.json"
visual_annotations_path="reports/analysis_YYYYMMDD.visual-annotations.json"
win_pattern_path="reports/analysis_YYYYMMDD.win-pattern.json"

uv run yt-vpd-rank >"$vpd_ranking_path"
jq -e 'type == "object"' "$vpd_ranking_path" >/dev/null

# この間に captured ranking の groups.top.items / groups.bottom.items だけを目視分類し、
# 下記契約の visual_annotations_path を生成する。

uv run yt-win-pattern \
  --ranking "$vpd_ranking_path" \
  --annotations "$visual_annotations_path" \
  >"$win_pattern_path"
jq -e 'type == "object"' "$win_pattern_path" >/dev/null
```

annotation は `{"videos": [...]}` のみを root に持ち、top / bottom の各 `video_id` を重複なく 1 件ずつ含める。各要素は `video_id` と `composition` / `color` / `text_placement` / `visual_flow` / `subject` の 5 キーを必須とし、観測できた分類値は空でない文字列、観測不能は `null` とする。中間群や captured ranking 外の ID は入れない。`yt-win-pattern` は `null` を `undetermined` として集計するため、`other` や推測値で補わない。

### 分析項目

以下の全項目をカバーする。各項目は `/wf-new` の企画立案と `/thumbnail` でのCTR最適化に直接活用されるため、断片的な分析では後続ステップの品質が下がる:

1. **CTR 改善戦略分析**: 高CTRコンテンツの特徴分析、サムネイル・タイトル最適化提案 — サムネイル制作の方向性決定に直結
2. **チャンネル特化パフォーマンス分析**: コレクション別比較、テーマ別パフォーマンス — 次期テーマ選定の根拠データ
3. **戦略的改善提案**: 上位動画の共通成功要因、直近投稿の動向分析、次期コレクション企画推奨 — `/wf-new` 企画工程の入力データ
4. **具体的アクションプラン**: CTR 達成のための具体的施策 — 即実行可能なアクションに落とし込む
5. **視聴維持率分析**: full 収集データでは `references/analysis-json-validator.md` の retention 契約に従って全有効動画を比較し、「中身の弱さ」仮説を数値根拠で評価する。standard データでは推測で補わず、full 収集が必要と明記する
6. **流入源・デバイス分析**: `yt-traffic-trend` の出力から流入源シェア（ブラウズ / 検索 / 外部等）の構成と推移、デバイス別視聴傾向、YT_SEARCH 検索語トップ N を数値根拠付きで分析する — SEO 施策・企画判断と `/wf-new` / `/video --describe` への接続データ。`search_terms` が空の場合は推測で補わず、`yt-analytics` での再収集が必要と明記する
7. **収益・RPM 分析**: `revenue_analytics.status == "available"` の場合、`video_analytics` のタイトルと `config/channel/content.json::tags.themes` を使ってテーマ別・コレクション別に `estimated_revenue` と `views` を合計し、加重 RPM（`収益合計 / 再生合計 * 1000`）を算出する。動画別 RPM の単純平均は使わない。各グループの収益・再生・RPM・対象動画数を JSON `revenue_analysis` に記録し、企画判断へ接続する。`status == "unavailable"` または旧データで `revenue_analytics` が無い場合は推測せず状態を保存する
8. **プレイリスト効果分析**: JSON の `playlist_analytics.playlists` から、視聴数上位 200 件のプレイリスト別の views・`view_share_percent`・`average_view_duration` を表で報告する。`view_share_percent` は上位 200 件内のシェアであり、チャンネル全体に対するシェアとして扱わない。`config/channel/playlists.json` と照合できる ID は名前／キーを併記し、Complete Collection を識別する。未登録 ID は ID のまま明記する。views とシェアはプレイリスト内視聴の多寡を示す観測値であり、概要欄・固定コメントなどの導線施策が原因であるとは断定しない。データ欠損・0件時はその旨を記載し、再収集を案内する。
9. **登録を生む動画の型**: `strategic_analysis.subscriber_conversion_ranking` の動画別登録転換率（`subscribers_gained ÷ views × 100`）上位を、タイトル・説明文からのテーマ、`duration`、`views`、`subscribers_gained` とともに要約する。`audience.by_subscribed_status` の登録済み／未登録の視聴比率を併記し、未登録視聴が多いのに転換率が低いのか、登録済み視聴が中心なのかを切り分けて次企画の仮説を示す。サムネイル傾向は動画 URL の実画像または `yt-thumbnail-correlate` の根拠を確認できた場合だけ記述する。`subscribedStatus` はチャンネル全体集計であり、個別動画の転換原因とは断定しない。`views` が 0 の動画の転換率は 0% として扱う。
10. **VPD 上位 / 下位の定量比較**: `vpd_ranking` の N / K と上位・下位動画、`win_pattern` の属性値別本数・known denominator の割合・pp 差・勝ち / 負け / 保留を記載する。目視属性の `undetermined` は判定不能として exact 件数を JSON path 付きで引用する。この母集団で観測した相関であり因果ではない旨を明記する。

### pandas ベースの詳細分析 CLI (v1.3+)

静的な `analytics_data_*.json` だけでなく、以下の専門 CLI を積極的に活用すること。デフォルト出力は AI 消費向け JSON で、`--text` フラグで人間向けサマリーに切替:

- **`yt-launch-curve --latest`**: 新作動画の投稿後 N 日時点のパフォーマンスを、過去動画の同日齢ベンチマーク (p25/p50/p75) と比較。判定・`trace`・`all_videos` ランキングを返す。新作の初速評価や「過去の成功パターン vs 今の初速」の判断に必須。
- **`yt-channel-trend`**: 日次 views/subs の移動平均、週次集計、前週比、z-score ベースの異常検知 (spike/dip)、up/flat/down トレンド判定。直近の勢い判断・バズ日特定に使う。
- **`yt-theme-compare`**: `config/channel/content.json::tags.themes`（コードからは `load_config().content.tags.themes`）のキーワードでタイトル分類し、各テーマの平均 launch curve・ピーク日齢平均・初速最強/ロングテール最強テーマを返す。テーマ選定の根拠データ。
- **`yt-traffic-trend`**: `data/analytics_data_*.json` スナップショット横断の流入源シェア推移（前スナップショット比の `share_delta` 含む）、最新のデバイス別集計、YT_SEARCH 検索語トップ N（`--top-search N`、default 10）を返す。流入構成の変化検知・SEO キーワード判断に必須。
- **`yt-ttp-health`**: 最新 `benchmark_YYYYMMDD.json` の pre-filter 投稿走査から、TTP 対象ごとの投稿停滞・再生低下・データ不足・入力欠損を返す。stdout JSON は変更せずトップレベル `ttp_health` へ保存する。
- **`yt-vpd-rank`**: 全動画を累計再生回数 / UTC 公開日齢の VPD で並べ、上位 / 中間 / 下位群を返す。1 回だけ実行し、stdout を同日付 captured artifact とトップレベル `vpd_ranking` へ変更せず保存する。
- **`yt-win-pattern`**: captured ranking と目視 annotation を受け、機械属性と目視 5 属性の本数・割合・pp 差・判定を返す。`--ranking` / `--annotations` で同じ snapshot を渡して 1 回だけ実行し、stdout を同日付 captured artifact とトップレベル `win_pattern` へ変更せず保存する。
- **`yt-thumbnail-correlate`**: サムネ画像の特徴量 (brightness/contrast/saturation/dominant_hue/colorfulness) と CTR/views/engagement の Pearson 相関。`--metric` 未指定なら CTR 欠測時に views へ自動フォールバックし、出力 JSON の `metric_fallback` に理由が残る。各相関には `p_value` / `p_value_adjusted`（Benjamini-Hochberg 補正）/ `significant` が付く。**`significant: false` の相関を方針の根拠に使わないこと**（引用時は「有意でない」と明記）。`note: "サンプル不足で判定不能"`（n<10）は判断材料にしない。次回サムネ制作の方向性。
- **`yt-kpi-dashboard`**: 成長 KPI 定点ビュー。`data/analytics_data_*.json` 全スナップショットを横断し、レバー別 KPI（views / Imp / CTR / 平均視聴維持率 / 登録者純増）の週次推移を前週比付きで返す。Reporting API の保持期間（60 日）を超えた過去の Imp / CTR も時系列に含まれ、欠測週は補間せず明示される。週次運用ループの冒頭で「どのレバーが先週動いたか」を 1 枚で確認し、深掘り対象の選定に使う（`--markdown` でテーブル表示、`--save` で `reports/kpi_weekly_YYYYMMDD.{json,md}` 保存）。`yt-channel-trend` が最新スナップショット 1 件の日次系列を見るのに対し、こちらはスナップショット横断の週次俯瞰。

subagent はこれらの出力 JSON を分析の根拠として使い、「数値 (例: 中央値比 6.3倍)」を含む主張を JSON evidence として保存する。形式は `references/analysis-json-validator.md` に従う。ただしメインエージェントへ返す完了報告には JSON 全文を含めず、レポートパスと主要数値の要約に絞る。

### 構造化 JSON 契約

構造、固定キー、evidence、検証コマンドは `references/analysis-json-validator.md` を単一ソースとする。`schema_version` は `3` とする。既存分析 4 CLI は `--text` を付けずに実行し、終了コード 0 の stdout をキー名や値を変更せず対応する `cli_outputs` キーに保存する。`yt-vpd-rank` / `yt-win-pattern` の stdout object も再構成せずトップレベル `vpd_ranking` / `win_pattern` に保存し、captured artifact と JSON 等価にする。`yt-ttp-health` も stdout を変更せずトップレベル `ttp_health` に保存する。入力がなく `status: unavailable` の場合も `ttp_health` 自体は省略しない。標準エラー出力、`--text` 出力、失敗した CLI の出力は保存対象にしない。

JSON の `ttp_health` に alert type / reason と不足理由を保存する。`status: unavailable` の場合は欠損を健全として扱わず、推奨 action に `/channel-research --benchmark` の再実行を含める。

成果物保存後に同 reference の検証手順を実行し、すべて成功した場合だけ完成扱いにする。戦略提案・次期候補・戦略ディスカッションの正本は JSON の `strategic_improvements` / `next_collection_candidates` / `strategic_discussion` とする。HTML は common renderer の派生成果物であり、後続スキルは JSON 固定キーだけを使用する。

`inputs` にはプレースホルダーではなく相対パスを保存する。`analysis_target` は `$ARGUMENTS` または更新時刻で選んだ分析本文の対象、`supplemental` は分析本文が実際に読み込んだ `data/video_analysis/` などの追加 JSON とする。`cli_selected` は既存 4 CLI の**直接分析入力 3 件**（最新 `data/analytics_data_*.json`、最新 `data/analytics/daily_per_video/*.json`、テーマ定義元 `config/channel/content.json`）だけを記録し、その既存の意味を変えない。VPD の captured ranking / annotation / win stdout は `inputs.intermediate` の 3 固定キーへ分離する。`yt-theme-compare` の `load_config()` が間接的にロードする他の `config/channel/*.json` や `config/localizations.json`、`yt-traffic-trend` がシェア推移のために読む過去の `data/analytics_data_*.json` スナップショット群は `cli_selected` に含めない。既存 4 CLI を再実行するときに異なる最新ファイルへ進んでしまわないよう、CLI 実行直後に確定済みパスが引き続き各ディレクトリの辞書順末尾であることを再確認する。変わっていた場合はその出力を保存せず、入力選定からやり直す。

### 分析品質基準

- 相関と因果の区別を明確にする
- 推奨事項に確信度を付記する
- データが不完全な場合は明示する
- 業界標準とチャンネル固有のベースラインを比較する

### 出力スタイル

- 具体的かつ実用的な改善策を含める
- データ可視化の概念を用いてトレンドを説明する

### レポート保存

subagent は分析結果を公開先と別の candidate JSON に保存する（チャンネル横断レポート）。公開先の同日付 `.md` だけが存在する場合は candidate 生成前に移行の Yes/No を利用者へ明示確認し、No なら既存 Markdown を変更せず停止する。Yes なら `--migration-decision yes`、新規または移行済み更新なら decision なしで次を実行する。

```bash
uv run yt-document-migrate <candidate.json> \
  --target reports/analysis_YYYYMMDD.json \
  --schema analysis-report.schema.json \
  [--migration-decision yes]
```

メインエージェントは同 basename JSON+HTML の存在・再読込・対応関係を確認し、`references/analysis-json-validator.md` の validator が exit 0 になることを機械的に確認する。schema 不正、stale/mismatched HTML、validator 失敗は未完了とし、JSON だけを後続 AI input とする。

このファイルは **`/wf-new` 企画工程の前提必須入力**として読まれる。企画工程の Phase 1-2 で
以下のセクションが重視される（内容で認識、番号は目安）:

- **§ 5 戦略的改善提案** — CTR 改善・コンテンツ最適化の方向性
- **§ 6 推奨される次期コレクション候補** — データから導出されたテーマ候補
- **§ 8 戦略ディスカッション** — 長期視点の示唆

個別コレクションの振り返りメモが必要な場合は、`20-documentation/` に任意で
追記してよい（`/wf-new` の入力にはならない）。

### 学びの insights 蓄積

レポート保存の検証（validator exit 0）後、subagent は次サイクルの企画・制作に効く主要な学びを `data/insights.jsonl` へ追記する。エントリ形式は `references/insights-entry.schema.json` を単一ソースとし、本文で必須キーや enum を再定義しない。この節は `source: "analysis"` の書き手契約であり、判定済み単一変数実験は `yt-experiment judge` が `source: "experiment"` として同じ schema へ exactly-once 還流する。

- 抽出元は構造化 JSON の固定キー `strategic_improvements` / `next_collection_candidates` / `strategic_discussion` とし、そこから次の制作行動に直結する学びを 1〜5 件に絞る。Markdown 本文からの再抽出はしない
- 各エントリは `source: "analysis"`、`source_path` に同日付の `reports/analysis_YYYYMMDD.json`、`status: "open"` で追記する。`evidence` には `<JSON ファイル名>#<json_path> = <value>` 形式の数値引用を最低 1 つ含める
- `lever` は学びが効く制作レバー（thumbnail / title / topic / bgm / metadata / other）へ内容から分類する
- 追記は append-only とする。既存行の削除・並べ替え・書き換えをしない（`status` / `status_note` の更新は読み手スキル `/wf-new` の責務であり、本スキルでは行わない）
- 既存エントリと同旨の `finding` は重複追記しない。新規知見が無い場合は追記 0 件とし、完了報告に「insights 追記なし（既存と同旨）」と明示する

追記後（追記 0 件の場合も含め）、メインエージェントが次の検証を実行し、exit 0 を確認してから完了を報告する:

```bash
uv run python3 .claude/skills/analytics/references/validate_insights.py data/insights.jsonl
```

validator が失敗した場合は未完了として扱い、不正エントリを修正してから再検証する。鮮度チェックで分析をスキップした場合は、同日の分析で追記済みのため insights を再追記しない。

## 障害時ガイダンス

分析 subagent は `data/` の収集済みスナップショットを読むため通常は外部 API を呼ばない。再収集が必要なときのみ以下が該当する。

| 状況 | 兆候 | 対処 |
|---|---|---|
| 入力データ不在 | `data/` のベンチマーク/Analytics スナップショットが無い | 先に `/channel-research --benchmark`・`/analytics --collect` 等を実行して入力を用意 |
| OAuth 未認証/失効 | `infrastructure.auth.youtube` の `FileNotFoundError`（`client_secrets.json` 不在）/ `AuthError` / HTTP 403 | 初回認証フローを再実行。403 が続く場合は `auth/token.json` を削除しスコープを確認のうえ再認証 |

## Next Step

分析完了後:
- `/wf-new` がデータに基づくコレクション企画を生成

## 関連ファイル

- `data/video_analysis/<slug>/<video_id>.json` — `/audit --video` の `scene_timeline` 出力（retention drop と動画展開のクロス参照に使う）
  - 冒頭クリップ窓（既定 900 秒、JSON の `analysis_window_sec`）内の分析結果。retention drop との照合では、窓外の全尺展開を推測しない。
