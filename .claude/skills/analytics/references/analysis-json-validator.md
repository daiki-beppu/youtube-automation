# Analysis JSON validator

`/analytics --analyze` が生成し、`/wf-new` が読む `reports/analysis_YYYYMMDD.json` の機械検証はこのファイルを単一ソースとする。

## 構造化 JSON 契約

```json
{
  "schema_version": 3,
  "generated_at": "2026-07-13T03:34:56Z",
  "summary": "主要指標・比較・示唆のサマリ",
  "inputs": {
    "analysis_target": "data/analytics_data_YYYYMMDD_HHMMSS.json",
    "cli_selected": [
      "data/analytics_data_YYYYMMDD_HHMMSS.json",
      "data/analytics/daily_per_video/YYYY-MM-DD_to_YYYY-MM-DD.json",
      "config/channel/content.json"
    ],
    "supplemental": [],
    "intermediate": {
      "vpd_ranking": "reports/analysis_YYYYMMDD.vpd-ranking.json",
      "visual_annotations": "reports/analysis_YYYYMMDD.visual-annotations.json",
      "win_pattern": "reports/analysis_YYYYMMDD.win-pattern.json"
    }
  },
  "commands": {
    "launch_curve": "uv run yt-launch-curve --latest",
    "channel_trend": "uv run yt-channel-trend",
    "theme_compare": "uv run yt-theme-compare",
    "traffic_trend": "uv run yt-traffic-trend",
    "vpd_ranking": "uv run yt-vpd-rank",
    "win_pattern": "uv run yt-win-pattern --ranking reports/analysis_YYYYMMDD.vpd-ranking.json --annotations reports/analysis_YYYYMMDD.visual-annotations.json"
  },
  "vpd_ranking": {"n": 4, "k": 1, "ranking": [], "groups": {}},
  "win_pattern": {"n": 4, "k": 1, "attributes": {}, "disclaimer": "Observed correlation in this VPD-ranked population; correlation does not imply causation."},
  "cli_outputs": {
    "launch_curve": {"target": {"ratio_vs_median": 1.42}},
    "channel_trend": {"summary": {"wow_growth_rate": 8.5}},
    "theme_compare": {"themes": [{"day7_mean": 1234.0}]},
    "traffic_trend": {"summary": {"top_source_share_percent": 45.2}}
  },
  "ttp_health": {
    "status": "ok",
    "source": "benchmark_20260715.json",
    "reference_date": "2026-07-15",
    "thresholds": {"stale_days": 60, "decline_ratio": 0.5, "window_days": 90},
    "channels": [
      {
        "slug": "rival-channel",
        "name": "Rival Channel",
        "channel_id": "UC123",
        "status": "alert",
        "last_upload_at": "2026-04-20",
        "days_since_last_upload": 86,
        "recent_window": {"start": "2026-04-16", "end": "2026-07-15", "video_count": 0, "avg_views": null},
        "prior_window": {"start": "2026-01-16", "end": "2026-04-15", "video_count": 8, "avg_views": 42000},
        "alerts": [{"type": "stale_posting", "reason": "最終投稿から 86 日経過（閾値 60 日）"}],
        "insufficiencies": []
      }
    ]
  },
  "retention_analysis": {
    "source": "data/analytics_data_YYYYMMDD_HHMMSS.json",
    "unit": "ratio",
    "hypothesis_evaluation": "supported",
    "summary": "中盤の低下が中身の弱さ仮説を支持する。",
    "videos": [
      {
        "retention_index": 0,
        "video_id": "VIDEO_ID",
        "average_retention": 0.62,
        "midpoint_retention": 0.55,
        "drop_point_index": 4,
        "drop_point": {"elapsed_ratio": 0.5, "watch_ratio": 0.55}
      }
    ]
  },
  "revenue_analysis": {
    "status": "available",
    "currency": "USD",
    "themes": [
      {"name": "Fantasy", "estimated_revenue": 31.0, "views": 5000, "rpm": 6.2, "video_count": 2}
    ],
    "collections": [
      {"name": "Complete Collection", "estimated_revenue": 31.0, "views": 5000, "rpm": 6.2, "video_count": 2}
    ]
  },
  "ctr_strategy": [],
  "channel_performance": [],
  "strategic_improvements": [
    {
      "statement": "<改善提案>",
      "evidence": [
        {"source": "launch_curve", "json_path": "$.cli_outputs.launch_curve.target.ratio_vs_median", "value": 1.42}
      ],
      "confidence": "high"
    }
  ],
  "next_collection_candidates": [
    {
      "statement": "<候補とその理由>",
      "evidence": [
        {"source": "theme_compare", "json_path": "$.cli_outputs.theme_compare.themes[0].day7_mean", "value": 1234.0}
      ],
      "confidence": "medium"
    }
  ],
  "action_plan": [],
  "strategic_discussion": [
    {
      "statement": "<長期視点の示唆>",
      "evidence": [
        {"source": "channel_trend", "json_path": "$.cli_outputs.channel_trend.summary.wow_growth_rate", "value": 8.5}
      ],
      "confidence": "low"
    }
  ]
}
```

