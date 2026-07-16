# 前提スキル鮮度判定ルール

`/collection-ideate` の Phase 1 を開始する前に、入力モードを 1 回だけ判定し、analytics mode の前提スキル出力が最新であることを確認する。
鮮度判定で stale を検出した場合は、種類に応じた Analytics skill を同じセッションで自動実行し、最新化に成功した場合だけ企画フローを継続する。

## stale report の自動更新

analytics mode の stale report は古い結果を企画入力に使わず、追加のユーザー確認なしで次の順に Skill ツールを直接呼ぶ。

- **相対 stale**（最新 report が最新収集データより古い）: `/analytics-analyze` を自動実行する。
- **絶対 stale**（最新収集データが `freshness_days` を超えて古い）: `/analytics-collect`、続けて `/analytics-analyze` を順に自動実行する。`/analytics-collect` が成功するまで `/analytics-analyze` を呼ばない。
- **fresh**: Analytics skill を追加で呼ばず、既存 report を使って Phase 1-2 へ進む。

自動実行した各 skill の完了条件をその skill の `SKILL.md` に従って確認する。全呼び出しの完了後、この文書の判定擬似コードを先頭から再実行し、新しい Markdown / JSON 同日付ペア、analysis JSON validator、相対・絶対鮮度を再検証する。すべて成功した場合だけ Phase 1-2 へ続行する。

skill 呼び出し失敗または再検証失敗時は、失敗した skill または検証項目と失敗理由を表示し、stale report を使わず停止する。再開条件は、表示した失敗原因を解消して `/collection-ideate` を再実行できる状態になること。停止後に古い分析から企画生成へ進んではならない。

## 順序依存

analytics mode の前提スキルは **(analyze ∥ benchmark) → audience-persona-design finalization** の構造:

- `/analytics-analyze` と `/benchmark` は**独立・並列**（両者とも生データの分析で上下関係なし）
- `/audience-persona-design` は最新ベンチマークのタグデータと `/viewer-voice` を入力に暫定 `persona-definition.md` を作る
- `/audience-persona-design` は暫定 persona から `/viewing-scene` を実行し、その結果を反映して最終 `persona-definition.md` を更新する

**analyze / benchmark は並列判定。その後 `/audience-persona-design` の最終 persona chain を判定する。** `persona-definition.md` / `viewing-scene-matrix.md` は存在チェックのみ（mtime 比較なし。更新タイミングは戦略判断のため人間が決める）。analytics mode の必須入力が未生成なら Phase 1 を中断し、stale なら自動更新と再検証の成功時だけ続行する。

analytics report の Markdown が存在しない場合は stale ではなく、以下の入力モードに分岐する。Markdown が存在する場合は、同じファイル名日付の JSON と `.claude/skills/analytics-analyze/references/analysis-json-validator.md` の validator 成功を analytics mode の Hard Gate とする。JSON 不在、ファイル名日付不一致、validator の exit 非 0 は fallback せず Phase 1 を中断し、`/analytics-analyze` の再実行を案内する:

