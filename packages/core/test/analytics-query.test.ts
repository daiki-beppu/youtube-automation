import { describe, expect, test } from "bun:test";

import { QuotaExhaustedError, YouTubeAPIError } from "@youtube-automation/core";

import {
  executeQuery,
  shouldRetryAnalyticsQuery,
} from "../src/analytics/query.ts";
import type { QueryParams } from "../src/analytics/query.ts";

type QueryClient = Parameters<typeof executeQuery>[0];

const gaxiosError = (message: string, response: unknown): Error =>
  Object.assign(new Error(message), { response });

const queryParams: QueryParams = {
  endDate: "2026-06-30",
  ids: "channel==UC_test",
  metrics: "views",
  startDate: "2026-06-01",
};

const makeAnalyticsClient = (behavior: () => unknown) => {
  let calls: readonly unknown[] = [];
  const client = {
    reports: {
      query: (params: unknown) => {
        calls = [...calls, params];
        return Promise.resolve().then(behavior);
      },
    },
  };
  return {
    get calls() {
      return calls;
    },
    client,
  };
};

describe("executeQuery", () => {
  test("returns the reports.query response data", async () => {
    const data = { rows: [["2026-06-01", 10]] };
    const fake = makeAnalyticsClient(() => ({ data }));

    const result = await executeQuery(
      fake.client as unknown as QueryClient,
      queryParams,
      "analytics query"
    );

    expect(result).toBe(data);
    expect(fake.calls).toEqual([queryParams]);
  });

  test("promotes a gaxios 429 to QuotaExhaustedError with retryAfterSeconds", async () => {
    const { client } = makeAnalyticsClient(() => {
      throw gaxiosError("quota exceeded", {
        data: { error: { errors: [{ reason: "quotaExceeded" }] } },
        headers: { "Retry-After": "120" },
        status: 429,
      });
    });

    await expect(
      executeQuery(
        client as unknown as QueryClient,
        queryParams,
        "analytics query"
      )
    ).rejects.toMatchObject({
      retryAfterSeconds: 120,
      statusCode: 429,
    });
  });

  test("leaves retryAfterSeconds undefined for a non-string Retry-After header", async () => {
    const { client } = makeAnalyticsClient(() => {
      throw gaxiosError("quota exceeded", {
        data: { error: { errors: [{ reason: "quotaExceeded" }] } },
        headers: { "retry-after": null },
        status: 429,
      });
    });

    await expect(
      executeQuery(
        client as unknown as QueryClient,
        queryParams,
        "analytics query"
      )
    ).rejects.toMatchObject({
      retryAfterSeconds: undefined,
      statusCode: 429,
    });
  });

  for (const retryAfter of ["", "   ", "later"]) {
    test(`leaves retryAfterSeconds undefined for unusable Retry-After ${JSON.stringify(retryAfter)}`, async () => {
      const { client } = makeAnalyticsClient(() => {
        throw gaxiosError("quota exceeded", {
          data: { error: { errors: [{ reason: "quotaExceeded" }] } },
          headers: { "retry-after": retryAfter },
          status: 429,
        });
      });

      await expect(
        executeQuery(
          client as unknown as QueryClient,
          queryParams,
          "analytics query"
        )
      ).rejects.toMatchObject({
        retryAfterSeconds: undefined,
        statusCode: 429,
      });
    });
  }

  test("preserves existing typed quota errors", async () => {
    const error = new QuotaExhaustedError("quota exceeded", 30);
    const { client } = makeAnalyticsClient(() => {
      throw error;
    });

    await expect(
      executeQuery(
        client as unknown as QueryClient,
        queryParams,
        "analytics query"
      )
    ).rejects.toBe(error);
  });

  test("preserves existing typed non-quota YouTube API errors", async () => {
    const error = new YouTubeAPIError("forbidden", { statusCode: 403 });
    const { client } = makeAnalyticsClient(() => {
      throw error;
    });

    await expect(
      executeQuery(
        client as unknown as QueryClient,
        queryParams,
        "analytics query"
      )
    ).rejects.toBe(error);
  });

  test("promotes existing typed 429 YouTube API errors to quota errors", async () => {
    const { client } = makeAnalyticsClient(() => {
      throw new YouTubeAPIError("quota exceeded", { statusCode: 429 });
    });

    await expect(
      executeQuery(
        client as unknown as QueryClient,
        queryParams,
        "analytics query"
      )
    ).rejects.toBeInstanceOf(QuotaExhaustedError);
  });

  test("normalizes non-quota gaxios errors to YouTubeAPIError", async () => {
    const { client } = makeAnalyticsClient(() => {
      throw gaxiosError("forbidden", {
        data: { error: { errors: [{ reason: "insufficientPermissions" }] } },
        status: 403,
      });
    });

    await expect(
      executeQuery(
        client as unknown as QueryClient,
        queryParams,
        "analytics query"
      )
    ).rejects.toMatchObject({
      reason: "insufficientPermissions",
      statusCode: 403,
    });
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