- `cli_outputs` の 4 キーには既存 4 CLI の stdout JSON object を変更せず保存する
- `vpd_ranking` / `win_pattern` には対応する CLI の stdout JSON object を変更せず保存する。stdout はそれぞれ `inputs.intermediate.vpd_ranking` / `inputs.intermediate.win_pattern` にも capture し、validator が JSON object の等価性を確認する
- `inputs.intermediate.visual_annotations` は、同じ captured ranking の top / bottom 全動画を目視 5 属性で分類した JSON とする。観測不能値は `null` とし、`yt-win-pattern` の `undetermined` 集計へ渡す
- `ttp_health` には `uv run yt-ttp-health` の stdout JSON object を変更せず保存する。benchmark 入力がない場合もキーを省略せず、CLI が返す `{"status":"unavailable", ...}` を保存する
- 戦略提案・次期候補・戦略ディスカッションの正本は `strategic_improvements` / `next_collection_candidates` / `strategic_discussion` とする。HTML は schema `x-view` から生成する派生成果物であり、後続スキルはこの 3 固定キーから提案を読む
- 固定キーの各要素は、空でない `statement`、1 件以上の `evidence`、`high` / `medium` / `low` の `confidence` を持つ
- `generated_at` は UTC の `YYYY-MM-DDTHH:MM:SSZ` 形式で保存する
- `inputs.analysis_target` / `inputs.supplemental` には分析本文が実際に読み込んだファイルの相対パスを保存する。既存の意味を変更せず、中間成果物 3 件は `inputs.intermediate` に分離して保存する
- `inputs.cli_selected` は、必須 4 CLI が直接選択する分析入力 3 件（最新 `data/analytics_data_*.json`、最新 `data/analytics/daily_per_video/*.json`、テーマ定義元 `config/channel/content.json`）だけを保存する。`yt-theme-compare` の `load_config()` が間接的にロードする他の `config/channel/*.json` や `config/localizations.json`、`yt-traffic-trend` がシェア推移のために読む過去の `data/analytics_data_*.json` スナップショット群は含めない
- `inputs.analysis_target` の `collection_depth` が `full` の場合、`retention_analysis` を必須とする。`source` は `inputs.analysis_target` と一致させ、単位は入力値と同じ `ratio`、仮説評価は `supported` / `not_supported` / `inconclusive` のいずれかとする
- `retention_analysis.videos[]` は `error` がなく、`data_points > 0` かつ空でない `retention_curve` を持つ実測データだけを対象にする。対象 index、video_id、average / midpoint、curve 低下点の index と値は入力 JSON の実値に一致させる
- `retention_analysis` には入力パス、単位、仮説評価、対象動画、average / midpoint / curve 低下点を構造化して保存し、HTML はその JSON だけから表示する
- `inputs.analysis_target` の `collection_depth` が `standard` の場合は `retention_analysis` を捏造せず、HTML 表示でも入力不足として扱う
- `inputs.analysis_target.revenue_analytics.status` が `available` の場合は `revenue_analysis.status` も `available` とし、`themes` / `collections` の各行に `name` / `estimated_revenue` / `views` / `rpm` / `video_count` を保存する。RPM は各グループの `estimated_revenue / views * 1000` で算出し、動画別 RPM の単純平均は使わない
- 収益データが `unavailable` の場合は `revenue_analysis.status: "unavailable"`、旧スナップショットで収益キーが無い場合は `revenue_analysis.status: "not_collected"` とする。どちらも `themes` / `collections` は空配列にし、推測値を保存しない
- `revenue_analysis` は常に状態を持ち、利用可能ならテーマ別・コレクション別集計、利用不可ならその状態を JSON に保存する

