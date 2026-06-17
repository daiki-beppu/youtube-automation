import { describe, expect, test } from "bun:test";

import { QuotaExhaustedError, YouTubeAPIError } from "@tayk/core";

import {
  parseRetryAfterSeconds,
  shouldRetryAnalyticsQuery,
  toAnalyticsQueryError,
} from "../src/analytics/query-error.ts";

const gaxiosError = (message: string, response: unknown): Error =>
  Object.assign(new Error(message), { response });

describe("parseRetryAfterSeconds", () => {
  test("parses a numeric Retry-After header", () => {
    const error = gaxiosError("quota exceeded", {
      headers: { "retry-after": "1800" },
      status: 429,
    });

    expect(parseRetryAfterSeconds(error)).toBe(1800);
  });

  test("parses Retry-After regardless of header casing", () => {
    const error = gaxiosError("quota exceeded", {
      headers: { "Retry-After": "1800" },
      status: 429,
    });

    expect(parseRetryAfterSeconds(error)).toBe(1800);
  });

  test("treats an empty Retry-After header as missing", () => {
    const error = gaxiosError("quota exceeded", {
      headers: { "retry-after": "" },
      status: 429,
    });

    expect(parseRetryAfterSeconds(error)).toBeUndefined();
  });

  test("treats a whitespace Retry-After header as missing", () => {
    const error = gaxiosError("quota exceeded", {
      headers: { "retry-after": "   " },
      status: 429,
    });

    expect(parseRetryAfterSeconds(error)).toBeUndefined();
  });

  test("treats a non-numeric Retry-After header as missing", () => {
    const error = gaxiosError("quota exceeded", {
      headers: { "retry-after": "later" },
      status: 429,
    });

    expect(parseRetryAfterSeconds(error)).toBeUndefined();
  });
});

describe("toAnalyticsQueryError", () => {
  test("promotes a gaxios 429 to QuotaExhaustedError with retryAfterSeconds", () => {
    const error = gaxiosError("quota exceeded", {
      data: { error: { errors: [{ reason: "quotaExceeded" }] } },
      headers: { "retry-after": "120" },
      status: 429,
    });

    const normalized = toAnalyticsQueryError(error, "analytics query");

    expect(normalized).toBeInstanceOf(QuotaExhaustedError);
    expect(normalized.statusCode).toBe(429);
    if (normalized instanceof QuotaExhaustedError) {
      expect(normalized.retryAfterSeconds).toBe(120);
    }
  });

  test("normalizes a non-quota gaxios error to YouTubeAPIError", () => {
    const error = gaxiosError("forbidden", {
      data: { error: { errors: [{ reason: "insufficientPermissions" }] } },
      status: 403,
    });

    const normalized = toAnalyticsQueryError(error, "analytics query");

    expect(normalized).toBeInstanceOf(YouTubeAPIError);
    expect(normalized).not.toBeInstanceOf(QuotaExhaustedError);
    expect(normalized.statusCode).toBe(403);
    expect(normalized.reason).toBe("insufficientPermissions");
  });

  test("preserves an existing typed YouTubeAPIError", () => {
    const error = new YouTubeAPIError("already normalized", {
      reason: "backendError",
      statusCode: 503,
    });

    expect(toAnalyticsQueryError(error, "analytics query")).toBe(error);
  });
});

describe("shouldRetryAnalyticsQuery", () => {
  test("does not retry quota errors", () => {
    expect(
      shouldRetryAnalyticsQuery(new QuotaExhaustedError("quota exceeded"))
    ).toBe(false);
  });

  test("does not retry permanent 4xx API errors", () => {
    expect(
      shouldRetryAnalyticsQuery(
        new YouTubeAPIError("forbidden", { statusCode: 403 })
      )
    ).toBe(false);
  });

  test("retries server-side 5xx API errors", () => {
    expect(
      shouldRetryAnalyticsQuery(
        new YouTubeAPIError("server error", { statusCode: 500 })
      )
    ).toBe(true);
  });

  test("retries normalized API errors with unknown status", () => {
    expect(shouldRetryAnalyticsQuery(new YouTubeAPIError("network drop"))).toBe(
      true
    );
  });

  test("does not retry raw errors before query normalization", () => {
    expect(shouldRetryAnalyticsQuery(new Error("raw failure"))).toBe(false);
  });
});
