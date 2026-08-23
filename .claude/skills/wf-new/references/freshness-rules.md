# 前提スキル鮮度判定ルール

`/wf-new` の企画工程を開始する前に、入力モードを 1 回だけ判定し、analytics mode の前提スキル出力が最新であることを確認する。
鮮度判定で stale を検出した場合は、種類に応じた Analytics skill を同じセッションで自動実行し、最新化に成功した場合だけ企画フローを継続する。

## stale report の自動更新

analytics mode の stale report は古い結果を企画入力に使わず、追加のユーザー確認なしで次の順に Skill ツールを直接呼ぶ。

- **相対 stale**（最新 report が最新収集データより古い）: `/analytics --analyze` を自動実行する。
- **絶対 stale**（最新収集データが `freshness_days` を超えて古い）: `/analytics --collect`、続けて `/analytics --analyze` を順に自動実行する。`/analytics --collect` が成功するまで `/analytics --analyze` を呼ばない。
- **fresh**: Analytics skill を追加で呼ばず、既存 report を使って Phase 1-2 へ進む。

自動実行した各 skill の完了条件をその skill の `SKILL.md` に従って確認する。全呼び出しの完了後、この文書の判定擬似コードを先頭から再実行し、新しい JSON / HTML 同日付ペア、analysis JSON validator、相対・絶対鮮度を再検証する。すべて成功した場合だけ Phase 1-2 へ続行する。

skill 呼び出し失敗または再検証失敗時は、失敗した skill または検証項目と失敗理由を表示し、stale report を使わず停止する。再開条件は、表示した失敗原因を解消して `/wf-new` を再実行できる状態になること。停止後に古い分析から企画生成へ進んではならない。

## 順序依存

analytics mode の前提スキルは **(analyze ∥ benchmark) → channel-strategy persona finalization** の構造:

- `/analytics --analyze` と `/channel-research --benchmark` は**独立・並列**（両者とも生データの分析で上下関係なし）
- `/channel-strategy --persona` は最新ベンチマークのタグデータと `/channel-research --voice` を入力に暫定 `persona-definition.json` pair を作る
- `/channel-strategy --persona` は暫定 persona から `/channel-strategy --scene` を実行し、その結果を反映して最終 `persona-definition.json` pair を更新する

**analyze / benchmark は並列判定。その後 `/channel-strategy --persona` の最終 persona chain を判定する。** `persona-definition.json` / `viewing-scene-matrix.json` は `RepositorySchema.CHANNEL_STRATEGY` の JSON+HTML pair として検証し、相互参照も確認する（mtime 比較なし）。候補が片側欠落・schema 不正・HTML digest 不一致・参照不整合なら fail-closed で停止する。両文書が未生成の場合、analytics mode の `ttp_mode: false` は Phase 1 を中断し、`true` は共通の欲求語彙選択規則による fallback で続行する。旧 Markdown は入力にしない。stale report は `ttp_mode` にかかわらず、自動更新と再検証の成功時だけ続行する。

検証済み analytics JSON+HTML が存在しない場合は stale ではなく、以下の入力モードに分岐する。JSON または HTML の候補が存在する場合は `.claude/skills/analytics/references/analysis-json-validator.md` の validator 成功を analytics mode の Hard Gate とする。片方不在、ファイル名日付不一致、schema/pair不一致、validator の exit 非 0 は fallback せず Phase 1 を中断し、`/analytics --analyze` の再実行を案内する:

| モード | 判定条件 | 企画生成の入力 |
|---|---|---|
| analytics mode | 同じファイル名日付の `reports/analysis_*.json` / `.html` ペアが存在し、validator が exit 0 で、stale ではない | 日次収集データ + 構造化分析 JSON + ベンチマーク + config |
| benchmark fallback mode | 検証済み analysis JSON が存在せず、`data/benchmark_*.json` が存在する | ベンチマークデータ + config |
| minimal mode | 検証済み analysis JSON と `data/benchmark_*.json` がどちらも存在しない | `ttp_mode: false` はユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config。`true` は `/channel-research --benchmark` を案内して停止し、企画生成しない |

## 鮮度判定表

