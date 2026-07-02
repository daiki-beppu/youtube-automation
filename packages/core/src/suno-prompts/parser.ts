import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

export interface SunoPattern {
  readonly lyrics: string;
  readonly nameEn: string;
  readonly nameJp: string;
  readonly scenes: readonly string[];
  readonly style?: string;
  readonly tempo: string;
}

export interface SunoPatternsFile {
  readonly mode?: "instrumental" | "vocal";
  readonly patterns: readonly SunoPattern[];
  readonly title: string;
  readonly tracks?: number;
}

const JsonMappingSchema = z.record(z.string(), z.unknown());

const RawSunoPatternSchema = z
  .object({
    lyrics: z.string().optional(),
    name_en: z.string(),
    name_jp: z.string(),
    scenes: z.array(z.string()).nonempty(),
    style: z.string().optional(),
    tempo: z.string(),
  })
  .strict()
  .transform(
    (input): SunoPattern => ({
      ...snakeToCamel(input),
      lyrics: input.lyrics?.trimEnd() ?? "",
    })
  );

const RawSunoPatternsFileSchema = z
  .object({
    mode: z.enum(["instrumental", "vocal"]).optional(),
    patterns: z.array(RawSunoPatternSchema).nonempty(),
    title: z.string().optional(),
    tracks: z.number().int().positive().optional(),
  })
  .strict()
  .transform(
    (input): SunoPatternsFile => ({
      ...(input.mode === undefined ? {} : { mode: input.mode }),
      patterns: input.patterns,
      title: input.title ?? "Suno Prompts",
      ...(input.tracks === undefined ? {} : { tracks: input.tracks }),
    })
  );

export const parseTopLevelJson = (text: string): Record<string, unknown> => {
  const parsed = JSON.parse(text) as unknown;
  return JsonMappingSchema.parse(parsed);
};

export const parsePatternsJson = (text: string): SunoPatternsFile =>
  RawSunoPatternsFileSchema.parse(JSON.parse(text) as unknown);
