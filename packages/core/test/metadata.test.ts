// Tests for metadata generation helpers and the public metadata facade.
//
// Per plan §2, only the *pure* surface is ported: title/description/localization
// /shorts/track-string generation. The audio-analysis (afinfo), workflow-state
// fs I/O, skill_config YAML and report orchestration are deferred. Functions
// that need section headers / usage lines / durations / tracks receive them as
// arguments (plan §4-B), so these tests pass them explicitly rather than reading
// a skill_config or running subprocesses.
//
// Signature contract (the test-first spec the draft implements), from plan §4-B:
//   cleanTrackTitle(filename) -> string
//   extractPatternKey(filename) -> "a"|"b"|"c"|"d"|null
//   buildTimestampsText(tracks, themeNames, themeInline) -> string
//   formatShortDurationPhrase(audio) -> string
//   buildShortDescription(config, {collectionName, ccVideoUrl}) -> string
//   buildShortLocalizations(config, {collectionName, theme, ccVideoUrl}) -> record
//   generateVideoMetadataService(input, {config}) -> Result<metadata, ServiceError>

import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  test,
} from "bun:test";

import {
  loadConfig,
  reset,
  tagsForCollection,
} from "@youtube-automation/core/config";
import type { ChannelConfig } from "@youtube-automation/core/config";
import {
  buildShortDescription,
  buildShortLocalizations,
  buildTimestampsText,
  cleanTrackTitle,
  extractPatternKey,
  formatShortDurationPhrase,
  generateVideoMetadataService,
} from "@youtube-automation/core/metadata";

import {
  buildCompleteCollectionDescription,
  formatSceneTitleViolations,
  generateCompleteCollectionTitle,
  generateLocalizations,
  validateScenePhrases,
} from "../src/metadata/collection.ts";
import {
  formatTitleTemplate,
  referencedPlaceholders,
} from "../src/metadata/format.ts";
import {
  cleanupChannels,
  minimalSections,
  restoreChannelDirEnv,
  saveChannelDirEnv,
  setupChannel,
} from "./config-fixtures.ts";
import type { Sections } from "./config-fixtures.ts";

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

// Loads a ChannelConfig from inline fixture sections + optional localizations.
const loadFrom = (
  sections: Sections,
  localizations?: Record<string, unknown>
): ChannelConfig => {
  const dir = setupChannel(sections, localizations);
  process.env.CHANNEL_DIR = dir;
  return loadConfig();
};

// A localizations fixture with two render languages and one language that lacks
// a short_title_template (to exercise the skip branch).
const LOCALIZATIONS = {
  languages: {
    de: {
      // No short_title_template -> skipped by buildShortLocalizations.
      title_template: "{scene_phrase} - {activities}",
    },
    en: {
      activities: "Study, Focus",
      description: { opening_poem: "Rainy night", tagline: "EN tagline" },
      short_title_template: "{theme} ✦ {channel_name} #Shorts",
      title_template: "{scene_phrase} {activities}",
    },
    ja: {
      activities: "勉強, 集中",
      description: { opening_poem: "雨の夜", tagline: "JAタグライン" },
      short_title_template: "{theme} ✦ {channel_name} #Shorts",
      title_template: "{scene_phrase}｜{activities}",
    },
  },
  supported_languages: ["en", "ja", "de"],
};

// --- referencedPlaceholders ------------------------------------------------

describe("referencedPlaceholders", () => {
  test("collects the field names a template references", () => {
    expect(
      [...referencedPlaceholders("{theme} - {activity}")].toSorted()
    ).toEqual(["activity", "theme"]);
  });

  test("normalizes attribute and index access to the base name", () => {
    // {a.b} and {c[0]} both reduce to their root field name
    expect([...referencedPlaceholders("{a.b} {c[0]}")].toSorted()).toEqual([
      "a",
      "c",
    ]);
  });

  test("returns an empty set for a template with no fields", () => {
    expect([...referencedPlaceholders("no placeholders here")]).toEqual([]);
  });

  test("treats doubled braces as escaped literals, not fields", () => {
    // Python string.Formatter parses {{ }} as a literal brace, not a field.
    expect([...referencedPlaceholders("{{literal}}")]).toEqual([]);
  });
});

