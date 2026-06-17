// Tests for collectVideoAnalyticsService (ADR-0003 §1) — the per-video metrics
// service that ports the Python VideoAnalyticsMixin (utils/video_analytics.py)
// to a pure Result boundary (issue #829).
//
// The service returns Promise<Result<{ metrics }, ServiceError>>: it never throws
// across its boundary and maps query failures to a ServiceError. The googleapis
// YouTube Analytics client (youtubeAnalytics_v2.Youtubeanalytics) is reached
// through a `deps` injection seam (mirroring image/service.ts:38-58 and
// oauth-refresh.test.ts:61-70), so these unit tests run with a fake client and
// never touch the network.
//
// Seam contract (documented here so the implementation matches the fakes):
//   deps.youtubeAnalytics.reports.query(params) -> { data: QueryResponse }
//     params: { ids: "channel==<channelId>", startDate, endDate,
//               dimensions: "video", metrics: "views,likes,comments,averageViewDuration",
//               filters?: "video==<videoId>" }
//     QueryResponse: { columnHeaders?: [{ name }], rows?: any[][] | null }
// On a 429 the query rejects with a gaxios-shaped error
//   { response: { status: 429, headers: { "retry-after": "<seconds>" } } }
// which the service promotes to a QuotaExhaustedError (retryAfterSeconds parsed
// from the Retry-After header) — non-retryable per the ADR-0003 retry規約 (#959).
//
// Output is the long/tidy melt: one record per (video, metric). The API metric
// `comments` is renamed to `commentCount`; metric columns are resolved by
// columnHeaders[].name (position-independent).

import { describe, expect, test } from "bun:test";

import { collectVideoAnalyticsService } from "@tayk/core/analytics/video";

// Derive input / deps shapes from the service signature so the test does not
// hard-code the exported type names (oauth-refresh.test.ts:25-26).
type VideoInput = Parameters<typeof collectVideoAnalyticsService>[0];
type VideoDeps = NonNullable<
  Parameters<typeof collectVideoAnalyticsService>[1]
>;

// --- fakes ----------------------------------------------------------------

type QueryBehavior = () => unknown;

// A fake youtubeAnalytics client whose reports.query records every params bag it
// was called with and runs the supplied behavior (a value-returning or throwing
// thunk) when awaited.
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

// A no-op backoff sleep so the retry path (non-429 API errors are retryable per
// defaultShouldRetry) resolves instantly instead of waiting the real 10s/30s.
const noSleep = (): Promise<void> => Promise.resolve();

const makeDeps = (client: unknown, sleep?: () => Promise<void>): VideoDeps =>
  ({
    youtubeAnalytics: client,
    ...(sleep === undefined ? {} : { sleep }),
  }) as unknown as VideoDeps;

// Builds a gaxios-shaped query response. Only `name` is set on each column
// header — that is the field the service resolves metrics by.
const queryResponse = (
  columns: readonly string[],
  rows: readonly unknown[][]
) => ({
  data: {
    columnHeaders: columns.map((name) => ({ name })),
    rows,
  },
});

// A gaxios-shaped 429 carrying a Retry-After hint, mirroring the rate-limit
// surface the service promotes to QuotaExhaustedError.
const quotaError = (): Error =>
  Object.assign(new Error("youtubeAnalytics.reports.query: quota exceeded"), {
    response: { headers: { "retry-after": "30" }, status: 429 },
  });

// A 429 whose Retry-After header is empty — there is no usable hint, so the
// service must leave retryAfterSeconds undefined (not coerce "" to 0).
const quotaErrorEmptyRetryAfter = (): Error =>
  Object.assign(new Error("youtubeAnalytics.reports.query: quota exceeded"), {
    response: { headers: { "retry-after": "" }, status: 429 },
  });

// A gaxios-shaped non-429 server error. defaultShouldRetry classifies it as
// retryable, so the service maps the exhausted failure to domain "api".
const serverError = (): Error =>
  Object.assign(new Error("internal server error"), {
    response: { status: 500 },
  });

