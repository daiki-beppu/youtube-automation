import { z } from "zod";

export const AUDIENCE_DEMOGRAPHIC_METRICS = ["viewerPercentage"] as const;
export const AUDIENCE_COUNTRY_METRICS = [
  "views",
  "estimatedMinutesWatched",
  "averageViewDuration",
  "subscribersGained",
  "viewSharePercent",
] as const;
export const AUDIENCE_SUBSCRIBED_STATUS_METRICS = [
  "views",
  "estimatedMinutesWatched",
  "averageViewDuration",
  "viewSharePercent",
] as const;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/u;
const YOUTUBE_CHANNEL_ID = /^UC[A-Za-z0-9_-]{22}$/u;
const YOUTUBE_VIDEO_ID = /^[A-Za-z0-9_-]{11}$/u;

const isoDate = z.string().regex(ISO_DATE, "must be a YYYY-MM-DD date");
const AUDIENCE_SEGMENTS = [
  "ageGroup",
  "gender",
  "country",
  "subscribedStatus",
] as const;
type AudienceSegment = (typeof AUDIENCE_SEGMENTS)[number];
const AUDIENCE_METRICS = [
  ...AUDIENCE_DEMOGRAPHIC_METRICS,
  ...AUDIENCE_COUNTRY_METRICS,
  ...AUDIENCE_SUBSCRIBED_STATUS_METRICS,
] as const;

const isAudienceSegment = (value: string): boolean =>
  AUDIENCE_SEGMENTS.some((segment) => segment === value);
const isAudienceMetric = (value: string): boolean =>
  AUDIENCE_METRICS.some((metric) => metric === value);
const resolveAudienceSegment = (value: string): AudienceSegment | undefined =>
  AUDIENCE_SEGMENTS.find((segment) => segment === value);
const SEGMENT_FIELD_NAMES = [
  "ageGroup",
  "country",
  "gender",
  "subscribedStatus",
] as const;
const METRICS_BY_SEGMENT: Record<AudienceSegment, readonly string[]> = {
  ageGroup: AUDIENCE_DEMOGRAPHIC_METRICS,
  country: AUDIENCE_COUNTRY_METRICS,
  gender: AUDIENCE_DEMOGRAPHIC_METRICS,
  subscribedStatus: AUDIENCE_SUBSCRIBED_STATUS_METRICS,
};

export const AudienceAnalyticsInput = z
  .object({
    channelId: z
      .string()
      .regex(YOUTUBE_CHANNEL_ID, "must be a valid YouTube channel ID"),
    endDate: isoDate,
    startDate: isoDate,
    videoId: z
      .string()
      .regex(YOUTUBE_VIDEO_ID, "must be a valid YouTube video ID")
      .optional(),
  })
  .strict()
  .refine((input) => input.startDate <= input.endDate, {
    message: "startDate must be on or before endDate",
    path: ["startDate"],
  });
export type AudienceAnalyticsInput = z.infer<typeof AudienceAnalyticsInput>;

const audienceMetricRecord = z
  .object({
    ageGroup: z.string().optional(),
    country: z.string().optional(),
    gender: z.string().optional(),
    metric: z.string().refine(isAudienceMetric, "unsupported audience metric"),
    segment: z
      .string()
      .refine(isAudienceSegment, "unsupported audience segment"),
    subscribedStatus: z.string().optional(),
    value: z.number(),
  })
  .strict()
  .superRefine((record, context) => {
    const segment = resolveAudienceSegment(record.segment);
    if (segment === undefined) {
      return;
    }
    const allowedMetrics = METRICS_BY_SEGMENT[segment];
    if (!allowedMetrics.some((metric) => metric === record.metric)) {
      context.addIssue({
        code: "custom",
        message: `${record.metric} is not valid for ${segment}`,
        path: ["metric"],
      });
    }
    for (const fieldName of SEGMENT_FIELD_NAMES) {
      const value = record[fieldName];
      if (fieldName === segment && value === undefined) {
        context.addIssue({
          code: "custom",
          message: `missing ${segment} value`,
          path: [segment],
        });
      }
      if (fieldName !== segment && value !== undefined) {
        context.addIssue({
          code: "custom",
          message: `${fieldName} is not valid for ${segment}`,
          path: [fieldName],
        });
      }
    }
  });

export const AudienceAnalyticsOutput = z
  .object({
    metrics: z.array(audienceMetricRecord),
  })
  .strict();
export type AudienceAnalyticsOutput = z.infer<typeof AudienceAnalyticsOutput>;
