// Skeleton entry for the core package. Real domain logic is migrated in later #727 issues.
export const greeting = (): string =>
  "youtube-channels-automation core (TS rewrite skeleton)";

export {
  AutomationError,
  QuotaExhaustedError,
  ServiceError,
  toServiceError,
  YouTubeAPIError,
  type YouTubeAPIErrorOptions,
} from "./errors.ts";
export { err, ok, type Result } from "./result.ts";
export {
  defaultShouldRetry,
  type RetryPolicy,
  type SleepMs,
  withRetry,
} from "./retry.ts";
