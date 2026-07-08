# tayk を専用の別リポで 0 ベース開発し、本リポの packages/ を削除する

## Status

accepted (2026-07-08)。ADR-0001 の「同一リポ big-bang branch」戦略と ADR-0008 の merge/同期プロトコルを supersede する。ADR-0015 のタイムライン・スコープゲートも本 ADR で失効（順次リリース方式に転換）。

## Context

ADR-0001 以降、TS リライトは同一リポの `feat/ts-rewrite` → main 統合 (#791 merge 済み) で進めてきたが、進捗は約 1 ヶ月で CLI 3 コマンド (`generate-master` / `generate-suno` / `skills`)。#772 では 1 コマンドの移植にレビュー修正 6 ラウンド（毎回 8〜10 ファイル・100〜300 行）を要した。原因は 2 つ:

1. **セレモニーの表面積** — ADR-0003/0004 の「1 機能 = schema + service + index + registry + CLI adapter + テスト 2 種」構造が、レビュアーに無限の cross-file 指摘面を与える
2. **Python parity という無限の指摘源** — CONTEXT.md は「移植ではなくスクラップ&ビルド」と再定義済みだったが、Python コードが同居する限り実践は parity 移植に回帰し、レビューは常に旧実装との差分を新たな指摘として生産できた

## Decision

1. **tayk は専用の別リポジトリで 0 ベース開発する**。「Python の移植」ではなく「仕様ベースの新規プロダクト」として作る。既存 `packages/` のコード・ADR-0002〜0004 のセレモニー構造は引き継がない
2. **本リポの `packages/` (TS 28K 行) と TS ツールチェーン (bun / oxlint / knip の CI レーン) は即削除する**。参照は git 履歴で足りる
3. **本リポは Python 版のメンテナンスモードに純化する**。Python の削除（cutover）は「first-party 下流の日常運用が tayk のみで回る」時点で判断し、tayk のリリース単位とは独立
4. **tayk v0.1.0 のゲートは縦スライス 1 本** — collection のフルライフサイクル 1 周（TTP ベンチマーク収集 → 企画 → 音源 → 動画 → upload → description）を first-party チャンネルで dogfood 完走できること。運用の根幹が TTP のため競合ベンチマーク収集は必須スコープ。一方、自チャンネルの実績分析（analytics-analyze / postmortem / dashboard）・knowledge codec 全 5 本・Remotion は v0.2 以降に 1 リリース 1 テーマで直列に積む。tracer は `collection.plan`（CONTEXT.md 参照 — benchmark 収集 → local store → read model → 企画で SSOT 設計を最初に end-to-end 検証できる）
5. **下流チャンネルリポとの契約**: ① 設定 (`config/channel/*.json`) は git 管理 JSON のまま維持。② 状態・履歴は local store (ADR-0017) を SSOT とし「ディレクトリ位置 = 状態」の暗黙表現を廃止。読み取りは local store の read model に一本化する（データ 4 分類は CONTEXT.md 参照）

## Why

- **物理分離が唯一 parity 回帰を止める**: 紙の上のフレーミング転換 (CONTEXT.md) では実践が移植に戻ることが実証された。Python コードが見えない別リポでは「旧実装との差分」というレビュー指摘のカテゴリ自体が消滅する
- **旧 TS コードを残さない**: 0 ベースの動機がセレモニー構造からの脱却である以上、旧コードが目の前にあると agent も人間も旧構造をコピペで引きずる
- **フルスコープゲートの放棄**: ADR-0015 のフルスコープ (7 点セット) を v0.1.0 のゲートにする方式が死のループの一因。機能は捨てず、順番に直列化する

## Considered Options

- **同一リポで継続 (ADR-0001 維持)**: parity 回帰と 2 ライン分岐 (ADR-0008 Amendment) が構造的に再発する。不採用
- **`packages/` を凍結して残す**: リファレンスとして有用に見えるが、旧構造のコピペ源になり、agent の「TS fix はここ」誤認事故も続く。git 履歴で代替可能。不採用
- **下流契約 (config 形式) も刷新**: SSOT 混乱の実体は ② 状態の表現であり、① 設定の JSON 形式は運用検証済み (ADR-0009)。ツール内部とデータ契約を同時に動かすと失敗の切り分けが不能になるため、① は維持

## Consequences

- 新リポへ「引き継ぐ決定」を明示する: ADR-0006 (npm 配布) / 0007 (tayk ブランド) / 0009 (JSON-only config) / 0017 (libSQL local store) / CONTEXT.md の MCP tool 2 層・knowledge codec・collection lifecycle 用語系。引き継がない決定: ADR-0002〜0004 (service registry セレモニー) / 0008 (merge 戦略)
- epic #727 と cutover issue #790 は本 ADR を出典として再編する
- 外部ユーザー (数十人規模) への移行告知 `docs/migration/python-to-tayk.md` は **日付を撤回しイベントベースに書き換える** — 「Python 版は tayk が実運用カバレッジに達するまでメンテナンスモードで維持。次の告知は dogfood 完走後」。日付ベース計画は 2 回連続破綻 (ADR-0015 本文 → Amendment) しており、3 度目の日付は約束しない
- 新リポの開発も takt メイン。workflow は組み込み default (9 step) を素のまま使い、レビュー終了条件 (仕様引用必須 / ラウンド上限) は予防的には入れない — tracer 実装でレビューが 3 ラウンドを超える再発が観測されたら、その実データを根拠に導入する
- 新リポ側の初期 ADR として、薄いアーキテクチャ規約 (1 MCP tool = 実装 1 ファイル + テスト 1 ファイル、registry レス) を起票する。CONTEXT.md の初期内容は本リポのグロッサリから MCP tool 2 層 / adapter / knowledge codec / collection lifecycle / データ 4 分類 / read model を移植する

## Related

- ADR-0001 / 0008 / 0015 (superseded・失効) / ADR-0017 (引き継ぎ) / CONTEXT.md「データ 4 分類」「read model」「cutover」
