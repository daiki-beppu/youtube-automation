# Metadata 層は config boundary 通過後の純演算: zod 化・Result 化を強いる parse surface を持たない

## Context

#825 (config 15 file の zod 化) のオリジナル scope には `packages/core/src/metadata/*.ts` (5 file = `collection.ts` / `format.ts` / `tracks.ts` / `shorts.ts` / `loc-data.ts`) の zod 化が含まれていたが、takt run の検証で「これら 5 file は JSON parse surface を持たない純関数 / 検証済み accessor であり、規定パターン (`z.object().strict().transform(snakeToCamel)` + `z.infer`) は適用不可能」と判明し、#825 は config 側に scope を絞って merge された。残された「metadata 5 file をどう扱うか」が #921 として宙に浮いていた。

2026-06-12 のアーキテクチャレビュー (PR#791) でコードを再検証した結果も同じ事実を示した:

- `grep -rn 'JSON.parse|readFileSync|readFile|fromJson|merged' packages/core/src/metadata/` → 0 件
- `format.ts` = 純文字列パーサ (Python `str.format` の移植)、`loc-data.ts` = 検証済み `config.localizations.data` への型付き accessor、`collection.ts` / `shorts.ts` / `tracks.ts` = camelCase 引数の純関数
- fs I/O・外部入力はすべて caller 責務として既に分離済み (例: afinfo / workflow-state は引数で受け取る)

一方で `packages/core/src/metadata.ts` (barrel) は 24+ export を露出しており、caller が title / description / localizations の呼び順・組み立てを知る必要がある。この外向きの浅さは #841 (metadata facade refactor) が `generateVideoMetadataService` 1 canonical entry への集約として既に計画している。

## Decision

#921 の選択肢 (a) を採用し、以下を確定する:

1. **metadata 層は config boundary 通過後の純演算層である。** 入力は `z.infer<typeof ConfigSchema>` 等から派生した検証済みの typed argument であり、独立した parse surface を持たない
2. **個々の metadata 関数に input schema / `Result` 返却を後付けしない。** boundary parse は config 側 (#825) で完了しており、二重 validation は意味のない zod wrapper の fabrication になる
3. **外向き interface は #841 の facade (`generateVideoMetadataService`) が担う。** service 境界 (ADR 0002/0003: schema + `Result<T, ServiceError>`) は facade の 1 箇所にだけ立て、内部 helper (`internals/`) は throw OK の純関数のまま維持する
4. **将来 metadata 層に新たな parse surface が生まれた場合** (例: seed JSON ロード、外部 LLM レスポンスの validate) は、その経路だけ個別に schema + Result 化する (#921 選択肢 (c) の個別適用)。全 helper への一括適用はしない

## Why

- **削除テスト**: metadata helper に schema を足しても消える複雑さがない — caller は既に typed value を渡しており、schema は「型が保証済みの値を再検証する」だけの pass-through になる
- **locality**: エラーの発生点は「外部入力の boundary」(config loader / 将来の facade 入口) に集約済み。純関数内の throw は programming error であり、Result で運ぶ価値がない (ADR 0003 が core 内部 throw を許容しているのと同じ理由)
- **#841 との整合**: facade 1 箇所に service 境界を立てる設計は、本 ADR の「boundary は 1 つ、内部は純演算」とちょうど噛み合う。(a) と (c) は対立ではなく合成できる
- **AFK 適合**: 「pure helper に zod wrapper を足さない」を明文化しないと、ADR 0003 の canonical template を見た AFK agent が metadata にも機械適用して fabrication を量産するリスクがある (#825 の takt run が 18/30 iteration 非収束に陥った原因の一つ)

## Considered Options

- **(b) 各 metadata 関数に input schema + Result 化 (不採用)**: 二重 validation の overhead のみ。検証済み入力に対する zod wrapper は fabrication であり、coder policy とも矛盾する
- **(c) を今すぐ全面適用 (不採用)**: 現時点で metadata 層に parse surface は存在しない。将来の新規境界に個別適用する方針として Decision 4 に縮退して取り込んだ
- **barrel 維持 + 全 export 公開のまま (不採用)**: 外向きの浅さ (24+ export) が残る。#841 が facade 集約を計画済みであり、本 ADR はそれを前提とする

## Consequences

- **#921 を closes**: 本 ADR が #921 の AC「decision として確定し明文化」を充足する。実装変更は不要 (現状維持が decision)
- **#841 の前提明記**: facade 実装時、`internals/` 配下の helper は schema / Result を持たない純関数のまま移動する。#841 の AC にある「ADR-0003 の canonical template に準拠」は **facade (service.ts) にのみ適用**し、internals には適用しない
- **新規 metadata helper の規約**: 純関数 + typed argument で書く。外部入力を読む必要が出たら、その読み込みだけを facade or 専用 service に切り出す
- **レビュー観点**: metadata 配下の PR で `z.object(...)` が internals に現れたら「parse surface が本当に存在するか」を確認する

## Related

- ADR 0002: Service-first architecture (service 境界の定義)
- ADR 0003: Service-boundary contracts (core 内部 throw 許容 / boundary での Result 化)
- ADR 0004: Core feature registry (facade が registry に載る将来形)
- #921 (本 ADR が decision を確定) / #825 (descope 元) / #841 (facade refactor、本 ADR と合成)
- Epic #727 / umbrella PR #791
