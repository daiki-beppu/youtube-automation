// Tests for collectChannelAnalyticsService (issue #828, ADR-0003 §1) — the
// channel-level daily-metrics service that ports the Python
// `utils/channel_analytics.py` Mixin to a Result boundary.
//
// Contract under test (the implementation in
// `packages/core/src/analytics/channel/` must satisfy these):
//   - service: collectChannelAnalyticsService(input, { youtubeAnalytics })
//       -> Promise<Result<ChannelAnalyticsOutput, ServiceError>>
//     never throws across the boundary; maps failures via toServiceError.
//   - output is LONG format: metrics[] where each record is one
//     { date, metric, value } cell (one metric per record, ADR-0003 §8 +
//     plan §4-1), with metric ∈ {views, estimatedMinutesWatched,
//     subscribersGained}.
//   - the YouTube Analytics client is reached through the injected `deps`
//     (image/service.ts:38-58 / oauth-refresh.test.ts pattern) so these unit
//     tests run with a fake `reports.query` and never touch the network.
//
// The fake client mirrors the googleapis surface verified against
// youtubeAnalytics/v2.d.ts: `client.reports.query(params)` resolves to
// `{ data: { columnHeaders?: { name? }[]; rows?: any[][] | null } }`.

import { describe, expect, test } from "bun:test";

import { QuotaExhaustedError, YouTubeAPIError } from "@youtube-automation/core";
import {
  ChannelAnalyticsInput,
  ChannelAnalyticsOutput,
  collectChannelAnalyticsService,
} from "@youtube-automation/core/analytics/channel";

// shouldRetryApiQuery is an internal cross-feature helper, not part of the
// package public exports. The retry-permit truth table is pinned through a
// relative import (oauth-interactive.test.ts:20 pattern).
import { shouldRetryApiQuery } from "../src/errors.ts";

// Derive the input / deps shapes from the service itself (oauth-refresh.test.ts:25-26)
// so the test pins behavior, not the exported name of the injection bag.
type ChannelAnalyticsDeps = Parameters<
  typeof collectChannelAnalyticsService
>[1];
type ChannelAnalyticsInputShape = Parameters<
  typeof collectChannelAnalyticsService
>[0];

// --- fakes ----------------------------------------------------------------

interface QueryResponse {
  readonly data: {
    readonly columnHeaders?: readonly { readonly name?: string }[];
    readonly rows?: readonly (readonly unknown[])[] | null;
  };
}
type QueryBehavior = () => QueryResponse;

// A fake YouTube Analytics client. `reports.query` records the params it was
// called with (so query-construction can be asserted) and runs the supplied
// behavior — a value-returning thunk for success, a throwing one for errors.
const makeAnalyticsClient = (behavior: QueryBehavior) => {
  const calls: unknown[] = [];
  const client = {
    reports: {
      query: (params: unknown) => {
        calls.push(params);
        return Promise.resolve().then(behavior);
      },
    },
  };
  return { calls, client };
};

const makeDeps = (
  client: unknown,
  sleep?: ChannelAnalyticsDeps["sleep"]
): ChannelAnalyticsDeps =>
  ({
    youtubeAnalytics: client,
    ...(sleep === undefined ? {} : { sleep }),
  }) as unknown as ChannelAnalyticsDeps;

// Builds a gaxios-shaped error (errors.test.ts:23): a real Error with a
// `response` carrying `status` + payload, mirroring the googleapis surface the
// service converts through YouTubeAPIError.fromGaxiosError.
const gaxiosError = (message: string, response: unknown): Error =>
  Object.assign(new Error(message), { response });

// Natural column order: the dimension (`day`) first, then the three metrics, as
// the YouTube Analytics API returns them.
const naturalResponse = (): QueryResponse => ({
  data: {
    columnHeaders: [
      { name: "day" },
      { name: "views" },
      { name: "estimatedMinutesWatched" },
      { name: "subscribersGained" },
    ],
    rows: [
      ["2026-06-01", 100, 500, 5],
      ["2026-06-02", 120, 560, 3],
    ],
  },
});

