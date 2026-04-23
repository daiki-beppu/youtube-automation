# 前提スキル鮮度判定ルール

`/ideate` の Phase 1 を開始する前に、前提スキルの出力が最新であることを確認する。
鮮度判定の結果に応じて、古いスキルの再実行を（ユーザーに）案内する。

## 順序依存

前提スキルは **(analyze ∥ benchmark) → persona → viewing-scene** の構造:

- `/analyze` と `/benchmark` は**独立・並列**（両者とも生データの分析で上下関係なし）
- `persona` は最新ベンチマークのタグデータを入力とする
- `viewing-scene` は `persona-definition.md` を入力とする

**analyze / benchmark は並列判定。その後 persona → viewing-scene を直列で判定する。** persona / viewing-scene は存在チェックのみ（mtime 比較なし。更新タイミングは戦略判断のため人間が決める）。stale または未生成を検出したら Phase 1 を中断し、該当スキルの実行をユーザーに促す。

## 鮮度判定表

| 順序 | 前提スキル | 出力ファイル | 鮮度判定ルール | 古い / 未生成の場合 |
|---|---|---|---|---|
| 1a | `/analyze` | `reports/analysis_*.md` | 最新 `data/analytics_data_*.json` のファイル名日付 (YYYYMMDD) より古ければ stale | `/ideate` を中断し、ユーザーに `/analyze`（必要なら `/collect` 先行）の実行を案内。**自動呼び出し不可**（AI 推論コスト発生のため） |
| 1b | `/benchmark` | `docs/benchmarks/*.md` + `data/benchmark_YYYYMMDD.json` | mtime が `config/skills/benchmark.yaml` の `freshness_days`（既定 3 日）より古ければ stale | `/benchmark` を Skill ツールで実行（内部で鮮度チェック + 差分更新） |
| 2 | `/persona` | `docs/channel/personas/persona-definition.md` | 存在すれば OK（mtime 比較なし。更新タイミングは戦略判断のため人間が決める） | ユーザーに `/persona` 実行を案内（自動呼び出しはしない — ペルソナ選択に `AskUserQuestion` が必要なため） |
| 3 | `/viewing-scene` | `docs/plans/viewing-scene-matrix.md` | 存在すれば OK（mtime 比較なし。persona 下流のため連動して判断） | ユーザーに `/viewing-scene` 実行を案内（自動呼び出しはしない — シーン選択に `AskUserQuestion` が必要なため） |

## workflow-state.json との同期

コレクションディレクトリ側（`collections/planning/<name>/workflow-state.json`）の `phase` 値と前提スキルの状態は以下のように対応する:

| workflow-state.phase | 想定される前提スキル状態 |
|---|---|
| `planning` | benchmark / persona / viewing-scene は `/ideate` セッション内で最新化される |
| `thumbnail-*` 以降 | ideate はすでに完了している。ideate に戻るときは前提スキルを改めて鮮度判定する |

## 判定擬似コード

```bash
# 1a. analyze — 日付粒度の stale 判定
LATEST_DATA=$(ls -t data/analytics_data_*.json 2>/dev/null | head -1)
LATEST_REPORT=$(ls -t reports/analysis_*.md 2>/dev/null | head -1)

if [ -z "$LATEST_REPORT" ]; then
  echo "analyze 未生成 → /ideate 中断、/collect → /analyze 先行を案内"
  exit 1
fi

if [ -n "$LATEST_DATA" ]; then
  DATA_DATE=$(echo "$LATEST_DATA" | grep -oE '[0-9]{8}' | head -1)
  REPORT_DATE=$(echo "$LATEST_REPORT" | grep -oE '[0-9]{8}' | head -1)
  if [ "$DATA_DATE" -gt "$REPORT_DATE" ]; then
    echo "analyze stale（data の方が新しい日付）→ /ideate 中断、/analyze 再実行を案内"
    exit 1
  fi
fi

# 1b. benchmark — /benchmark スキル内の鮮度チェックに委譲
#    （freshness_days より古い md があれば自動更新）

# 2. persona — 存在チェックのみ
if [ ! -f docs/channel/personas/persona-definition.md ]; then
  echo "persona 未定義 → /persona を案内"
fi

# 3. viewing-scene — 存在チェックのみ
if [ ! -f docs/plans/viewing-scene-matrix.md ]; then
  echo "viewing-scene 未定義 → /viewing-scene を案内"
fi
```

## 再実行トリガー条件まとめ

| 発動条件 | 対応 |
|---|---|
| `reports/analysis_*.md` が存在しない | `/ideate` を中断し、`/collect → /analyze` の先行実行を案内 |
| `reports/analysis_*.md` が最新 `data/analytics_data_*.json` より古い日付 | `/ideate` を中断し、`/analyze` の再実行を案内 |
| `data/benchmark_*.json` が 3 日より古い | `/benchmark` を Skill ツールで自動実行 |
| `persona-definition.md` が存在しない | `/ideate` を中断し、`/persona` の先行実行を案内 |
| `viewing-scene-matrix.md` が存在しない | `/ideate` を中断し、`/viewing-scene` の先行実行を案内 |

## 関連

- `references/collection-lifecycle.md` — コレクション作成全体のライフサイクル
- `/benchmark` skill 内の鮮度チェック実装（`freshness_days` が真のソース）
