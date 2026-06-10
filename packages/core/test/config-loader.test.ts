import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  test,
} from "bun:test";
import { existsSync, realpathSync } from "node:fs";
import { join, resolve } from "node:path";

// Imported by the published package name + "./config" subpath so the test
// exercises the core `exports` map. A missing/broken subpath export fails
// resolution here, not in tsc.
import { channelDir, loadConfig, reset } from "@youtube-automation/core/config";

import {
  cleanupChannels,
  minimalSections,
  restoreChannelDirEnv,
  saveChannelDirEnv,
  setupChannel,
  setupEmptyChannel,
  writeJson,
} from "./config-fixtures.ts";

beforeAll(saveChannelDirEnv);
afterAll(restoreChannelDirEnv);

beforeEach(() => {
  Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  reset();
});

afterEach(() => {
  reset();
  Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  cleanupChannels();
});

// --- happy path: minimal required sections --------------------------------

describe("loadConfig — minimal sections", () => {
  test("assembles meta/content/youtube with documented defaults", () => {
    // Given a channel with only the three required section files
    const dir = setupChannel(minimalSections());
    process.env.CHANNEL_DIR = dir;

    // When the config is loaded
    const config = loadConfig();

    // Then meta is read straight from channel.*
    expect(config.meta.channelName).toBe("Test Channel");
    expect(config.meta.channelShort).toBe("TC");
    expect(config.meta.youtubeHandle).toBe("@testchannel");
    expect(config.meta.channelUrl).toBe("https://youtube.com/@testchannel");
    expect(config.meta.tagline).toBe("Test tagline");

    // And content + youtube carry the parsed + defaulted values
    expect(config.content.genre.primary).toBe("chiptune");
    expect(config.content.tags.base).toEqual(["chiptune music", "8-bit"]);
    expect(config.youtube.api.language).toBe("ja");
    // suno is the default engine
    expect(config.youtube.musicEngine).toBe("suno");
    // release is the default content model
    expect(config.youtube.contentModel.type).toBe("release");
    // content_model.languages falls back to [api.language] when unspecified
    expect(config.youtube.contentModel.languages).toEqual(["ja"]);

    // And optional sections collapse to their disabled/empty defaults
    expect(config.localizations.exists).toBe(false);
    expect(config.localizations.supportedLanguages).toEqual(["ja"]);
    expect(config.analytics.collectionFilterKeywords).toEqual([]);
    expect(config.playlists.items).toEqual({});
    expect(config.audio.targetDurationMin).toBeNull();
    expect(config.comments.enabled).toBe(false);
    expect(config.pinnedComment.enabled).toBe(false);
    expect(config.shorts.enabled).toBe(false);
    expect(config.distrokid.enabled).toBe(false);
  });
});

// --- required-key validation ----------------------------------------------

describe("loadConfig — required keys", () => {
  test("throws a config:-prefixed error naming a missing dotted key path", () => {
    // Given a channel missing the required channel.name
    const sections = minimalSections();
    const meta = sections["meta.json"] as { channel: Record<string, unknown> };
    Reflect.deleteProperty(meta.channel, "name");
    const dir = setupChannel(sections);
    process.env.CHANNEL_DIR = dir;

    // When/Then load fails fast, naming the offending key path
    expect(() => loadConfig()).toThrow(/^config:/u);
    expect(() => loadConfig()).toThrow(/channel\.name/u);
  });
});

// --- top-level merge guards ------------------------------------------------

describe("loadConfig — top-level merge", () => {
  test("rejects a duplicate top-level key across two files", () => {
    // Given `youtube` declared in both youtube.json and (wrongly) meta.json
    const sections = minimalSections();
    (sections["meta.json"] as Record<string, unknown>).youtube = {
      category_id: "20",
    };
    const dir = setupChannel(sections);
    process.env.CHANNEL_DIR = dir;

    // When/Then the collision is reported, not silently last-wins merged
    expect(() => loadConfig()).toThrow(/^config:/u);
    expect(() => loadConfig()).toThrow(/youtube/u);
  });

  test("rejects a file whose top level is not an object", () => {
    // Given an extra file whose root is an array
    const sections = minimalSections();
    sections["extra.json"] = ["not", "an", "object"];
    const dir = setupChannel(sections);
    process.env.CHANNEL_DIR = dir;

    // When/Then the non-object top level is rejected at merge time
    expect(() => loadConfig()).toThrow(/^config:/u);
  });
});

// --- structural guards -----------------------------------------------------

describe("loadConfig — structural guards", () => {
  test("rejects a leftover legacy channel_config.json", () => {
    // Given the pre-split config file still present alongside the new layout
    const dir = setupChannel(minimalSections());
    writeJson(join(dir, "config", "channel_config.json"), { legacy: true });
    process.env.CHANNEL_DIR = dir;

    // When/Then load refuses and points at the migration tool
    expect(() => loadConfig()).toThrow(/channel_config\.json/u);
  });

  test("rejects an empty config/channel directory", () => {
    // Given config/channel/ exists but holds no JSON files
    const dir = setupEmptyChannel();
    process.env.CHANNEL_DIR = dir;

    // When/Then load fails rather than returning an empty config
    expect(() => loadConfig()).toThrow(/^config:/u);
  });
});

