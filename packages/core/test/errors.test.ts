import { describe, expect, test } from "bun:test";

// Imports by the published package name (not a relative path) so the tests
// exercise the package `exports` map / barrel re-export, not just the source
// file. A broken `exports` or missing barrel entry fails resolution here
// instead of slipping past tsc.
import {
  AutomationError,
  err,
  ok,
  QuotaExhaustedError,
  ServiceError,
  toServiceError,
  YouTubeAPIError,
} from "@youtube-automation/core";
import type { Result } from "@youtube-automation/core";
import { z } from "zod";

// classifyGaxiosError is an internal cross-feature helper shared by service
// boundaries, intentionally NOT re-exported from the public barrel, so it is
// imported by source path — the same convention the other internal-symbol tests
// use (e.g. analytics-channel.test.ts).
import { classifyGaxiosError } from "../src/errors.ts";

// Builds a gaxios-shaped error: a real Error (so `error instanceof Error`
// holds and `.message` is read for the wrapped message) with a `response`
// carrying `status` and parsed/raw `data`, mirroring the Google API client
// surface the Python `from_http_error` consumed via duck typing.
const gaxiosError = (message: string, response: unknown): Error =>
  Object.assign(new Error(message), { response });

describe("AutomationError (base)", () => {
  test("extends the native Error so generic catch sites still work", () => {
    // Given a base AutomationError
    const error = new AutomationError("boom");
    // Then it is a native Error and an AutomationError
    expect(error).toBeInstanceOf(Error);
    expect(error).toBeInstanceOf(AutomationError);
  });

  test("preserves the message and exposes the subclass name", () => {
    // Given a base AutomationError with a message
    const error = new AutomationError("boom");
    // Then the message round-trips and name reflects the concrete class
    expect(error.message).toBe("boom");
    expect(error.name).toBe("AutomationError");
  });
});

describe("YouTubeAPIError", () => {
  test("instanceof AutomationError and Error", () => {
    // Given a bare YouTubeAPIError
    const error = new YouTubeAPIError("api failed");
    // Then it is part of the AutomationError hierarchy
    expect(error).toBeInstanceOf(AutomationError);
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("YouTubeAPIError");
  });

  test("statusCode and reason default to undefined when omitted", () => {
    // Given a YouTubeAPIError constructed with only a message
    const error = new YouTubeAPIError("api failed");
    // Then the optional fields are absent
    expect(error.statusCode).toBeUndefined();
    expect(error.reason).toBeUndefined();
  });

  test("retains statusCode and reason when supplied", () => {
    // Given a YouTubeAPIError with status + reason options
    const error = new YouTubeAPIError("api failed", {
      reason: "forbidden",
      statusCode: 403,
    });
    // Then both fields are stored
    expect(error.statusCode).toBe(403);
    expect(error.reason).toBe("forbidden");
  });
});

