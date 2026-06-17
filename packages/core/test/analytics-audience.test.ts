import { describe, expect, test } from "bun:test";

import {
  AudienceAnalyticsInput,
  AudienceAnalyticsOutput,
  collectAudienceService,
} from "@tayk/core/analytics/audience";

type AudienceInput = Parameters<typeof collectAudienceService>[0];
type AudienceDeps = Parameters<typeof collectAudienceService>[1];
type AudienceResult = Awaited<ReturnType<typeof collectAudienceService>>;

interface QueryResponse {
  readonly data: {
    readonly columnHeaders?: readonly { readonly name?: string }[];
    readonly rows?: readonly (readonly unknown[])[];
  };
}

type QueryBehavior = (params: Record<string, unknown>) => QueryResponse;
type Sleep = (ms: number) => Promise<void>;

const makeAnalyticsClient = (behavior: QueryBehavior) => {
  const calls: Record<string, unknown>[] = [];
  const client = {
    reports: {
      query: (params: Record<string, unknown>) => {
        calls.push(params);
        return Promise.resolve().then(() => behavior(params));
      },
    },
  };
  return { calls, client };
};

const noSleep: Sleep = () => Promise.resolve();

const makeDeps = (client: unknown, sleep?: Sleep): AudienceDeps =>
  ({
    youtubeAnalytics: client,
    ...(sleep === undefined ? {} : { sleep }),
  }) as unknown as AudienceDeps;

const queryResponse = (
  columns: readonly string[],
  rows: readonly (readonly unknown[])[]
): QueryResponse => ({
  data: {
    columnHeaders: columns.map((name) => ({ name })),
    rows,
  },
});

const gaxiosQuotaError = (): Error =>
  Object.assign(new Error("quota exceeded"), {
    response: {
      data: { error: { errors: [{ reason: "quotaExceeded" }] } },
      headers: { "retry-after": "90" },
      status: 429,
    },
  });

const gaxiosQuotaErrorWithRetryAfter = (retryAfter: string): Error =>
  Object.assign(new Error("quota exceeded"), {
    response: {
      data: { error: { errors: [{ reason: "quotaExceeded" }] } },
      headers: { "retry-after": retryAfter },
      status: 429,
    },
  });

const gaxiosStatusError = (status: number): Error =>
  Object.assign(new Error(`analytics api failed with ${status}`), {
    response: { status },
  });

const gaxiosUnknownStatusError = (): Error =>
  Object.assign(new Error("analytics api failed with unknown status"), {
    response: {},
  });

const baseInput: AudienceInput = {
  channelId: "UCabcdefghijklmnopqrstuv",
  endDate: "2026-06-14",
  startDate: "2026-06-01",
};

const validVideoId = "dQw4w9WgXcQ";

const audienceResponses = (params: Record<string, unknown>): QueryResponse => {
  switch (params.dimensions) {
    case "ageGroup,gender": {
      return queryResponse(
        ["ageGroup", "gender", "viewerPercentage"],
        [
          ["age18-24", "male", 10],
          ["age18-24", "female", 15],
          ["age25-34", "male", 20],
          ["age25-34", "female", 5],
        ]
      );
    }
    case "country": {
      return queryResponse(
        [
          "country",
          "views",
          "estimatedMinutesWatched",
          "averageViewDuration",
          "subscribersGained",
        ],
        [
          ["JP", 80, 400, 300, 8],
          ["US", 20, 100, 240, 2],
        ]
      );
    }
    case "subscribedStatus": {
      return queryResponse(
        [
          "subscribedStatus",
          "views",
          "estimatedMinutesWatched",
          "averageViewDuration",
        ],
        [
          ["SUBSCRIBED", 60, 360, 300],
          ["UNSUBSCRIBED", 40, 140, 210],
        ]
      );
    }
    default: {
      throw new Error(`unexpected dimensions: ${String(params.dimensions)}`);
    }
  }
};

const expectOk = (result: AudienceResult) => {
  if (!result.ok) {
    throw new Error(
      `expected ok, got ${result.error.domain}: ${result.error.message}`
    );
  }
  return result.value;
};

