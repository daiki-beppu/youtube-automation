// ショート設定（optional・オプトイン）。merged から `shorts` を取り出し camelCase へ。

import { z } from "zod";

import { snakeToCamel } from "../../internal/case.ts";

/** `shorts` セクション（optional・オプトイン）。 */
export const Shorts = z
  .object({
    shorts: z
      .object({
        collection: z
          .object({
            chapter_offset_sec: z.number().default(30),
            default_count: z.number().default(3),
          })
          .strict()
          .prefault({}),
        enabled: z.boolean().default(false),
        min_hours_between_shorts_per_collection: z.number().default(24),
        mode: z.string().default("auto"),
        publish_time: z.string().default("08:00"),
        release: z
          .object({
            duration_sec: z.number().default(40),
            languages: z.array(z.string()).default(["jp", "en"]),
            start_sec: z.number().default(30),
          })
          .strict()
          .prefault({}),
      })
      .strict()
      .prefault({}),
  })
  .transform((o) => snakeToCamel(o.shorts));

export type Shorts = z.infer<typeof Shorts>;
