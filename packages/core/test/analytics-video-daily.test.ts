// Tests for the video × day daily analytics service boundary (ADR-0003, #830).
//
// The service collects per-video daily views from the YouTube Analytics API.
// At `dimensions=video,day` granularity only `views` is available — impressions
// and CTR are NOT exposed by the API at this dimension pair.
//
// The canonical output shape is `{ metrics: [{ date, videoId, views }, ...] }`
// (ADR-0003 template: one record per data point under a `metrics` array).
//
// All tests mock the `YouTubeAnalyticsClient` dependency and inject a fake
// `sleep` to prevent real backoff waits. The service NEVER throws — failures
// surface as `Result<_, ServiceError>`.

import { describe, expect, test } from "bun:test";

import { QuotaExhaustedError } from "@youtube-automation/core";
import { collectVideoDailyAnalyticsService } from "@youtube-automation/core/analytics/video-daily";
import type { CollectVideoDailyAnalyticsInput } from "@youtube-automation/core/analytics/video-daily";
import type { YouTubeAnalyticsClient } from "@youtube-automation/core/oauth/client";

// --- fakes ----------------------------------------------------------------

// A fake YouTube Analytics client. Records query calls and delegates to a
// behavior thunk that returns or throws. The thunk is invoked on every query
// (including each retry attempt), so a stateful closure can vary behavior per
// attempt and an "always throws" thunk covers the whole retry budget.
const makeMockYtAnalytics = (behavior: () => unknown) => {
  const queryCalls: unknown[] = [];
  return {
    mock: {
      reports: {
        query: (params: unknown) => {
          queryCalls.push(params);
          return Promise.resolve().then(behavior);
        },
      },
    } as unknown as YouTubeAnalyticsClient,
    queryCalls,
  };
};

// Build a Gaxios-shaped error (an Error with a `response` carrying status /
// headers / data), mirroring the convention in errors.test.ts and what the
// googleapis client actually throws.
const gaxiosError = (message: string, response: unknown): Error =>
  Object.assign(new Error(message), { response });

// Inject in place of real backoff so retrying paths never wait on a timer.
const noSleep = () => Promise.resolve();

const baseInput: CollectVideoDailyAnalyticsInput = {
  channelId: "UC_test_channel",
  endDate: "2025-01-31",
  startDate: "2025-01-01",
};

const videoDailyColumnHeaders = [
  { name: "video" },
  { name: "day" },
  { name: "views" },
];

// --- success path ----------------------------------------------------------

describe("collectVideoDailyAnalyticsService success", () => {
  test("returns ok Result with one metrics record per API row", async () => {
    const { mock } = makeMockYtAnalytics(() => ({
      data: {
        columnHeaders: videoDailyColumnHeaders,
        rows: [
          ["vid1", "2025-01-01", 100],
          ["vid1", "2025-01-02", 150],
          ["vid2", "2025-01-01", 200],
        ],
      },
    }));
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.metrics).toHaveLength(3);
    expect(r.value.metrics[0]).toEqual({
      date: "2025-01-01",
      videoId: "vid1",
      views: 100,
    });
    expect(r.value.metrics[1]).toEqual({
      date: "2025-01-02",
      videoId: "vid1",
      views: 150,
    });
    expect(r.value.metrics[2]).toEqual({
      date: "2025-01-01",
      videoId: "vid2",
      views: 200,
    });
  });

  test("passes the fixed query contract for channel-wide collection", async () => {
    const { mock, queryCalls } = makeMockYtAnalytics(() => ({
      data: { columnHeaders: videoDailyColumnHeaders, rows: [] },
    }));
    await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(queryCalls).toHaveLength(1);
    const params = queryCalls[0] as Record<string, unknown>;
    expect(params.dimensions).toBe("video,day");
    expect(params.metrics).toBe("views");
    expect(params.sort).toBe("day");
    expect(params.ids).toBe("channel==UC_test_channel");
    expect(params.startDate).toBe("2025-01-01");
    expect(params.endDate).toBe("2025-01-31");
    expect(params.filters).toBeUndefined();
  });

  test("preserves a numeric zero views value", async () => {
    const { mock } = makeMockYtAnalytics(() => ({
      data: {
        columnHeaders: videoDailyColumnHeaders,
        rows: [["vid1", "2025-01-01", 0]],
      },
    }));
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.metrics[0]).toEqual({
      date: "2025-01-01",
      videoId: "vid1",
      views: 0,
    });
  });

  test("normalizes null views values to 0", async () => {
    const { mock } = makeMockYtAnalytics(() => ({
      data: {
        columnHeaders: videoDailyColumnHeaders,
        rows: [["vid1", "2025-01-01", null]],
      },
    }));
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.metrics).toEqual([
      { date: "2025-01-01", videoId: "vid1", views: 0 },
    ]);
  });

  test("maps rows by columnHeaders when API column order changes", async () => {
    const { mock } = makeMockYtAnalytics(() => ({
      data: {
        columnHeaders: [{ name: "day" }, { name: "video" }, { name: "views" }],
        rows: [["2025-01-01", "vid1", 100]],
      },
    }));
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.metrics).toEqual([
      { date: "2025-01-01", videoId: "vid1", views: 100 },
    ]);
  });
});

