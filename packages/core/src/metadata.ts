export type {
  GenerateMetadataInput,
  GenerateMetadataOutput,
} from "./metadata/schema.ts";
export { generateVideoMetadataService } from "./metadata/service.ts";
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
  type TimestampLoopOptions,
  type TimestampTrack,
} from "./metadata/tracks.ts";
