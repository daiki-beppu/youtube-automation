import { z } from "zod";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/u;

export const TRAFFIC_SOURCE_VIEWS_METRIC = "views";

export const TRAFFIC_SOURCE_API_METRICS = [
  TRAFFIC_SOURCE_VIEWS_METRIC,
  "estimatedMinutesWatched",
  "averageViewDuration",
] as const;

const TRAFFIC_SOURCE_OUTPUT_METRICS = [
  ...TRAFFIC_SOURCE_API_METRICS,
  "viewSharePercent",
] as const;

const isTrafficSourceMetric = (value: string): boolean =>
  TRAFFIC_SOURCE_OUTPUT_METRICS.some((metric) => metric === value);

export const TrafficSourceAnalyticsInput = z
  .object({
    channelId: z.string().min(1),
    endDate: z.string().regex(ISO_DATE),
    startDate: z.string().regex(ISO_DATE),
    videoId: z.string().min(1).optional(),
  })
  .strict()
  .refine((input) => input.startDate <= input.endDate, {
    message: "startDate must be on or before endDate",
    path: ["startDate"],
  });
export type TrafficSourceAnalyticsInput = z.infer<
  typeof TrafficSourceAnalyticsInput
>;

export const TrafficSourceAnalyticsOutput = z
  .object({
    metrics: z.array(
      z
        .object({
          metric: z
            .string()
            .refine(isTrafficSourceMetric, "unsupported traffic source metric"),
          trafficSourceType: z.string(),
          value: z.number(),
        })
        .strict()
    ),
  })
  .strict();
export type TrafficSourceAnalyticsOutput = z.infer<
  typeof TrafficSourceAnalyticsOutput
>;