// --- malformed API response ------------------------------------------------

describe("collectVideoDailyAnalyticsService malformed API response", () => {
  test("returns io error when the views column header is missing", async () => {
    const { mock } = makeMockYtAnalytics(() => ({
      data: {
        columnHeaders: [{ name: "video" }, { name: "day" }],
        rows: [["vid1", "2025-01-01", 100]],
      },
    }));
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("io");
    expect(r.error.message).toContain('missing the "views" column');
  });

  test("returns io error when rows are present without columnHeaders", async () => {
    const { mock } = makeMockYtAnalytics(() => ({
      data: { rows: [["vid1", "2025-01-01", 100]] },
    }));
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("io");
    expect(r.error.message).toContain("response has rows but no columnHeaders");
  });

  test("returns io error when a row is missing the views cell", async () => {
    const { mock } = makeMockYtAnalytics(() => ({
      data: {
        columnHeaders: videoDailyColumnHeaders,
        rows: [["vid1", "2025-01-01"]],
      },
    }));
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("io");
    expect(r.error.message).toContain('non-numeric "views" value');
  });
});

// --- video filter ----------------------------------------------------------

describe("collectVideoDailyAnalyticsService with videoIds filter", () => {
  test("passes filters param when videoIds is provided", async () => {
    const { mock, queryCalls } = makeMockYtAnalytics(() => ({
      data: {
        columnHeaders: videoDailyColumnHeaders,
        rows: [["vid1", "2025-01-01", 50]],
      },
    }));
    const r = await collectVideoDailyAnalyticsService(
      { ...baseInput, videoIds: ["vid1", "vid2"] },
      { sleep: noSleep, ytAnalytics: mock }
    );
    expect(r.ok).toBe(true);
    expect(queryCalls).toHaveLength(1);
    const params = queryCalls[0] as Record<string, unknown>;
    expect(params.filters).toBe("video==vid1,vid2");
    expect(params.dimensions).toBe("video,day");
    expect(params.metrics).toBe("views");
    expect(params.ids).toBe("channel==UC_test_channel");
  });

  test("omits filters param when videoIds is an empty array", async () => {
    const { mock, queryCalls } = makeMockYtAnalytics(() => ({
      data: { columnHeaders: videoDailyColumnHeaders, rows: [] },
    }));
    const r = await collectVideoDailyAnalyticsService(
      { ...baseInput, videoIds: [] },
      { sleep: noSleep, ytAnalytics: mock }
    );
    expect(r.ok).toBe(true);
    const params = queryCalls[0] as Record<string, unknown>;
    expect(params.filters).toBeUndefined();
  });
});

// --- quota error -----------------------------------------------------------

