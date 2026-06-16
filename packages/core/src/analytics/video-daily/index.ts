// ADR 0002/0003 canonical template: feature の公開面は schema + service のみ。
export {
  CollectVideoDailyAnalyticsInput,
  CollectVideoDailyAnalyticsOutput,
} from "./schema.ts";
export { collectVideoDailyAnalyticsService } from "./service.ts";
