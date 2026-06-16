// オーディオ設定（optional）。merged から `audio` を取り出し camelCase へ transform。

import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

/** `audio` セクション（optional）。 */
export const Audio = z
  .object({
    audio: z
      .object({
        chapter_max: z.number().default(100),
        target_duration_max: z.number().nullable().default(null),
        target_duration_min: z.number().nullable().default(null),
      })
      .strict()
      .prefault({}),
  })
  .transform((o) => snakeToCamel(o.audio));

export type Audio = z.infer<typeof Audio>;