describe("AudienceAnalyticsInput schema", () => {
  test("parses channel-wide input with an optional videoId", () => {
    const input = { ...baseInput, videoId: validVideoId };

    expect(AudienceAnalyticsInput.parse(input)).toEqual(input);
  });

  test("rejects unknown input keys", () => {
    expect(() =>
      AudienceAnalyticsInput.parse({ ...baseInput, extra: true })
    ).toThrow();
  });

  test("rejects non YYYY-MM-DD dates", () => {
    expect(() =>
      AudienceAnalyticsInput.parse({ ...baseInput, startDate: "2026/06/01" })
    ).toThrow();
  });

  test("rejects blank channel and video identifiers", () => {
    expect(() =>
      AudienceAnalyticsInput.parse({ ...baseInput, channelId: "" })
    ).toThrow();
    expect(() =>
      AudienceAnalyticsInput.parse({ ...baseInput, videoId: "" })
    ).toThrow();
  });

  test("rejects channel identifiers containing separators or whitespace", () => {
    for (const channelId of [
      "UCabcdefghijklmnopqrstu,",
      "UCabcdefghijklmnopqrstu;",
      "UCabcdefghijklmnopqrstu=",
      "UCabcdefghij klmnopqrstuv",
    ]) {
      expect(() =>
        AudienceAnalyticsInput.parse({ ...baseInput, channelId })
      ).toThrow();
    }
  });

  test("rejects video identifiers containing separators, whitespace, or a non-YouTube shape", () => {
    for (const videoId of [
      "dQw4w9WgXc,",
      "dQw4w9WgXc;",
      "dQw4w9WgXc=",
      "dQw4w9W XcQ",
      "too-short",
      "too-long-video-id",
    ]) {
      expect(() =>
        AudienceAnalyticsInput.parse({ ...baseInput, videoId })
      ).toThrow();
    }
  });

  test("rejects an input whose startDate is after endDate", () => {
    expect(() =>
      AudienceAnalyticsInput.parse({
        ...baseInput,
        endDate: "2026-06-01",
        startDate: "2026-06-14",
      })
    ).toThrow();
  });
});

describe("AudienceAnalyticsOutput schema", () => {
  test("parses one metric per record in long format", () => {
    const payload = {
      metrics: [
        {
          ageGroup: "age18-24",
          metric: "viewerPercentage",
          segment: "ageGroup",
          value: 25,
        },
        {
          country: "JP",
          metric: "views",
          segment: "country",
          value: 80,
        },
      ],
    };

    expect(AudienceAnalyticsOutput.parse(payload)).toEqual(payload);
  });

  test("rejects wide metric records and unknown output keys", () => {
    expect(() =>
      AudienceAnalyticsOutput.parse({
        metrics: [
          {
            country: "JP",
            metric: "countryMetrics",
            segment: "country",
            value: 80,
            views: 80,
          },
        ],
      })
    ).toThrow();
  });

  test("rejects segment and metric mismatches", () => {
    expect(() =>
      AudienceAnalyticsOutput.parse({
        metrics: [
          {
            ageGroup: "age18-24",
            metric: "views",
            segment: "ageGroup",
            value: 25,
          },
        ],
      })
    ).toThrow();
    expect(() =>
      AudienceAnalyticsOutput.parse({
        metrics: [
          {
            country: "JP",
            metric: "viewerPercentage",
            segment: "country",
            value: 80,
          },
        ],
      })
    ).toThrow();
  });

  test("rejects fields from a different segment", () => {
    expect(() =>
      AudienceAnalyticsOutput.parse({
        metrics: [
          {
            ageGroup: "age18-24",
            country: "JP",
            metric: "views",
            segment: "country",
            value: 80,
          },
        ],
      })
    ).toThrow();
  });
});

