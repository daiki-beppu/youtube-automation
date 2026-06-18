import type { z } from "zod";

import type { ChannelConfig } from "./config/index.ts";
import type { ServiceError } from "./errors.ts";
import type { ImageProvider } from "./image/index.ts";
import {
  GenerateImageInput,
  GenerateImageOutput,
  generateImageService,
} from "./image/index.ts";
import type { YouTubeAnalyticsClient, YouTubeClient } from "./oauth/client.ts";
import type { Result } from "./result.ts";
import {
  listSkillsService,
  SkillListInputSchema,
  SkillListOutputSchema,
  SkillSyncInputSchema,
  SkillSyncOutputSchema,
  syncAssetService,
} from "./skills-sync/index.ts";
import {
  generateSunoPromptsService,
  GenerateSunoInputSchema,
  GenerateSunoOutputSchema,
} from "./suno-prompts/index.ts";

// ADR-0004: core feature registry。feature 名 → {description, schema, deps, run} の
// data registry を core が所有し、packages/cli (citty defineCommand) と packages/mcp
// (MCP tool) はこの registry を各プロトコルへ変換する adapter のみを持つ
// (依存方向 core ← cli / core ← mcp は不変、cli ⇄ mcp の相互 import は oxlint で禁止)。
//
// naming convention: registry キーは dotted ("skills.list")。
//   - CLI adapter: subcommand 階層 (`tayk skills list`)
//   - MCP adapter: underscore (`skills_list`)

// service が要求しうる重い依存の型対応表 (#993)。各 service は deps 配列で必要な key
// だけを宣言し、Pick<DepsMap, D> で run の第 2 引数を compile-time に確定させる。
//   - config:      ChannelConfig (#961 前倒し。service は loadConfig() を内部呼びしない)
//   - imageProvider: Gemini / OpenAI image provider
//   - yt:          YouTube Data API v3 client
//   - ytAnalytics: YouTube Analytics API v2 client (最小権限: analytics service は yt に触れない)
// 個別 client を載せるのは最小権限の原則。token ではなく構築済み client を注入する。
export interface DepsMap {
  channelDir: string;
  config: ChannelConfig;
  imageProvider: ImageProvider;
  yt: YouTubeClient;
  ytAnalytics: YouTubeAnalyticsClient;
}

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
  "image.generate": defineRegistryEntry({
    deps: ["channelDir", "imageProvider"],
    description: "Gemini / OpenAI provider で画像を生成して保存する",
    inputSchema: GenerateImageInput,
    outputSchema: GenerateImageOutput,
    run: (input, deps) =>
      generateImageService(input, {
        channelDir: deps.channelDir,
        provider: deps.imageProvider,
      }),
  }),
  "skills.list": defineRegistryEntry({
    deps: [],
    description: "同梱スキル一覧を列挙する",
    inputSchema: SkillListInputSchema,
    outputSchema: SkillListOutputSchema,
    run: listSkillsService,
  }),
  "skills.sync": defineRegistryEntry({
    deps: [],
    description: "同梱資産 (skills / CLAUDE.md) を対象リポジトリへ配布する",
    inputSchema: SkillSyncInputSchema,
    outputSchema: SkillSyncOutputSchema,
    run: syncAssetService,
  }),
  "suno.generate": defineRegistryEntry({
    deps: ["channelDir"],
    description: "Suno UI 投入用 Style / Lyrics prompt を生成する",
    inputSchema: GenerateSunoInputSchema,
    outputSchema: GenerateSunoOutputSchema,
    run: generateSunoPromptsService,
  }),
} as const;

export type RegistryKey = keyof typeof REGISTRY;
