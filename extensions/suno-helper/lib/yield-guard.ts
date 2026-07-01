import { DEFAULT_YIELD_DURATION_FILTER, MAX_YIELD_RETRY } from "../../shared/constants";

export interface DurationFilter {
  minSec: number;
  maxSec: number;
}

export interface YieldClip {
  id: string;
  durationSec?: number;
}

export interface ClipDurationResult {
  id: string;
  ok: boolean;
  durationSec?: number;
  reason?: "missing-duration" | "too-short" | "too-long";
}

export interface YieldEvaluation {
  acceptedClipIds: string[];
  rejectedClipIds: string[];
  results: ClipDurationResult[];
}

export const DEFAULT_DURATION_FILTER: DurationFilter = {
  minSec: DEFAULT_YIELD_DURATION_FILTER.minSec,
  maxSec: DEFAULT_YIELD_DURATION_FILTER.maxSec,
};

export function checkDuration(durationSec: number | undefined, filter: DurationFilter): Omit<ClipDurationResult, "id"> {
  if (durationSec === undefined) {
    return { ok: false, reason: "missing-duration" };
  }
  if (durationSec < filter.minSec) {
    return { ok: false, durationSec, reason: "too-short" };
  }
  if (durationSec > filter.maxSec) {
    return { ok: false, durationSec, reason: "too-long" };
  }
  return { ok: true, durationSec };
}

export function evaluateClips(clips: YieldClip[], filter: DurationFilter = DEFAULT_DURATION_FILTER): YieldEvaluation {
  const results = clips.map(
    (clip): ClipDurationResult => ({ id: clip.id, ...checkDuration(clip.durationSec, filter) }),
  );
  return {
    acceptedClipIds: results.filter((result) => result.ok).map((result) => result.id),
    rejectedClipIds: results.filter((result) => !result.ok).map((result) => result.id),
    results,
  };
}

export function shouldRetry(retryCount: number, maxRetry: number = MAX_YIELD_RETRY): boolean {
  return retryCount < maxRetry;
}

export function formatYieldFailure(
  evaluation: YieldEvaluation,
  filter: DurationFilter = DEFAULT_DURATION_FILTER,
): string {
  const details = evaluation.results
    .map((result) => {
      const duration = result.durationSec === undefined ? "unknown" : `${Math.round(result.durationSec)}s`;
      return `${result.id}:${duration}${result.reason ? `:${result.reason}` : ""}`;
    })
    .join(", ");
  return `duration guard NG (${filter.minSec}-${filter.maxSec}s): ${details}`;
}