describe("YouTubeAPIError.fromGaxiosError", () => {
  test("extracts statusCode, reason (errors[0]) and prefixes context", () => {
    // Given a gaxios error with status and an errors[] reason
    const raw = gaxiosError("quota exceeded", {
      data: {
        error: {
          errors: [{ domain: "youtube.quota", reason: "quotaExceeded" }],
          reason: "legacyReason",
        },
      },
      status: 403,
    });
    // When converting it for a named operation
    const error = YouTubeAPIError.fromGaxiosError(raw, "videos.insert");
    // Then it is a YouTubeAPIError with extracted fields and context-prefixed message
    expect(error).toBeInstanceOf(YouTubeAPIError);
    expect(error.statusCode).toBe(403);
    expect(error.reason).toBe("quotaExceeded");
    expect(error.context).toBe("videos.insert");
    expect(error.message).toBe("videos.insert: quota exceeded");
  });

  test("falls back to the legacy error.reason when errors[] is absent", () => {
    // Given a gaxios error whose payload carries only the legacy top-level reason
    const raw = gaxiosError("bad request", {
      data: { error: { reason: "badRequest" } },
      status: 400,
    });
    // When converting it
    const error = YouTubeAPIError.fromGaxiosError(raw, "videos.list");
    // Then the legacy reason is used
    expect(error.statusCode).toBe(400);
    expect(error.reason).toBe("badRequest");
  });

  test("parses a JSON string payload (data is not pre-parsed)", () => {
    // Given a gaxios error whose data is a raw JSON string
    const raw = gaxiosError("forbidden", {
      data: JSON.stringify({
        error: { errors: [{ reason: "quotaExceeded" }] },
      }),
      status: 403,
    });
    // When converting it
    const error = YouTubeAPIError.fromGaxiosError(raw, "videos.insert");
    // Then the reason is extracted from the parsed string
    expect(error.statusCode).toBe(403);
    expect(error.reason).toBe("quotaExceeded");
  });

  test("reason is undefined when the data string is not valid JSON", () => {
    // Given a gaxios error whose data is an unparseable string
    const raw = gaxiosError("gateway error", {
      data: "<html>502 Bad Gateway</html>",
      status: 502,
    });
    // When converting it
    const error = YouTubeAPIError.fromGaxiosError(raw, "videos.insert");
    // Then status survives but reason degrades to undefined
    expect(error.statusCode).toBe(502);
    expect(error.reason).toBeUndefined();
  });

  test("statusCode and reason are undefined when response is missing", () => {
    // Given a bare error with no gaxios response attached
    const raw = new Error("network down");
    // When converting it
    const error = YouTubeAPIError.fromGaxiosError(raw, "videos.insert");
    // Then both fields degrade to undefined but the message is still prefixed
    expect(error.statusCode).toBeUndefined();
    expect(error.reason).toBeUndefined();
    expect(error.message).toBe("videos.insert: network down");
  });

  test("non-Error input is stringified into the message", () => {
    // Given a non-Error value as the failure
    const error = YouTubeAPIError.fromGaxiosError("raw string failure", "op");
    // Then String(error) is used for the message body
    expect(error.message).toBe("op: raw string failure");
    expect(error.statusCode).toBeUndefined();
    expect(error.reason).toBeUndefined();
  });

  test("never auto-upgrades a 429 to QuotaExhaustedError (Python parity)", () => {
    // Given a gaxios error with HTTP 429
    const raw = gaxiosError("rate limited", {
      data: { error: { errors: [{ reason: "rateLimitExceeded" }] } },
      status: 429,
    });
    // When converting it
    const error = YouTubeAPIError.fromGaxiosError(raw, "videos.insert");
    // Then it stays a plain YouTubeAPIError (no automatic 429 branch)
    expect(error).toBeInstanceOf(YouTubeAPIError);
    expect(error).not.toBeInstanceOf(QuotaExhaustedError);
    expect(error.statusCode).toBe(429);
  });
});

describe("QuotaExhaustedError", () => {
  test("nests under YouTubeAPIError, AutomationError and Error", () => {
    // Given a QuotaExhaustedError
    const error = new QuotaExhaustedError("quota gone");
    // Then the full hierarchy holds
    expect(error).toBeInstanceOf(YouTubeAPIError);
    expect(error).toBeInstanceOf(AutomationError);
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("QuotaExhaustedError");
  });

  test("pins statusCode to 429", () => {
    // Given a QuotaExhaustedError
    const error = new QuotaExhaustedError("quota gone");
    // Then the status is the fixed 429
    expect(error.statusCode).toBe(429);
  });

  test("retains retryAfterSeconds when provided", () => {
    // Given a QuotaExhaustedError with a retry hint
    const error = new QuotaExhaustedError("quota gone", 30);
    // Then the hint is stored
    expect(error.retryAfterSeconds).toBe(30);
  });

  test("retryAfterSeconds is undefined when omitted", () => {
    // Given a QuotaExhaustedError without a retry hint
    const error = new QuotaExhaustedError("quota gone");
    // Then the hint is absent
    expect(error.retryAfterSeconds).toBeUndefined();
  });
});

