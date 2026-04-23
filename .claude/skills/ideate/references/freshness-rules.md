# 前提スキル鮮度判定ルール

`/ideate` の Phase 1-2 を開始する前に、前提スキルの出力が最新であることを確認する。
鮮度判定の結果に応じて、古いスキルの再実行を（ユーザーに）案内する。

## 順序依存

前提スキルは **benchmark → persona → viewing-scene** の順に依存している:

- `persona` は最新ベンチマークのタグデータを入力とする
- `viewing-scene` は `persona-definition.md` を入力とする

**順序依存があるため上から順に直列で判定する。** 1 benchmark → 2 persona → 3 viewing-scene の順に通過させる。persona / viewing-scene は存在チェックのみ（mtime 比較なし。更新タイミングは戦略判断のため人間が決める）。未生成だった場合は Phase 1-2 を中断し、該当スキルの実行をユーザーに促す。

## 鮮度判定表

| 順序 | 前提スキル | 出力ファイル | 鮮度判定ルール | 古い / 未生成の場合 |
|---|---|---|---|---|
| 1 | `/benchmark` | `docs/benchmarks/*.md` + `data/benchmark_YYYYMMDD.json` | mtime が `config/skills/benchmark.yaml` の `freshness_days`（既定 3 日）より古ければ stale | `/benchmark` を Skill ツールで実行（内部で鮮度チェック + 差分更新） |
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
# 1. benchmark — /benchmark スキル内の鮮度チェックに委譲
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
| `data/benchmark_*.json` が 3 日より古い | `/benchmark` を Skill ツールで自動実行 |
| `persona-definition.md` が存在しない | `/ideate` を中断し、`/persona` の先行実行を案内 |
| `viewing-scene-matrix.md` が存在しない | `/ideate` を中断し、`/viewing-scene` の先行実行を案内 |

## 関連

- `references/collection-lifecycle.md` — コレクション作成全体のライフサイクル
- `/benchmark` skill 内の鮮度チェック実装（`freshness_days` が真のソース）
