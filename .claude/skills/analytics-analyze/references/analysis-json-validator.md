# Analysis JSON validator

`/analytics-analyze` が生成し、`/collection-ideate` が読む `reports/analysis_YYYYMMDD.json` の機械検証はこのファイルを単一ソースとする。

## 構造化 JSON 契約

```json
{
  "schema_version": 1,
  "generated_at": "2026-07-13T03:34:56Z",
  "inputs": {
    "analysis_target": "data/analytics_data_YYYYMMDD_HHMMSS.json",
    "cli_selected": [
      "data/analytics_data_YYYYMMDD_HHMMSS.json",
      "data/analytics/daily_per_video/YYYY-MM-DD_to_YYYY-MM-DD.json",
      "config/channel/content.json"
    ],
    "supplemental": []
  },
  "commands": {
    "launch_curve": "uv run yt-launch-curve --latest",
    "channel_trend": "uv run yt-channel-trend",
    "theme_compare": "uv run yt-theme-compare",
    "traffic_trend": "uv run yt-traffic-trend"
  },
  "cli_outputs": {
    "launch_curve": {"target": {"ratio_vs_median": 1.42}},
    "channel_trend": {"summary": {"wow_growth_rate": 8.5}},
    "theme_compare": {"themes": [{"day7_mean": 1234.0}]},
    "traffic_trend": {"summary": {"top_source_share_percent": 45.2}}
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

- `cli_outputs` の 4 キーには各 CLI の stdout JSON object を変更せず保存する
- 戦略提案・次期候補・戦略ディスカッションの正本は `strategic_improvements` / `next_collection_candidates` / `strategic_discussion` とする。Markdown は人間向けの説明と数値引用を担う派生成果物であり、後続スキルはこの 3 固定キーから提案を読む
- 固定キーの各要素は、空でない `statement`、1 件以上の `evidence`、`high` / `medium` / `low` の `confidence` を持つ
- `generated_at` は UTC の `YYYY-MM-DDTHH:MM:SSZ` 形式で保存する
- `inputs.analysis_target` / `inputs.supplemental` には分析本文が実際に読み込んだファイルの相対パスを保存する
- `inputs.cli_selected` は、必須 4 CLI が直接選択する分析入力 3 件（最新 `data/analytics_data_*.json`、最新 `data/analytics/daily_per_video/*.json`、テーマ定義元 `config/channel/content.json`）だけを保存する。`yt-theme-compare` の `load_config()` が間接的にロードする他の `config/channel/*.json` や `config/localizations.json`、`yt-traffic-trend` がシェア推移のために読む過去の `data/analytics_data_*.json` スナップショット群は含めない
- `inputs.analysis_target` の `collection_depth` が `full` の場合、`retention_analysis` を必須とする。`source` は `inputs.analysis_target` と一致させ、単位は入力値と同じ `ratio`、仮説評価は `supported` / `not_supported` / `inconclusive` のいずれかとする
- `retention_analysis.videos[]` は `error` がなく、`data_points > 0` かつ空でない `retention_curve` を持つ実測データだけを対象にする。対象 index、video_id、average / midpoint、curve 低下点の index と値は入力 JSON の実値に一致させる
- Markdown の「視聴維持率分析」には入力パス、単位、仮説評価、対象動画、動画間比較（有効データが 1 本なら比較不可の明記）、average / midpoint / curve 低下点の数値を JSON path 付きで記載する
- `inputs.analysis_target` の `collection_depth` が `standard` の場合も Markdown に「視聴維持率分析」見出しを設け、`状態: full 収集が必要` と単独行で明記する
- `inputs.analysis_target.revenue_analytics.status` が `available` の場合は `revenue_analysis.status` も `available` とし、`themes` / `collections` の各行に `name` / `estimated_revenue` / `views` / `rpm` / `video_count` を保存する。RPM は各グループの `estimated_revenue / views * 1000` で算出し、動画別 RPM の単純平均は使わない
- 収益データが `unavailable` の場合は `revenue_analysis.status: "unavailable"`、旧スナップショットで収益キーが無い場合は `revenue_analysis.status: "not_collected"` とする。どちらも `themes` / `collections` は空配列にし、推測値を保存しない
- Markdown には常に「収益・RPM 分析」見出しを設ける。利用可能ならテーマ別・コレクション別集計と入力 JSON path を記載し、利用不可なら状態を明記する

## 実行

`analysis_json` と `analysis_md` に同日付ペアの実在パスを設定し、次を一つの Bash セッションで実行する。全コマンドが exit 0 の場合だけ構造化 JSON 契約を満たす。exit 非 0 の場合は成果物として使用しない。

```bash
analysis_json="reports/analysis_YYYYMMDD.json"
analysis_md="reports/analysis_YYYYMMDD.md"

set -euo pipefail

analysis_json_name=$(basename "$analysis_json")
analysis_md_name=$(basename "$analysis_md")
printf '%s\n' "$analysis_json_name" | grep -Eq '^analysis_[0-9]{8}\.json$'
printf '%s\n' "$analysis_md_name" | grep -Eq '^analysis_[0-9]{8}\.md$'
analysis_json_date=$(printf '%s\n' "$analysis_json_name" | grep -oE '[0-9]{8}')
analysis_md_date=$(printf '%s\n' "$analysis_md_name" | grep -oE '[0-9]{8}')
test "$analysis_json_date" = "$analysis_md_date"

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
      and ($e.source | IN("launch_curve", "channel_trend", "theme_compare", "traffic_trend"))
      and ($e.json_path | type == "string")
      and ($e.json_path | test("^\\$\\.cli_outputs\\.(launch_curve|channel_trend|theme_compare|traffic_trend)(\\.[A-Za-z0-9_-]+|\\[[0-9]+\\])+$"))
      and ($e.json_path | startswith("$.cli_outputs.\($e.source)."))
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

  def all_evidence($root):
    [(($root.strategic_improvements[],
       $root.next_collection_candidates[],
       $root.strategic_discussion[]) | .evidence[])];

  . as $root
  | (type == "object")
    and (.schema_version == 1)
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
    and (.commands == {
      "launch_curve": "uv run yt-launch-curve --latest",
      "channel_trend": "uv run yt-channel-trend",
      "theme_compare": "uv run yt-theme-compare",
      "traffic_trend": "uv run yt-traffic-trend"
    })
    and (.cli_outputs | type == "object")
    and (.cli_outputs.launch_curve | nonempty_object)
    and (.cli_outputs.channel_trend | nonempty_object)
    and (.cli_outputs.theme_compare | nonempty_object)
    and (.cli_outputs.traffic_trend | nonempty_object)
    and (["strategic_improvements", "next_collection_candidates", "strategic_discussion"]
         | all(.[];
             . as $key
             | (($root[$key] | type == "array" and length > 0)
                and ($root[$key] | all(.[]; fixed_item_ok($root))))))
    and (["launch_curve", "channel_trend", "theme_compare", "traffic_trend"]
         | all(.[];
             . as $source
             | (all_evidence($root) | any(.[]; .source == $source))))
' "$analysis_json"

while IFS= read -r input_path; do
  test -f "$input_path"
done < <(jq -er '.inputs | [.analysis_target, .cli_selected[], .supplemental[]] | .[]' "$analysis_json")

analysis_target=$(jq -er '.inputs.analysis_target' "$analysis_json")
if jq -e '.collection_depth == "full"' "$analysis_target" >/dev/null; then
  grep -Eq '^#{1,6}[[:space:]]+視聴維持率分析' "$analysis_md"

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

  retention_unit=$(jq -er '.retention_analysis.unit' "$analysis_json")
  hypothesis_evaluation=$(jq -er '.retention_analysis.hypothesis_evaluation' "$analysis_json")
  grep -Fqx "入力: $analysis_target" "$analysis_md"
  grep -Fqx "単位: $retention_unit" "$analysis_md"
  grep -Fqx "仮説評価: $hypothesis_evaluation" "$analysis_md"
  grep -Eq '^動画間比較: .+' "$analysis_md"

  while IFS= read -r evidence_line; do
    grep -Fqx "$evidence_line" "$analysis_md"
  done < <(
    jq -r --arg file "$(basename "$analysis_target")" --slurpfile targets "$analysis_target" '
      $targets[0] as $target
      | .retention_analysis.videos[]
      | . as $item
      | ($item.retention_index | tostring) as $retention_index
      | ($item.drop_point_index | tostring) as $drop_point_index
      | $target.retention[$item.retention_index] as $actual
      | $actual.retention_curve[$item.drop_point_index] as $point
      | "対象動画: \($actual.video_id)",
        "\($file)#$.retention[\($retention_index)].average_retention = \($actual.average_retention)",
        "\($file)#$.retention[\($retention_index)].midpoint_retention = \($actual.midpoint_retention)",
        "\($file)#$.retention[\($retention_index)].retention_curve[\($drop_point_index)].elapsed_ratio = \($point.elapsed_ratio)",
        "\($file)#$.retention[\($retention_index)].retention_curve[\($drop_point_index)].watch_ratio = \($point.watch_ratio)"
    ' "$analysis_json"
  )
else
  grep -Eq '^#{1,6}[[:space:]]+視聴維持率分析' "$analysis_md"
  grep -Fqx '状態: full 収集が必要' "$analysis_md"
fi

grep -Eq '^#{1,6}[[:space:]]+収益・RPM 分析' "$analysis_md"
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

for source in launch_curve channel_trend theme_compare traffic_trend; do
  found=false
  while IFS= read -r citation; do
    if grep -Fqx "$citation" "$analysis_md"; then
      found=true
      break
    fi
  done < <(
    jq -r --arg source "$source" --arg file "$(basename "$analysis_json")" '
      [(.strategic_improvements[], .next_collection_candidates[], .strategic_discussion[])
       | .evidence[]
       | select(.source == $source)
       | "\($file)#\(.json_path) = \(.value)"]
      | .[]
    ' "$analysis_json"
  )
  test "$found" = true
done
```

## 検証する evidence 契約

- `source` は `launch_curve` / `channel_trend` / `theme_compare` / `traffic_trend` のいずれか
- `json_path` は `$.cli_outputs.<source>` から始まり、object key は `.key`、array index は `[0]` 形式で表す
- `json_path` の `<source>` は `source` と一致する
- `json_path` が指す値は実在する number で、`value` と一致する

CLI 出力 4 件はそれぞれ非空 object でなければならない。固定キーの配列・要素形状、`confidence`、evidence のいずれかが不正な場合も validator は失敗する。

Markdown の数値引用は `<JSON ファイル名>#<json_path> = <value>` の形式に統一する。上の手順は、検証済み evidence と一致する引用が 4 CLI それぞれについて Markdown に 1 件以上あることも確認する。

各引用は Markdown の単独行に記載する。行全体を固定文字列として照合するため、次の負例のように evidence が `1.42` なのに Markdown が `1.421` の場合は一致しない。

```bash
expected_citation='analysis_20260713.json#$.cli_outputs.launch_curve.target.ratio_vs_median = 1.42'
mismatched_citation='analysis_20260713.json#$.cli_outputs.launch_curve.target.ratio_vs_median = 1.421'

if grep -Fqx "$expected_citation" <(printf '%s\n' "$mismatched_citation"); then
  echo "ERROR: mismatched citation was accepted" >&2
  exit 1
fi
```