const findRecord = (
  metrics: readonly { metric: string; value: number; videoId: string }[],
  videoId: string,
  metric: string
) => metrics.find((m) => m.videoId === videoId && m.metric === metric);

// The canonical column order: the video dimension followed by the four metrics
// in the API's metric names (comments, not commentCount).
const CANONICAL_COLUMNS = [
  "video",
  "views",
  "likes",
  "comments",
  "averageViewDuration",
];

const baseInput: VideoInput = {
  channelId: "UC_test_channel",
  endDate: "2026-06-14",
  startDate: "2026-06-01",
};

// --- success path ----------------------------------------------------------

describe("collectVideoAnalyticsService success", () => {
  test("melts each video row into one record per metric and maps comments to commentCount", async () => {
    // Given an Analytics response with two video rows across the four metric columns
    const { client } = makeAnalyticsClient(() =>
      queryResponse(CANONICAL_COLUMNS, [
        ["vidA", 1000, 50, 8, 215],
        ["vidB", 500, 20, 3, 180],
      ])
    );

    // When collecting per-video analytics
    const r = await collectVideoAnalyticsService(baseInput, makeDeps(client));

    // Then it succeeds with one record per (video, metric) — 2 videos × 4 metrics
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.metrics).toHaveLength(8);

    // And values land on the right (video, metric), with comments → commentCount
    expect(findRecord(r.value.metrics, "vidA", "views")?.value).toBe(1000);
    expect(findRecord(r.value.metrics, "vidA", "commentCount")?.value).toBe(8);
    expect(
      findRecord(r.value.metrics, "vidB", "averageViewDuration")?.value
    ).toBe(180);

    // And the raw API metric name never leaks into the output
    expect(findRecord(r.value.metrics, "vidA", "comments")).toBeUndefined();

    // And every emitted value is a number (output schema value: z.number())
    for (const record of r.value.metrics) {
      expect(typeof record.value).toBe("number");
    }
  });

  test("forwards channel id, video dimension, metric names and date range to the query", async () => {
    // Given a successful single-row response
    const { calls, client } = makeAnalyticsClient(() =>
      queryResponse(CANONICAL_COLUMNS, [["vidA", 1, 1, 1, 1]])
    );

    // When collecting analytics for a channel
    const r = await collectVideoAnalyticsService(baseInput, makeDeps(client));

    // Then it succeeds and issues exactly one query
    expect(r.ok).toBe(true);
    expect(calls).toHaveLength(1);
    const params = calls[0] as Record<string, unknown>;

    // And the channel id is encoded as the required ids filter, with the video dimension
    expect(params.ids).toBe("channel==UC_test_channel");
    expect(params.dimensions).toBe("video");

    // And the date range passes through unchanged
    expect(params.startDate).toBe("2026-06-01");
    expect(params.endDate).toBe("2026-06-14");

    // And the metrics use the API name `comments`, not the output name commentCount
    const metrics = String(params.metrics);
    expect(metrics).toContain("views");
    expect(metrics).toContain("likes");
    expect(metrics).toContain("comments");
    expect(metrics).toContain("averageViewDuration");
    expect(metrics).not.toContain("commentCount");

    // And no video filter is set when only a channel is requested
    expect(params.filters).toBeUndefined();
  });

  test("adds a video filter when videoId is supplied", async () => {
    // Given an input that narrows to a single video
    const { calls, client } = makeAnalyticsClient(() =>
      queryResponse(CANONICAL_COLUMNS, [["vidA", 10, 2, 1, 90]])
    );
    const input: VideoInput = { ...baseInput, videoId: "vidA" };

    // When collecting analytics for that video
    const r = await collectVideoAnalyticsService(input, makeDeps(client));

    // Then the query carries a video== filter while ids still scopes to the channel
    expect(r.ok).toBe(true);
    const params = calls[0] as Record<string, unknown>;
    expect(params.filters).toBe("video==vidA");
    expect(params.ids).toBe("channel==UC_test_channel");
  });

  test("resolves metric columns by name, independent of column order", async () => {
    // Given a response whose metric columns are in a scrambled, non-canonical order
    const scrambledColumns = [
      "video",
      "comments",
      "averageViewDuration",
      "views",
      "likes",
    ];
    const { client } = makeAnalyticsClient(() =>
      queryResponse(scrambledColumns, [["vidA", 8, 215, 1000, 50]])
    );

    // When collecting analytics
    const r = await collectVideoAnalyticsService(baseInput, makeDeps(client));

    // Then each value is matched to its metric by column name, not by position
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(findRecord(r.value.metrics, "vidA", "commentCount")?.value).toBe(8);
    expect(
      findRecord(r.value.metrics, "vidA", "averageViewDuration")?.value
    ).toBe(215);
    expect(findRecord(r.value.metrics, "vidA", "views")?.value).toBe(1000);
    expect(findRecord(r.value.metrics, "vidA", "likes")?.value).toBe(50);
  });

  test("returns an empty metrics array when the response carries no rows", async () => {
    // Given a response with column headers but the rows element omitted (API: no data)
    const { client } = makeAnalyticsClient(() => ({
      data: { columnHeaders: CANONICAL_COLUMNS.map((name) => ({ name })) },
    }));

    // When collecting analytics
    const r = await collectVideoAnalyticsService(baseInput, makeDeps(client));

    // Then it succeeds with an empty metric set rather than throwing
    expect(r.ok).toBe(true);
    if (!r.ok) {
      throw new Error(`expected ok, got ${r.error.domain}: ${r.error.message}`);
    }
    expect(r.value.metrics).toEqual([]);
  });
});