// --- formatTitleTemplate ---------------------------------------------------

describe("formatTitleTemplate", () => {
  test("substitutes allowed placeholders", () => {
    expect(
      formatTitleTemplate(
        "{theme} - {activity}",
        { activity: "Study", theme: "Village" },
        "content.json: title.template"
      )
    ).toBe("Village - Study");
  });

  test("throws a validation:-prefixed error naming an unknown placeholder", () => {
    // Given a template referencing a key absent from the values dict
    expect(() =>
      formatTitleTemplate(
        "{theme} {adjective}",
        { theme: "Village" },
        "content.json: title.template"
      )
    ).toThrow(/^validation:/u);
  });

  test("includes the offending key and context in the error message", () => {
    expect(() =>
      formatTitleTemplate(
        "{theme} {adjective}",
        { theme: "Village" },
        "content.json: title.template"
      )
    ).toThrow(/adjective/u);
  });
});

// --- cleanTrackTitle -------------------------------------------------------

describe("cleanTrackTitle", () => {
  test("strips an 8bit prefix and title-cases", () => {
    expect(cleanTrackTitle("8bit village town")).toBe("Village Town");
  });

  test("strips a two-digit number prefix and converts separators", () => {
    expect(cleanTrackTitle("01-rainy-night")).toBe("Rainy Night");
  });

  test("strips a pattern prefix with a variation suffix", () => {
    expect(cleanTrackTitle("pattern-a1-deep_focus")).toBe("Deep Focus");
  });

  test("removes a trailing parenthetical suffix", () => {
    expect(cleanTrackTitle("midnight drive (Remix)")).toBe("Midnight Drive");
  });

  test("keeps small words lowercase except the first word", () => {
    expect(cleanTrackTitle("a-tale-of-two-cities")).toBe(
      "A Tale of Two Cities"
    );
  });
});

// --- extractPatternKey -----------------------------------------------------

describe("extractPatternKey", () => {
  test("extracts the lowercase pattern letter", () => {
    expect(extractPatternKey("01-pattern-a-foo.mp3")).toBe("a");
  });

  test("tolerates a variation digit after the letter", () => {
    expect(extractPatternKey("03-pattern-B1-x.mp3")).toBe("b");
  });

  test("returns null for an out-of-range letter", () => {
    expect(extractPatternKey("01-pattern-e-x.mp3")).toBeNull();
  });

  test("returns null when a second letter follows (negative lookahead)", () => {
    expect(extractPatternKey("01-pattern-ab-x.mp3")).toBeNull();
  });

  test("returns null without a leading numeric prefix", () => {
    expect(extractPatternKey("pattern-a-x.mp3")).toBeNull();
  });

  test("returns null for a non-pattern filename", () => {
    expect(extractPatternKey("midnight-drive.mp3")).toBeNull();
  });
});

// --- buildTimestampsText ---------------------------------------------------

describe("buildTimestampsText", () => {
  const themeInline = { prefix: "── ", suffix: " ──" };

  test("returns an empty string for no tracks", () => {
    expect(buildTimestampsText([], {}, themeInline)).toBe("");
  });

  test("emits theme headers on pattern switches and track lines otherwise", () => {
    // Given three tracks spanning two patterns, with one named theme
    const tracks = [
      { patternKey: "a", timestamp: "0:00", title: "Song A" },
      { patternKey: "a", timestamp: "2:00", title: "Song B" },
      { patternKey: "b", timestamp: "4:00", title: "Song C" },
    ];
    const themeNames = { a: "Morning" };

    // When building the timestamp body
    const text = buildTimestampsText(tracks, themeNames, themeInline);

    // Then the named header decorates pattern a, the fallback labels pattern b,
    // and header lines carry no leading timestamp (YouTube chapter rule).
    expect(text).toBe(
      [
        "── Morning ──",
        "0:00 Song A",
        "2:00 Song B",
        "── Pattern B ──",
        "4:00 Song C",
      ].join("\n")
    );
  });

  test("renders a flat track list when no pattern keys are present", () => {
    const tracks = [
      { timestamp: "0:00", title: "One" },
      { timestamp: "1:30", title: "Two" },
    ];

    expect(buildTimestampsText(tracks, {}, themeInline)).toBe(
      "0:00 One\n1:30 Two"
    );
  });
});

