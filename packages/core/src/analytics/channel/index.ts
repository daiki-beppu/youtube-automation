// ADR 0002/0003 canonical template: feature の公開面は schema + service のみ。
export { ChannelAnalyticsInput, ChannelAnalyticsOutput } from "./schema.ts";
export { collectChannelAnalyticsService } from "./service.ts";