// --- quota path ------------------------------------------------------------

describe("collectVideoAnalyticsService quota", () => {
  test("maps a 429 to a quota ServiceError carrying retryAfterSeconds without retrying", async () => {
    // Given a query that rejects with a gaxios-shaped 429 + Retry-After header
    const { calls, client } = makeAnalyticsClient(() => {
      throw quotaError();
    });

    // When collecting analytics
    const r = await collectVideoAnalyticsService(baseInput, makeDeps(client));

    // Then the boundary returns err(domain "quota") — it never throws across itself
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a quota failure");
    }
    expect(r.error.domain).toBe("quota");
    if (r.error.domain === "quota") {
      expect(r.error.retryAfterSeconds).toBe(30);
    }

    // And quota is non-retryable: the query ran exactly once (ADR-0003 retry規約)
    expect(calls).toHaveLength(1);
  });

  test("leaves retryAfterSeconds undefined when the Retry-After header is empty", async () => {
    // Given a 429 whose Retry-After header is an empty string (no usable hint)
    const { client } = makeAnalyticsClient(() => {
      throw quotaErrorEmptyRetryAfter();
    });

    // When collecting analytics
    const r = await collectVideoAnalyticsService(baseInput, makeDeps(client));

    // Then it is still a quota error, but "" is not coerced to 0 seconds
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a quota failure");
    }
    expect(r.error.domain).toBe("quota");
    if (r.error.domain === "quota") {
      expect(r.error.retryAfterSeconds).toBeUndefined();
    }
  });
});

// --- api error path --------------------------------------------------------

describe("collectVideoAnalyticsService api error", () => {
  test('maps a non-429 server error to domain "api" after exhausting retries', async () => {
    // Given a query that always rejects with a gaxios-shaped 500
    const { calls, client } = makeAnalyticsClient(() => {
      throw serverError();
    });

    // When collecting analytics with a no-op backoff sleep injected
    const r = await collectVideoAnalyticsService(
      baseInput,
      makeDeps(client, noSleep)
    );

    // Then the boundary returns err(domain "api") carrying the HTTP status
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected an api failure");
    }
    expect(r.error.domain).toBe("api");
    if (r.error.domain === "api") {
      expect(r.error.httpStatus).toBe(500);
    }

    // And unlike quota, a 5xx is retryable: it ran the default 3 attempts
    expect(calls).toHaveLength(3);
  });
});