// --- formatShortDurationPhrase ---------------------------------------------

describe("formatShortDurationPhrase", () => {
  test("falls back to 'Full collection' when target_duration_min is null", () => {
    const config = loadFrom(minimalSections());
    expect(formatShortDurationPhrase(config.publishing.audio)).toBe(
      "Full collection"
    );
  });

  test("renders a singular hour for 60 minutes", () => {
    const sections = minimalSections();
    sections["audio.json"] = { audio: { target_duration_min: 60 } };
    const config = loadFrom(sections);
    expect(formatShortDurationPhrase(config.publishing.audio)).toBe("1 hour");
  });

  test("renders plural hours for a multi-hour duration", () => {
    const sections = minimalSections();
    sections["audio.json"] = { audio: { target_duration_min: 120 } };
    const config = loadFrom(sections);
    expect(formatShortDurationPhrase(config.publishing.audio)).toBe("2 hours");
  });

  // Python `round()` は round-half-to-even。30 分の奇数倍（.5 境界）で
  // half-up な `Math.round` と乖離するため、Python と一致することを担保する。
  // 90→1.5→even 2 / 150→2.5→even 2（Math.round なら 3）/ 210→3.5→even 4。
  test.each([
    [90, "2 hours"],
    [150, "2 hours"],
    [210, "4 hours"],
  ])(
    "rounds %d minutes half-to-even like Python round()",
    (targetMin, expected) => {
      const sections = minimalSections();
      sections["audio.json"] = { audio: { target_duration_min: targetMin } };
      const config = loadFrom(sections);
      expect(formatShortDurationPhrase(config.publishing.audio)).toBe(expected);
    }
  );
});

// --- buildShortDescription -------------------------------------------------

describe("buildShortDescription", () => {
  test("includes the CC link line when a url is supplied", () => {
    const config = loadFrom(minimalSections());

    const desc = buildShortDescription(config, {
      ccVideoUrl: "https://youtu.be/abc",
      collectionName: "Rainy Night",
    });

    expect(desc.split("\n")).toEqual([
      "Rainy Night (Full collection) | Test Channel",
      "",
      "♫ Full → https://youtu.be/abc",
      "",
      "#Shorts",
    ]);
  });

  test("omits the CC link line when the url is empty", () => {
    const config = loadFrom(minimalSections());

    const desc = buildShortDescription(config, {
      ccVideoUrl: "",
      collectionName: "Rainy Night",
    });

    expect(desc.split("\n")).toEqual([
      "Rainy Night (Full collection) | Test Channel",
      "",
      "#Shorts",
    ]);
  });
});

// --- buildShortLocalizations -----------------------------------------------