describe("collectAudienceService success", () => {
  test("collects demographics, country, and subscriber breakdown as long metrics", async () => {
    const { client } = makeAnalyticsClient(audienceResponses);

    const value = expectOk(
      await collectAudienceService(baseInput, makeDeps(client))
    );

    expect(value.metrics).toContainEqual({
      ageGroup: "age18-24",
      metric: "viewerPercentage",
      segment: "ageGroup",
      value: 25,
    });
    expect(value.metrics).toContainEqual({
      gender: "male",
      metric: "viewerPercentage",
      segment: "gender",
      value: 30,
    });
    expect(value.metrics).toContainEqual({
      country: "JP",
      metric: "views",
      segment: "country",
      value: 80,
    });
    expect(value.metrics).toContainEqual({
      country: "JP",
      metric: "viewSharePercent",
      segment: "country",
      value: 80,
    });
    expect(value.metrics).toContainEqual({
      metric: "viewSharePercent",
      segment: "subscribedStatus",
      subscribedStatus: "SUBSCRIBED",
      value: 60,
    });

    expect(value.metrics.some((metric) => "views" in metric)).toBe(false);
  });

  test("uses the documented query contract for all audience dimensions", async () => {
    const { calls, client } = makeAnalyticsClient(audienceResponses);

    const result = await collectAudienceService(baseInput, makeDeps(client));

    expect(result.ok).toBe(true);
    expect(calls).toHaveLength(3);
    expect(calls.map((call) => call.dimensions)).toEqual([
      "ageGroup,gender",
      "country",
      "subscribedStatus",
    ]);
    const [demographicCall, countryCall, subscribedStatusCall] = calls;
    if (!demographicCall || !countryCall || !subscribedStatusCall) {
      throw new Error("expected three audience query calls");
    }
    expect(demographicCall.metrics).toBe("viewerPercentage");
    expect(countryCall.metrics).toBe(
      "views,estimatedMinutesWatched,averageViewDuration,subscribersGained"
    );
    expect(countryCall.sort).toBe("-views");
    expect(subscribedStatusCall.metrics).toBe(
      "views,estimatedMinutesWatched,averageViewDuration"
    );
    expect(subscribedStatusCall.sort).toBe("-views");
    for (const call of calls) {
      expect(call.ids).toBe("channel==UCabcdefghijklmnopqrstuv");
      expect(call.startDate).toBe("2026-06-01");
      expect(call.endDate).toBe("2026-06-14");
      expect(call.filters).toBeUndefined();
    }
  });

  test("rounds country and subscriber view share percentages to one decimal place", async () => {
    const { client } = makeAnalyticsClient((params) => {
      switch (params.dimensions) {
        case "ageGroup,gender": {
          return queryResponse(["ageGroup", "gender", "viewerPercentage"], []);
        }
        case "country": {
          return queryResponse(
            [
              "country",
              "views",
              "estimatedMinutesWatched",
              "averageViewDuration",
              "subscribersGained",
            ],
            [
              ["JP", 1, 10, 30, 0],
              ["US", 2, 20, 40, 0],
            ]
          );
        }
        case "subscribedStatus": {
          return queryResponse(
            [
              "subscribedStatus",
              "views",
              "estimatedMinutesWatched",
              "averageViewDuration",
            ],
            [
              ["SUBSCRIBED", 1, 10, 30],
              ["UNSUBSCRIBED", 2, 20, 40],
            ]
          );
        }
        default: {
          throw new Error(
            `unexpected dimensions: ${String(params.dimensions)}`
          );
        }
      }
    });

    const value = expectOk(
      await collectAudienceService(baseInput, makeDeps(client))
    );

    expect(value.metrics).toContainEqual({
      country: "JP",
      metric: "viewSharePercent",
      segment: "country",
      value: 33.3,
    });
    expect(value.metrics).toContainEqual({
      metric: "viewSharePercent",
      segment: "subscribedStatus",
      subscribedStatus: "SUBSCRIBED",
      value: 33.3,
    });
  });

  test("adds a video filter to every query when videoId is supplied", async () => {
    const { calls, client } = makeAnalyticsClient(audienceResponses);

    const result = await collectAudienceService(
      { ...baseInput, videoId: validVideoId },
      makeDeps(client)
    );

    expect(result.ok).toBe(true);
    expect(calls).toHaveLength(3);
    for (const call of calls) {
      expect(call.ids).toBe("channel==UCabcdefghijklmnopqrstuv");
      expect(call.filters).toBe(`video==${validVideoId}`);
    }
  });
});