| 順序 | 前提スキル | 出力ファイル | 鮮度判定ルール | 古い / 未生成の場合 |
|---|---|---|---|---|
| 1a | `/analytics --analyze` | 同じファイル名日付の `reports/analysis_*.json` + `.html` | 先に schema/pair validator が exit 0 であること。次のいずれかを満たせば stale（OR 結合）: (1) **相対比較** — 最新 `data/analytics_data_*.json` のファイル名日付 (YYYYMMDD) より古い / (2) **絶対鮮度** — 最新 `data/analytics_data_*.json` のファイル名日付が実行日 (today) から `config/skills/collection-ideate.yaml` の `freshness_days`（既定 7 日）を超えて経過 | 検証済み pair 不在は benchmark fallback mode / minimal mode へ分岐する。片方だけ存在、不正、または validator 失敗は停止。相対 stale は `/analytics --analyze`、絶対 stale は `/analytics --collect` → `/analytics --analyze` を自動実行し、再検証成功時だけ続行する |
| 1b | `/channel-research --benchmark` | 検証済み `docs/benchmarks/benchmark-report.json` + `.html` と `data/benchmark_YYYYMMDD.json` | analytics mode では pair の古い方の mtime が `config/skills/benchmark.yaml` の `freshness_days`（既定 3 日）より古ければ stale | analytics mode では `/channel-research --benchmark` を Skill ツールで実行（内部で鮮度チェック + 差分更新）。benchmark fallback mode では検証済み JSON を読む。minimal mode は `ttp_mode: false` ならスキップし、`true` なら `/channel-research --benchmark` を案内して停止する |
| 2 | `/channel-strategy --persona` | `docs/channel/personas/persona-definition.json` + `.html` | `read_published_json_document(..., RepositorySchema.CHANNEL_STRATEGY)` 相当で検証（mtime 比較なし） | pair 未生成時の mode 別 fallback は従来どおり。候補の片側欠落・schema/pair 不正は停止 |
| 3 | `/channel-strategy --persona` finalization | `docs/plans/viewing-scene-matrix.json` + `.html` | 同じ canonical reader で検証し、scene の `persona_id`、persona の `scene_ids` と scene ID の相互参照を確認 | pair 未生成時の mode 別 fallback は従来どおり。pair/参照不正は成果物を変更せず停止 |

## workflow-state.json との同期

コレクションディレクトリ側（`collections/planning/<name>/workflow-state.json`）の `phase` 値と前提スキルの状態は以下のように対応する:

| workflow-state.phase | 入力モード | 想定される前提スキル状態 |
|---|---|---|
| `planning` | analytics mode | benchmark は `/wf-new` セッション内で鮮度確認・必要時更新される。persona / viewing-scene は存在確認し、不足時は `ttp_mode: false` なら中断してユーザーに前提スキル実行を促し、`true` なら共通 fallback で続行する |
| `planning` | benchmark fallback mode | 既存 `data/benchmark_*.json` を読むが `/channel-research --benchmark` は自動実行しない。persona / viewing-scene が無ければ、ベンチマークデータ + config から初回仮説として扱う |
| `planning` | minimal mode | `ttp_mode: false` は benchmark を持たず、persona / viewing-scene が無ければユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config から初回仮説として扱う。`true` は `/channel-research --benchmark` を案内して停止し、`data/benchmark_*.json` 生成後に入力モードを再判定する |
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
      echo "AUTO_REFRESH_SKILLS=/analytics --analyze"
      return 3
      ;;
    absolute)
      echo "AUTO_REFRESH_SKILLS=/analytics --collect,/analytics --analyze"
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
LATEST_REPORT=$(latest_by_filename_date "reports/analysis_*.json")
LATEST_BENCHMARK=$(latest_by_filename_date "data/benchmark_*.json")

if [ -z "$LATEST_REPORT" ]; then
  if [ -n "$LATEST_BENCHMARK" ]; then
    INPUT_MODE="benchmark fallback mode"
    echo "analyze 未生成 → benchmark fallback mode で続行"
  else
    INPUT_MODE="minimal mode"
    if [ "$COLLECTION_IDEATE_TTP_MODE" = "true" ]; then
      echo "analyze / benchmark 未生成かつ ttp_mode=true → /channel-research --benchmark を案内して停止"
      exit 1
    fi
    echo "analyze / benchmark 未生成かつ ttp_mode=false → minimal mode でユーザー直接入力を確認"
  fi