describe("collectVideoDailyAnalyticsService quota error", () => {
  test("returns err with domain quota on QuotaExhaustedError", async () => {
    const { mock } = makeMockYtAnalytics(() => {
      throw new QuotaExhaustedError("quota exceeded", 3600);
    });
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    expect(r.error.domain).toBe("quota");
  });

  test("does not retry a quota error (single API call)", async () => {
    const { mock, queryCalls } = makeMockYtAnalytics(() => {
      throw new QuotaExhaustedError("quota exceeded", 3600);
    });
    await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(queryCalls).toHaveLength(1);
  });

  test("surfaces retryAfterSeconds on the quota ServiceError", async () => {
    const { mock } = makeMockYtAnalytics(() => {
      throw new QuotaExhaustedError("quota exceeded", 1800);
    });
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    if (r.error.domain !== "quota") {
      throw new Error(`expected quota, got ${r.error.domain}`);
    }
    expect(r.error.httpStatus).toBe(429);
    expect(r.error.retryAfterSeconds).toBe(1800);
  });

  test("converts a raw gaxios 429 into a quota ServiceError without retrying", async () => {
    const { mock, queryCalls } = makeMockYtAnalytics(() => {
      throw gaxiosError("rate limit exceeded", {
        data: { error: { errors: [{ reason: "quotaExceeded" }] } },
        headers: { "retry-after": "1800" },
        status: 429,
      });
    });
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    if (r.error.domain !== "quota") {
      throw new Error(`expected quota, got ${r.error.domain}`);
    }
    expect(r.error.httpStatus).toBe(429);
    expect(r.error.retryAfterSeconds).toBe(1800);
    expect(queryCalls).toHaveLength(1);
  });
});

// --- transient vs permanent API errors ------------------------------------

describe("collectVideoDailyAnalyticsService retry behavior", () => {
  test("retries a transient 5xx and succeeds on the next attempt", async () => {
    let attempt = 0;
    const { mock, queryCalls } = makeMockYtAnalytics(() => {
      attempt += 1;
      if (attempt === 1) {
        throw gaxiosError("server error", { data: {}, status: 500 });
      }
      return {
        data: {
          columnHeaders: videoDailyColumnHeaders,
          rows: [["vid1", "2025-01-01", 42]],
        },
      };
    });
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.metrics).toEqual([
      { date: "2025-01-01", videoId: "vid1", views: 42 },
    ]);
    expect(queryCalls).toHaveLength(2);
  });

  test("does not retry a permanent 4xx and returns an api ServiceError", async () => {
    const { mock, queryCalls } = makeMockYtAnalytics(() => {
      throw gaxiosError("forbidden", {
        data: { error: { errors: [{ reason: "forbidden" }] } },
        status: 403,
      });
    });
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected failure");
    }
    if (r.error.domain !== "api") {
      throw new Error(`expected api, got ${r.error.domain}`);
    }
    expect(r.error.httpStatus).toBe(403);
    expect(r.error.reason).toBe("forbidden");
    expect(queryCalls).toHaveLength(1);
  });
});

// --- empty response --------------------------------------------------------

describe("collectVideoDailyAnalyticsService empty response", () => {
  test("returns ok with empty metrics when API returns no data rows", async () => {
    const { mock } = makeMockYtAnalytics(() => ({
      data: { rows: [] },
    }));
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.metrics).toEqual([]);
  });

  test("returns ok with empty metrics when the response has no rows field", async () => {
    const { mock } = makeMockYtAnalytics(() => ({
      data: {},
    }));
    const r = await collectVideoDailyAnalyticsService(baseInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.metrics).toEqual([]);
  });
});

// --- input validation ------------------------------------------------------

describe("collectVideoDailyAnalyticsService input validation", () => {
  test("returns err with domain validation when input has extra keys", async () => {
    const { mock, queryCalls } = makeMockYtAnalytics(() => ({
      data: { columnHeaders: videoDailyColumnHeaders, rows: [] },
    }));
    const malformed = {
      ...baseInput,
      unexpected: true,
    } as unknown as CollectVideoDailyAnalyticsInput;

    const r = await collectVideoDailyAnalyticsService(malformed, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected validation failure");
    }
    expect(r.error.domain).toBe("validation");
    expect(queryCalls).toEqual([]);
  });

  test("returns err with domain validation when date format is invalid", async () => {
    const { mock, queryCalls } = makeMockYtAnalytics(() => ({
      data: { columnHeaders: videoDailyColumnHeaders, rows: [] },
    }));
    const badInput = {
      channelId: "UC_test",
      endDate: "2025-01-31",
      startDate: "01/01/2025",
    } as unknown as CollectVideoDailyAnalyticsInput;

    const r = await collectVideoDailyAnalyticsService(badInput, {
      sleep: noSleep,
      ytAnalytics: mock,
    });
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected validation failure");
    }
    expect(r.error.domain).toBe("validation");
    expect(queryCalls).toEqual([]);
  });
});
