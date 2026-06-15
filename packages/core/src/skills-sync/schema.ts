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
