// Analytics・Benchmark（Python `utils/config/analytics.py` の移植）。

import { asRecord } from "./internal.ts";

/** `benchmark` セクション（optional）。channels は JSON 構造を verbatim 保持。 */
interface Benchmark {
  readonly channels: readonly Record<string, unknown>[];
}

/** `analytics` + `benchmark` の合成（どちらも optional）。 */
export interface Analytics {
  readonly collectionFilterKeywords: readonly string[];
  readonly benchmark: Benchmark;
}

export const parseAnalytics = (merged: Record<string, unknown>): Analytics => {
  const an = asRecord(merged.analytics, "analytics");
  const bm = asRecord(merged.benchmark, "benchmark");
  return {
    benchmark: {
      channels: [
        ...((bm.channels as Record<string, unknown>[] | undefined) ?? []),
      ],
    },
    collectionFilterKeywords: [
      ...((an.collection_filter_keywords as string[] | undefined) ?? []),
    ],
  };
};
