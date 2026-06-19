// Error strategy for packages/core (ADR-0003 §2-3).
//
// Only the three payload-carrying classes survive as `instanceof`-discriminated
// throw types: `AutomationError` (base), `YouTubeAPIError` (statusCode / reason
// / context), and `QuotaExhaustedError` (retryAfterSeconds). The former
// name-tag classes (Config / Auth / Validation / Upload / Generator) are gone;
// callers throw `new Error("config: ...")` / `"validation: ..."` and the
// boundary converts everything to a `ServiceError` via `toServiceError`.
//
// The three surviving classes form one cohesive payload hierarchy, so the
// per-file class cap is relaxed here rather than scattering them across files.
/* eslint-disable max-classes-per-file */
import { z } from "zod";

import { isRecord } from "../internal/guards.ts";

const HTTP_SERVER_ERROR_MIN = 500;
const RETRY_AFTER_HEADER = "retry-after";
const RETRY_AFTER_SECONDS_PATTERN = /^\d+$/u;
const NON_RETRYABLE_PREFIXES = ["config:", "validation:", "auth:"] as const;

const parseJson = (text: string): unknown => {
  try {
    return JSON.parse(text);
  } catch {
    // An error payload that is not JSON (e.g. an HTML 502 page) carries no
    // machine-readable reason; degrading to undefined is the intended contract,
    // not a swallowed failure — the HTTP status is still surfaced separately.
    return undefined;
  }
};

// Mirrors the Python `_payload_reason`: prefer the first `errors[].reason`,
// then fall back to the legacy top-level `error.reason`.
const extractReason = (data: unknown): string | undefined => {
  const payload = typeof data === "string" ? parseJson(data) : data;
  if (!isRecord(payload)) {
    return undefined;
  }
  const { error } = payload;
  if (!isRecord(error)) {
    return undefined;
  }
  if (Array.isArray(error.errors)) {
    for (const item of error.errors) {
      if (isRecord(item) && typeof item.reason === "string") {
        return item.reason;
      }
    }
  }
  return typeof error.reason === "string" ? error.reason : undefined;
};

/** Base exception for youtube-channels-automation. */
export class AutomationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AutomationError";
  }
}

/** Optional metadata carried by a {@link YouTubeAPIError}. */
export interface YouTubeAPIErrorOptions {
  /** Operation name (and any argument hint) the call was made under. */
  readonly context?: string;
  /** Machine-readable reason extracted from the API error payload. */
  readonly reason?: string;
  /** HTTP status code from the failing API response. */
  readonly statusCode?: number;
}

/**
 * YouTube Data API / Analytics API call error.
 *
 * - quota exceeded
 * - authentication failure
 * - malformed response
 */
export class YouTubeAPIError extends AutomationError {
  readonly statusCode?: number;
  readonly reason?: string;
  readonly context?: string;

  constructor(message: string, options?: YouTubeAPIErrorOptions) {
    super(message);
    this.name = "YouTubeAPIError";
    this.statusCode = options?.statusCode;
    this.reason = options?.reason;
    this.context = options?.context;
  }

  /**
   * Convert a googleapis Gaxios-shaped error into a {@link YouTubeAPIError},
   * mirroring the Python `from_http_error` duck typing.
   *
   * Pulls the HTTP status and the machine-readable reason out of the
   * `response` payload and prefixes the message with `context`. Does NOT
   * auto-upgrade a 429 to {@link QuotaExhaustedError} — that branch is the
   * caller's decision, matching Python parity.
   */
  static fromGaxiosError(error: unknown, context: string): YouTubeAPIError {
    const body = error instanceof Error ? error.message : String(error);
    const response = isRecord(error) ? error.response : undefined;
    const statusCode =
      isRecord(response) && typeof response.status === "number"
        ? response.status
        : undefined;
    const reason = extractReason(
      isRecord(response) ? response.data : undefined
    );
    return new YouTubeAPIError(`${context}: ${body}`, {
      context,
      reason,
      statusCode,
    });
  }
}

/**
 * Quota exhausted / rate-limit exceeded (HTTP 429).
 *
 * Signals to callers that the operation is resumable after a delay.
 * `retryAfterSeconds` is the suggested wait derived from the Retry-After
 * header (undefined when unavailable).
 */
export class QuotaExhaustedError extends YouTubeAPIError {
  readonly retryAfterSeconds?: number;

