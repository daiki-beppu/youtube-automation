// Analytics・Benchmark（merged の `analytics` + `benchmark`、どちらも optional）。
//
// `benchmark.channels` は JSON 構造を verbatim 保持する（snake key を camel 化しない）。

import { z } from "zod";

/** `analytics` + `benchmark` の合成（どちらも optional）。 */
export const Analytics = z
  .object({
    analytics: z
      .object({
        collection_filter_keywords: z.array(z.string()).default([]),
      })
      .strict()
      .prefault({}),
    benchmark: z
      .object({
        channels: z.array(z.record(z.string(), z.unknown())).default([]),
      })
      .strict()
      .prefault({}),
  })
  .transform((o) => ({
    benchmark: { channels: o.benchmark.channels },
    collectionFilterKeywords: o.analytics.collection_filter_keywords,
  }));

export type Analytics = z.infer<typeof Analytics>;