// Metric columns in a different order than the canonical request order, so the
// service must map by columnHeaders[].name (plan §4-3/§7, positional-index guard).
const shuffledResponse = (): QueryResponse => ({
  data: {
    columnHeaders: [
      { name: "day" },
      { name: "subscribersGained" },
      { name: "views" },
      { name: "estimatedMinutesWatched" },
    ],
    rows: [["2026-06-01", 5, 100, 500]],
  },
});

// A period with no data — the API omits `rows` (v2.d.ts contract).
const noRowsResponse = (): QueryResponse => ({
  data: {
    columnHeaders: [{ name: "day" }, { name: "views" }],
    rows: null,
  },
});

const baseInput: ChannelAnalyticsInputShape = {
  channelId: "UC_channel_123",
  endDate: "2026-06-02",
  startDate: "2026-06-01",
};

// The service's exact Result type, derived from the function under test so the
// narrowing helper stays type-exact without re-declaring the shape.
type ServiceResult = Awaited<ReturnType<typeof collectChannelAnalyticsService>>;

// Narrowing helper: fail loudly with the error domain when an ok was expected
// (the codebase's `if (!result.ok) throw` idiom, oauth-refresh.test.ts:93-95).
const expectOk = (result: ServiceResult) => {
  if (!result.ok) {
    throw new Error(
      `expected ok, got ${result.error.domain}: ${result.error.message}`
    );
  }
  return result.value;
};

// --- success path ---------------------------------------------------------

describe("collectChannelAnalyticsService success", () => {
  test("reshapes daily rows into one record per metric (long format)", async () => {
    // Given a fake client returning two days of three metrics each
    const { client } = makeAnalyticsClient(naturalResponse);

    // When collecting channel analytics for the period
    const result = await collectChannelAnalyticsService(
      baseInput,
      makeDeps(client)
    );

    // Then it is ok and carries 2 days × 3 metrics = 6 long records
    const value = expectOk(result);
    expect(value.metrics).toHaveLength(6);

    // And every (date, metric, value) cell is present
    expect(value.metrics).toContainEqual({
      date: "2026-06-01",
      metric: "views",
      value: 100,
    });
    expect(value.metrics).toContainEqual({
      date: "2026-06-01",
      metric: "estimatedMinutesWatched",
      value: 500,
    });
    expect(value.metrics).toContainEqual({
      date: "2026-06-01",
      metric: "subscribersGained",
      value: 5,
    });
    expect(value.metrics).toContainEqual({
      date: "2026-06-02",
      metric: "views",
      value: 120,
    });
    expect(value.metrics).toContainEqual({
      date: "2026-06-02",
      metric: "estimatedMinutesWatched",
      value: 560,
    });
    expect(value.metrics).toContainEqual({
      date: "2026-06-02",
      metric: "subscribersGained",
      value: 3,
    });
  });

  test("preserves values so callers can aggregate per metric", async () => {
    // Given the same two-day response
    const { client } = makeAnalyticsClient(naturalResponse);

    // When collecting
    const value = expectOk(
      await collectChannelAnalyticsService(baseInput, makeDeps(client))
    );

    // Then summing each metric across days yields the period totals
    const sumOf = (metric: string): number =>
      value.metrics
        .filter((m) => m.metric === metric)
        .reduce((total, m) => total + m.value, 0);
    expect(sumOf("views")).toBe(220);
    expect(sumOf("estimatedMinutesWatched")).toBe(1060);
    expect(sumOf("subscribersGained")).toBe(8);
  });

  test("resolves metric columns by header name, not position", async () => {
    // Given a response whose metric columns are in a different order than the
    // canonical request order (the service must map by columnHeaders[].name)
    const { client } = makeAnalyticsClient(shuffledResponse);

    // When collecting
    const value = expectOk(
      await collectChannelAnalyticsService(baseInput, makeDeps(client))
    );

    // Then each value still lands on the metric named in its column header
    expect(value.metrics).toContainEqual({
      date: "2026-06-01",
      metric: "views",
      value: 100,
    });
    expect(value.metrics).toContainEqual({
      date: "2026-06-01",
      metric: "subscribersGained",
      value: 5,
    });
    expect(value.metrics).toContainEqual({
      date: "2026-06-01",
      metric: "estimatedMinutesWatched",
      value: 500,
    });
  });

  test("returns an empty metrics array when the API omits rows", async () => {
    // Given a period with no data — the API omits `rows` (v2.d.ts contract)
    const { client } = makeAnalyticsClient(noRowsResponse);

    // When collecting
    const value = expectOk(
      await collectChannelAnalyticsService(baseInput, makeDeps(client))
    );

    // Then it is ok with no records (not an error)
    expect(value.metrics).toEqual([]);
  });
});

