// オーディオ設定（Python `utils/config/audio.py` の移植・optional）。

import { asRecord } from "./internal.ts";

/** `audio` セクション（optional）。 */
export interface Audio {
  readonly targetDurationMin: number | null;
  readonly targetDurationMax: number | null;
  readonly chapterMax: number;
}

export const parseAudio = (merged: Record<string, unknown>): Audio => {
  const ad = asRecord(merged.audio, "audio");
  return {
    chapterMax: (ad.chapter_max as number | undefined) ?? 100,
    targetDurationMax: (ad.target_duration_max as number | undefined) ?? null,
    targetDurationMin: (ad.target_duration_min as number | undefined) ?? null,
  };
};
