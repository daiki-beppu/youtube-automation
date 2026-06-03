// ショート設定（Python `utils/config/shorts.py` + loader `_build_shorts` の移植）。

import { asRecord } from "./internal.ts";

const DEFAULT_PUBLISH_TIME = "08:00";
const DEFAULT_MIN_HOURS_BETWEEN_SHORTS = 24;

/** collection 型（`/short`）固有の生成設定。 */
interface ShortsCollection {
  readonly defaultCount: number;
  readonly chapterOffsetSec: number;
}

/** release 型（`/short-release`）固有の生成設定。 */
interface ShortsRelease {
  readonly languages: readonly string[];
  readonly startSec: number;
  readonly durationSec: number;
}

/** `shorts` セクション（optional・オプトイン）。 */
export interface Shorts {
  readonly enabled: boolean;
  readonly publishTime: string;
  readonly minHoursBetweenShortsPerCollection: number;
  readonly mode: string;
  readonly collection: ShortsCollection;
  readonly release: ShortsRelease;
}

export const parseShorts = (merged: Record<string, unknown>): Shorts => {
  const sh = asRecord(merged.shorts, "shorts");
  const col = asRecord(sh.collection, "shorts.collection");
  const rel = asRecord(sh.release, "shorts.release");
  return {
    collection: {
      chapterOffsetSec: (col.chapter_offset_sec as number | undefined) ?? 30,
      defaultCount: (col.default_count as number | undefined) ?? 3,
    },
    enabled: (sh.enabled as boolean | undefined) ?? false,
    minHoursBetweenShortsPerCollection:
      (sh.min_hours_between_shorts_per_collection as number | undefined) ??
      DEFAULT_MIN_HOURS_BETWEEN_SHORTS,
    mode: (sh.mode as string | undefined) ?? "auto",
    publishTime:
      (sh.publish_time as string | undefined) ?? DEFAULT_PUBLISH_TIME,
    release: {
      durationSec: (rel.duration_sec as number | undefined) ?? 40,
      languages: [...((rel.languages as string[] | undefined) ?? ["jp", "en"])],
      startSec: (rel.start_sec as number | undefined) ?? 30,
    },
  };
};