describe("classifyGaxiosError", () => {
  test("promotes a 429 to QuotaExhaustedError carrying the Retry-After hint", () => {
    // Given a gaxios-shaped 429 with a Retry-After header
    const raw = gaxiosError("rate limited", {
      headers: { "retry-after": "45" },
      status: 429,
    });
    // When classifying it for a named operation
    const error = classifyGaxiosError(raw, "videos.insert");
    // Then it is promoted to a QuotaExhaustedError (so withRetry stops retrying)
    // carrying the parsed Retry-After hint and a context-prefixed message
    expect(error).toBeInstanceOf(QuotaExhaustedError);
    expect(error.statusCode).toBe(429);
    expect((error as QuotaExhaustedError).retryAfterSeconds).toBe(45);
    expect(error.message).toBe("videos.insert: rate limited");
  });

  test("reads the Retry-After header regardless of casing", () => {
    const raw = gaxiosError("rate limited", {
      headers: { "Retry-After": "120" },
      status: 429,
    });
    const error = classifyGaxiosError(raw, "videos.insert");
    expect(error).toBeInstanceOf(QuotaExhaustedError);
    expect((error as QuotaExhaustedError).retryAfterSeconds).toBe(120);
  });

  test("trims a Retry-After header before parsing integer seconds", () => {
    const raw = gaxiosError("rate limited", {
      headers: { "retry-after": "  60  " },
      status: 429,
    });
    const error = classifyGaxiosError(raw, "videos.insert");
    expect(error).toBeInstanceOf(QuotaExhaustedError);
    expect((error as QuotaExhaustedError).retryAfterSeconds).toBe(60);
  });

  test("ignores a fractional Retry-After header", () => {
    const raw = gaxiosError("rate limited", {
      headers: { "retry-after": "1.5" },
      status: 429,
    });
    const error = classifyGaxiosError(raw, "videos.insert");
    expect(error).toBeInstanceOf(QuotaExhaustedError);
    expect((error as QuotaExhaustedError).retryAfterSeconds).toBeUndefined();
  });

  test("ignores a non-string Retry-After header", () => {
    const raw = gaxiosError("rate limited", {
      headers: { "retry-after": 30 },
      status: 429,
    });
    const error = classifyGaxiosError(raw, "videos.insert");
    expect(error).toBeInstanceOf(QuotaExhaustedError);
    expect((error as QuotaExhaustedError).retryAfterSeconds).toBeUndefined();
  });

  test("leaves the Retry-After hint undefined when the header is absent", () => {
    // Given a 429 with no Retry-After header
    const raw = gaxiosError("rate limited", { status: 429 });
    // When classifying it
    const error = classifyGaxiosError(raw, "videos.insert");
    // Then it is still a quota error, but with no usable retry hint
    expect(error).toBeInstanceOf(QuotaExhaustedError);
    expect((error as QuotaExhaustedError).retryAfterSeconds).toBeUndefined();
  });

  test("promotes a typed YouTubeAPIError with status 429 to QuotaExhaustedError", () => {
    // Given a service seam that already normalized the error as YouTubeAPIError
    const typed = new YouTubeAPIError("videos.insert: quota exceeded", {
      statusCode: 429,
    });
    // When classifying it at a retry boundary
    const error = classifyGaxiosError(typed, "videos.insert");
    // Then it still becomes quota so retry policy does not treat it as API 429
    expect(error).toBeInstanceOf(QuotaExhaustedError);
    expect(error.message).toBe("videos.insert: quota exceeded");
    expect((error as QuotaExhaustedError).retryAfterSeconds).toBeUndefined();
  });

  test("preserves an already-typed QuotaExhaustedError instance", () => {
    // Given a quota error with a parsed retry hint
    const quota = new QuotaExhaustedError("quota exceeded", 90);
    // When classifying it again
    const error = classifyGaxiosError(quota, "videos.insert");
    // Then the payload-carrying instance is preserved
    expect(error).toBe(quota);
  });

  test("leaves a non-429 as a plain YouTubeAPIError for the retry path", () => {
    // Given a gaxios-shaped 500
    const raw = gaxiosError("internal error", { status: 500 });
    // When classifying it
    const error = classifyGaxiosError(raw, "videos.insert");
    // Then it stays a retryable YouTubeAPIError, not a quota error
    expect(error).toBeInstanceOf(YouTubeAPIError);
    expect(error).not.toBeInstanceOf(QuotaExhaustedError);
    expect(error.statusCode).toBe(500);
  });

  test("preserves an existing typed YouTubeAPIError", () => {
    const normalized = new YouTubeAPIError("already normalized", {
      reason: "backendError",
      statusCode: 503,
    });
    const error = classifyGaxiosError(normalized, "videos.insert");
    expect(error).toBe(normalized);
  });

  test("preserves an existing typed QuotaExhaustedError", () => {
    const normalized = new QuotaExhaustedError("quota exceeded", 900);
    const error = classifyGaxiosError(normalized, "videos.insert");
    expect(error).toBe(normalized);
    expect(error).toBeInstanceOf(QuotaExhaustedError);
    expect((error as QuotaExhaustedError).retryAfterSeconds).toBe(900);
  });
});