else
  REPORT_DATE=$(basename "$LATEST_REPORT" | grep -oE '[0-9]{8}' | head -1)
  ANALYSIS_JSON="$LATEST_REPORT"
  ANALYSIS_HTML="reports/analysis_${REPORT_DATE}.html"
  # ANALYSIS_HTML の存在を確認し、analysis_json=$ANALYSIS_JSON、
  # analysis_html=$ANALYSIS_HTML として
  # .claude/skills/analytics/references/analysis-json-validator.md の
  # validator 全体を実行する。JSON 不在または exit 非 0 なら
  # /wf-new の企画工程を中断し、/analytics --analyze 再実行を案内する。
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
    # return 3 を受けたエージェントは /analytics --collect の成功後に
    # /analytics --analyze を自動実行する。途中失敗時は後続へ進まない。
    exit $?
  fi

  # (2) 相対比較: report が収集データより古い
  if [ "$DATA_DATE" -gt "$REPORT_DATE" ]; then
    echo "analyze stale（data の方が新しい日付）"
    handle_analysis_stale relative
    # return 3 を受けたエージェントは /analytics --analyze を自動実行する。
    # 呼び出し失敗または再検証失敗は理由と再開条件を表示して停止する。
    exit $?
  fi
fi

# 1b. benchmark
case "$INPUT_MODE" in
  "analytics mode")
    echo "benchmark stale 判定は /channel-research --benchmark スキル内の鮮度チェックに委譲"
    ;;
  "benchmark fallback mode")
    echo "既存の data/benchmark_*.json を Read で読み込む。/channel-research --benchmark は自動実行しない"
    ;;
  "minimal mode")
    # ttp_mode=true は入力モード判定時に停止済み。
    echo "ttp_mode=false のため benchmark をスキップし、テーマ / ジャンル / 雰囲気をユーザーに確認"
    ;;
esac

# 2-3. canonical persona chain — JSON+HTML pair と参照整合性を検証
PERSONA_JSON=docs/channel/personas/persona-definition.json
SCENE_JSON=docs/plans/viewing-scene-matrix.json
if [ -e "$PERSONA_JSON" ] || [ -e "${PERSONA_JSON%.json}.html" ] || [ -e "$SCENE_JSON" ] || [ -e "${SCENE_JSON%.json}.html" ]; then
  if ! "${PYTHON:-python}" - <<'PY'
from pathlib import Path

from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import read_published_json_document

persona = read_published_json_document(Path("docs/channel/personas/persona-definition.json"), RepositorySchema.CHANNEL_STRATEGY)
scene = read_published_json_document(Path("docs/plans/viewing-scene-matrix.json"), RepositorySchema.CHANNEL_STRATEGY)
persona_id = persona["persona"]["id"]
scene_ids = {item["id"] for item in scene["scenes"]}
if scene["persona_id"] != persona_id or not set(persona["scene_ids"]).issubset(scene_ids):
    raise ValueError("persona/scene の参照が一致しません")
PY
  then
    echo "persona chain 検証失敗 → 成果物を変更せず /channel-strategy --persona の再実行を案内"
    exit 1
  fi
  echo "検証済み canonical persona chain を使用"
  PERSONA_CHAIN_VALID=true
else
  PERSONA_CHAIN_VALID=false
fi

if [ "$PERSONA_CHAIN_VALID" != "true" ]; then
  if [ "$INPUT_MODE" = "analytics mode" ] && [ "$COLLECTION_IDEATE_TTP_MODE" = "false" ]; then
    echo "persona 未定義 → /wf-new 企画工程中断、/channel-strategy --persona を案内"
    exit 1
  elif [ "$INPUT_MODE" = "analytics mode" ]; then
    echo "persona 未定義かつ ttp_mode=true → 共通の欲求語彙選択規則に従い、競合コメント / タイトルから初回仮説の視聴者像を作って続行"
  else
    echo "persona 未定義 → config と入力データから初回仮説の視聴者像を作る"
  fi
fi

