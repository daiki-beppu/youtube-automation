// 動画別 analytics feature の公開 API（ADR-0003 canonical 配置 packages/core/src/<feature>/）。
//
// 公開 API:
// - collectVideoAnalyticsService(input, deps): ADR-0003 Result 境界
// - CollectVideoAnalyticsInput / CollectVideoAnalyticsOutput: service 境界の zod schema（+ z.infer 型）
// - VideoAnalyticsDeps: 構築済み Analytics クライアントを渡す注入 seam の型

export {
  CollectVideoAnalyticsInput,
  CollectVideoAnalyticsOutput,
} from "./schema.ts";
export {
  collectVideoAnalyticsService,
  type VideoAnalyticsDeps,
} from "./service.ts";
