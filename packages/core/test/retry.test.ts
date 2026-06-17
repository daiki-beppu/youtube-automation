// Tests for the shared retry seam `withRetry` / `defaultShouldRetry` (#959).
//
// The seam owns the retry budget that providers used to reimplement per
// adapter: a default of 3 attempts with a 10/30/60-second backoff schedule
// (asserted here in ms via an injected fake sleep recorder). Non-retryable
// errors — `QuotaExhaustedError` (ADR-0003: quota goes back to the caller as a
// Result) and `config:` / `validation:` / `auth:`-prefixed domain errors — are
// rethrown immediately; everything else retries and the LAST error is rethrown
// once the budget is exhausted (never swallowed).

import { describe, expect, test } from "bun:test";

import { defaultShouldRetry, QuotaExhaustedError, withRetry } from "@tayk/core";

// Records every injected sleep so no test waits on real timers.
const makeSleepRecorder = () => {
  const sleeps: number[] = [];
  return {
    sleep: (ms: number): Promise<void> => {
      sleeps.push(ms);
      return Promise.resolve();
    },
    sleeps,
  };
};

// An attempt that consumes the next behavior per call (throwing or returning).
const makeAttempt = <T>(behaviors: (() => T)[]) => {
  const calls: number[] = [];
  const attempt = (attemptIndex: number): Promise<T> => {
    calls.push(attemptIndex);
    const behavior =
      behaviors[Math.min(calls.length - 1, behaviors.length - 1)];
    if (!behavior) {
      throw new Error("test setup: no behavior queued");
    }
    return Promise.resolve().then(behavior);
  };
  return { attempt, calls };
};

// --- success path -----------------------------------------------------------

describe("withRetry success", () => {
  test("returns the first successful value without sleeping", async () => {
    // Given an attempt that succeeds immediately
    const { sleep, sleeps } = makeSleepRecorder();
    const { attempt, calls } = makeAttempt([() => "ok"]);

    // When running it through withRetry
    const value = await withRetry(attempt, { sleep });

    // Then the value is returned after one attempt and no backoff wait
    expect(value).toBe("ok");
    expect(calls).toEqual([0]);
    expect(sleeps).toEqual([]);
  });

  test("retries retryable errors with the 10s/30s backoff then succeeds", async () => {
    // Given two transient failures followed by a success
    const { sleep, sleeps } = makeSleepRecorder();
    const { attempt, calls } = makeAttempt<string>([
      () => {
        throw new Error("503 backend unavailable");
      },
      () => {
        throw new Error("deadline exceeded");
      },
      () => "third time lucky",
    ]);

    // When running it through withRetry with the default policy
    const value = await withRetry(attempt, { sleep });

    // Then the third attempt wins after the documented backoff series (in ms)
    expect(value).toBe("third time lucky");
    expect(calls).toEqual([0, 1, 2]);
    expect(sleeps).toEqual([10_000, 30_000]);
  });
});

// --- non-retryable short-circuit ---------------------------------------------

describe("withRetry non-retryable errors", () => {
  test("rethrows a config:-prefixed error immediately without retrying", async () => {
    // Given an attempt that throws a config domain error
    const { sleep, sleeps } = makeSleepRecorder();
    const { attempt, calls } = makeAttempt<never>([
      () => {
        throw new Error("config: aspect_ratio が未対応です");
      },
    ]);

    // When running it through withRetry
    // Then the error surfaces as-is after one attempt and no backoff wait
    await expect(withRetry(attempt, { sleep })).rejects.toThrow(/^config:/u);
    expect(calls).toEqual([0]);
    expect(sleeps).toEqual([]);
  });

  test("rethrows a QuotaExhaustedError immediately (quota is not retried)", async () => {
    // Given an attempt that signals quota exhaustion (ADR-0003)
    const { sleep, sleeps } = makeSleepRecorder();
    const quota = new QuotaExhaustedError("quota exceeded", 120);
    const { attempt, calls } = makeAttempt<never>([
      () => {
        throw quota;
      },
    ]);

    // When running it through withRetry
    let caught: unknown;
    try {
      await withRetry(attempt, { sleep });
    } catch (error) {
      caught = error;
    }

    // Then the very same error instance is rethrown with no retry
    expect(caught).toBe(quota);
    expect(calls).toEqual([0]);
    expect(sleeps).toEqual([]);
  });
});

// --- budget exhaustion --------------------------------------------------------

describe("withRetry budget exhaustion", () => {
  test("rethrows the LAST error after maxAttempts failures", async () => {
    // Given an attempt that fails differently on every call
    const { sleep, sleeps } = makeSleepRecorder();
    const { attempt, calls } = makeAttempt<never>([
      () => {
        throw new Error("first failure");
      },
      () => {
        throw new Error("second failure");
      },
      () => {
        throw new Error("third failure");
      },
    ]);

    // When the default 3-attempt budget is exhausted
    let caught: unknown;
    try {
      await withRetry(attempt, { sleep });
    } catch (error) {
      caught = error;
    }

    // Then the last error (not the first) is rethrown after two waits
    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toBe("third failure");
    expect(calls).toEqual([0, 1, 2]);
    expect(sleeps).toEqual([10_000, 30_000]);
  });

  test("reuses the tail backoff value when attempts outnumber the schedule", async () => {
    // Given 5 attempts but only a two-entry backoff schedule
    const { sleep, sleeps } = makeSleepRecorder();
    const { attempt, calls } = makeAttempt<never>([
      () => {
        throw new Error("always failing");
      },
    ]);

    // When running with maxAttempts=5 and backoffSeconds=[1, 2]
    let caught: unknown;
    try {
      await withRetry(attempt, {
        backoffSeconds: [1, 2],
        maxAttempts: 5,
        sleep,
      });
    } catch (error) {
      caught = error;
    }

    // Then the tail value (2s) is reused for every wait beyond the schedule
    expect((caught as Error).message).toBe("always failing");
    expect(calls).toEqual([0, 1, 2, 3, 4]);
    expect(sleeps).toEqual([1000, 2000, 2000, 2000]);
  });
});

// --- defaultShouldRetry --------------------------------------------------------

describe("defaultShouldRetry", () => {
  test("classifies domain prefixes and quota as non-retryable", () => {
    // Given the documented non-retryable shapes
    // When classifying them
    // Then prefixes and quota are false; transient errors and non-Errors are true
    expect(defaultShouldRetry(new Error("config: broken"))).toBe(false);
    expect(defaultShouldRetry(new Error("validation: bad field"))).toBe(false);
    expect(defaultShouldRetry(new Error("auth: token expired"))).toBe(false);
    expect(defaultShouldRetry(new QuotaExhaustedError("quota"))).toBe(false);
    expect(defaultShouldRetry(new Error("503 backend unavailable"))).toBe(true);
    expect(defaultShouldRetry("string error")).toBe(true);
  });
});