describe("buildShortLocalizations", () => {
  test("returns an empty record when no localizations are configured", () => {
    const config = loadFrom(minimalSections());

    expect(
      buildShortLocalizations(config, {
        ccVideoUrl: "https://youtu.be/abc",
        collectionName: "Rainy Night",
        theme: "village",
      })
    ).toEqual({});
  });

  test("formats per-language titles and skips languages without a template", () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    const loc = buildShortLocalizations(config, {
      ccVideoUrl: "https://youtu.be/abc",
      collectionName: "Rainy Night",
      theme: "Village",
    });

    // en/ja have short_title_template; de does not and is skipped
    expect(Object.keys(loc).toSorted()).toEqual(["en", "ja"]);
    expect(loc.en?.title).toBe("Village ✦ Test Channel #Shorts");
  });

  test("falls back to the default short description body when no template", () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    const loc = buildShortLocalizations(config, {
      ccVideoUrl: "https://youtu.be/abc",
      collectionName: "Rainy Night",
      theme: "Village",
    });

    // en lacks short_description_template -> shared build_short_description body
    expect(loc.en?.description).toContain("#Shorts");
    expect(loc.en?.description?.length).toBeLessThanOrEqual(5000);
  });

  // Regression guard (family: magic-number-dup): the short-localization
  // description must be truncated at the SAME codepoint ceiling that the
  // complete-collection description uses (DESCRIPTION_CODEPOINT_LIMIT = 5000,
  // single-sourced in metadata/format.ts). A template that overflows 5000
  // codepoints must clamp to exactly 5000 — if shorts re-introduced a divergent
  // literal, this boundary would drift.
  test("truncates an overflowing short description at the shared 5000 limit", () => {
    const overflowTagline = "x".repeat(6000);
    const localizations = {
      languages: {
        en: {
          description: { tagline: overflowTagline },
          short_description_template: "{tagline}",
          short_title_template: "{theme} #Shorts",
        },
        // ja is required by the default content_model.languages but lacks a
        // short_title_template, so buildShortLocalizations skips it.
        ja: { title_template: "{scene_phrase}" },
      },
      supported_languages: ["en", "ja"],
    };
    const config = loadFrom(minimalSections(), localizations);

    const loc = buildShortLocalizations(config, {
      ccVideoUrl: "https://youtu.be/abc",
      collectionName: "Rainy Night",
      theme: "Village",
    });

    expect([...(loc.en?.description ?? "")].length).toBe(5000);
  });
});

// --- scene phrase validation ----------------------------------------------

describe("validateScenePhrases", () => {
  test("returns no violations when every localized title fits 100 codepoints", () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    const violations = validateScenePhrases(
      { de: "Stiller Regen", en: "Quiet Rain", ja: "静かな雨" },
      config,
      ""
    );

    expect(violations).toEqual([]);
  });

  test("flags a language whose localized title exceeds 100 codepoints", () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);
    const longPhrase = "x".repeat(120);

    const violations = validateScenePhrases(
      { de: "Stiller Regen", en: longPhrase, ja: "静かな雨" },
      config,
      ""
    );

    expect(violations.map((v) => v.lang)).toContain("en");
    const enViolation = violations.find((v) => v.lang === "en");
    expect(enViolation?.length).toBeGreaterThan(100);
  });

  test("throws when a supported language is missing a scene phrase", () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    expect(() =>
      validateScenePhrases({ en: "Quiet Rain", ja: "静かな雨" }, config, "")
    ).toThrow(/de/u);
  });
});

describe("formatSceneTitleViolations", () => {
  test("renders one indented line per violation with the overflow delta", () => {
    const text = formatSceneTitleViolations([
      {
        lang: "ja",
        length: 105,
        template: "{scene_phrase}",
        title: "超過タイトル",
      },
    ]);

    expect(text).toBe("  - [ja] 105 codepoints (+5): 超過タイトル");
  });
});

// --- generateCompleteCollectionTitle ---------------------------------------