// --- API query construction contract --------------------------------------

describe("collectChannelAnalyticsService query construction", () => {
  test("queries the channel id position and the day dimension", async () => {
    // Given a fake client recording its query params
    const { calls, client } = makeAnalyticsClient(naturalResponse);

    // When collecting for a channel
    await collectChannelAnalyticsService(baseInput, makeDeps(client));

    // Then the channelId is sent in the `ids` position as channel==<id>, the
    // dimension is `day`, the dates are passed through, and all three metrics
    // are requested
    expect(calls).toHaveLength(1);
    const params = calls[0] as Record<string, unknown>;
    expect(params.ids).toBe("channel==UC_channel_123");
    expect(params.dimensions).toBe("day");
    expect(params.startDate).toBe("2026-06-01");
    expect(params.endDate).toBe("2026-06-02");
    const metrics = String(params.metrics);
    expect(metrics).toContain("views");
    expect(metrics).toContain("estimatedMinutesWatched");
    expect(metrics).toContain("subscribersGained");
  });

  test("narrows to a single video via filters, not the ids position", async () => {
    // Given an input that also carries a videoId
    const { calls, client } = makeAnalyticsClient(naturalResponse);
    const input: ChannelAnalyticsInputShape = {
      ...baseInput,
      videoId: "VID_456",
    };

    // When collecting
    await collectChannelAnalyticsService(input, makeDeps(client));

    // Then the videoId goes into `filters` as video==<id> — the ids position
    // still scopes the channel (the videoId is NOT swapped into ids)
    const params = calls[0] as Record<string, unknown>;
    expect(params.ids).toBe("channel==UC_channel_123");
    expect(String(params.filters)).toContain("video==VID_456");
  });

  test("omits the video filter when no videoId is given", async () => {
    // Given a channel-only input
    const { calls, client } = makeAnalyticsClient(naturalResponse);

    // When collecting
    await collectChannelAnalyticsService(baseInput, makeDeps(client));

    // Then no video filter is attached
    const params = calls[0] as Record<string, unknown>;
    expect(params.filters ?? "").not.toContain("video==");
  });
});

// --- quota error path -----------------------------------------------------

describe("collectChannelAnalyticsService quota error path", () => {
  test("maps a 429 quota error to a quota ServiceError without throwing", async () => {
    // Given a fake query that rejects with a gaxios-shaped 429 quota error
    const { client } = makeAnalyticsClient(() => {
      throw gaxiosError("quota exceeded", {
        data: { error: { errors: [{ reason: "quotaExceeded" }] } },
        status: 429,
      });
    });

    // When collecting
    const result = await collectChannelAnalyticsService(
      baseInput,
      makeDeps(client)
    );

    // Then the boundary returns err(domain "quota") — never throws — and the
    // quota variant is pinned to httpStatus 429 (errors.ts ServiceError)
    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a quota failure");
    }
    expect(result.error.domain).toBe("quota");
    if (result.error.domain === "quota") {
      expect(result.error.httpStatus).toBe(429);
    }
  });

  test("propagates the Retry-After header into retryAfterSeconds", async () => {
    // Given a 429 quota error whose gaxios response carries a Retry-After header
    const { client } = makeAnalyticsClient(() => {
      throw gaxiosError("quota exceeded", {
        data: { error: { errors: [{ reason: "quotaExceeded" }] } },
        headers: { "retry-after": "120" },
        status: 429,
      });
    });

    // When collecting
    const result = await collectChannelAnalyticsService(
      baseInput,
      makeDeps(client)
    );

    // Then the quota ServiceError surfaces the suggested wait (contract §1) so
    // callers can back off — the header value flows through as seconds
    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a quota failure");
    }
    expect(result.error.domain).toBe("quota");
    if (result.error.domain === "quota") {
      expect(result.error.retryAfterSeconds).toBe(120);
    }
  });

  test("does not retry a quota error — the query runs exactly once", async () => {
    // Given a query that always rejects with a 429 quota error
    const { calls, client } = makeAnalyticsClient(() => {
      throw gaxiosError("quota exceeded", {
        data: { error: { errors: [{ reason: "quotaExceeded" }] } },
        status: 429,
      });
    });

    // When collecting
    await collectChannelAnalyticsService(baseInput, makeDeps(client));

    // Then quota is surfaced to the caller without burning the retry budget
    // (ADR-0003: quota is returned as a Result, never retried). A regression
    // that made quota retryable would call the API 3× here.
    expect(calls).toHaveLength(1);
  });
});