## 実行

`analysis_json` と `analysis_html` に同日付ペアの実在パスを設定し、次を一つの Bash セッションで実行する。全コマンドが exit 0 の場合だけ構造化 JSON 契約を満たす。exit 非 0 の場合は成果物として使用しない。

```bash
analysis_json="reports/analysis_YYYYMMDD.json"
analysis_html="reports/analysis_YYYYMMDD.html"

set -euo pipefail

analysis_json_name=$(basename "$analysis_json")
analysis_html_name=$(basename "$analysis_html")
printf '%s\n' "$analysis_json_name" | grep -Eq '^analysis_[0-9]{8}\.json$'
printf '%s\n' "$analysis_html_name" | grep -Eq '^analysis_[0-9]{8}\.html$'
analysis_json_date=$(printf '%s\n' "$analysis_json_name" | grep -oE '[0-9]{8}')
analysis_html_date=$(printf '%s\n' "$analysis_html_name" | grep -oE '[0-9]{8}')
test "$analysis_json_date" = "$analysis_html_date"

jq -e '
  def nonempty_string:
    type == "string" and length > 0;

  def nonempty_object:
    type == "object" and length > 0;

  def repository_relative_path:
    nonempty_string
    and (startswith("/") | not)
    and (split("/") | all(.[]; . != ".."));

  def path_parts:
    [scan("\\.([A-Za-z0-9_-]+)|\\[([0-9]+)\\]")
     | if .[0] != null then .[0] else (.[1] | tonumber) end];

  def evidence_ok($root):
    . as $e
    | (type == "object")
      and ($e.source | IN("launch_curve", "channel_trend", "theme_compare", "traffic_trend", "vpd_ranking", "win_pattern"))
      and ($e.json_path | type == "string")
      and ($e.json_path | test("^\\$\\.(cli_outputs\\.(launch_curve|channel_trend|theme_compare|traffic_trend)|(vpd_ranking|win_pattern))(\\.[A-Za-z0-9_-]+|\\[[0-9]+\\])+$"))
      and (if ($e.source | IN("vpd_ranking", "win_pattern")) then
             ($e.json_path | startswith("$.\($e.source)."))
           else
             ($e.json_path | startswith("$.cli_outputs.\($e.source)."))
           end)
      and ($e.value | type == "number")
      and (($e.json_path | path_parts) as $parts
           | (try ($root | getpath($parts)) catch null) as $actual
           | ($actual | type == "number") and ($actual == $e.value));

  def fixed_item_ok($root):
    . as $item
    | (type == "object")
      and ($item.statement | nonempty_string)
      and ($item.confidence | IN("high", "medium", "low"))
      and ($item.evidence | type == "array" and length > 0)
      and ($item.evidence | all(.[]; evidence_ok($root)));

  def ttp_alert_ok:
    (type == "object")
    and (.type | IN("stale_posting", "views_decline"))
    and (.reason | nonempty_string);

  def ttp_channel_ok:
    (type == "object")
    and (.status | IN("healthy", "alert", "insufficient_data", "missing_data"))
    and (.alerts | type == "array")
    and (.insufficiencies | type == "array")
    and (if .status == "alert" then (.alerts | length > 0) else true end)
    and (.alerts | all(.[]; ttp_alert_ok));

  def ttp_health_ok:
    (type == "object")
    and (.status | IN("ok", "unavailable"))
    and (.channels | type == "array")
    and (if .status == "unavailable" then
           (.reason | nonempty_string)
         else
           (.source | nonempty_string)
           and (.reference_date | nonempty_string)
           and (.thresholds | type == "object")
           and (.channels | all(.[]; ttp_channel_ok))
         end);

  def all_evidence($root):
    [(($root.strategic_improvements[],
       $root.next_collection_candidates[],
       $root.strategic_discussion[]) | .evidence[])];

  def integer:
    type == "number" and . >= 0 and . == floor;

  def ranking_item_ok:
    (type == "object")
    and (.video_id | nonempty_string)
    and (.cumulative_views | integer)
    and (.days_since_publish | integer and . >= 1)
    and (has("duration"))
    and ((.duration == null) or (.duration | nonempty_string))
    and (.vpd | type == "number");

  def vpd_ranking_ok:
    . as $ranking
    | ($ranking | type == "object")
      and ($ranking.n | integer and . >= 2)
      and ($ranking.k | integer and . >= 1 and . <= (($ranking.n / 2) | floor))
      and ($ranking.ranking | type == "array" and length == $ranking.n and all(.[]; ranking_item_ok))
      and (($ranking.ranking | map(.video_id)) as $ids | ($ids | unique | length) == ($ids | length))
      and ($ranking.groups | type == "object")
      and (["top", "middle", "bottom"] | all(.[];
            . as $name
            | ($ranking.groups[$name] | type == "object")
              and ($ranking.groups[$name].items | type == "array")
              and ($ranking.groups[$name].count == ($ranking.groups[$name].items | length))
              and ($ranking.groups[$name].items | all(.[]; ranking_item_ok))))
      and ($ranking.groups.top.count == $ranking.k)
      and ($ranking.groups.bottom.count == $ranking.k)
      and ($ranking.groups.middle.count == ($ranking.n - (2 * $ranking.k)))
      and (([$ranking.groups.top.items[], $ranking.groups.middle.items[], $ranking.groups.bottom.items[]]
            | map(.video_id)) == ($ranking.ranking | map(.video_id)));

  def automatic_attributes:
    ["theme", "title_pattern", "duration", "publish_weekday", "publish_time"];

  def visual_attributes:
    ["composition", "color", "text_placement", "visual_flow", "subject"];

  def attribute_population_ok($summary; $k):
    ($summary | type == "object")
    and ($summary.top_known_count | integer)
    and ($summary.bottom_known_count | integer)
    and ($summary.undetermined_count | type == "object")
    and ($summary.undetermined_count.top | integer)
    and ($summary.undetermined_count.bottom | integer)
    and ($summary.values | type == "object")
    and (($summary.top_known_count + $summary.undetermined_count.top) == $k)
    and (($summary.bottom_known_count + $summary.undetermined_count.bottom) == $k);

  def win_pattern_ok($ranking):
    . as $win
    | (type == "object")
      and (.n == $ranking.n)
      and (.k == $ranking.k)
      and (.attributes | type == "object")
      and (($win.attributes | keys | sort) == ((automatic_attributes + visual_attributes) | sort))
      and ((automatic_attributes + visual_attributes)
           | all(.[]; . as $name | attribute_population_ok($win.attributes[$name]; $ranking.k)))
      and (["theme", "title_pattern", "publish_weekday", "publish_time"]
           | all(.[]; . as $name
             | ($win.attributes[$name].top_known_count == $ranking.k)
               and ($win.attributes[$name].bottom_known_count == $ranking.k)))
      and ($win.attributes.duration.undetermined_count.top
           == ([$ranking.groups.top.items[] | select(.duration == null)] | length))
      and ($win.attributes.duration.undetermined_count.bottom
           == ([$ranking.groups.bottom.items[] | select(.duration == null)] | length))
      and (($win.attributes.duration.top_known_count + $win.attributes.duration.bottom_known_count) > 0)
      and (.disclaimer | type == "string")
      and (.disclaimer | test("correlation"; "i"))
      and (.disclaimer | test("causation"; "i"));

  . as $root
  | (type == "object")
    and (.schema_version == 3)
    and (.generated_at | type == "string")
    and (.generated_at | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"))
    and (.generated_at
         | . as $generated_at
         | try ((fromdateiso8601 | strftime("%Y-%m-%dT%H:%M:%SZ")) == $generated_at) catch false)
    and (.inputs | type == "object")
    and (.inputs.analysis_target | repository_relative_path)
    and (.inputs.cli_selected | type == "array" and length == 3 and all(.[]; repository_relative_path))
    and (.inputs.cli_selected | any(.[]; test("^data/analytics_data_.+\\.json$")))
    and (.inputs.cli_selected | any(.[]; test("^data/analytics/daily_per_video/.+\\.json$")))
    and (.inputs.cli_selected | index("config/channel/content.json") != null)
    and (.inputs.supplemental | type == "array" and all(.[]; repository_relative_path))
    and (.inputs.intermediate | type == "object")
    and (.inputs.intermediate.vpd_ranking | repository_relative_path)
    and (.inputs.intermediate.visual_annotations | repository_relative_path)
    and (.inputs.intermediate.win_pattern | repository_relative_path)
    and (.commands == {
      "launch_curve": "uv run yt-launch-curve --latest",
      "channel_trend": "uv run yt-channel-trend",
      "theme_compare": "uv run yt-theme-compare",
      "traffic_trend": "uv run yt-traffic-trend",
      "vpd_ranking": "uv run yt-vpd-rank",
      "win_pattern": ("uv run yt-win-pattern --ranking " + .inputs.intermediate.vpd_ranking + " --annotations " + .inputs.intermediate.visual_annotations)
    })
    and (.cli_outputs | type == "object")
    and (.cli_outputs.launch_curve | nonempty_object)
    and (.cli_outputs.channel_trend | nonempty_object)
    and (.cli_outputs.theme_compare | nonempty_object)
    and (.cli_outputs.traffic_trend | nonempty_object)
    and (.ttp_health | ttp_health_ok)
    and (.vpd_ranking | vpd_ranking_ok)
    and (.win_pattern | win_pattern_ok($root.vpd_ranking))
    and (["strategic_improvements", "next_collection_candidates", "strategic_discussion"]
         | all(.[];
             . as $key
             | (($root[$key] | type == "array" and length > 0)
                and ($root[$key] | all(.[]; fixed_item_ok($root))))))
    and (["launch_curve", "channel_trend", "theme_compare", "traffic_trend", "vpd_ranking", "win_pattern"]
         | all(.[];
             . as $source
             | (all_evidence($root) | any(.[]; .source == $source))))
' "$analysis_json"

while IFS= read -r input_path; do
  test -f "$input_path"
done < <(jq -er '.inputs | [.analysis_target, .cli_selected[], .supplemental[], .intermediate[]] | .[]' "$analysis_json")

vpd_ranking_path=$(jq -er '.inputs.intermediate.vpd_ranking' "$analysis_json")
visual_annotations_path=$(jq -er '.inputs.intermediate.visual_annotations' "$analysis_json")
win_pattern_path=$(jq -er '.inputs.intermediate.win_pattern' "$analysis_json")

jq -e \
  --slurpfile captured_ranking "$vpd_ranking_path" \
  --slurpfile annotations "$visual_annotations_path" \
  --slurpfile captured_win "$win_pattern_path" '
  def visual_attributes:
    ["composition", "color", "text_placement", "visual_flow", "subject"];

  def annotation_for($id):
    $annotations[0].videos[] | select(.video_id == $id);

  . as $root
  | ($root.vpd_ranking == $captured_ranking[0])
    and ($root.win_pattern == $captured_win[0])
    and ($annotations[0] | type == "object" and keys == ["videos"])
    and ($annotations[0].videos | type == "array" and length == (2 * $root.vpd_ranking.k))
    and ($annotations[0].videos | all(.[];
          . as $annotation
          | type == "object"
          and (keys | sort) == ((["video_id"] + visual_attributes) | sort)
          and (.video_id | type == "string" and length > 0)
          and (visual_attributes | all(.[]; . as $name
                | ($annotation[$name] == null
                   or ($annotation[$name] | type == "string" and length > 0))))))
    and (($annotations[0].videos | map(.video_id) | sort)
         == ([$root.vpd_ranking.groups.top.items[].video_id,
              $root.vpd_ranking.groups.bottom.items[].video_id] | sort))
    and (visual_attributes | all(.[]; . as $attribute
          | ([ $root.vpd_ranking.groups.top.items[].video_id as $id
               | annotation_for($id) | select(.[$attribute] == null) ] | length)
              == $root.win_pattern.attributes[$attribute].undetermined_count.top
            and ([ $root.vpd_ranking.groups.bottom.items[].video_id as $id
                   | annotation_for($id) | select(.[$attribute] == null) ] | length)
              == $root.win_pattern.attributes[$attribute].undetermined_count.bottom))
' "$analysis_json" >/dev/null

analysis_target=$(jq -er '.inputs.analysis_target' "$analysis_json")
if jq -e '.collection_depth == "full"' "$analysis_target" >/dev/null; then
  jq -e --arg source "$analysis_target" --slurpfile targets "$analysis_target" '
    def nonempty_string:
      type == "string" and length > 0;

    def nonnegative_integer:
      type == "number" and . >= 0 and . == floor;

    def retention_item_ok($target):
      . as $item
      | ($item.retention_index | nonnegative_integer)
        and ($item.drop_point_index | nonnegative_integer)
        and ($target.retention[$item.retention_index] as $actual
             | ($actual | type == "object")
               and ($actual | has("error") | not)
               and ($actual.data_points | type == "number" and . > 0)
               and ($actual.retention_curve | type == "array" and length > 0)
               and ($actual.video_id | type == "string" and length > 0)
               and ($item.video_id == $actual.video_id)
               and ($item.average_retention | type == "number" and . == $actual.average_retention)
               and ($item.midpoint_retention | type == "number" and . == $actual.midpoint_retention)
               and ($actual.retention_curve[$item.drop_point_index] as $point
                    | ($point | type == "object")
                      and ($item.drop_point | type == "object")
                      and ($item.drop_point.elapsed_ratio | type == "number" and . == $point.elapsed_ratio)
                      and ($item.drop_point.watch_ratio | type == "number" and . == $point.watch_ratio)));

    def valid_retention_indices($target):
      [$target.retention
       | to_entries[]
       | select((.value | type == "object")
                and (.value | has("error") | not)
                and (.value.data_points | type == "number" and . > 0)
                and (.value.retention_curve | type == "array" and length > 0)
                and (.value.video_id | type == "string" and length > 0)
                and (.value.average_retention | type == "number")
                and (.value.midpoint_retention | type == "number"))
       | .key];

    $targets[0] as $target
    | valid_retention_indices($target) as $valid_indices
    | ($valid_indices | length > 0)
      and (.retention_analysis | type == "object")
      and (.retention_analysis.source == $source)
      and (.retention_analysis.unit == "ratio")
      and (.retention_analysis.hypothesis_evaluation
           | IN("supported", "not_supported", "inconclusive"))
      and (.retention_analysis.summary | nonempty_string)
      and (.retention_analysis.videos | type == "array" and length > 0)
      and ((.retention_analysis.videos | map(.retention_index) | sort) == $valid_indices)
      and (.retention_analysis.videos | all(.[]; retention_item_ok($target)))
  ' "$analysis_json" >/dev/null

fi

jq -e --slurpfile targets "$analysis_target" '
  def revenue_group_ok:
    (type == "object")
    and (.name | type == "string" and length > 0)
    and (.estimated_revenue | type == "number")
    and (.views | type == "number" and . >= 0)
    and (.rpm | type == "number")
    and (.video_count | type == "number" and . >= 0 and . == floor)
    and (if .views == 0 then .rpm == 0 else ((.estimated_revenue / .views * 1000) - .rpm | fabs) < 0.000001 end);

  $targets[0] as $target
  | (.revenue_analysis | type == "object")
    and (.revenue_analysis.themes | type == "array")
    and (.revenue_analysis.collections | type == "array")
    and (if ($target | has("revenue_analytics") | not) then
           (.revenue_analysis.status == "not_collected")
           and (.revenue_analysis.themes == [])
           and (.revenue_analysis.collections == [])
         elif $target.revenue_analytics.status == "unavailable" then
           (.revenue_analysis.status == "unavailable")
           and (.revenue_analysis.themes == [])
           and (.revenue_analysis.collections == [])
         else
           (.revenue_analysis.status == "available")
           and (.revenue_analysis.currency == $target.revenue_analytics.currency)
           and (.revenue_analysis.themes | all(.[]; revenue_group_ok))
           and (.revenue_analysis.collections | all(.[]; revenue_group_ok))
         end)
' "$analysis_json" >/dev/null

uv run yt-document-render "$analysis_json" --schema analysis-report.schema.json --check >/dev/null
```

## 検証する evidence 契約

- `source` は `launch_curve` / `channel_trend` / `theme_compare` / `traffic_trend` / `vpd_ranking` / `win_pattern` のいずれか
- 既存 4 CLI の `json_path` は `$.cli_outputs.<source>`、VPD 2 CLI は `$.<source>` から始まり、object key は `.key`、array index は `[0]` 形式で表す
- `json_path` の `<source>` は `source` と一致する
- `json_path` が指す値は実在する number で、`value` と一致する

CLI 出力 6 件はそれぞれ非空 object でなければならない。VPD ranking は N / K、unique ID、top / middle / bottom の重複・欠落・順序を検証し、win pattern は同じ N / K と目視 annotation の判定不能件数を検証する。固定キーの配列・要素形状、`confidence`、evidence のいずれかが不正な場合も validator は失敗する。

HTML は validated JSON と `analysis-report.schema.json` の `x-view` だけから決定的に生成する。validator は JSON の全 semantic evidence 契約に加え、同 basename HTML が common renderer の期待値と完全一致することを確認する。