describe("generateCompleteCollectionTitle", () => {
  const baseOptions = {
    activities: "Study, Focus",
    activity: "Study",
    durationDisplay: "2 hours",
    durationShort: "2h",
    sceneEmoji: "",
    scenePhrase: "Quiet Rain",
    theme: "Village",
  };

  test("formats the configured title template", () => {
    const config = loadFrom(minimalSections());

    expect(generateCompleteCollectionTitle(config, baseOptions)).toBe(
      "Village - Study"
    );
  });

  test("injects the title-cased genre style for {style}", () => {
    const sections = minimalSections();
    (sections["content.json"] as { title: Record<string, unknown> }).title = {
      template: "{style} {theme}",
    };
    const config = loadFrom(sections);

    // genre.style "8-bit" -> Python str.title() -> "8-Bit"
    expect(generateCompleteCollectionTitle(config, baseOptions)).toBe(
      "8-Bit Village"
    );
  });

  test("counts length in codepoints, not UTF-16 units (no false overflow)", () => {
    const sections = minimalSections();
    (sections["content.json"] as { title: Record<string, unknown> }).title = {
      template: "{scene_phrase}",
    };
    const config = loadFrom(sections);
    // 60 astral emoji = 60 codepoints (120 UTF-16 units). Must NOT throw.
    const phrase = "😀".repeat(60);

    expect(
      generateCompleteCollectionTitle(config, {
        ...baseOptions,
        scenePhrase: phrase,
      })
    ).toBe(phrase);
  });

  test("throws when the title exceeds 100 codepoints", () => {
    const sections = minimalSections();
    (sections["content.json"] as { title: Record<string, unknown> }).title = {
      template: "{scene_phrase}",
    };
    const config = loadFrom(sections);
    const phrase = "😀".repeat(101);

    expect(() =>
      generateCompleteCollectionTitle(config, {
        ...baseOptions,
        scenePhrase: phrase,
      })
    ).toThrow(/100/u);
  });
});

// --- buildCompleteCollectionDescription (AC: structure parity) -------------

describe("buildCompleteCollectionDescription", () => {
  const sectionHeaders = {
    channelLinkTemplate: "🔗 {channel_name}:",
    perfectFor: "🎮 Perfect for:",
    usageAttribution: "📝 Usage & Attribution:",
  };
  const usageLines = ["• Original AI composition", "• Free for personal use"];

  test("opens with the 🎵 title header followed by a blank line", () => {
    const config = loadFrom(minimalSections());

    const desc = buildCompleteCollectionDescription(config, {
      sectionHeaders,
      timestampBody: "0:00 Song A\n2:00 Song B",
      title: "8-Bit Village - Study",
      usageLines,
    });
    const lines = desc.split("\n");

    expect(lines[0]).toBe("🎵 8-Bit Village - Study");
    expect(lines[1]).toBe("");
  });

  test("embeds the timestamp body when supplied", () => {
    const config = loadFrom(minimalSections());

    const desc = buildCompleteCollectionDescription(config, {
      sectionHeaders,
      timestampBody: "0:00 Song A\n2:00 Song B",
      title: "Title",
      usageLines,
    });

    expect(desc).toContain("0:00 Song A\n2:00 Song B");
  });

  test("orders opening, usage, perfect-for, channel link and hashtags", () => {
    const config = loadFrom(minimalSections());

    const desc = buildCompleteCollectionDescription(config, {
      sectionHeaders,
      timestampBody: "0:00 Song A",
      title: "Title",
      usageLines,
    });

    // The rendered opening, usage block, perfect-for items, channel link
    // (with channel name interpolated), cta/tagline and hashtag line all appear.
    expect(desc).toContain("8-Bit chiptune for RPG");
    expect(desc).toContain("📝 Usage & Attribution:");
    expect(desc).toContain("• Original AI composition");
    expect(desc).toContain("🎮 Perfect for:");
    expect(desc).toContain("• Studying");
    expect(desc).toContain("🔗 Test Channel:");
    expect(desc).toContain("Test tagline");
    expect(desc).toContain("#ChiptuneMusic");

    // And they appear in the documented order (plan §5 parity).
    const order = [
      "🎵 Title",
      "0:00 Song A",
      "8-Bit chiptune for RPG",
      "📝 Usage & Attribution:",
      "🎮 Perfect for:",
      "🔗 Test Channel:",
      "#ChiptuneMusic",
    ].map((needle) => desc.indexOf(needle));
    const sorted = [...order].toSorted((a, b) => a - b);
    expect(order).toEqual(sorted);
    expect(order.every((idx) => idx >= 0)).toBe(true);
  });
});

// --- generateLocalizations -------------------------------------------------

