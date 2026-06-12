import type { z } from "zod";

import {
  listSkillsService,
  SkillListInputSchema,
  SkillListOutputSchema,
} from "../skills-sync/index.ts";
import type { ServiceError } from "./errors.ts";
import type { Result } from "./result.ts";

// ADR-0004: core feature registry。feature 名 → {description, schema, deps, run} の
// data registry を core が所有し、packages/cli (citty defineCommand) と packages/mcp
// (MCP tool) はこの registry を各プロトコルへ変換する adapter のみを持つ
// (依存方向 core ← cli / core ← mcp は不変、cli ⇄ mcp の相互 import は oxlint で禁止)。
//
// naming convention: registry キーは dotted ("skills.list")。
//   - CLI adapter: subcommand 階層 (`yt skills list`)
//   - MCP adapter: underscore (`skills_list`)

// service が要求しうる重い依存の対応表。#826 (oauth) で client factory が入ったら
// interface へ拡張する (例: `youtube: youtube_v3.Youtube`)。
export type DepsMap = Record<never, never>;

// registry entry の契約。deps に宣言した key だけが run の第 2 引数に渡る
// (宣言漏れ・過多は compile error — ADR-0004 §2)。
export interface RegistryEntry<
  I extends z.ZodType = z.ZodType,
  O extends z.ZodType = z.ZodType,
  D extends keyof DepsMap = never,
> {
  readonly deps: readonly D[];
  readonly description: string;
  readonly inputSchema: I;
  readonly outputSchema: O;
  readonly run: (
    input: z.output<I>,
    deps: Pick<DepsMap, D>
  ) => Promise<Result<z.output<O>, ServiceError>>;
}

// per-entry に型推論を効かせる identity helper (deps と run の整合をここで検査する)。
const defineRegistryEntry = <
  I extends z.ZodType,
  O extends z.ZodType,
  D extends keyof DepsMap = never,
>(
  entry: RegistryEntry<I, O, D>
): RegistryEntry<I, O, D> => entry;

export const REGISTRY = {
  "skills.list": defineRegistryEntry({
    deps: [],
    description: "同梱スキル一覧を列挙する",
    inputSchema: SkillListInputSchema,
    outputSchema: SkillListOutputSchema,
    run: listSkillsService,
  }),
} as const;

export type RegistryKey = keyof typeof REGISTRY;