  constructor(message: string, retryAfterSeconds?: number) {
    super(message, { statusCode: 429 });
    this.name = "QuotaExhaustedError";
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export const defaultShouldRetry = (error: unknown): boolean => {
  if (error instanceof QuotaExhaustedError) {
    return false;
  }
  const message = error instanceof Error ? error.message : "";
  return !NON_RETRYABLE_PREFIXES.some((prefix) => message.startsWith(prefix));
};

/**
 * Read the Retry-After hint (in seconds) off a Gaxios-shaped error.
 *
 * A missing header, an empty/blank string, or a non-numeric value all yield
 * undefined: `Number("")` is 0 and must not be misread as "retry in 0 seconds".
 */
const retryAfterSecondsFrom = (error: unknown): number | undefined => {
  const headers = (
    error as { response?: { headers?: Record<string, unknown> } }
  )?.response?.headers;
  const raw = headers
    ? Object.entries(headers).find(
        ([key]) => key.toLowerCase() === "retry-after"
      )?.[1]
    : undefined;
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

/**
 * Classify a Gaxios-shaped API failure into a payload-carrying throw type,
 * sitting next to {@link YouTubeAPIError.fromGaxiosError} as the single home for
 * gaxios-error triage shared by the service boundaries.
 *
 * A 429 is promoted to {@link QuotaExhaustedError} (carrying the Retry-After
 * hint) so `withRetry` stops retrying and the boundary surfaces a quota
 * ServiceError per the ADR-0003 retry規約; every other status stays a
 * {@link YouTubeAPIError} for the transient-retry path. `context` names the
 * failing operation for the message prefix.
 */
export const classifyGaxiosError = (
  error: unknown,
  context: string
): YouTubeAPIError => {
  if (error instanceof QuotaExhaustedError) {
    return error;
  }
  if (error instanceof YouTubeAPIError) {
    if (error.statusCode === 429) {
      return new QuotaExhaustedError(error.message);
    }
    return error;
  }
  const apiError = YouTubeAPIError.fromGaxiosError(error, context);
  if (apiError.statusCode === 429) {
    return new QuotaExhaustedError(
      apiError.message,
      retryAfterSecondsFrom(error)
    );
  }
  return apiError;
};

export const shouldRetryApiQuery = (error: unknown): boolean => {
  if (!defaultShouldRetry(error)) {
    return false;
  }
  if (error instanceof YouTubeAPIError) {
    return (
      error.statusCode === undefined ||
      error.statusCode >= HTTP_SERVER_ERROR_MIN
    );
  }
  return true;
};

// ServiceError (ADR-0003 §2): the wire-shape every service boundary emits. A
// zod discriminated union on `domain` so MCP can `JSON.stringify` it straight
// into a JSON-RPC error — a class hierarchy would lose its prototype chain.
export const ServiceError = z.discriminatedUnion("domain", [
  z.object({
    domain: z.literal("quota"),
    httpStatus: z.literal(429),
    message: z.string(),
    retryAfterSeconds: z.number().optional(),
  }),
  z.object({
    domain: z.literal("api"),
    httpStatus: z.number(),
    message: z.string(),
    reason: z.string().optional(),
  }),
  z.object({ domain: z.literal("auth"), message: z.string() }),
  z.object({
    domain: z.literal("config"),
    message: z.string(),
    path: z.string().optional(),
  }),
  z.object({
    domain: z.literal("validation"),
    field: z.string().optional(),
    message: z.string(),
  }),
  z.object({
    domain: z.literal("io"),
    message: z.string(),
    path: z.string().optional(),
  }),
]);
export type ServiceError = z.infer<typeof ServiceError>;

/**
 * Convert any thrown value into a {@link ServiceError} at a service boundary
 * (ADR-0003 §3).
 *
 * The `instanceof` checks come first so payload-carrying errors keep their
 * fields. `QuotaExhaustedError` MUST be tested before `YouTubeAPIError` — it
 * extends it, so the order is load-bearing or quota errors degrade to `api`.
 * Everything else falls back to the `message` prefix convention; an unprefixed
 * `Error` (or any non-Error value via `String`) lands in `io`.
 */
export const toServiceError = (e: unknown): ServiceError => {
  if (e instanceof QuotaExhaustedError) {
    return {
      domain: "quota",
      httpStatus: 429,
      message: e.message,
      retryAfterSeconds: e.retryAfterSeconds,
    };
  }
  if (e instanceof YouTubeAPIError) {
    return {
      domain: "api",
      httpStatus: e.statusCode ?? 500,
      message: e.message,
      reason: e.reason,
    };
  }
  if (e instanceof z.ZodError) {
    return {
      domain: "validation",
      field: e.issues[0]?.path.map(String).join("."),
      message: e.message,
    };
  }
  const message = e instanceof Error ? e.message : String(e);
  if (message.startsWith("config:")) {
    return { domain: "config", message };
  }
  if (message.startsWith("auth:")) {
    return { domain: "auth", message };
  }
  if (message.startsWith("validation:")) {
    return { domain: "validation", message };
  }
  return { domain: "io", message };
};
