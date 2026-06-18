import { tagsForCollection } from "../config/content.ts";
import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";
import {
  buildCompleteCollectionDescription,
  generateCompleteCollectionTitle,
  generateLocalizations,
} from "./internals/collection.ts";
import { buildTimestampsText } from "./internals/tracks.ts";
import { VideoMetadataInput, VideoMetadataOutput } from "./schema.ts";

export const generateVideoMetadataService = (
  input: VideoMetadataInput
): Promise<Result<VideoMetadataOutput, ServiceError>> => {
  try {
    const request = VideoMetadataInput.parse(input);
    const timestampBody = buildTimestampsText(
      request.timestamps.tracks,
      request.timestamps.themeNames,
      request.timestamps.themeInline
    );
    const title = generateCompleteCollectionTitle(
      request.config,
      request.title
    );
    const description = buildCompleteCollectionDescription(request.config, {
      sectionHeaders: request.description.sectionHeaders,
      timestampBody,
      title,
      usageLines: request.description.usageLines,
    });
    const localizations = generateLocalizations(request.config, {
      sceneEmoji: request.title.sceneEmoji,
      scenePhrases: request.localizations.scenePhrases,
      sectionHeaders: request.localizations.sectionHeaders,
      timestampBody,
    });
    const tags = tagsForCollection(
      request.config.publishing.content.tags,
      request.collectionName
    );
    return Promise.resolve(
      ok(VideoMetadataOutput.parse({ description, localizations, tags, title }))
    );
  } catch (error) {
    return Promise.resolve(err(toServiceError(error)));
  }
};
