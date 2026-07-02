# Service-first architecture: zod schema as source of truth, MCP/CLI as thin clients

## Status

accepted (2026-06-02)。実装は `feat/ts-rewrite` 上で進行中（cutover #790 で main へ反映予定）。

## Context

ADR 0001 で確定した「Python → TS(bun) big-bang 移行」は `packages/core` (純ロジック) + `packages/cli` (yt-* 群) + 将来の `packages/mcp` (MCP server) の 3 workspace 構造で進む。60+ 子 issue を AFK agent (takt) が並列に書き、最終的に MCP server から CLI と同じ機能を expose する設計。

ここで暗黙の「どう書くか」を放置すると、AFK loop の途中で AI agent ごとに service 関数の境界・型導出・依存方向がブレ、cutover #790 で

- CLI が直接 `googleapis` を import している (MCP 経由で expose できない)
- MCP tool が CLI に shell-out している (型情報がない)
- schema が CLI / MCP / service の 3 箇所で重複定義されている

といった retrofit を強要される。これを convention だけで防ぐのは 60+ AFK では不可能で、**mechanical enforcement** が要る。

## Decision

`packages/core` 配下の domain feature は以下のシェイプで実装し、`packages/cli` と将来の `packages/mcp` はその service 関数を呼ぶ薄いラッパとする:

1. **zod schema が input/output の正**: `packages/core/<feature>/schema.ts` に input / output schema を zod で定義し、TypeScript 型は `z.infer<typeof Schema>` で導出する。schema を別途 `interface` で書き直さない
2. **service 関数が単一エントリ**: `packages/core/<feature>/service.ts` が input schema を受け取り output schema に従う Promise を返す。境界で `Schema.parse()` を必ず通す
3. **CLI / MCP は schema を再宣言しない**: thin wrapper として service だけを呼ぶ。引数 parse → service 呼び出し → 整形出力 のみ。`googleapis` / `sharp` / `google-auth-library` 等の重い依存を直接 import しない
4. **依存方向は core ← cli / core ← mcp の 1 方向のみ**: core から cli/mcp への逆依存禁止。cli と mcp は互いに独立 (どちらか片方しか load されないシナリオを許容)

## Why

- **AI agent 適合**: zod schema は LLM が読みやすく、型推論で `z.infer` を引き出せば AI が書き間違える余地が減る。同じ schema を hand-written `interface` と並べると drift が必ず起きる
- **MCP 経由 expose の前提条件**: MCP tool は input schema を JSON Schema として宣言する必要がある。zod は `zod-to-json-schema` 等で MCP 互換に変換できるが、interface だけだとできない
- **enforcement の現実性**: oxlint の `no-restricted-imports` で「`packages/cli/**` から `googleapis` を import 禁止」を機械担保できる。convention だけで 60+ AFK issue を守らせるのは無理
- **CLI と MCP の DRY**: yt-channel-status と mcp `tool: get_channel_status` が同じ service を呼ぶ。CLI に business logic を書くと MCP 化のときに移植が二度手間

## Considered Options

- **convention only (本 ADR 不採用案)**: README / CONTRIBUTING に書くだけ。**60+ AFK issue で必ず崩れる** ため不採用
- **type-level fence (`internal` brand 型で service だけが core 関数を呼べる)**: TypeScript 型操作で表現できるが、AI agent が type magic を読み解いて回避してしまうリスクがある。lint rule の方が直接的
- **DI container (tsyringe / inversify) 化**: service 関数を class にして DI で差し替え可能にする。CLI / MCP の差し替えにはオーバースペック、static import で十分。yagni
- **zod 以外の schema library (valibot / arktype)**: valibot は bundle size 最適だが MCP server で問題にならない。arktype は構文が独自で AI agent の出力が安定しない。**zod は MCP SDK (`@modelcontextprotocol/sdk`) が peer dependency 化しているデファクト**で、本 epic の依存ツリーで重複しないため zod を採用

## Canonical Template

新規 feature `<feature>` (例: `skills-sync`, `errors`, `secrets`) を `packages/core` に追加するときは、以下の 3 ファイルから始める:

> **📁 配置規約 (2026-06-14) / template は ADR-0003 が上書き**: 本節のテンプレは ADR-0003 の Canonical Template が最新版で上書きしている。配置は **`src/` あり**が canonical — core feature は **`packages/core/src/<feature>/`**、CLI command は **`packages/cli/src/commands/<feature>/`**。skills-sync / internal の `src` なし実装は #984 で移送する。

### `packages/core/src/<feature>/schema.ts`

