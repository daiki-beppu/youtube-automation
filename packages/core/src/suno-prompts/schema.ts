import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

export const SUNO_DOCS_DIR = "20-documentation";
export const SUNO_PATTERNS_FILENAME = "suno-patterns.yaml";
export const SUNO_CONFIG_FILENAME = "suno.yaml";
export const SUNO_PROMPTS_MD_FILENAME = "suno-prompts.md";
export const SUNO_PROMPTS_JSON_FILENAME = "suno-prompts.json";

const GenerateSunoSnakeInputSchema = z
  .object({
    path: z.string(),
  })
  .strict();

const GenerateSunoCamelInputSchema = z
  .object({
    path: z.string(),
  })
  .strict();

export const GenerateSunoInputSchema = z
  .union([GenerateSunoSnakeInputSchema, GenerateSunoCamelInputSchema])
  .transform((input): { path: string } => snakeToCamel(input));

const SunoPromptEntrySchema = z
  .object({
    exclude_styles: z.string().optional(),
    lyrics: z.string(),
    name: z.string(),
    style: z.string(),
    style_influence: z.number().optional(),
    vocal_gender: z.string().optional(),
    weirdness: z.number().optional(),
  })
  .strict();

export const GenerateSunoOutputSchema = z
  .object({
    entryCount: z.number().int().nonnegative(),
    jsonPath: z.string(),
    markdownPath: z.string(),
    warnings: z.array(z.string()),
  })
  .strict();

export type GenerateSunoInput = z.infer<typeof GenerateSunoInputSchema>;
export type GenerateSunoOutput = z.infer<typeof GenerateSunoOutputSchema>;
export type SunoPromptEntry = z.infer<typeof SunoPromptEntrySchema>;

export const SunoPromptEntriesSchema = z.array(SunoPromptEntrySchema);
