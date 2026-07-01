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
  if (filter.min_sec !== undefined && duration < filter.min_sec) {
    return false;
  }
  if (filter.max_sec !== undefined && duration > filter.max_sec) {
    return false;
  }
  return true;
}

export function evaluateClips(clips: DurationClip[], filter: DurationFilter): DurationEvaluation {
  const result: DurationEvaluation = { ok: [], ng: [] };
  for (const clip of clips) {
    if (clip.duration !== undefined && checkDuration(clip.duration, filter)) {
      result.ok.push(clip.id);
    } else {
      result.ng.push(clip.id);
    }
  }
  return result;
}

export function shouldRetry(attemptCount: number, maxRetry: number = MAX_YIELD_RETRY): boolean {
  return attemptCount < maxRetry;
}