# 3. viewing-scene reflection — canonical chain 未生成時の fallback
if [ "$PERSONA_CHAIN_VALID" != "true" ]; then
  if [ "$INPUT_MODE" = "analytics mode" ] && [ "$COLLECTION_IDEATE_TTP_MODE" = "false" ]; then
    echo "viewing-scene 未定義 → /wf-new 企画工程中断、/channel-strategy --persona で /channel-strategy --scene 実行と最終 persona-definition.json pair 更新を案内"
    exit 1
  elif [ "$INPUT_MODE" = "analytics mode" ]; then
    echo "viewing-scene 未定義かつ ttp_mode=true → 共通 fallback の競合コメント / タイトルから視聴シーンを仮説化して続行（根拠がなければ判定不能）"
  else
    echo "viewing-scene 未定義 → 初回仮説の視聴者像から視聴シーンを仮説化"
  fi
fi
```

## 再実行トリガー条件まとめ

| 発動条件 | 対応 |
|---|---|
| 検証済み `reports/analysis_*.json` が存在せず、`data/benchmark_*.json` が存在する | benchmark fallback mode として続行し、ベンチマークデータ + config で初回企画を生成 |
| 検証済み analysis JSON と `data/benchmark_*.json` がどちらも存在しない | minimal mode として `ttp_mode` を確認する。`false` はユーザー直接入力（テーマ / ジャンル / 雰囲気）+ config で初回企画を生成し、`true` は `/channel-research --benchmark` を案内して停止する |
| 最新 `reports/analysis_*.json` と同じファイル名日付の `.html` が存在しない、または analysis validator が exit 非 0 | `/wf-new` を中断し、`/analytics --analyze` の再実行を案内 |
| 検証済み `reports/analysis_*.json` が最新 `data/analytics_data_*.json` より古い日付 | `/analytics --analyze` を自動実行し、再検証成功時だけ企画フローを続行 |
| analytics mode で最新 `data/analytics_data_*.json` のファイル名日付が実行日 (today) から `config/skills/collection-ideate.yaml` の `freshness_days`（既定 7 日）を超えて経過（絶対鮮度、#1427） | `/analytics --collect` → `/analytics --analyze` の順で自動実行し、再検証成功時だけ企画フローを続行 |
| analytics mode で `data/benchmark_*.json` が `config/skills/benchmark.yaml` の `freshness_days`（既定 3 日）より古い | `/channel-research --benchmark` を Skill ツールで自動実行 |
| analytics mode で `persona-definition.json pair` が存在しない | `ttp_mode: false` は `/wf-new` を中断し、`/channel-strategy --persona` の先行実行を案内する。`true` は共通の欲求語彙選択規則に従い、利用可能な競合コメント / タイトルから初回仮説の視聴者像を作り、ソースと根拠を明記して続行する |
| benchmark fallback mode / minimal mode で `persona-definition.json pair` が存在しない | benchmark fallback mode と `ttp_mode: false` の minimal mode は中断せず、config と入力データから初回仮説の視聴者像を作る。`ttp_mode: true` の minimal mode はこの判定前に停止する |
| analytics mode で `viewing-scene-matrix.json pair` が存在しない | `ttp_mode: false` は `/wf-new` を中断し、`/channel-strategy --persona` で `/channel-strategy --scene` 実行と最終 `persona-definition.json pair` 更新を行うよう案内する。`true` は共通 fallback から視聴シーンを仮説化し、利用可能な根拠がなければ `判定不能` として続行する |
| benchmark fallback mode / minimal mode で `viewing-scene-matrix.json pair` が存在しない | benchmark fallback mode と `ttp_mode: false` の minimal mode は中断せず、仮説ペルソナから視聴シーンを仮説化する。`ttp_mode: true` の minimal mode はこの判定前に停止する |

## 関連

- `references/collection-lifecycle.md` — コレクション作成全体のライフサイクル
- `/channel-research --benchmark` skill 内の鮮度チェック実装（benchmark 側 `freshness_days` が真のソース）
- `.claude/skills/wf-new/references/collection-ideate.config.default.yaml` の `freshness_days` — 分析データの絶対鮮度チェック既定値（チャンネル側は `config/skills/collection-ideate.yaml` で上書き）
