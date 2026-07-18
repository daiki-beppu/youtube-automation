import type { DurationFilter } from "../../shared/api";
import { MAX_YIELD_RETRY } from "../../shared/constants";

export interface DurationClip {
  id: string;
  duration?: number;
}

export interface DurationEvaluation {
  ok: string[];
  ng: string[];
}

export type DurationOutlierPolicy = { kind: "retain" } | { kind: "regenerate" };

export type DurationAttemptResult =
  | { kind: "evaluated"; evaluation: DurationEvaluation }
  | { kind: "evaluation-failed"; message: string };

export type DurationAttemptDecision =
  | { kind: "accept"; acceptedClipIds: string[]; warning?: string }
  | { kind: "retry"; message: string }
  | { kind: "fail"; message: string; reason: "evaluation" | "outlier" };

export function checkDuration(
  duration: number,
  filter: DurationFilter
): boolean {
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

export function evaluateClips(
  clips: DurationClip[],
  filter: DurationFilter
): DurationEvaluation {
  return {
    ok: clips
      .filter(
        (clip) =>
          clip.duration !== undefined && checkDuration(clip.duration, filter)
      )
      .map((clip) => clip.id),
    ng: clips
      .filter(
        (clip) =>
          clip.duration === undefined || !checkDuration(clip.duration, filter)
      )
      .map((clip) => clip.id),
  };
}

export function shouldRetryDurationOutlier(options: {
  attemptCount: number;
  maxRetry?: number;
}): boolean {
  return options.attemptCount < (options.maxRetry ?? MAX_YIELD_RETRY);
}

export function decideDurationAttempt(options: {
  clipIds: string[];
  result: DurationAttemptResult;
  filter: DurationFilter;
  policy: DurationOutlierPolicy;
  attemptCount: number;
  maxRetry?: number;
}): DurationAttemptDecision {
  if (options.result.kind === "evaluation-failed") {
    if (
      options.policy.kind === "regenerate" &&
      shouldRetryDurationOutlier({
        attemptCount: options.attemptCount,
        maxRetry: options.maxRetry,
      })
    ) {
      return { kind: "retry", message: options.result.message };
    }
    return {
      kind: "fail",
      message: options.result.message,
      reason: "evaluation",
    };
  }

  const { evaluation } = options.result;
  if (evaluation.ok.length > 0) {
    if (options.policy.kind === "regenerate") {
      return { kind: "accept", acceptedClipIds: evaluation.ok };
    }
    const warning =
      evaluation.ng.length > 0
        ? `${formatYieldFailure(evaluation, options.filter)}; 再生成 OFF のため全 clip を採用候補として保持します`
        : undefined;
    return { kind: "accept", acceptedClipIds: options.clipIds, warning };
  }

  const message = formatYieldFailure(evaluation, options.filter);
  if (options.policy.kind === "retain") {
    return {
      kind: "accept",
      acceptedClipIds: options.clipIds,
      warning: `${message}; 再生成 OFF のため全 clip を採用候補として保持します`,
    };
  }
  if (
    shouldRetryDurationOutlier({
      attemptCount: options.attemptCount,
      maxRetry: options.maxRetry,
    })
  ) {
    return { kind: "retry", message };
  }
  return { kind: "fail", message, reason: "outlier" };
}

export function formatYieldFailure(
  evaluation: DurationEvaluation,
  filter: DurationFilter
): string {
  const range = `${filter.min_sec}-${filter.max_sec}s`;
  const rejected =
    evaluation.ng.length === 0 ? "none" : evaluation.ng.join(", ");
  return `duration guard NG (${range}): ${rejected}`;
}