// --- Result / ok / err ----------------------------------------------------

describe("Result helpers", () => {
  test("ok wraps a value into a success Result", () => {
    // Given a success value
    const result: Result<number, string> = ok(42);
    // Then the discriminant is ok:true and the value is carried
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toBe(42);
    }
  });

  test("err wraps an error into a failure Result", () => {
    // Given a failure value
    const result: Result<number, string> = err("boom");
    // Then the discriminant is ok:false and the error is carried
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBe("boom");
    }
  });

  test("ok carries object values by reference without copying", () => {
    // Given an object payload
    const payload = { id: 7 };
    const result = ok(payload);
    // Then the wrapper exposes the exact same reference (no defensive clone)
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value).toBe(payload);
    }
  });

  test("the ok discriminant narrows away the error arm at runtime", () => {
    // Given a failure Result discriminated only by the `ok` flag
    const result: Result<string, ServiceError> = err({
      domain: "io",
      message: "disk full",
    });
    // Then `ok` is the single source of truth for which arm is populated
    expect("value" in result).toBe(false);
    expect("error" in result).toBe(true);
  });
});

// --- ServiceError zod schema ----------------------------------------------

describe("ServiceError schema", () => {
  test("accepts a quota variant pinned to httpStatus 429", () => {
    // Given a quota-domain payload
    const parsed = ServiceError.parse({
      domain: "quota",
      httpStatus: 429,
      message: "quota gone",
      retryAfterSeconds: 30,
    });
    // Then it round-trips with the discriminator and payload intact
    expect(parsed).toEqual({
      domain: "quota",
      httpStatus: 429,
      message: "quota gone",
      retryAfterSeconds: 30,
    });
  });

  test("rejects a quota variant whose httpStatus is not the 429 literal", () => {
    // Given a quota payload with a non-429 status
    // When parsing it
    // Then the literal(429) constraint fails fast
    expect(() =>
      ServiceError.parse({ domain: "quota", httpStatus: 500, message: "m" })
    ).toThrow();
  });

  test("accepts an api variant with an arbitrary numeric httpStatus", () => {
    // Given an api-domain payload
    const parsed = ServiceError.parse({
      domain: "api",
      httpStatus: 403,
      message: "api failed",
      reason: "forbidden",
    });
    // Then the numeric status and optional reason survive
    expect(parsed.domain).toBe("api");
    if (parsed.domain === "api") {
      expect(parsed.httpStatus).toBe(403);
      expect(parsed.reason).toBe("forbidden");
    }
  });

  test("accepts the auth / config / validation / io variants", () => {
    // Given each remaining domain payload
    // Then all parse against the discriminated union
    expect(ServiceError.parse({ domain: "auth", message: "a" }).domain).toBe(
      "auth"
    );
    expect(
      ServiceError.parse({ domain: "config", message: "c", path: "x" }).domain
    ).toBe("config");
    expect(
      ServiceError.parse({ domain: "validation", field: "x", message: "v" })
        .domain
    ).toBe("validation");
    expect(
      ServiceError.parse({ domain: "io", message: "i", path: "/tmp" }).domain
    ).toBe("io");
  });

  test("rejects an unknown domain discriminator", () => {
    // Given a payload whose domain is outside the 6-variant union
    // When parsing it
    // Then the discriminatedUnion rejects it
    expect(() =>
      ServiceError.parse({ domain: "network", message: "m" })
    ).toThrow();
  });
});

// --- toServiceError -------------------------------------------------------