// --- non-quota API error path ---------------------------------------------

describe("collectChannelAnalyticsService api error path", () => {
  test("retries a transient 500 through the service with injected sleep", async () => {
    // Given a query that fails once with a transient 500 and then succeeds
    const sleeps: number[] = [];
    const sleep: ChannelAnalyticsDeps["sleep"] = (ms) => {
      sleeps.push(ms);
      return Promise.resolve();
    };
    let attempts = 0;
    const { calls, client } = makeAnalyticsClient(() => {
      attempts += 1;
      if (attempts === 1) {
        throw gaxiosError("server error", {
          data: { error: { errors: [{ reason: "backendError" }] } },
          status: 500,
        });
      }
      return naturalResponse();
    });

    // When collecting with a no-op backoff sleep injected
    const result = await collectChannelAnalyticsService(
      baseInput,
      makeDeps(client, sleep)
    );

    // Then the retry runs through the service boundary without real waiting
    const value = expectOk(result);
    expect(value.metrics).toHaveLength(6);
    expect(calls).toHaveLength(2);
    expect(sleeps).toEqual([10_000]);
  });

  test("maps a 403 API error to an api ServiceError without throwing", async () => {
    // Given a fake query that rejects with a non-quota gaxios error
    const { client } = makeAnalyticsClient(() => {
      throw gaxiosError("forbidden", {
        data: { error: { errors: [{ reason: "forbidden" }] } },
        status: 403,
      });
    });

    // When collecting
    const result = await collectChannelAnalyticsService(
      baseInput,
      makeDeps(client)
    );

    // Then it is mapped to err(domain "api"), distinct from quota
    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected an api failure");
    }
    expect(result.error.domain).toBe("api");
  });

  test("does not retry a permanent 4xx error — the query runs exactly once", async () => {
    // Given a query that always rejects with a permanent 403
    const { calls, client } = makeAnalyticsClient(() => {
      throw gaxiosError("forbidden", {
        data: { error: { errors: [{ reason: "forbidden" }] } },
        status: 403,
      });
    });

    // When collecting
    await collectChannelAnalyticsService(baseInput, makeDeps(client));

    // Then a permanent client error is not retried — only 5xx / unknown-status
    // failures are transient per shouldRetryApiQuery (plan §4-2, load-bearing)
    expect(calls).toHaveLength(1);
  });
});

// --- input validation -----------------------------------------------------

describe("collectChannelAnalyticsService input validation", () => {
  test("rejects an unknown input key via the strict schema", async () => {
    // Given a client that would succeed if it were ever reached
    const { calls, client } = makeAnalyticsClient(naturalResponse);

    // And an input carrying an extra key the `.strict()` schema must reject
    const malformed = {
      ...baseInput,
      unexpected: true,
    } as unknown as ChannelAnalyticsInputShape;

    // When collecting with the malformed input
    const result = await collectChannelAnalyticsService(
      malformed,
      makeDeps(client)
    );

    // Then the boundary parses first and reports a validation ServiceError,
    // without ever calling the API
    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a validation failure");
    }
    expect(result.error.domain).toBe("validation");
    expect(calls).toHaveLength(0);
  });

  test("rejects a non YYYY-MM-DD start date", async () => {
    // Given a syntactically invalid start date
    const { client } = makeAnalyticsClient(naturalResponse);
    const input = {
      ...baseInput,
      startDate: "2026/06/01",
    } as ChannelAnalyticsInputShape;

    // When collecting
    const result = await collectChannelAnalyticsService(
      input,
      makeDeps(client)
    );

    // Then it is a validation ServiceError
    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a validation failure");
    }
    expect(result.error.domain).toBe("validation");
  });
});

// --- schema units ---------------------------------------------------------

