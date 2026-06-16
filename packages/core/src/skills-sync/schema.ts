import { z } from "zod";

// ADR 0002: zod schema が input/output の正。型は z.infer で導出し interface と並書しない。
export const SkillListInputSchema = z
  .object({
    // 省略時は packages/cli/_skills の同梱 resource を読む (service.ts で解決)。
    skillsDir: z.string().optional(),
  })
  .strict();

export const SkillListOutputSchema = z
  .object({
    skills: z.array(z.string()),
    source: z.string(),
  })
  .strict();

export type SkillListInput = z.infer<typeof SkillListInputSchema>;
export type SkillListOutput = z.infer<typeof SkillListOutputSchema>;

// service が配布する資産の契約値。CLI の "all" sugar はこの集合を展開する
// (展開は CLI の責務 — service は "all" を受け取らない / #742)。enum の単一情報源。
export const SYNC_ASSETS = ["skills", "claude-md"] as const;

// .agents/skills mirror の状態。標準レイアウト (.claude/skills) でのみ試行し、
// それ以外は null。symlink 非対応環境では握りつぶさず "unsupported" として surface する。
const AGENTS_SKILLS_LINK_STATES = ["linked", "skipped", "unsupported"] as const;

// 1 資産あたりの配布結果。skills は skill ディレクトリ単位、claude-md は単一ファイル。
const SyncEntrySchema = z
  .object({
    name: z.string(),
    result: z.enum(["created", "skipped"]),
  })
  .strict();

export const SkillSyncInputSchema = z
  .object({
    // service が扱う資産は skills | claude-md のみ ("all" は CLI sugar で弾く)。
    asset: z.enum(SYNC_ASSETS),
    // 既存ファイル/シンボリックリンクを上書きするか。CLI は常に明示し service が既定を埋める。
    force: z.boolean().default(false),
    // 省略時は資産ごとの既定ターゲット (skills→.claude/skills, claude-md→.claude/CLAUDE.md) を service が埋める。
    target: z.string().optional(),
  })
  .strict();

export const SkillSyncOutputSchema = z
  .object({
    agentsSkillsLink: z.enum(AGENTS_SKILLS_LINK_STATES).nullable(),
    asset: z.string(),
    entries: z.array(SyncEntrySchema),
    target: z.string(),
  })
  .strict();

export type SkillSyncInput = z.infer<typeof SkillSyncInputSchema>;
export type SkillSyncOutput = z.infer<typeof SkillSyncOutputSchema>;