describe("toServiceError", () => {
  test("maps QuotaExhaustedError to the quota domain (before the api branch)", () => {
    // Given a QuotaExhaustedError (which is also a YouTubeAPIError)
    const error = new QuotaExhaustedError("quota gone", 45);
    // When converting it
    const se = toServiceError(error);
    // Then the quota branch wins over the api branch despite the inheritance
    expect(se).toEqual({
      domain: "quota",
      httpStatus: 429,
      message: "quota gone",
      retryAfterSeconds: 45,
    });
  });

  test("maps YouTubeAPIError to the api domain with its statusCode", () => {
    // Given a YouTubeAPIError carrying status + reason
    const error = new YouTubeAPIError("api failed", {
      reason: "forbidden",
      statusCode: 403,
    });
    // When converting it
    const se = toServiceError(error);
    // Then it becomes an api-domain ServiceError
    expect(se).toEqual({
      domain: "api",
      httpStatus: 403,
      message: "api failed",
      reason: "forbidden",
    });
  });

  test("defaults a YouTubeAPIError without statusCode to httpStatus 500", () => {
    // Given a YouTubeAPIError with no status code
    const error = new YouTubeAPIError("api failed");
    // When converting it
    const se = toServiceError(error);
    // Then the api branch falls back to 500 rather than emitting undefined
    expect(se.domain).toBe("api");
    if (se.domain === "api") {
      expect(se.httpStatus).toBe(500);
    }
  });

  test("maps a ZodError to the validation domain with the issue path as field", () => {
    // Given a zod validation failure on a nested field
    const schema = z.object({ a: z.object({ b: z.string() }) });
    const result = schema.safeParse({ a: { b: 123 } });
    expect(result.success).toBe(false);
    // When converting the ZodError
    const se = toServiceError((result as { error: z.ZodError }).error);
    // Then the validation domain carries the dotted issue path
    expect(se.domain).toBe("validation");
    if (se.domain === "validation") {
      expect(se.field).toBe("a.b");
    }
  });

  test("maps a config:-prefixed Error to the config domain", () => {
    // Given a plain Error using the config prefix convention
    const error = new Error("config: missing channel.name");
    // When converting it
    const se = toServiceError(error);
    // Then the prefix routes it to the config domain (message preserved)
    expect(se).toEqual({
      domain: "config",
      message: "config: missing channel.name",
    });
  });

  test("maps an auth:-prefixed Error to the auth domain", () => {
    // Given a plain Error using the auth prefix convention
    const error = new Error("auth: token expired");
    // When converting it
    const se = toServiceError(error);
    // Then the prefix routes it to the auth domain
    expect(se).toEqual({ domain: "auth", message: "auth: token expired" });
  });

  test("maps a validation:-prefixed Error to the validation domain", () => {
    // Given a plain Error using the validation prefix convention
    const error = new Error("validation: unknown placeholder {adjective}");
    // When converting it
    const se = toServiceError(error);
    // Then the prefix routes it to the validation domain
    expect(se.domain).toBe("validation");
    expect(se.message).toBe("validation: unknown placeholder {adjective}");
  });

  test("maps an unprefixed Error to the io domain", () => {
    // Given a plain Error with no recognised prefix
    const error = new Error("disk full");
    // When converting it
    const se = toServiceError(error);
    // Then it falls back to the io domain
    expect(se).toEqual({ domain: "io", message: "disk full" });
  });

  test("maps a non-Error thrown value to the io domain via String()", () => {
    // Given a thrown value that is not an Error instance
    // When converting a string and a number
    const fromString = toServiceError("boom");
    const fromNumber = toServiceError(42);
    // Then both are stringified into an io-domain ServiceError
    expect(fromString).toEqual({ domain: "io", message: "boom" });
    expect(fromNumber).toEqual({ domain: "io", message: "42" });
  });

  test("every toServiceError result parses back through the ServiceError schema", () => {
    // Given representative inputs across all known branches
    const inputs: unknown[] = [
      new QuotaExhaustedError("q", 10),
      new YouTubeAPIError("api", { statusCode: 500 }),
      new Error("config: c"),
      new Error("auth: a"),
      new Error("validation: v"),
      new Error("io"),
      "raw",
    ];
    // When converting each and re-validating against the schema
    // Then every ServiceError is a valid member of the discriminated union
    for (const input of inputs) {
      const se = toServiceError(input);
      expect(() => ServiceError.parse(se)).not.toThrow();
    }
  });
});
