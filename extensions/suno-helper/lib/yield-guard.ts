import { MAX_YIELD_RETRY } from "../../shared/constants";
import type { DurationFilter } from "../../shared/api";

export interface DurationClip {
  id: string;
  duration?: number;
}

export interface DurationEvaluation {
  ok: string[];
  ng: string[];
}

export function checkDuration(duration: number, filter: DurationFilter): boolean {
  if (!Number.isFinite(duration)) {
    return false;
  }
  if (duration < filter.min_sec) {
    return false;
  }
  if (duration > filter.max_sec) {
    return false;
  }
  return true;
}

export function evaluateClips(clips: DurationClip[], filter: DurationFilter): DurationEvaluation {
  return {
    ok: clips
      .filter((clip) => clip.duration !== undefined && checkDuration(clip.duration, filter))
      .map((clip) => clip.id),
    ng: clips
      .filter((clip) => clip.duration === undefined || !checkDuration(clip.duration, filter))
      .map((clip) => clip.id),
  };
}

export function shouldRetry(attemptCount: number, maxRetry: number = MAX_YIELD_RETRY): boolean {
  return attemptCount < maxRetry;
}

export function formatYieldFailure(evaluation: DurationEvaluation, filter: DurationFilter): string {
  const range = `${filter.min_sec}-${filter.max_sec}s`;
  const rejected = evaluation.ng.length === 0 ? "none" : evaluation.ng.join(", ");
  return `duration guard NG (${range}): ${rejected}`;
}