describe("generateLocalizations", () => {
  const sectionHeaders = {
    channelLinkTemplate: "🔗 {channel_name}:",
    trackList: "🎶 Tracklist",
    usageAttribution: "📝 Usage",
  };

  test("produces a localized title + description per supported language", () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    const loc = generateLocalizations(config, {
      sceneEmoji: "",
      scenePhrases: { de: "Stiller Regen", en: "Quiet Rain", ja: "静かな雨" },
      sectionHeaders,
      timestampBody: "0:00 Song A",
    });

    // Each supported language is rendered with a title formatted from its template
    expect(Object.keys(loc).toSorted()).toEqual(["de", "en", "ja"]);
    expect(loc.en?.title).toBe("Quiet Rain Study, Focus");
  });

  test("embeds the shared timestamp body and per-language tagline", () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    const loc = generateLocalizations(config, {
      sceneEmoji: "",
      scenePhrases: { de: "Stiller Regen", en: "Quiet Rain", ja: "静かな雨" },
      sectionHeaders,
      timestampBody: "0:00 Song A",
    });

    expect(loc.en?.description).toContain("0:00 Song A");
    expect(loc.en?.description).toContain("EN tagline");
    expect(loc.en?.description?.length).toBeLessThanOrEqual(5000);
  });

  test("throws when a scene phrase overflows 100 codepoints", () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    expect(() =>
      generateLocalizations(config, {
        sceneEmoji: "",
        scenePhrases: {
          de: "Stiller Regen",
          en: "x".repeat(120),
          ja: "静かな雨",
        },
        sectionHeaders,
        timestampBody: "0:00 Song A",
      })
    ).toThrow();
  });
});

// --- generateVideoMetadataService -----------------------------------------

