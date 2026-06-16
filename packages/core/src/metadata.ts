// metadata 生成 API の公開バレル（Python `utils/metadata_generator.py` の pure 部分）。
//
// tags（config/content）と loadTemplate（templates）もこのサブパスから再 export し、
// 呼び出し側が metadata 関連を 1 か所から import できるようにする。

export { tagsForCollection } from "./config/content.ts";
export {
  buildCompleteCollectionDescription,
  formatSceneTitleViolations,
  generateCompleteCollectionTitle,
  generateLocalizations,
  type SceneTitleViolation,
  validateScenePhrases,
} from "./metadata/collection.ts";
export {
  formatTitleTemplate,
  referencedPlaceholders,
} from "./metadata/format.ts";
export {
  buildShortDescription,
  buildShortLocalizations,
  formatShortDurationPhrase,
} from "./metadata/shorts.ts";
export {
  buildTimestampsText,
  cleanTrackTitle,
  extractPatternKey,
  type PatternKey,
  type ThemeInline,
  type TimestampTrack,
} from "./metadata/tracks.ts";
export { loadTemplate } from "./templates.ts";