describe("ChannelAnalyticsInput schema", () => {
  test("parses a channel-only input", () => {
    // Given a minimal valid input
    // Then strict parse round-trips it unchanged
    expect(ChannelAnalyticsInput.parse(baseInput)).toEqual(baseInput);
  });

  test("parses an input with an optional videoId", () => {
    // Given an input including videoId
    const input = { ...baseInput, videoId: "VID_456" };
    // Then it parses with the videoId retained
    expect(ChannelAnalyticsInput.parse(input)).toEqual(input);
  });

  test("rejects a missing channelId", () => {
    // Given an input without the required channelId
    const input = { endDate: "2026-06-02", startDate: "2026-06-01" };
    // Then parse throws (channelId is required)
    expect(() => ChannelAnalyticsInput.parse(input)).toThrow();
  });

  test("rejects an unknown key (strict)", () => {
    // Given an input with an extra key
    const input = { ...baseInput, extra: 1 };
    // Then the strict schema rejects it
    expect(() => ChannelAnalyticsInput.parse(input)).toThrow();
  });
});

describe("ChannelAnalyticsOutput schema", () => {
  test("parses a valid long-format payload", () => {
    // Given a payload of one record per (date, metric)
    const payload = {
      metrics: [
        { date: "2026-06-01", metric: "views", value: 100 },
        { date: "2026-06-01", metric: "subscribersGained", value: 5 },
      ],
    };
    // Then it parses unchanged
    expect(ChannelAnalyticsOutput.parse(payload)).toEqual(payload);
  });

  test("rejects a metric outside the allowed enum", () => {
    // Given a record naming a metric the service does not collect
    const payload = {
      metrics: [{ date: "2026-06-01", metric: "likes", value: 9 }],
    };
    // Then the enum constraint rejects it
    expect(() => ChannelAnalyticsOutput.parse(payload)).toThrow();
  });

  test("rejects an unknown key on a metric record (strict)", () => {
    // Given a record with an extra field
    const payload = {
      metrics: [
        { country: "JP", date: "2026-06-01", metric: "views", value: 100 },
      ],
    };
    // Then the strict schema rejects it
    expect(() => ChannelAnalyticsOutput.parse(payload)).toThrow();
  });
});

// --- retry-permit predicate -----------------------------------------------
// Pins shouldRetryApiQuery's truth table directly. The service's quota/403 paths
// only assert the *negative* branch (calls === 1); without this, the
// retry-permit branch (5xx / unknown-status → retry, load-bearing per
// service.ts:83-94) is unexercised and a regression making 5xx non-retryable
// would pass silently. Pure predicate calls — no real sleep / API.

describe("shouldRetryApiQuery", () => {
  test("retries a transient 5xx server error", () => {
    // Given the normalizer produced a 503 YouTubeAPIError
    // Then the failure is treated as transient and retried
    expect(
      shouldRetryApiQuery(new YouTubeAPIError("boom", { statusCode: 503 }))
    ).toBe(true);
  });

  test("retries at the 500 server-error boundary", () => {
    // Given the lowest 5xx status (HTTP_SERVER_ERROR_MIN)
    // Then it is still transient
    expect(
      shouldRetryApiQuery(new YouTubeAPIError("boom", { statusCode: 500 }))
    ).toBe(true);
  });

  test("retries when the status is unknown (network drop normalized without a status)", () => {
    // Given a YouTubeAPIError carrying no statusCode
    // Then it is treated as a transient failure
    expect(shouldRetryApiQuery(new YouTubeAPIError("boom"))).toBe(true);
  });

  test("does not retry a permanent 4xx client error", () => {
    // Given a 403 forbidden
    // Then it is permanent and not retried
    expect(
      shouldRetryApiQuery(new YouTubeAPIError("forbidden", { statusCode: 403 }))
    ).toBe(false);
  });

  test("does not retry a quota error (surfaced as a Result instead)", () => {
    // Given a 429 quota error — defaultShouldRetry gates it out (ADR-0003)
    // Then it is not retried
    expect(shouldRetryApiQuery(new QuotaExhaustedError("quota exceeded"))).toBe(
      false
    );
  });

  test("retries a raw transient error", () => {
    expect(shouldRetryApiQuery(new Error("transient blip"))).toBe(true);
  });
});
