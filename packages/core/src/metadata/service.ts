import {
  activityForTheme,
  sceneForTheme,
  tagsForCollection,
} from "../config/content.ts";
import type { ChannelConfig } from "../config/index.ts";
import { createService } from "../service-frame.ts";
import {
  buildCompleteCollectionDescription,
  generateCompleteCollectionTitle,
  generateLocalizations,
  validateScenePhrases,
} from "./collection.ts";
import { rawLocalizations } from "./loc-data.ts";
import { GenerateMetadataInput, GenerateMetadataOutput } from "./schema.ts";
import type {
  GenerateMetadataInput as GenerateMetadataInputValue,
  GenerateMetadataOutput as GenerateMetadataOutputValue,
} from "./schema.ts";
import { buildTimestampsText } from "./tracks.ts";
import type { TimestampTrack } from "./tracks.ts";

type GenerateMetadataTrack = GenerateMetadataInputValue["tracks"][number];
type LocalizationResult = Pick<
  GenerateMetadataOutputValue,
  "localizations" | "violations"
>;

const DESCRIPTION_SECTION_HEADERS = {
  channelLinkTemplate: "🔗 {channel_name}:",
  perfectFor: "🎮 Perfect for:",
  usageAttribution: "📝 Usage & Attribution:",
} as const;

const LOCALIZATION_SECTION_HEADERS = {
  channelLinkTemplate: "🔗 {channel_name}:",
  trackList: "🎶 Tracklist",
  usageAttribution: "📝 Usage & Attribution:",
} as const;

const TIMESTAMP_THEME_INLINE = { prefix: "── ", suffix: " ──" } as const;

const COMPLETE_COLLECTION_USAGE_LINES = [
  "• Original AI composition",
  "• Free for personal & non-commercial use",
  "• For commercial use, check the platform's AI content policy",
  "• Redistribution prohibited",
] as const;

const secondsToTimestamp = (seconds: number): string => {
  const total = Math.trunc(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainingSeconds = total % 60;
  const paddedSeconds = remainingSeconds.toString().padStart(2, "0");
  if (hours === 0) {
    return `${minutes}:${paddedSeconds}`;
  }
  const paddedMinutes = minutes.toString().padStart(2, "0");
  return `${hours}:${paddedMinutes}:${paddedSeconds}`;
};

const roundHalfToEven = (value: number): number => {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff < 0.5) {
    return floor;
  }
  if (diff > 0.5) {
    return floor + 1;
  }
  return floor % 2 === 0 ? floor : floor + 1;
};

const formatDurationDisplay = (seconds: number): string => {
  const minutes = seconds / 60;
  if (minutes < 35) {
    const rounded = Math.max(roundHalfToEven(minutes / 5) * 5, 5);
    return `${rounded} min`;
  }
  if (minutes < 75) {
    return "1 Hour";
  }
  if (minutes < 105) {
    return "1.5 Hours";
  }
  if (minutes < 135) {
    return "2 Hours";
  }
  const roundedHalfHours = roundHalfToEven((minutes / 60) * 2) / 2;
  return `${roundedHalfHours} Hours`;
};

const formatDurationShort = (seconds: number): string => {
  const minutes = seconds / 60;
  if (minutes < 35) {
    return `${Math.max(roundHalfToEven(minutes / 5) * 5, 5)}m`;
  }
  return `${roundHalfToEven((minutes / 60) * 2) / 2}h`;
};

const primaryActivity = (activities: string): string => {
  const [first] = activities.split(",");
  if (first === undefined || first.trim().length === 0) {
    throw new Error("validation: activity is required");
  }
  return first.trim();
};

const toTimestampTracks = (
  tracks: readonly GenerateMetadataTrack[]
): TimestampTrack[] =>
  tracks.map((track) => ({
    timestamp: secondsToTimestamp(track.startSeconds),
    title: track.title,
  }));