| モード | 判定条件 | 企画生成の入力 |
|---|---|---|
| analytics mode | 同じファイル名日付の `reports/analysis_*.md` / `.json` ペアが存在し、validator が exit 0 で、stale ではない | 日次収集データ + 構造化分析 JSON + ベンチマーク + config |
| benchmark fallback mode | `reports/analysis_*.md` が存在せず、`data/benchmark_*.json` が存在する | ベンチマークデータ + config |
| minimal mode | `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも存在しない | `ttp_mode: false` はユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config。`true` は `/benchmark` を案内して停止し、企画生成しない |

## 鮮度判定表

| 順序 | 前提スキル | 出力ファイル | 鮮度判定ルール | 古い / 未生成の場合 |
|---|---|---|---|---|
| 1a | `/analytics-analyze` | 同じファイル名日付の `reports/analysis_*.md` + `.json` | 先に JSON ペア validator が exit 0 であること。次のいずれかを満たせば stale（OR 結合）: (1) **相対比較** — 最新 `data/analytics_data_*.json` のファイル名日付 (YYYYMMDD) より古い / (2) **絶対鮮度** — 最新 `data/analytics_data_*.json` のファイル名日付が実行日 (today) から `config/skills/collection-ideate.yaml` の `freshness_days`（既定 7 日）を超えて経過 | Markdown 不在は benchmark fallback mode / minimal mode へ分岐する。minimal mode は `ttp_mode: false` だけ続行し、`true` は `/benchmark` を案内して停止する。JSON 不在または validator 失敗は従来どおり停止。相対 stale は `/analytics-analyze`、絶対 stale は `/analytics-collect` → `/analytics-analyze` を自動実行し、再検証成功時だけ続行する |
| 1b | `/benchmark` | `docs/benchmarks/*.md` + `data/benchmark_YYYYMMDD.json` | analytics mode では mtime が `config/skills/benchmark.yaml` の `freshness_days`（既定 3 日）より古ければ stale | analytics mode では `/benchmark` を Skill ツールで実行（内部で鮮度チェック + 差分更新）。benchmark fallback mode では既存データを読む。minimal mode は `ttp_mode: false` ならスキップし、`true` なら `/benchmark` を案内して停止する |
| 2 | `/audience-persona-design` | `docs/channel/personas/persona-definition.md` | 存在すれば OK（mtime 比較なし。更新タイミングは戦略判断のため人間が決める） | analytics mode ではユーザーに `/audience-persona-design` 実行を案内して中断。benchmark fallback mode / `ttp_mode: false` の minimal mode では config と入力データから初回仮説の視聴者像を作る。`ttp_mode: true` の minimal mode はこの判定前に停止する |
| 3 | `/audience-persona-design` finalization | `docs/plans/viewing-scene-matrix.md` | 存在すれば OK（mtime 比較なし。persona 下流のため連動して判断） | analytics mode ではユーザーに `/audience-persona-design` で `/viewing-scene` 実行と最終 `persona-definition.md` 更新を行うよう案内して中断。benchmark fallback mode / `ttp_mode: false` の minimal mode では仮説ペルソナから視聴シーンを仮説化する。`ttp_mode: true` の minimal mode はこの判定前に停止する |

## workflow-state.json との同期

コレクションディレクトリ側（`collections/planning/<name>/workflow-state.json`）の `phase` 値と前提スキルの状態は以下のように対応する:

| workflow-state.phase | 入力モード | 想定される前提スキル状態 |
|---|---|---|
| `planning` | analytics mode | benchmark は `/collection-ideate` セッション内で鮮度確認・必要時更新される。persona / viewing-scene は存在確認し、不足時は中断してユーザーに前提スキル実行を促す |
| `planning` | benchmark fallback mode | 既存 `data/benchmark_*.json` を読むが `/benchmark` は自動実行しない。persona / viewing-scene が無ければ、ベンチマークデータ + config から初回仮説として扱う |
| `planning` | minimal mode | `ttp_mode: false` は benchmark を持たず、persona / viewing-scene が無ければユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config から初回仮説として扱う。`true` は `/benchmark` を案内して停止し、`data/benchmark_*.json` 生成後に入力モードを再判定する |
| `thumbnail-*` 以降 | 全モード | ideate はすでに完了している。ideate に戻るときは入力モード判定と前提スキル確認を改めて実行する |

## 判定擬似コード

設定読み込みゲートで解決した `ttp_mode` は、文字列 `true` / `false` として
`COLLECTION_IDEATE_TTP_MODE` に渡してから実行する。

```bash
# 1a. 入力モード判定 + analyze の日付粒度 stale 判定
handle_analysis_stale() {
  local stale_kind="$1"
  # return 3 はエージェントが下記 Skill ツール呼び出しをその場で実行するゲート。
  # 全 skill 成功後にこの擬似コードを先頭から再実行し、ペア、validator、
  # 相対・絶対鮮度のすべてが成功した場合だけ Phase 1-2 へ進む。
  case "$stale_kind" in
    relative)
      echo "AUTO_REFRESH_SKILLS=/analytics-analyze"
      return 3
      ;;
    absolute)
      echo "AUTO_REFRESH_SKILLS=/analytics-collect,/analytics-analyze"
      return 3
      ;;
    *)
      echo "未知の stale kind: $stale_kind" >&2
      return 1
      ;;
  esac
}

latest_by_filename_date() {
  local pattern="$1"
  local dir="${pattern%/*}"
  local glob="${pattern##*/}"
  find "$dir" -maxdepth 1 -type f -name "$glob" 2>/dev/null | while IFS= read -r file; do
    if [ ! -f "$file" ]; then
      continue
    fi
    date=$(basename "$file" | grep -oE '[0-9]{8}' | head -1)
    if [ -n "$date" ]; then
      printf '%s\t%s\n' "$date" "$file"
    fi
  done | sort -r | head -1 | cut -f2-
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
    if [ "$COLLECTION_IDEATE_TTP_MODE" = "true" ]; then
      echo "analyze / benchmark 未生成かつ ttp_mode=true → /benchmark を案内して停止"
      exit 1
    fi
    echo "analyze / benchmark 未生成かつ ttp_mode=false → minimal mode でユーザー直接入力を確認"
  fi
