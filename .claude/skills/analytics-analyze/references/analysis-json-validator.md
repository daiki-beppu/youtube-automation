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
    "theme_compare": "uv run yt-theme-compare"
  },
  "cli_outputs": {
    "launch_curve": {"target": {"ratio_vs_median": 1.42}},
    "channel_trend": {"summary": {"wow_growth_rate": 8.5}},
    "theme_compare": {"themes": [{"day7_mean": 1234.0}]}
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

- `cli_outputs` の 3 キーには各 CLI の stdout JSON object を変更せず保存する
- 戦略提案・次期候補・戦略ディスカッションの正本は `strategic_improvements` / `next_collection_candidates` / `strategic_discussion` とする。Markdown は人間向けの説明と数値引用を担う派生成果物であり、後続スキルはこの 3 固定キーから提案を読む
- 固定キーの各要素は、空でない `statement`、1 件以上の `evidence`、`high` / `medium` / `low` の `confidence` を持つ
- `generated_at` は UTC の `YYYY-MM-DDTHH:MM:SSZ` 形式で保存する
- `inputs.analysis_target` / `inputs.supplemental` には分析本文が実際に読み込んだファイルの相対パスを保存する
- `inputs.cli_selected` は、3 CLI が直接選択する分析入力 3 件（最新 `data/analytics_data_*.json`、最新 `data/analytics/daily_per_video/*.json`、テーマ定義元 `config/channel/content.json`）だけを保存する。`yt-theme-compare` の `load_config()` が間接的にロードする他の `config/channel/*.json` や `config/localizations.json` は含めない

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
      and ($e.source | IN("launch_curve", "channel_trend", "theme_compare"))
      and ($e.json_path | type == "string")
      and ($e.json_path | test("^\\$\\.cli_outputs\\.(launch_curve|channel_trend|theme_compare)(\\.[A-Za-z0-9_-]+|\\[[0-9]+\\])+$"))
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
      "theme_compare": "uv run yt-theme-compare"
    })
    and (.cli_outputs | type == "object")
    and (.cli_outputs.launch_curve | nonempty_object)
    and (.cli_outputs.channel_trend | nonempty_object)
    and (.cli_outputs.theme_compare | nonempty_object)
    and (["strategic_improvements", "next_collection_candidates", "strategic_discussion"]
         | all(.[];
             . as $key
             | (($root[$key] | type == "array" and length > 0)
                and ($root[$key] | all(.[]; fixed_item_ok($root))))))
    and (["launch_curve", "channel_trend", "theme_compare"]
         | all(.[];
             . as $source
             | (all_evidence($root) | any(.[]; .source == $source))))
' "$analysis_json"

while IFS= read -r input_path; do
  test -f "$input_path"
done < <(jq -er '.inputs | [.analysis_target, .cli_selected[], .supplemental[]] | .[]' "$analysis_json")

for source in launch_curve channel_trend theme_compare; do
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

- `source` は `launch_curve` / `channel_trend` / `theme_compare` のいずれか
- `json_path` は `$.cli_outputs.<source>` から始まり、object key は `.key`、array index は `[0]` 形式で表す
- `json_path` の `<source>` は `source` と一致する
- `json_path` が指す値は実在する number で、`value` と一致する

CLI 出力 3 件はそれぞれ非空 object でなければならない。固定キーの配列・要素形状、`confidence`、evidence のいずれかが不正な場合も validator は失敗する。

Markdown の数値引用は `<JSON ファイル名>#<json_path> = <value>` の形式に統一する。上の手順は、検証済み evidence と一致する引用が 3 CLI それぞれについて Markdown に 1 件以上あることも確認する。

各引用は Markdown の単独行に記載する。行全体を固定文字列として照合するため、次の負例のように evidence が `1.42` なのに Markdown が `1.421` の場合は一致しない。

```bash
expected_citation='analysis_20260713.json#$.cli_outputs.launch_curve.target.ratio_vs_median = 1.42'
mismatched_citation='analysis_20260713.json#$.cli_outputs.launch_curve.target.ratio_vs_median = 1.421'

if grep -Fqx "$expected_citation" <(printf '%s\n' "$mismatched_citation"); then
  echo "ERROR: mismatched citation was accepted" >&2
  exit 1
fi
```
