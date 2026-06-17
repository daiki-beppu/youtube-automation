import { isRecord } from "../../internal/guards.ts";
import { QuotaExhaustedError, YouTubeAPIError } from "../errors.ts";
import { defaultShouldRetry } from "../retry.ts";

const HTTP_SERVER_ERROR_MIN = 500;
const RETRY_AFTER_HEADER = "retry-after";

const findRetryAfterHeader = (
  headers: Record<string, unknown>
): unknown | undefined => {
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === RETRY_AFTER_HEADER) {
      return value;
    }
  }
  return undefined;
};

export const parseRetryAfterSeconds = (error: unknown): number | undefined => {
  if (
    !(
      isRecord(error) &&
      isRecord(error.response) &&
      isRecord(error.response.headers)
    )
  ) {
    return undefined;
  }
  const raw = findRetryAfterHeader(error.response.headers);
  if (typeof raw !== "string") {
    return undefined;
  }
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return undefined;
  }
  const seconds = Number(trimmed);
  return Number.isFinite(seconds) ? seconds : undefined;
};

export const toAnalyticsQueryError = (
  error: unknown,
  context: string
): YouTubeAPIError => {
  if (error instanceof YouTubeAPIError) {
    return error;
  }
  const apiError = YouTubeAPIError.fromGaxiosError(error, context);
  if (apiError.statusCode === 429) {
    return new QuotaExhaustedError(
      apiError.message,
      parseRetryAfterSeconds(error)
    );
  }
  return apiError;
};

export const shouldRetryAnalyticsQuery = (error: unknown): boolean => {
  if (!defaultShouldRetry(error)) {
    return false;
  }
  if (!(error instanceof YouTubeAPIError)) {
    return false;
  }
  return (
    error.statusCode === undefined || error.statusCode >= HTTP_SERVER_ERROR_MIN
  );
};