const totalDurationSeconds = (
  tracks: readonly GenerateMetadataTrack[]
): number => {
  let latestEnd = 0;
  for (const track of tracks) {
    latestEnd = Math.max(latestEnd, track.startSeconds + track.durationSeconds);
  }
  return latestEnd;
};

const buildTimestamps = (tracks: readonly GenerateMetadataTrack[]): string =>
  buildTimestampsText(toTimestampTracks(tracks), {}, TIMESTAMP_THEME_INLINE);

const scenePhraseForTitle = (
  config: ChannelConfig,
  request: GenerateMetadataInputValue
): string => {
  const englishScenePhrase = request.scenePhrases?.en;
  if (englishScenePhrase !== undefined) {
    return englishScenePhrase;
  }
  const configuredScene = sceneForTheme(
    config.publishing.content.title,
    request.theme
  );
  return configuredScene.length > 0 ? configuredScene : request.theme;
};

const buildTitle = (
  config: ChannelConfig,
  request: GenerateMetadataInputValue
): string => {
  const activities = activityForTheme(
    config.publishing.content.title,
    request.theme
  );
  const durationSeconds = totalDurationSeconds(request.tracks);
  return generateCompleteCollectionTitle(config, {
    activities,
    activity: primaryActivity(activities),
    durationDisplay: formatDurationDisplay(durationSeconds),
    durationShort: formatDurationShort(durationSeconds),
    sceneEmoji: "",
    scenePhrase: scenePhraseForTitle(config, request),
    theme: request.theme,
  });
};

const buildDescription = (
  config: ChannelConfig,
  title: string,
  timestamps: string
): string =>
  buildCompleteCollectionDescription(config, {
    sectionHeaders: DESCRIPTION_SECTION_HEADERS,
    timestampBody: timestamps,
    title,
    usageLines: COMPLETE_COLLECTION_USAGE_LINES,
  });

const collectionNameForTags = (request: GenerateMetadataInputValue): string =>
  request.collectionSlug === undefined ? request.theme : request.collectionSlug;

const scenePhrasesForLocalizations = (
  config: ChannelConfig,
  request: GenerateMetadataInputValue
): Readonly<Record<string, string>> => {
  if (request.scenePhrases !== undefined) {
    return request.scenePhrases;
  }
  const scenePhrase = scenePhraseForTitle(config, request);
  const localizations = rawLocalizations(config);
  const result: Record<string, string> = {};
  for (const lang of localizations.supported_languages ?? []) {
    result[lang] = scenePhrase;
  }
  return result;
};

const buildLocalizations = (
  config: ChannelConfig,
  request: GenerateMetadataInputValue,
  timestamps: string
): LocalizationResult => {
  const scenePhrases = scenePhrasesForLocalizations(config, request);
  const violations = validateScenePhrases(scenePhrases, config, "");
  if (violations.length > 0) {
    return { localizations: undefined, violations };
  }
  return {
    localizations: generateLocalizations(config, {
      sceneEmoji: "",
      scenePhrases,
      sectionHeaders: LOCALIZATION_SECTION_HEADERS,
      timestampBody: timestamps,
    }),
    violations,
  };
};

const buildMetadataOutput = (
  config: ChannelConfig,
  request: GenerateMetadataInputValue
): GenerateMetadataOutputValue => {
  const timestamps = buildTimestamps(request.tracks);
  const title = buildTitle(config, request);
  const description = buildDescription(config, title, timestamps);
  const tags = tagsForCollection(
    config.publishing.content.tags,
    collectionNameForTags(request)
  );
  const { localizations, violations } = buildLocalizations(
    config,
    request,
    timestamps
  );

  return GenerateMetadataOutput.parse({
    description,
    localizations,
    tags,
    timestamps,
    title,
    violations,
  });
};

export const generateVideoMetadataService = createService(
  GenerateMetadataInput,
  GenerateMetadataOutput,
  (request, deps: { config: ChannelConfig }) =>
    buildMetadataOutput(deps.config, request)
);
