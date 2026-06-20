import { afterEach, beforeEach, describe, expect, test } from "bun:test";

import { loadConfig, reset } from "@youtube-automation/core/config";
import { generateVideoMetadataService } from "@youtube-automation/core/metadata";

import {
  cleanupChannels,
  minimalSections,
  setupChannel,
} from "./config-fixtures.ts";

const loadMinimalConfig = () => {
  const channelDir = setupChannel(minimalSections());
  process.env.CHANNEL_DIR = channelDir;
  return loadConfig();
};

beforeEach(() => {
  Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  reset();
});

afterEach(() => {
  reset();
  Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  cleanupChannels();
});

describe("generateVideoMetadataService contract", () => {
  test("uses collectionSlug for tag matching when it differs from theme", async () => {
    const config = loadMinimalConfig();

    const result = await generateVideoMetadataService(
      {
        collectionSlug: "village-square",
        theme: "Battle Royale",
        tracks: [{ durationSeconds: 60, startSeconds: 0, title: "Song A" }],
      },
      { config }
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.tags).toContain("village music");
    expect(result.value.tags).not.toContain("battle music");
  });
});
