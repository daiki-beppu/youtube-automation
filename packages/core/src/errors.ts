// The domain exception hierarchy is one cohesive unit (order.md targets a
// single packages/core errors module), so the per-file class cap is relaxed
// here rather than scattering the hierarchy across files.
/* eslint-disable max-classes-per-file */

// Domain exception hierarchy, ported from the Python `utils/exceptions.py`.
// `AutomationError` is the base every domain error extends, so a single
// `catch (e instanceof AutomationError)` site captures all of them while
// `instanceof` on the concrete class still discriminates.

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

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

/**
 * Config file load / validation error.
 *
 * - missing required keys in config/channel/*.json
 * - config file not found
 * - JSON parse error
 */
export class ConfigError extends AutomationError {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

/**
 * OAuth 2.0 authentication error.
 *
 * - client_secrets.json load failure
 * - run_local_server flow failure
 * - GoogleAuthError family roll-up
 */
export class AuthError extends AutomationError {
  constructor(message: string) {
    super(message);
    this.name = "AuthError";
  }
}

/**
 * Input data validation error.
 *
 * - invalid metadata values
 * - invalid file paths
 * - invalid collection names
 */
export class ValidationError extends AutomationError {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

/**
 * Video / thumbnail upload failure.
 *
 * - retry limit reached
 * - file missing
 * - thumbnail compression failure
 */
export class UploadError extends AutomationError {
  constructor(message: string) {
    super(message);
    this.name = "UploadError";
  }
}

/** Reply-generation backend failure (API error, malformed response, etc.). */
export class GeneratorError extends AutomationError {
  constructor(message: string) {
    super(message);
    this.name = "GeneratorError";
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