// --- malformed response (missing column) -----------------------------------

describe("collectVideoAnalyticsService malformed response", () => {
  test('maps a response missing an expected column to domain "io"', async () => {
    // Given a successful response whose rows omit the required `video` column
    const { client } = makeAnalyticsClient(() =>
      queryResponse(
        ["views", "likes", "comments", "averageViewDuration"],
        [[1000, 50, 8, 215]]
      )
    );

    // When collecting analytics
    const r = await collectVideoAnalyticsService(baseInput, makeDeps(client));

    // Then the missing-column guard surfaces as an io error (unprefixed throw)
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected an io failure");
    }
    expect(r.error.domain).toBe("io");
    expect(r.error.message).toContain("video");
  });

  test('maps a non-numeric metric value to domain "validation" via the output schema', async () => {
    // Given a well-formed response whose `views` cell is a string, not a number
    // (a distinct malformed-response mode from a missing column: the melt
    // succeeds, but the output schema's value: z.number() must reject the row)
    const { client } = makeAnalyticsClient(() =>
      queryResponse(CANONICAL_COLUMNS, [["vidA", "not-a-number", 50, 8, 215]])
    );

    // When collecting analytics
    const r = await collectVideoAnalyticsService(baseInput, makeDeps(client));

    // Then the output-schema guard surfaces as a validation error (ZodError →
    // toServiceError), not io — the value contract is load-bearing
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a validation failure");
    }
    expect(r.error.domain).toBe("validation");
  });
});

// --- input validation ------------------------------------------------------

describe("collectVideoAnalyticsService input validation", () => {
  test("rejects an unknown input key via the strict schema without querying", async () => {
    // Given a client that would succeed if it were ever reached
    const { calls, client } = makeAnalyticsClient(() =>
      queryResponse(CANONICAL_COLUMNS, [["vidA", 1, 1, 1, 1]])
    );

    // And an input carrying an extra key the `.strict()` schema must reject
    const malformed = {
      ...baseInput,
      unexpected: true,
    } as unknown as VideoInput;

    // When collecting analytics with the malformed input
    const r = await collectVideoAnalyticsService(malformed, makeDeps(client));

    // Then the boundary parses first: a validation error, query never invoked
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a validation failure");
    }
    expect(r.error.domain).toBe("validation");
    expect(calls).toEqual([]);
  });

  test("rejects a startDate that is not in YYYY-MM-DD form", async () => {
    const { calls, client } = makeAnalyticsClient(() =>
      queryResponse(CANONICAL_COLUMNS, [["vidA", 1, 1, 1, 1]])
    );
    // Given an input whose startDate uses slashes instead of the ISO date format
    const malformed: VideoInput = { ...baseInput, startDate: "2026/06/01" };

    // When collecting analytics
    const r = await collectVideoAnalyticsService(malformed, makeDeps(client));

    // Then the regex-constrained field fails validation before any query
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a validation failure");
    }
    expect(r.error.domain).toBe("validation");
    expect(calls).toEqual([]);
  });

  test("rejects input missing the required channelId", async () => {
    const { calls, client } = makeAnalyticsClient(() =>
      queryResponse(CANONICAL_COLUMNS, [["vidA", 1, 1, 1, 1]])
    );
    // Given an input with no channelId (videoId alone cannot scope an Analytics query)
    const malformed = {
      endDate: "2026-06-14",
      startDate: "2026-06-01",
    } as unknown as VideoInput;

    // When collecting analytics
    const r = await collectVideoAnalyticsService(malformed, makeDeps(client));

    // Then channelId being required is enforced at the boundary
    expect(r.ok).toBe(false);
    if (r.ok) {
      throw new Error("expected a validation failure");
    }
    expect(r.error.domain).toBe("validation");
    expect(calls).toEqual([]);
  });
});
