import { describe, expect, test } from "bun:test";

// Imports by the published package name (not a relative path) so the tests
// exercise the package `exports` map / barrel re-export, not just the source
// file. A broken `exports` or missing barrel entry fails resolution here
// instead of slipping past tsc.
import {
  AuthError,
  AutomationError,
  ConfigError,
  GeneratorError,
  QuotaExhaustedError,
  UploadError,
  ValidationError,
  YouTubeAPIError,
} from "@youtube-automation/core";

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

describe("plain domain subclasses extend AutomationError", () => {
  // Each entry: concrete class paired with its expected `name`.
  const cases: readonly (readonly [
    new (m: string) => AutomationError,
    string,
  ])[] = [
    [ConfigError, "ConfigError"],
    [AuthError, "AuthError"],
    [ValidationError, "ValidationError"],
    [UploadError, "UploadError"],
    [GeneratorError, "GeneratorError"],
  ];

  for (const [Ctor, name] of cases) {
    test(`${name} instanceof AutomationError and Error`, () => {
      // Given an instance of the domain subclass
      const error = new Ctor("nope");
      // Then it sits under AutomationError in the hierarchy
      expect(error).toBeInstanceOf(AutomationError);
      expect(error).toBeInstanceOf(Error);
      expect(error).toBeInstanceOf(Ctor);
    });

    test(`${name} carries its message and class name`, () => {
      // Given an instance with a message
      const error = new Ctor("nope");
      // Then message and name are preserved
      expect(error.message).toBe("nope");
      expect(error.name).toBe(name);
    });
  }
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

describe("throw / catch round-trips", () => {
  // Each domain class must be catchable both as itself and as AutomationError.
  const throwers: readonly (readonly [string, () => never])[] = [
    [
      "ConfigError",
      () => {
        throw new ConfigError("c");
      },
    ],
    [
      "YouTubeAPIError",
      () => {
        throw new YouTubeAPIError("y");
      },
    ],
    [
      "QuotaExhaustedError",
      () => {
        throw new QuotaExhaustedError("q");
      },
    ],
    [
      "AuthError",
      () => {
        throw new AuthError("a");
      },
    ],
    [
      "ValidationError",
      () => {
        throw new ValidationError("v");
      },
    ],
    [
      "UploadError",
      () => {
        throw new UploadError("u");
      },
    ],
    [
      "GeneratorError",
      () => {
        throw new GeneratorError("g");
      },
    ],
  ];

  for (const [name, thrower] of throwers) {
    test(`${name} is catchable as AutomationError`, () => {
      // When the domain error is thrown
      // Then a generic AutomationError catch site captures it
      let caught: unknown;
      try {
        thrower();
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(AutomationError);
    });
  }
});
