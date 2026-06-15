# Core feature registry: name → {schema, service, deps} を core が所有し、CLI/MCP は adapter

## Context

ADR 0002 は「依存方向は core ← cli / core ← mcp の 1 方向のみ。cli と mcp は互いに独立」と決定したが、Phase 3 の計画 (#842 / #843) はこれと矛盾する形になっていた:

- #842 の AC: 「`packages/cli/src/registry.ts` から全 command を取得可能 (**将来 MCP server が同じ registry を import**)」
- #843 の本文: 「`packages/mcp/src/tools/index.ts`: **`packages/cli/src/registry.ts` の command registry を import** し、各 command を MCP tool に変換」

このまま実装すると mcp → cli の依存が生まれ、citty (CLI 専用依存) が MCP server の依存ツリーに入り、「どちらか片方しか load されないシナリオを許容」という ADR 0002 §4 の前提と、oxlint による thin-client fence の根拠が崩れる。

また sequencing の問題も観測された。#842 (citty dispatcher、HITL) は Phase 3 配置だが、Phase 2 の #837 は「batch 処理は CLI 側 `packages/cli/commands/{auto,collection}/cli.ts`、本 issue では skeleton のみ」と CLI command を先に量産する。analytics 系 10 issue も同様。convention が確定する前に AFK agent が現行 `yt-skills` の手書き argv parse スタイルを 12 回以上複製し、#842 で全件 retrofit になる。さらに「`[domain] message` 表示 + quota → exit 75」という Result→exit-code 方針は `packages/cli/skills-sync/cli.ts` 1 箇所にしか実装がなく、共通 helper はどの issue にも計上されていなかった。

## Decision

### 1. registry の実体は `packages/core/src/registry.ts` に置く

feature 名 → {description, inputSchema, outputSchema, deps, run} の **data registry** を core が所有する。cli / mcp はこの registry を import して、それぞれ自分のプロトコル (citty defineCommand / MCP tool) へ変換する adapter だけを持つ。**mcp → cli / cli → mcp の import は引き続き禁止** (ADR 0002 §4 不変)。

```typescript
// packages/core/src/registry.ts
import { z } from "zod";
import type { Result } from "./result.ts";
import type { ServiceError } from "./errors.ts";

/**
 * service が要求しうる重い依存の対応表。
 * #826 (oauth) 以降で youtube: youtube_v3.Youtube 等を追加する。
 */
export interface DepsMap {
  // youtube: youtube_v3.Youtube;                      // #826 で追加
  // youtubeAnalytics: youtubeAnalytics_v2.Youtubeanalytics; // #826 で追加
}

export interface RegistryEntry<
  I extends z.ZodType = z.ZodType,
  O extends z.ZodType = z.ZodType,
  D extends keyof DepsMap = never,
> {
  readonly description: string;
  readonly inputSchema: I;
  readonly outputSchema: O;
  /** run が必要とする deps を宣言する。宣言した key だけが run に渡る (型で拘束) */
  readonly deps: readonly D[];
  readonly run: (
    input: z.output<I>,
    deps: Pick<DepsMap, D>,
  ) => Promise<Result<z.output<O>, ServiceError>>;
}

export const REGISTRY = {
  "skills.list": {
    description: "同梱スキル一覧を列挙する",
    inputSchema: SkillListInputSchema,
    outputSchema: SkillListOutputSchema,
    deps: [],
    run: listSkillsService,
  },
  // 新 feature はここに 1 entry 追加するだけで CLI subcommand / MCP tool の両方に載る
} as const satisfies Record<string, RegistryEntry<z.ZodType, z.ZodType, never>>;
```

### 2. deps は typed `DepsMap` + `Pick` で宣言する

`deps: ["youtube"]` と宣言した entry の `run` 第 2 引数は `Pick<DepsMap, "youtube">` に確定する。宣言漏れ・宣言過多は compile error。deps の **組み立て** (token 入手 → client build) は adapter 側の責務: CLI は `getYouTubeClient()` (interactive 可、#826)、MCP は env token + `refreshTokenService` のみ (ADR 0003 §5)。

### 3. naming convention: registry キーは dotted

- registry キー: `skills.list` / `upload.video` / `analytics.channel` (dotted、小文字)
- CLI adapter: dot を subcommand 階層に展開 → `tayk skills list`（bin 名は ADR-0007 で `yt`→`tayk`）
- MCP adapter: dot を underscore に変換 → tool name `skills_list`

### 4. CLI flags は per-command 手書き、Result→exit-code は共通 helper

zod schema から CLI flags を自動導出しない (positional / alias / UX は schema に乗らない)。各 `packages/cli/src/commands/<feature>/cli.ts` は citty `defineCommand` で args を手書きし、registry entry の `run` を呼ぶ。出力整形と exit code は `packages/cli/lib/run-command.ts` の共通 helper に集約する:

- `r.ok` → stdout へ整形出力 (`--json` で raw JSON)
- `!r.ok` → stderr へ `[domain] message`、exit code は `quota` = 75 (EX_TEMPFAIL)、それ以外 = 1

### 5. #842 は Phase 2 の CLI 着手前に前倒しする

#842 の scope を「core registry + citty dispatcher + run-command helper + skills subcommand 化」に絞って先に実装し、convention を確定させる。Phase 2 で CLI command を伴う issue は本 ADR の convention に従う。

## Why

- **ADR 0002 §4 の維持**: registry を core に置けば cli / mcp は互いに独立のまま。MCP server の依存ツリーに citty が入らない
- **leverage**: 新 feature は core に entry 1 個追加するだけで CLI / MCP 両方に露出する。schema + service は既に core にある (ADR 0002/0003) ので、registry entry は数行の宣言で済む
- **locality**: description / deps 宣言が schema・service の隣 (core) に集まる。MCP tool の description を直すのに mcp package を触らない
- **AFK 適合**: `satisfies` + typed DepsMap で「宣言した deps だけが渡る」を compile が担保する。convention だけで 12+ AFK issue に deps 規約を守らせる必要がない
- **retrofit 回避**: convention が Phase 2 の量産前に確定することで、手書き argv parse の複製 12+ 件と Phase 3 での全件書き直しを防ぐ

## Considered Options

- **cli / mcp が各自で列挙 (registry なし)**: ADR 0002 違反は消えるが、feature 追加のたびに core + cli + mcp の 3 箇所を触る。MCP tool の自動生成 (leverage) を放棄することになり不採用
- **mcp → cli registry import (#843 原案)**: ADR 0002 §4 違反。citty が MCP に混入。不採用
- **zod schema から CLI flags を自動導出**: flat schema なら可能だが、positional args / alias / interactive prompt が schema に表現できず、CLI UX が schema 都合に縛られる。flags 手書き + service 共有で十分。不採用
- **lazy ctx (全 deps を getter で渡す)**: generic 不要でシンプルだが、「どの tool が何を使うか」が型から見えず、MCP 側で per-tool の権限・credential 制御をする将来に拡張できない。不採用

## Enforcement

### Mechanical (oxlint)

`oxlint.config.ts` の per-file overrides に追加:

- `packages/mcp/**` から `packages/cli/**` への import を **error** (`no-restricted-imports`)
- `packages/cli/**` から `packages/mcp/**` への import を **error**
- 既存 fence (cli/mcp から googleapis 等の直 import 禁止、ADR 0002) は不変

### Review (子 issue PR self-review チェック)

- [ ] 新 feature を `REGISTRY` に登録したか (entry なしの service は CLI/MCP から見えない)
- [ ] `deps` 宣言と service signature が一致しているか (`satisfies` が通っていれば OK)
- [ ] CLI command が `run-command.ts` の共通 helper を使い、独自に exit code を決めていないか

## Consequences

- **#842 の scope 変更**: 「`packages/cli/src/registry.ts`」→「`packages/core/src/registry.ts` + cli は adapter」。Phase 3 → Phase 2 前へ前倒し
- **#843 の修正**: tools/index.ts は `packages/core/src/registry.ts` を import する。blocked-by は #842 のまま
- **DepsMap の拡張**: #826 (oauth) が `youtube` / `youtubeAnalytics` を DepsMap に追加する。googleapis の型 import は type-only で core に入る
- **ADR 0002 canonical template の追記**: 新 feature の手順に「(4) `REGISTRY` に entry を登録する」が加わる
- **`yt-skills` bin の廃止**: `tayk skills list` に統合 (#842、bin 名 ADR-0007)。Python 側 cutover (#790) までは下流に影響なし

## Related

- ADR 0002: Service-first architecture (依存方向の決定元。本 ADR は §4 を維持する実装形)
- ADR 0003: Service-boundary contracts (Result / ServiceError / auth seam。run-command helper はこの契約の CLI 側終端)
- Epic #727 / umbrella PR #791
- #842 (citty dispatcher → 本 ADR で scope 変更 + 前倒し) / #843 (MCP server → import 元を core に修正)