// --- cross-file validation -------------------------------------------------

describe("loadConfig — cross-file validation", () => {
  test("rejects content_model.languages outside supported_languages", () => {
    // Given a content language not present in localizations.supported_languages
    const sections = minimalSections();
    (sections["youtube.json"] as Record<string, unknown>).content_model = {
      languages: ["en"],
      type: "collection",
    };
    const dir = setupChannel(sections, {
      languages: {},
      supported_languages: ["ja", "ko"],
    });
    process.env.CHANNEL_DIR = dir;

    // When/Then the subset rule is enforced
    expect(() => loadConfig()).toThrow(/supported_languages/u);
  });

  test("rejects theme_scenes keys absent from tags.themes", () => {
    // Given a title.theme_scenes key that is not a declared tags.themes key
    const sections = minimalSections();
    (
      sections["content.json"] as { title: Record<string, unknown> }
    ).title.theme_scenes = { unknown_theme: { activities: "Study" } };
    const dir = setupChannel(sections);
    process.env.CHANNEL_DIR = dir;

    // When/Then the dangling theme key is rejected
    expect(() => loadConfig()).toThrow(/theme_scenes/u);
  });
});

// --- singleton + reset -----------------------------------------------------

describe("loadConfig — singleton semantics", () => {
  test("memoizes and only re-reads after reset()", () => {
    // Given a loaded config
    const dir = setupChannel(minimalSections());
    process.env.CHANNEL_DIR = dir;
    const first = loadConfig();

    // When loaded again without reset, the same instance is returned
    expect(loadConfig()).toBe(first);

    // And mutating the file does not invalidate the cached instance
    const changed = minimalSections();
    (
      changed["meta.json"] as { channel: Record<string, unknown> }
    ).channel.name = "Changed";
    writeJson(
      join(dir, "config", "channel", "meta.json"),
      changed["meta.json"]
    );
    expect(loadConfig()).toBe(first);

    // Until reset() clears the singleton, after which the new value is read
    reset();
    const third = loadConfig();
    expect(third).not.toBe(first);
    expect(third.meta.channelName).toBe("Changed");
  });
});

// --- channelDir resolution -------------------------------------------------

describe("channelDir", () => {
  test("returns the CHANNEL_DIR env value verbatim", () => {
    // Given CHANNEL_DIR set explicitly
    const dir = setupChannel(minimalSections());
    process.env.CHANNEL_DIR = dir;

    // When resolving the channel dir
    // Then the env value is used directly
    expect(channelDir()).toBe(dir);
  });

  test("walks cwd ancestors to find config/channel when env is unset", () => {
    // Given no env var and a cwd nested under a channel root
    const dir = setupChannel(minimalSections());
    const nested = join(dir, "collections", "foo");
    writeJson(join(nested, ".keep.json"), {});
    Reflect.deleteProperty(process.env, "CHANNEL_DIR");
    const originalCwd = process.cwd();
    try {
      process.chdir(nested);

      // When resolving with ancestor search
      // Then it climbs to the directory that owns config/channel/
      expect(realpathSync(channelDir())).toBe(realpathSync(dir));
    } finally {
      process.chdir(originalCwd);
    }
  });
});

// --- real sample_channel fixture (acceptance criteria) --------------------

describe("loadConfig — tests/fixtures/sample_channel", () => {
  // Repo root is three levels up from packages/core/test/ (see skills-sync.test).
  const repoRoot = resolve(import.meta.dir, "..", "..", "..");
  const sampleChannel = join(repoRoot, "tests", "fixtures", "sample_channel");

  test("the committed fixture exists with config/channel", () => {
    // Guards the precondition for the green-load assertion below.
    expect(existsSync(join(sampleChannel, "config", "channel"))).toBe(true);
  });

  test("loads the committed fixture green with expected values", () => {
    // Given the shared Python/TS fixture channel
    process.env.CHANNEL_DIR = sampleChannel;

    // When loaded through the TS API
    const config = loadConfig();

    // Then the cross-section values match the fixture on disk
    expect(config.meta.channelName).toBe("Test Channel");
    expect(config.meta.branding.description).toBe(
      "Test channel description for sync."
    );
    expect(config.youtube.api.language).toBe("ja");
    // musicEngine is unset in the fixture, so it falls back to the default
    expect(config.youtube.musicEngine).toBe("suno");
    expect(config.youtube.contentModel.type).toBe("collection");
    expect(config.localizations.exists).toBe(true);
    expect(config.localizations.supportedLanguages).toEqual(["ja", "en", "de"]);
    expect(config.shorts.enabled).toBe(true);
    expect(config.comments.enabled).toBe(false);
    expect(config.pinnedComment.enabled).toBe(true);
    expect(config.playlists.items.main).toEqual({
      auto_add: true,
      playlist_id: "PLtest123",
      title: null,
    });
  });
});