```typescript
import { z } from "zod";

export const FeatureInputSchema = z.object({
  // example: target: z.string(), force: z.boolean().default(false)
});

export const FeatureOutputSchema = z.object({
  // example: synced: z.array(z.string()), skipped: z.array(z.string())
});

export type FeatureInput = z.infer<typeof FeatureInputSchema>;
export type FeatureOutput = z.infer<typeof FeatureOutputSchema>;
```

### `packages/core/src/<feature>/service.ts`

```typescript
import { FeatureInputSchema, FeatureOutputSchema } from "./schema.ts";
import type { FeatureInput, FeatureOutput } from "./schema.ts";

export async function featureService(input: FeatureInput): Promise<FeatureOutput> {
  const parsed = FeatureInputSchema.parse(input);
  // ...重い依存 (googleapis / sharp 等) は core 内でのみ import...
  const result = { /* ... */ };
  return FeatureOutputSchema.parse(result);
}
```

### `packages/cli/src/commands/<feature>/cli.ts` (thin wrapper)

```typescript
import { featureService, FeatureInputSchema } from "@youtube-automation/core/<feature>";

export async function runFeatureCli(argv: string[]): Promise<void> {
  // 引数を parse して FeatureInputSchema に渡せる形に整える
  const input = FeatureInputSchema.parse({ /* argv から組み立てる */ });
  const output = await featureService(input);
  // 整形出力 (console.log / process.stdout.write)
  console.log(JSON.stringify(output, null, 2));
}
```

### 将来 `packages/mcp/src/tools/<feature>.ts` (今 epic では未実装)

```typescript
import { z } from "zod";
import { featureService, FeatureInputSchema } from "@youtube-automation/core/<feature>";

// MCP tool 定義は同じ FeatureInputSchema を inputSchema として再利用
export const featureTool = {
  name: "feature",
  description: "...",
  inputSchema: FeatureInputSchema,
  handler: async (input: z.infer<typeof FeatureInputSchema>) => {
    return await featureService(input);
  },
};
```

## Out of Scope (post-#727 別 epic)

本 ADR は **single-user CLI/MCP の TS rewrite** に限定する。以下は別 epic として ADR を別途切る (本 ADR には記載しない):

- subscription / entitlement enforcement (有料機能ゲート)
- queue / job model (長時間 job の async 化、retry / cancel)
- user/workspace 単位の multi-tenancy (auth / config / 1Password の tenant 分離)

これらは architectural shape を service interface 越しに後付けで導入可能 (entitlement は service 入口で check、queue は service を job worker から呼ぶ、tenant は input schema に context 追加) なので、本 ADR の決定と矛盾しない。

## Enforcement

### Mechanical (oxlint)

`oxlint.config.ts` の per-file overrides で以下を強制する:

- `packages/cli/**` および `packages/mcp/**` から `googleapis`, `google-auth-library`, `sharp`, `@modelcontextprotocol/sdk` の直 import を **error** にする (`no-restricted-imports`)
- `packages/core/**` は disable (core 内では当然許可)

ローカル `bun run lint` と CI `ts-lint` ジョブの両方で fail する。**convention に頼らない**。

### Review

子 issue PR の self-review チェックリストに以下を含める:

- [ ] core feature が schema.ts / service.ts に分離されているか
- [ ] CLI / MCP が `@youtube-automation/core/<feature>` の **named import** のみで service を呼んでいるか (重い依存の直 import なし)
- [ ] zod schema → `z.infer` で型を導出しているか (`interface` と並書していないか)

## Consequences

- **新 lint rule の retrofit**: 本 ADR が main に landed した後、`feat/ts-rewrite::oxlint.config.ts` に rule を反映する別 commit (#727 配下) が要る
- **#732 acceptance criteria 更新**: first tracer (yt-skills list) は本 ADR の canonical template に従って実装する。「`packages/core/skills-sync/{schema,service}.ts` 構造」を acceptance に追記する
- **zod 依存追加**: `packages/core/package.json` に `zod` 依存を追加する初回 issue は #732 (template 確立)
- **既存 PoC との関係**: `poc/ts-rewrite/` は本 ADR の対象外 (撤退判定用 PoC は独立 workspace、本番コードではない)
- **将来の `packages/mcp` 導入時**: service 関数の再利用で MCP tool 化が機械的になる。新規 service を書かなくて済む

## Related

- ADR 0001: Python → TypeScript(bun) big-bang 移行 (本 ADR の前提)
- Epic #727: TS rewrite (本 ADR の対象)
- Future epics (本 ADR で起票): subscription / queue / multi-tenancy
