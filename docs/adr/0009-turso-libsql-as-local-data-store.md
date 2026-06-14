# Turso (libSQL) をローカルデータストアとして導入

## Status

accepted (2026-06-15)

## Context

現行の Python 版はすべてのランタイムデータ（analytics スナップショット、コスト追跡、投票ログ、コレクション状態、ベンチマーク）を JSON ファイルで保存している。この方式には 3 つの構造的問題がある:

1. **クロスクエリが高コスト** — 「planning 中の全コレクションで videoup 完了済み」のような横断検索に `find` + `jq` が必要
2. **LLM トークンの浪費** — skill が JSON を全読みして LLM コンテキストに載せるため、1 回の `/wf-status` で ~34,000 tokens を消費。SQL なら結果行だけで ~2,000 tokens（94% 削減）
3. **時系列分析の非効率** — pandas DataFrame を毎回 JSON から組み立て直す。日次メトリクスの正規化テーブルがあれば直接集計できる

TS rewrite（epic #727）が進行中であり、Python 側にデータ層を作り込んでも cutover で捨てることになる。

## Decision

`feat/ts-rewrite` ブランチに **Turso（libSQL）** を **ローカル embedded DB** として導入し、**Drizzle ORM** で管理する。

### スコープ

DB に入れるもの:

| データ | テーブル設計 |
|---|---|
| Analytics 日次メトリクス | 完全正規化（`video_daily_metrics`）。API レスポンスのスキーマ揺れはインジェスト時に吸収 |
| コスト追跡 | 正規化（`cost_entries`） |
| 投票ログ | 正規化（`vote_log`） |
| コレクション状態 | 状態テーブル（`collections`）+ イベントログ（`collection_events`）の 2 層。ファイルパスが canonical ID |
| ベンチマーク時系列 | 正規化（`benchmark_snapshots`） |

DB に入れないもの:

- **チャンネル設定**（`config/channel/*.json`）— git 管理・diff 可視性が重要。SSOT は JSON のまま

### 配置

- 1 チャンネル = 1 DB ファイル: `<CHANNEL_DIR>/data/local.db`（`.gitignore` 対象）
- チャンネル横断クエリは `ATTACH` で対応（頻度が低いため）

### マイグレーション

- Drizzle Kit（`drizzle-kit generate`）が `.sql` マイグレーションファイルを自動生成
- 言語非依存の `.sql` が git に残るため、将来の技術選定変更時にも参照可能

### 既存データの投入

- 使い捨てインポートスクリプトで既存 JSON を全量投入（数万行規模で処理時間は問題にならない）

### クエリ手段

- `tayk db` CLI サブコマンド（定型レポート）
- skill からの DB 参照（LLM トークン削減の本命）
- Drizzle Studio / SQLite 互換クライアント（アドホック探索）

## Why

- **SQLite ではなく Turso (libSQL)**: SQLite 互換のローカル性能を維持しつつ、将来のベクトル類似検索（コレクション重複検出、SEO カニバリ検出）やリモート同期（embedded replica）へのアップグレードパスを確保する。初期はローカル embedded のみで運用し、ベクトル・リモートは具体的ニーズが出てから追加する
- **Drizzle ORM**: TS rewrite と同じスタック。スキーマ定義が TS 型と DB スキーマの SSOT になり二重管理がない。Drizzle Kit が生成する `.sql` は言語非依存で可読性も保てる
- **コレクション状態の 2 層モデル（状態 + イベントログ）**: `/wf-status` は最新 phase を即引きしたい（`collections` テーブル）。一方「suno → videoup に何日かかった？」の振り返りにはイベント履歴が要る（`collection_events`）。transaction で atomic 更新すれば整合性は保てる
- **設定を DB に入れない**: 変更頻度が低く（開設時 1 回 + 微調整）、git diff で履歴を追える価値の方が高い。DB に入れると「直したつもりが反映されてない」事故が起きやすい

## Consequences

- `feat/ts-rewrite` の `packages/core/` に Drizzle 依存が加わる
- 下流チャンネルリポの `.gitignore` に `data/local.db` 追加が必要
- analytics 収集スクリプト（TS 版）は JSON 保存から DB INSERT に書き換え
- skill が DB を参照するためのヘルパー（`tayk db query` 相当）が必要
- JSON スナップショットの保存は廃止できるが、移行期は並行出力も可

## Related

- ADR-0001 / ADR-0002（TS rewrite アーキテクチャ）
- ADR-0004（registry — `tayk db` サブコマンドの登録先）
- Epic #727（TS rewrite）/ #790（cutover）