else
  REPORT_DATE=$(basename "$LATEST_REPORT" | grep -oE '[0-9]{8}' | head -1)
  ANALYSIS_JSON="reports/analysis_${REPORT_DATE}.json"
  # ANALYSIS_JSON の存在を確認し、analysis_json=$ANALYSIS_JSON、
  # analysis_md=$LATEST_REPORT として
  # .claude/skills/analytics-analyze/references/analysis-json-validator.md の
  # validator 全体を実行する。JSON 不在または exit 非 0 なら
  # /collection-ideate を中断し、/analytics-analyze 再実行を案内する。
  INPUT_MODE="analytics mode"
fi

if [ "$INPUT_MODE" = "analytics mode" ] && [ -n "$LATEST_DATA" ]; then
  DATA_DATE=$(echo "$LATEST_DATA" | grep -oE '[0-9]{8}' | head -1)
  REPORT_DATE=$(echo "$LATEST_REPORT" | grep -oE '[0-9]{8}' | head -1)
  # (1) 絶対鮮度チェック (#1427): 収集データ自体が実行日から freshness_days を超えて古い。
  #     相対比較と OR 結合 — DATA_DATE == REPORT_DATE でもこちらで stale になり得る
  #     両方が成立する場合は collect が必要な絶対 stale を優先する。
  # 設定読み込みゲートで load_skill_config("collection-ideate") 相当の
  # default + config/skills/collection-ideate.yaml deep-merge を先に行い、
  # 解決済み freshness_days をこの擬似コードへ渡す。
  if [ -z "${COLLECTION_IDEATE_FRESHNESS_DAYS:-}" ]; then
    echo "collection-ideate freshness_days が未解決です。設定読み込みゲートを実行してください" >&2
    exit 1
  fi
  case "$COLLECTION_IDEATE_FRESHNESS_DAYS" in
    *[!0-9]*)
      echo "collection-ideate freshness_days は整数である必要があります: ${COLLECTION_IDEATE_FRESHNESS_DAYS}" >&2
      exit 1
      ;;
  esac
  FRESHNESS_DAYS="$COLLECTION_IDEATE_FRESHNESS_DAYS"
  to_epoch() {
    # YYYYMMDD → epoch 秒（BSD date / GNU date 両対応）
    date -j -f '%Y%m%d' "$1" +%s 2>/dev/null || date -d "$1" +%s
  }
  TODAY=${TODAY:-$(date +%Y%m%d)}
  ELAPSED_DAYS=$(( ($(to_epoch "$TODAY") - $(to_epoch "$DATA_DATE")) / 86400 ))
  if [ "$ELAPSED_DAYS" -gt "$FRESHNESS_DAYS" ]; then
    echo "analyze stale（収集データが ${ELAPSED_DAYS} 日前 > freshness_days=${FRESHNESS_DAYS}）"
    handle_analysis_stale absolute
    # return 3 を受けたエージェントは /analytics-collect の成功後に
    # /analytics-analyze を自動実行する。途中失敗時は後続へ進まない。
    exit $?
  fi

  # (2) 相対比較: report が収集データより古い
  if [ "$DATA_DATE" -gt "$REPORT_DATE" ]; then
    echo "analyze stale（data の方が新しい日付）"
    handle_analysis_stale relative
    # return 3 を受けたエージェントは /analytics-analyze を自動実行する。
    # 呼び出し失敗または再検証失敗は理由と再開条件を表示して停止する。
    exit $?
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
    # ttp_mode=true は入力モード判定時に停止済み。
    echo "ttp_mode=false のため benchmark をスキップし、テーマ / ジャンル / 雰囲気をユーザーに確認"
    ;;
