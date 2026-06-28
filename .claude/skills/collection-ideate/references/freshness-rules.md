# 前提スキル鮮度判定ルール

`/collection-ideate` の Phase 1 を開始する前に、入力モードを 1 回だけ判定し、analytics mode の前提スキル出力が最新であることを確認する。
鮮度判定の結果に応じて、古いスキルの再実行を（ユーザーに）案内する。

## 順序依存

analytics mode の前提スキルは **(analyze ∥ benchmark) → persona → viewing-scene** の構造:

- `/analytics-analyze` と `/benchmark` は**独立・並列**（両者とも生データの分析で上下関係なし）
- `persona` は最新ベンチマークのタグデータを入力とする
- `viewing-scene` は `persona-definition.md` を入力とする

**analyze / benchmark は並列判定。その後 persona → viewing-scene を直列で判定する。** persona / viewing-scene は存在チェックのみ（mtime 比較なし。更新タイミングは戦略判断のため人間が決める）。analytics mode の必須入力で stale または未生成を検出したら Phase 1 を中断し、該当スキルの実行をユーザーに促す。

analytics report が存在しない場合は stale ではなく、以下の入力モードに分岐する:

| モード | 判定条件 | 企画生成の入力 |
|---|---|---|
| analytics mode | `reports/analysis_*.md` が存在し、stale ではない | 日次収集データ + ベンチマーク + config |
| benchmark fallback mode | `reports/analysis_*.md` が存在せず、`data/benchmark_*.json` が存在する | ベンチマークデータ + config |
| minimal mode | `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも存在しない | ユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config |

## 鮮度判定表

| 順序 | 前提スキル | 出力ファイル | 鮮度判定ルール | 古い / 未生成の場合 |
|---|---|---|---|---|
| 1a | `/analytics-analyze` | `reports/analysis_*.md` | 最新 `data/analytics_data_*.json` のファイル名日付 (YYYYMMDD) より古ければ stale | report 不在は benchmark fallback mode / minimal mode へ進む。report が stale の場合のみ `/collection-ideate` を中断し、ユーザーに `/analytics-analyze`（必要なら `/analytics-collect` 先行）の実行を案内。**自動呼び出し不可**（AI 推論コスト発生のため） |
| 1b | `/benchmark` | `docs/benchmarks/*.md` + `data/benchmark_YYYYMMDD.json` | analytics mode では mtime が `config/skills/benchmark.yaml` の `freshness_days`（既定 3 日）より古ければ stale | analytics mode では `/benchmark` を Skill ツールで実行（内部で鮮度チェック + 差分更新）。benchmark fallback mode では既存データを読み、minimal mode ではスキップ |
| 2 | `/audience-persona` | `docs/channel/personas/persona-definition.md` | 存在すれば OK（mtime 比較なし。更新タイミングは戦略判断のため人間が決める） | analytics mode ではユーザーに `/audience-persona` 実行を案内して中断。benchmark fallback mode / minimal mode では config と入力データから初回仮説の視聴者像を作る |
| 3 | `/viewing-scene` | `docs/plans/viewing-scene-matrix.md` | 存在すれば OK（mtime 比較なし。persona 下流のため連動して判断） | analytics mode ではユーザーに `/viewing-scene` 実行を案内して中断。benchmark fallback mode / minimal mode では仮説ペルソナから視聴シーンを仮説化する |

## workflow-state.json との同期

コレクションディレクトリ側（`collections/planning/<name>/workflow-state.json`）の `phase` 値と前提スキルの状態は以下のように対応する:

| workflow-state.phase | 入力モード | 想定される前提スキル状態 |
|---|---|---|
| `planning` | analytics mode | benchmark は `/collection-ideate` セッション内で鮮度確認・必要時更新される。persona / viewing-scene は存在確認し、不足時は中断してユーザーに前提スキル実行を促す |
| `planning` | benchmark fallback mode | 既存 `data/benchmark_*.json` を読むが `/benchmark` は自動実行しない。persona / viewing-scene が無ければ、ベンチマークデータ + config から初回仮説として扱う |
| `planning` | minimal mode | benchmark は持たない。persona / viewing-scene が無ければ、ユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config から初回仮説として扱う |
| `thumbnail-*` 以降 | 全モード | ideate はすでに完了している。ideate に戻るときは入力モード判定と前提スキル確認を改めて実行する |

## 判定擬似コード

```bash
# 1a. 入力モード判定 + analyze の日付粒度 stale 判定
latest_by_filename_date() {
  local pattern="$1"
  while IFS= read -r file; do
    if [ ! -f "$file" ]; then
      continue
    fi
    date=$(basename "$file" | grep -oE '[0-9]{8}' | head -1)
    if [ -n "$date" ]; then
      printf '%s\t%s\n' "$date" "$file"
    fi
  done < <(compgen -G "$pattern") | sort -r | head -1 | cut -f2-
}

LATEST_DATA=$(latest_by_filename_date "data/analytics_data_*.json")
LATEST_REPORT=$(latest_by_filename_date "reports/analysis_*.md")
LATEST_BENCHMARK=$(latest_by_filename_date "data/benchmark_*.json")

if [ -z "$LATEST_REPORT" ]; then
  if [ -n "$LATEST_BENCHMARK" ]; then
    INPUT_MODE="benchmark fallback mode"
    echo "analyze 未生成 → benchmark fallback mode で続行"
  else
    INPUT_MODE="minimal mode"
    echo "analyze / benchmark 未生成 → minimal mode でユーザー直接入力を確認"
  fi
else
  INPUT_MODE="analytics mode"
fi

if [ "$INPUT_MODE" = "analytics mode" ] && [ -n "$LATEST_DATA" ]; then
  DATA_DATE=$(echo "$LATEST_DATA" | grep -oE '[0-9]{8}' | head -1)
  REPORT_DATE=$(echo "$LATEST_REPORT" | grep -oE '[0-9]{8}' | head -1)
  if [ "$DATA_DATE" -gt "$REPORT_DATE" ]; then
    echo "analyze stale（data の方が新しい日付）→ /collection-ideate 中断、/analytics-analyze 再実行を案内"
    exit 1
  fi
fi

# 1b. benchmark
case "$INPUT_MODE" in
  "analytics mode")
    echo "benchmark stale 判定は /benchmark スキル内の鮮度チェックに委譲"
    ;;
  "benchmark fallback mode")
    echo "既存の data/benchmark_*.json を Read で読み込む。/benchmark は自動実行しない"
    ;;
  "minimal mode")
    echo "benchmark をスキップし、テーマ / ジャンル / 雰囲気をユーザーに確認"
    ;;
esac

# 2. persona — 存在チェックのみ
if [ ! -f docs/channel/personas/persona-definition.md ]; then
  if [ "$INPUT_MODE" = "analytics mode" ]; then
    echo "persona 未定義 → /collection-ideate 中断、/audience-persona を案内"
    exit 1
  else
    echo "persona 未定義 → config と入力データから初回仮説の視聴者像を作る"
  fi
fi

# 3. viewing-scene — 存在チェックのみ
if [ ! -f docs/plans/viewing-scene-matrix.md ]; then
  if [ "$INPUT_MODE" = "analytics mode" ]; then
    echo "viewing-scene 未定義 → /collection-ideate 中断、/viewing-scene を案内"
    exit 1
  else
    echo "viewing-scene 未定義 → 初回仮説の視聴者像から視聴シーンを仮説化"
  fi
fi
```

## 再実行トリガー条件まとめ

| 発動条件 | 対応 |
|---|---|
| `reports/analysis_*.md` が存在せず、`data/benchmark_*.json` が存在する | benchmark fallback mode として続行し、ベンチマークデータ + config で初回企画を生成 |
| `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも存在しない | minimal mode として続行し、ユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config で初回企画を生成 |
| `reports/analysis_*.md` が最新 `data/analytics_data_*.json` より古い日付 | `/collection-ideate` を中断し、`/analytics-analyze` の再実行を案内 |
| analytics mode で `data/benchmark_*.json` が `config/skills/benchmark.yaml` の `freshness_days`（既定 3 日）より古い | `/benchmark` を Skill ツールで自動実行 |
| analytics mode で `persona-definition.md` が存在しない | `/collection-ideate` を中断し、`/audience-persona` の先行実行を案内 |
| benchmark fallback mode / minimal mode で `persona-definition.md` が存在しない | 中断せず、config と入力データから初回仮説の視聴者像を作る |
| analytics mode で `viewing-scene-matrix.md` が存在しない | `/collection-ideate` を中断し、`/viewing-scene` の先行実行を案内 |
| benchmark fallback mode / minimal mode で `viewing-scene-matrix.md` が存在しない | 中断せず、仮説ペルソナから視聴シーンを仮説化する |

## 関連

- `references/collection-lifecycle.md` — コレクション作成全体のライフサイクル
- `/benchmark` skill 内の鮮度チェック実装（`freshness_days` が真のソース）
