import { describe, expect, test } from "bun:test";

import { QuotaExhaustedError } from "@youtube-automation/core";
import {
  TrafficSourceAnalyticsInput,
  TrafficSourceAnalyticsOutput,
  collectTrafficSourceService,
} from "@youtube-automation/core/analytics/traffic-source";

type TrafficSourceInput = Parameters<typeof collectTrafficSourceService>[0];
type TrafficSourceDeps = Parameters<typeof collectTrafficSourceService>[1];
type TrafficSourceResult = Awaited<
  ReturnType<typeof collectTrafficSourceService>
>;

interface QueryResponse {
  readonly data: {
    readonly columnHeaders?: readonly { readonly name?: string }[];
    readonly rows?: readonly (readonly unknown[])[] | null;
  };
}

const columns = [
  "insightTrafficSourceType",
  "views",
  "estimatedMinutesWatched",
  "averageViewDuration",
] as const;

const baseInput: TrafficSourceInput = {
  channelId: "UC_test_channel",
  endDate: "2026-06-30",
  startDate: "2026-06-01",
};

const makeAnalyticsClient = (behavior: () => QueryResponse) => {
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

const makeDeps = (client: unknown): TrafficSourceDeps =>
  ({ youtubeAnalytics: client }) as unknown as TrafficSourceDeps;

const makeDepsWithNoSleep = (client: unknown): TrafficSourceDeps =>
  ({
    sleep: () => Promise.resolve(),
    youtubeAnalytics: client,
  }) as unknown as TrafficSourceDeps;

const gaxiosError = (message: string, response: unknown): Error =>
  Object.assign(new Error(message), { response });

const queryResponse = (
  columnNames: readonly string[],
  rows: readonly (readonly unknown[])[]
): QueryResponse => ({
  data: {
    columnHeaders: columnNames.map((name) => ({ name })),
    rows,
  },
});

const canonicalResponse = (): QueryResponse =>
  queryResponse(columns, [
    ["YT_SEARCH", 150, 600, 240],
    ["BROWSE", 100, 350, 210],
    ["RELATED_VIDEO", 50, 125, 150],
  ]);

const expectOk = (result: TrafficSourceResult) => {
  if (!result.ok) {
    throw new Error(
      `expected ok, got ${result.error.domain}: ${result.error.message}`
    );
  }
  return result.value;
};

const findMetric = (
  metrics: readonly {
    readonly metric: string;
    readonly trafficSourceType: string;
    readonly value: number;
  }[],
  trafficSourceType: string,
  metric: string
) =>
  metrics.find(
    (record) =>
      record.trafficSourceType === trafficSourceType && record.metric === metric
  );

const expectValidationError = async (
  input: TrafficSourceInput,
  client: unknown,
  calls: readonly unknown[]
) => {
  const result = await collectTrafficSourceService(input, makeDeps(client));

  expect(result.ok).toBe(false);
  if (result.ok) {
    throw new Error("expected validation failure");
  }
  expect(result.error.domain).toBe("validation");
  expect(calls).toHaveLength(0);
};

describe("collectTrafficSourceService success", () => {
  test("returns one long-format record per traffic source metric", async () => {
    const { client } = makeAnalyticsClient(canonicalResponse);

    const value = expectOk(
      await collectTrafficSourceService(baseInput, makeDeps(client))
    );

    expect(value.metrics).toHaveLength(12);
    expect(findMetric(value.metrics, "YT_SEARCH", "views")?.value).toBe(150);
    expect(
      findMetric(value.metrics, "YT_SEARCH", "estimatedMinutesWatched")?.value
    ).toBe(600);
    expect(
      findMetric(value.metrics, "YT_SEARCH", "averageViewDuration")?.value
    ).toBe(240);
    expect(
      findMetric(value.metrics, "YT_SEARCH", "viewSharePercent")?.value
    ).toBe(50);
    expect(findMetric(value.metrics, "BROWSE", "viewSharePercent")?.value).toBe(
      33.3
    );
    expect(
      findMetric(value.metrics, "RELATED_VIDEO", "viewSharePercent")?.value
    ).toBe(16.7);
  });

  test("resolves source and metric columns by header name", async () => {
    const { client } = makeAnalyticsClient(() =>
      queryResponse(
        [
          "averageViewDuration",
          "views",
          "insightTrafficSourceType",
          "estimatedMinutesWatched",
        ],
        [[240, 150, "YT_SEARCH", 600]]
      )
    );

    const value = expectOk(
      await collectTrafficSourceService(baseInput, makeDeps(client))
    );

    expect(value.metrics).toContainEqual({
      metric: "views",
      trafficSourceType: "YT_SEARCH",
      value: 150,
    });
    expect(value.metrics).toContainEqual({
      metric: "estimatedMinutesWatched",
      trafficSourceType: "YT_SEARCH",
      value: 600,
    });
    expect(value.metrics).toContainEqual({
      metric: "averageViewDuration",
      trafficSourceType: "YT_SEARCH",
      value: 240,
    });
    expect(value.metrics).toContainEqual({
      metric: "viewSharePercent",
      trafficSourceType: "YT_SEARCH",
      value: 100,
    });
  });

  test("returns an empty metrics array when the API omits rows", async () => {
    const { client } = makeAnalyticsClient(() => ({
      data: { columnHeaders: columns.map((name) => ({ name })), rows: null },
    }));

    const value = expectOk(
      await collectTrafficSourceService(baseInput, makeDeps(client))
    );

    expect(value.metrics).toEqual([]);
  });

  test("uses zero share when total views are zero", async () => {
    const { client } = makeAnalyticsClient(() =>
      queryResponse(columns, [["YT_SEARCH", 0, 0, 0]])
    );

    const value = expectOk(
      await collectTrafficSourceService(baseInput, makeDeps(client))
    );

    expect(
      findMetric(value.metrics, "YT_SEARCH", "viewSharePercent")?.value
    ).toBe(0);
  });

  test("uses the API averageViewDuration instead of recalculating from watched minutes", async () => {
    const { client } = makeAnalyticsClient(() =>
      queryResponse(columns, [["YT_SEARCH", 120, 1000, 321]])
    );

    const value = expectOk(
      await collectTrafficSourceService(baseInput, makeDeps(client))
    );

    expect(
      findMetric(value.metrics, "YT_SEARCH", "averageViewDuration")?.value
    ).toBe(321);
  });

  test("aggregates duplicate traffic source rows with a views-weighted average duration", async () => {
    const { client } = makeAnalyticsClient(() =>
      queryResponse(columns, [
        ["YT_SEARCH", 100, 100, 30],
        ["BROWSE", 50, 150, 180],
        ["YT_SEARCH", 50, 900, 90],
      ])
    );

    const value = expectOk(
      await collectTrafficSourceService(baseInput, makeDeps(client))
    );

    expect(value.metrics).toHaveLength(8);
    expect(findMetric(value.metrics, "YT_SEARCH", "views")?.value).toBe(150);
    expect(
      findMetric(value.metrics, "YT_SEARCH", "estimatedMinutesWatched")?.value
    ).toBe(1000);
    expect(
      findMetric(value.metrics, "YT_SEARCH", "averageViewDuration")?.value
    ).toBe(50);
    expect(
      findMetric(value.metrics, "YT_SEARCH", "viewSharePercent")?.value
    ).toBe(75);
    expect(findMetric(value.metrics, "BROWSE", "viewSharePercent")?.value).toBe(
      25
    );
  });
});

describe("collectTrafficSourceService query construction", () => {
  test("queries traffic source type breakdown for a channel period", async () => {
    const { calls, client } = makeAnalyticsClient(canonicalResponse);

    await collectTrafficSourceService(baseInput, makeDeps(client));

    expect(calls).toHaveLength(1);
    const params = calls[0] as Record<string, unknown>;
    expect(params.ids).toBe("channel==UC_test_channel");
    expect(params.startDate).toBe("2026-06-01");
    expect(params.endDate).toBe("2026-06-30");
    expect(params.dimensions).toBe("insightTrafficSourceType");
    expect(params.metrics).toBe(
      "views,estimatedMinutesWatched,averageViewDuration"
    );
    expect(params.sort).toBe("-views");
    expect(params.filters).toBeUndefined();
  });

  test("passes videoId as a filter without replacing the channel ids position", async () => {
    const { calls, client } = makeAnalyticsClient(canonicalResponse);

    await collectTrafficSourceService(
      { ...baseInput, videoId: "vid_123" },
      makeDeps(client)
    );

    const params = calls[0] as Record<string, unknown>;
    expect(params.ids).toBe("channel==UC_test_channel");
    expect(params.filters).toBe("video==vid_123");
  });
});

describe("collectTrafficSourceService validation", () => {
  test("returns validation error for unknown input keys before calling the API", async () => {
    const { calls, client } = makeAnalyticsClient(canonicalResponse);

    await expectValidationError(
      { ...baseInput, unexpected: true } as unknown as TrafficSourceInput,
      client,
      calls
    );
  });

  test("returns validation error for non YYYY-MM-DD dates", async () => {
    const { calls, client } = makeAnalyticsClient(canonicalResponse);

    await expectValidationError(
      { ...baseInput, startDate: "2026/06/01" } as TrafficSourceInput,
      client,
      calls
    );
  });

  test("returns validation error for reversed date ranges before calling the API", async () => {
    const { calls, client } = makeAnalyticsClient(canonicalResponse);

    await expectValidationError(
      { ...baseInput, endDate: "2026-06-01", startDate: "2026-06-30" },
      client,
      calls
    );
  });
});

describe("collectTrafficSourceService quota errors", () => {
  test("maps a gaxios 429 into quota ServiceError and preserves Retry-After", async () => {
    const { calls, client } = makeAnalyticsClient(() => {
      throw gaxiosError("quota exceeded", {
        data: { error: { errors: [{ reason: "quotaExceeded" }] } },
        headers: { "retry-after": "1800" },
        status: 429,
      });
    });

    const result = await collectTrafficSourceService(
      baseInput,
      makeDeps(client)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected quota failure");
    }
    expect(result.error.domain).toBe("quota");
    if (result.error.domain === "quota") {
      expect(result.error.httpStatus).toBe(429);
      expect(result.error.retryAfterSeconds).toBe(1800);
    }
    expect(calls).toHaveLength(1);
  });

  test("leaves Retry-After undefined when a quota response has an empty header", async () => {
    const { client } = makeAnalyticsClient(() => {
      throw gaxiosError("quota exceeded", {
        data: { error: { errors: [{ reason: "quotaExceeded" }] } },
        headers: { "retry-after": " " },
        status: 429,
      });
    });

    const result = await collectTrafficSourceService(
      baseInput,
      makeDeps(client)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected quota failure");
    }
    expect(result.error.domain).toBe("quota");
    if (result.error.domain === "quota") {
      expect(result.error.retryAfterSeconds).toBeUndefined();
    }
  });

  test("preserves typed quota errors without retrying or degrading the domain", async () => {
    const { calls, client } = makeAnalyticsClient(() => {
      throw new QuotaExhaustedError("quota exceeded", 3600);
    });

    const result = await collectTrafficSourceService(
      baseInput,
      makeDepsWithNoSleep(client)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected quota failure");
    }
    expect(result.error.domain).toBe("quota");
    if (result.error.domain === "quota") {
      expect(result.error.retryAfterSeconds).toBe(3600);
    }
    expect(calls).toHaveLength(1);
  });
});

describe("collectTrafficSourceService api errors", () => {
  test("maps a permanent 403 into api ServiceError without retrying", async () => {
    const { calls, client } = makeAnalyticsClient(() => {
      throw gaxiosError("forbidden", {
        data: { error: { errors: [{ reason: "insufficientPermissions" }] } },
        status: 403,
      });
    });

    const result = await collectTrafficSourceService(
      baseInput,
      makeDepsWithNoSleep(client)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected api failure");
    }
    expect(result.error.domain).toBe("api");
    if (result.error.domain === "api") {
      expect(result.error.httpStatus).toBe(403);
      expect(result.error.reason).toBe("insufficientPermissions");
    }
    expect(calls).toHaveLength(1);
  });

  test("retries a transient 500 and returns the next successful response", async () => {
    let attempt = 0;
    const { calls, client } = makeAnalyticsClient(() => {
      attempt += 1;
      if (attempt === 1) {
        throw gaxiosError("server error", { data: {}, status: 500 });
      }
      return queryResponse(columns, [["YT_SEARCH", 42, 120, 180]]);
    });

    const value = expectOk(
      await collectTrafficSourceService(baseInput, makeDepsWithNoSleep(client))
    );

    expect(value.metrics).toContainEqual({
      metric: "views",
      trafficSourceType: "YT_SEARCH",
      value: 42,
    });
    expect(calls).toHaveLength(2);
  });

  test("returns an error Result when a metric cell is null instead of numeric", async () => {
    const { client } = makeAnalyticsClient(() =>
      queryResponse(columns, [["YT_SEARCH", null, 120, 180]])
    );

    const result = await collectTrafficSourceService(
      baseInput,
      makeDeps(client)
    );

    expect(result.ok).toBe(false);
  });
});

describe("TrafficSourceAnalyticsInput schema", () => {
  test("parses channel-only input", () => {
    expect(TrafficSourceAnalyticsInput.parse(baseInput)).toEqual(baseInput);
  });

  test("parses input with optional videoId", () => {
    const input = { ...baseInput, videoId: "vid_123" };

    expect(TrafficSourceAnalyticsInput.parse(input)).toEqual(input);
  });

  test("rejects unknown keys", () => {
    expect(() =>
      TrafficSourceAnalyticsInput.parse({ ...baseInput, extra: true })
    ).toThrow();
  });

  test("rejects invalid date format", () => {
    expect(() =>
      TrafficSourceAnalyticsInput.parse({
        ...baseInput,
        endDate: "06/30/2026",
      })
    ).toThrow();
  });

  test("rejects reversed date ranges", () => {
    expect(() =>
      TrafficSourceAnalyticsInput.parse({
        ...baseInput,
        endDate: "2026-06-01",
        startDate: "2026-06-30",
      })
    ).toThrow();
  });
});

describe("TrafficSourceAnalyticsOutput schema", () => {
  test("parses a long-format traffic source metric payload", () => {
    const payload = {
      metrics: [
        { metric: "views", trafficSourceType: "YT_SEARCH", value: 150 },
        {
          metric: "viewSharePercent",
          trafficSourceType: "YT_SEARCH",
          value: 50,
        },
      ],
    };

    expect(TrafficSourceAnalyticsOutput.parse(payload)).toEqual(payload);
  });

  test("rejects unknown keys on metric records", () => {
    const payload = {
      metrics: [
        {
          metric: "views",
          source: "search",
          trafficSourceType: "YT_SEARCH",
          value: 150,
        },
      ],
    };

    expect(() => TrafficSourceAnalyticsOutput.parse(payload)).toThrow();
  });

  test("rejects unsupported metric names", () => {
    const payload = {
      metrics: [{ metric: "likes", trafficSourceType: "YT_SEARCH", value: 10 }],
    };

    expect(() => TrafficSourceAnalyticsOutput.parse(payload)).toThrow();
  });
});