describe("generateVideoMetadataService", () => {
  test("keeps the public metadata barrel limited to the facade and retained utilities", async () => {
    const metadata =
      (await import("@youtube-automation/core/metadata")) as Record<
        string,
        unknown
      >;

    for (const name of [
      "buildShortDescription",
      "buildShortLocalizations",
      "buildTimestampsText",
      "cleanTrackTitle",
      "extractPatternKey",
      "formatShortDurationPhrase",
      "generateVideoMetadataService",
    ]) {
      expect(typeof metadata[name]).toBe("function");
    }

    for (const name of [
      "GenerateMetadataInput",
      "GenerateMetadataOutput",
      "buildCompleteCollectionDescription",
      "formatTitleTemplate",
      "generateCompleteCollectionTitle",
      "generateLocalizations",
      "loadTemplate",
      "referencedPlaceholders",
      "validateScenePhrases",
    ]) {
      expect(name in metadata).toBe(false);
    }
  });

  test("generates title, description, tags, timestamps and localizations", async () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    const result = await generateVideoMetadataService(
      {
        collectionSlug: "battle-royale",
        scenePhrases: {
          de: "Stiller Regen",
          en: "Quiet Rain",
          ja: "静かな雨",
        },
        theme: "Battle Royale",
        tracks: [
          { durationSeconds: 120, startSeconds: 0, title: "Song A" },
          { durationSeconds: 180, startSeconds: 120, title: "Song B" },
        ],
      },
      { config }
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.title).toBe("Battle Royale - Study");
    expect(result.value.timestamps).toBe("0:00 Song A\n2:00 Song B");
    expect(result.value.description).toContain("🎵 Battle Royale - Study");
    expect(result.value.description).toContain("0:00 Song A\n2:00 Song B");
    expect(result.value.tags).toContain("battle music");
    expect(result.value.localizations?.en?.title).toBe(
      "Quiet Rain Study, Focus"
    );
    expect(result.value.localizations?.ja?.description).toContain(
      "0:00 Song A"
    );
    expect(result.value.violations).toEqual([]);
  });

  test("generates localizations from config, theme and tracks without scenePhrases", async () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    const result = await generateVideoMetadataService(
      {
        theme: "Battle Royale",
        tracks: [
          { durationSeconds: 120, startSeconds: 0, title: "Song A" },
          { durationSeconds: 180, startSeconds: 120, title: "Song B" },
        ],
      },
      { config }
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.localizations?.en?.title).toBe(
      "Battle Royale Study, Focus"
    );
    expect(result.value.localizations?.ja?.description).toContain(
      "0:00 Song A"
    );
    expect(result.value.violations).toEqual([]);
  });

  test.each([
    { durationSeconds: 60, expected: "5 min|5m" },
    { durationSeconds: 90 * 60, expected: "1.5 Hours|1.5h" },
    { durationSeconds: 150 * 60, expected: "2.5 Hours|2.5h" },
  ])(
    "formats duration placeholders with Python parity for $durationSeconds seconds",
    async ({ durationSeconds, expected }) => {
      const sections = minimalSections();
      (sections["content.json"] as { title: Record<string, unknown> }).title = {
        template: "{duration_display}|{duration_short}",
      };
      const config = loadFrom(sections, LOCALIZATIONS);

      const result = await generateVideoMetadataService(
        {
          theme: "Battle Royale",
          tracks: [{ durationSeconds, startSeconds: 0, title: "Song A" }],
        },
        { config }
      );

      expect(result.ok).toBe(true);
      if (!result.ok) {
        throw new Error(result.error.message);
      }
      expect(result.value.title).toBe(expected);
    }
  );

  test("uses the latest timeline end for duration placeholders", async () => {
    const sections = minimalSections();
    (sections["content.json"] as { title: Record<string, unknown> }).title = {
      template: "{duration_display}|{duration_short}",
    };
    const config = loadFrom(sections, LOCALIZATIONS);

    const result = await generateVideoMetadataService(
      {
        theme: "Battle Royale",
        tracks: [
          { durationSeconds: 60 * 60, startSeconds: 0, title: "Song A" },
          { durationSeconds: 60 * 60, startSeconds: 30 * 60, title: "Song B" },
        ],
      },
      { config }
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.title).toBe("1.5 Hours|1.5h");
  });

  test("uses scenePhrases.en for a scene phrase title template", async () => {
    const sections = minimalSections();
    (sections["content.json"] as { title: Record<string, unknown> }).title = {
      template: "{scene_phrase} - {activity}",
    };
    const config = loadFrom(sections, LOCALIZATIONS);

    const result = await generateVideoMetadataService(
      {
        scenePhrases: {
          de: "Stiller Regen",
          en: "Quiet Rain",
          ja: "静かな雨",
        },
        theme: "Battle Royale",
        tracks: [{ durationSeconds: 60, startSeconds: 0, title: "Song A" }],
      },
      { config }
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.title).toBe("Quiet Rain - Study");
  });

  test("returns title length violations without generating localizations", async () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    const result = await generateVideoMetadataService(
      {
        scenePhrases: {
          de: "Stiller Regen",
          en: "x".repeat(120),
          ja: "静かな雨",
        },
        theme: "Battle Royale",
        tracks: [{ durationSeconds: 60, startSeconds: 0, title: "Song A" }],
      },
      { config }
    );

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    expect(result.value.localizations).toBeUndefined();
    expect(result.value.violations.map((violation) => violation.lang)).toEqual([
      "en",
    ]);
  });

  test("returns a validation error for malformed input", async () => {
    const config = loadFrom(minimalSections(), LOCALIZATIONS);

    const result = await generateVideoMetadataService(
      { theme: "Battle Royale", unexpected: true } as unknown as Parameters<
        typeof generateVideoMetadataService
      >[0],
      { config }
    );

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation failure");
    }
    expect(result.error.domain).toBe("validation");
  });
});

// --- tags helper -----------------------------------------------------------

describe("tagsForCollection", () => {
  test("returns base + channel + matched theme tags", () => {
    const config = loadFrom(minimalSections());

    const tags = tagsForCollection(
      config.publishing.content.tags,
      "battle royale"
    );

    // base tags + lowercased channel name + the matched "battle" theme tags
    expect(tags).toContain("chiptune music");
    expect(tags).toContain("battle music");
    expect(tags.length).toBeLessThanOrEqual(50);
  });
});