describe("collectAudienceService error paths", () => {
  test("returns a validation ServiceError for an unsafe channelId without querying", async () => {
    const { calls, client } = makeAnalyticsClient(audienceResponses);

    const result = await collectAudienceService(
      { ...baseInput, channelId: `${baseInput.channelId},mine==true` },
      makeDeps(client)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a validation failure");
    }
    expect(result.error.domain).toBe("validation");
    expect(calls).toHaveLength(0);
  });

  test("returns a validation ServiceError for an unsafe videoId without querying", async () => {
    const { calls, client } = makeAnalyticsClient(audienceResponses);

    const result = await collectAudienceService(
      { ...baseInput, videoId: `${validVideoId};country==JP` },
      makeDeps(client)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a validation failure");
    }
    expect(result.error.domain).toBe("validation");
    expect(calls).toHaveLength(0);
  });

  test("returns a validation ServiceError for an inverted date range without querying", async () => {
    const { calls, client } = makeAnalyticsClient(audienceResponses);

    const result = await collectAudienceService(
      { ...baseInput, endDate: "2026-06-01", startDate: "2026-06-14" },
      makeDeps(client)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a validation failure");
    }
    expect(result.error.domain).toBe("validation");
    expect(calls).toHaveLength(0);
  });

  test("retries a 500 query error and returns success when the retry succeeds", async () => {
    let attempts = 0;
    const { calls, client } = makeAnalyticsClient((params) => {
      if (params.dimensions === "ageGroup,gender" && attempts === 0) {
        attempts += 1;
        throw gaxiosStatusError(500);
      }
      return audienceResponses(params);
    });

    const result = await collectAudienceService(
      baseInput,
      makeDeps(client, noSleep)
    );

    expect(result.ok).toBe(true);
    expect(calls).toHaveLength(4);
    expect(calls.map((call) => call.dimensions)).toEqual([
      "ageGroup,gender",
      "ageGroup,gender",
      "country",
      "subscribedStatus",
    ]);
  });

  test("does not retry a 403 query error and returns an API ServiceError", async () => {
    const { calls, client } = makeAnalyticsClient(() => {
      throw gaxiosStatusError(403);
    });

    const result = await collectAudienceService(
      baseInput,
      makeDeps(client, noSleep)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected an api failure");
    }
    expect(result.error.domain).toBe("api");
    if (result.error.domain === "api") {
      expect(result.error.httpStatus).toBe(403);
    }
    expect(calls).toHaveLength(1);
  });

  test("returns a quota ServiceError for a 429 without retrying", async () => {
    const { calls, client } = makeAnalyticsClient(() => {
      throw gaxiosQuotaError();
    });

    const result = await collectAudienceService(baseInput, makeDeps(client));

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a quota failure");
    }
    expect(result.error.domain).toBe("quota");
    if (result.error.domain === "quota") {
      expect(result.error.retryAfterSeconds).toBe(90);
    }
    expect(calls).toHaveLength(1);
  });

  test("leaves retryAfterSeconds undefined when a 429 Retry-After header is empty", async () => {
    const { calls, client } = makeAnalyticsClient(() => {
      throw gaxiosQuotaErrorWithRetryAfter("");
    });

    const result = await collectAudienceService(baseInput, makeDeps(client));

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a quota failure");
    }
    expect(result.error.domain).toBe("quota");
    if (result.error.domain === "quota") {
      expect(result.error.retryAfterSeconds).toBeUndefined();
    }
    expect(calls).toHaveLength(1);
  });

  test("leaves retryAfterSeconds undefined when a 429 Retry-After header is blank", async () => {
    const { calls, client } = makeAnalyticsClient(() => {
      throw gaxiosQuotaErrorWithRetryAfter("   ");
    });

    const result = await collectAudienceService(baseInput, makeDeps(client));

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a quota failure");
    }
    expect(result.error.domain).toBe("quota");
    if (result.error.domain === "quota") {
      expect(result.error.retryAfterSeconds).toBeUndefined();
    }
    expect(calls).toHaveLength(1);
  });

  test("retries an API error whose status is unknown", async () => {
    let attempts = 0;
    const { calls, client } = makeAnalyticsClient((params) => {
      if (params.dimensions === "ageGroup,gender" && attempts === 0) {
        attempts += 1;
        throw gaxiosUnknownStatusError();
      }
      return audienceResponses(params);
    });

    const result = await collectAudienceService(
      baseInput,
      makeDeps(client, noSleep)
    );

    expect(result.ok).toBe(true);
    expect(calls).toHaveLength(4);
  });

  test("validates input before making an API request", async () => {
    const { calls, client } = makeAnalyticsClient(audienceResponses);

    const result = await collectAudienceService(
      { ...baseInput, unexpected: true } as unknown as AudienceInput,
      makeDeps(client)
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected a validation failure");
    }
    expect(result.error.domain).toBe("validation");
    expect(calls).toHaveLength(0);
  });
});