esac

# 2. persona — 存在チェックのみ
if [ ! -f docs/channel/personas/persona-definition.md ]; then
  if [ "$INPUT_MODE" = "analytics mode" ]; then
    echo "persona 未定義 → /collection-ideate 中断、/audience-persona-design を案内"
    exit 1
  else
    echo "persona 未定義 → config と入力データから初回仮説の視聴者像を作る"
  fi
fi

# 3. viewing-scene reflection — 存在チェックのみ
if [ ! -f docs/plans/viewing-scene-matrix.md ]; then
  if [ "$INPUT_MODE" = "analytics mode" ]; then
    echo "viewing-scene 未定義 → /collection-ideate 中断、/audience-persona-design で /viewing-scene 実行と最終 persona-definition.md 更新を案内"
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
| `reports/analysis_*.md` と `data/benchmark_*.json` がどちらも存在しない | minimal mode として `ttp_mode` を確認する。`false` はユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config で初回企画を生成し、`true` は `/benchmark` を案内して停止する |
| 最新 `reports/analysis_*.md` と同じファイル名日付の `.json` が存在しない、または analysis JSON validator が exit 非 0 | `/collection-ideate` を中断し、`/analytics-analyze` の再実行を案内 |
| `reports/analysis_*.md` が最新 `data/analytics_data_*.json` より古い日付 | `/analytics-analyze` を自動実行し、再検証成功時だけ企画フローを続行 |
| analytics mode で最新 `data/analytics_data_*.json` のファイル名日付が実行日 (today) から `config/skills/collection-ideate.yaml` の `freshness_days`（既定 7 日）を超えて経過（絶対鮮度、#1427） | `/analytics-collect` → `/analytics-analyze` の順で自動実行し、再検証成功時だけ企画フローを続行 |
| analytics mode で `data/benchmark_*.json` が `config/skills/benchmark.yaml` の `freshness_days`（既定 3 日）より古い | `/benchmark` を Skill ツールで自動実行 |
| analytics mode で `persona-definition.md` が存在しない | `/collection-ideate` を中断し、`/audience-persona-design` の先行実行を案内 |
| benchmark fallback mode / minimal mode で `persona-definition.md` が存在しない | benchmark fallback mode と `ttp_mode: false` の minimal mode は中断せず、config と入力データから初回仮説の視聴者像を作る。`ttp_mode: true` の minimal mode はこの判定前に停止する |
| analytics mode で `viewing-scene-matrix.md` が存在しない | `/collection-ideate` を中断し、`/audience-persona-design` で `/viewing-scene` 実行と最終 `persona-definition.md` 更新を行うよう案内 |
| benchmark fallback mode / minimal mode で `viewing-scene-matrix.md` が存在しない | benchmark fallback mode と `ttp_mode: false` の minimal mode は中断せず、仮説ペルソナから視聴シーンを仮説化する。`ttp_mode: true` の minimal mode はこの判定前に停止する |

## 関連

- `references/collection-lifecycle.md` — コレクション作成全体のライフサイクル
- `/benchmark` skill 内の鮮度チェック実装（benchmark 側 `freshness_days` が真のソース）
- `.claude/skills/collection-ideate/config.default.yaml` の `freshness_days` — 分析データの絶対鮮度チェック既定値（チャンネル側は `config/skills/collection-ideate.yaml` で上書き）
