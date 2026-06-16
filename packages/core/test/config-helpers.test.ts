import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  test,
} from "bun:test";

// The dataclass methods from the Python config sections are ported as
// co-located pure functions operating on the parsed sections. They are part of
// the faithful "whole utils/config" port (plan §5).
import {
  activityForTheme,
  brandingAsApiDict,
  hashtagLine,
  loadConfig,
  renderOpening,
  reset,
  sceneForTheme,
  tagsDefault,
  tagsForCollection,
} from "@youtube-automation/core/config";

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

const load = (sections: Sections) => {
  const dir = setupChannel(sections);
  process.env.CHANNEL_DIR = dir;
  return loadConfig();
};

// --- tags ------------------------------------------------------------------

describe("tagsDefault", () => {
  test("appends the lowercased channel name to base tags", () => {
    // Given the minimal content tags + channel "Test Channel"
    const config = load(minimalSections());

    // Then the default list ends with the lowercased channel name
    expect(tagsDefault(config.publishing.content.tags)).toEqual([
      "chiptune music",
      "8-bit",
      "test channel",
    ]);
  });
});

describe("tagsForCollection", () => {
  test("adds channel-specific + matched-theme tags, capped at 50", () => {
    // Given channel-specific tags and themed tag lists
    const sections = minimalSections();
    (
      sections["content.json"] as { tags: Record<string, unknown> }
    ).tags.channel_specific = ["ch-tag"];
    const config = load(sections);

    // When building tags for a battle-themed collection name
    const tags = tagsForCollection(
      config.publishing.content.tags,
      "Epic Battle BGM"
    );

    // Then default + channel-specific + the matched theme tags are present
    expect(tags).toContain("ch-tag");
    // battle is the matched theme
    expect(tags).toContain("battle music");
    expect(tags).toContain("boss battle");
    // village is an unmatched theme
    expect(tags).not.toContain("village music");
    // the default list carries the channel name
    expect(tags).toContain("test channel");
    expect(tags.length).toBeLessThanOrEqual(50);
  });
});

// --- descriptions ----------------------------------------------------------

describe("renderOpening", () => {
  test("formats {style}/{primary}/{context} with title-cased style", () => {
    // Given opening "{style} {primary} for {context}" + genre 8-bit/chiptune/RPG
    const config = load(minimalSections());

    // Then style is title-cased and placeholders are interpolated
    expect(renderOpening(config.publishing.content.descriptions)).toBe(
      "8-Bit chiptune for RPG"
    );
  });
});

describe("hashtagLine", () => {
  test("joins the hashtags with a single space", () => {
    // Given two hashtags
    const sections = minimalSections();
    (
      sections["content.json"] as { descriptions: Record<string, unknown> }
    ).descriptions.hashtags = ["#ChiptuneMusic", "#8bit"];
    const config = load(sections);

    // Then they render as a space-joined line
    expect(hashtagLine(config.publishing.content.descriptions)).toBe(
      "#ChiptuneMusic #8bit"
    );
  });
});

// --- title: activity_for_theme (#80 longest-match) ------------------------

describe("activityForTheme — legacy theme_activities", () => {
  test("matches a theme substring, else falls back to default_activity", () => {
    // Given legacy theme_activities mapping battle→Gaming, default Chill
    const sections = minimalSections();
    const { title } = sections["content.json"] as {
      title: Record<string, unknown>;
    };
    title.default_activity = "Chill";
    title.theme_activities = { battle: "Gaming" };
    const config = load(sections);

    // Then a battle-themed name resolves to Gaming, others to the default
    expect(
      activityForTheme(config.publishing.content.title, "Epic Battle Scene")
    ).toBe("Gaming");
    expect(
      activityForTheme(config.publishing.content.title, "Ocean Waves")
    ).toBe("Chill");
  });
});

// tags.themes must declare the same keys (cross-file subset rule), so cafe and
// campus-cafe are added to themes alongside the theme_scenes entries.
const withScenes = (): Sections => {
  const sections = minimalSections();
  const content = sections["content.json"] as {
    tags: { themes: Record<string, unknown> };
    title: Record<string, unknown>;
  };
  content.tags.themes = {
    cafe: ["cafe music"],
    "campus-cafe": ["campus cafe music"],
  };
  content.title.default_activity = "Study";
  content.title.theme_scenes = {
    cafe: { activities: "Study · Work · Reading", scene: "Cafe" },
    "campus-cafe": {
      activities: "Study · Work · Late Night",
      scene: "Campus Cafe",
    },
  };
  return sections;
};

describe("activityForTheme — theme_scenes longest-match (#80)", () => {
  test("prefers an exact key match regardless of insertion order", () => {
    // Given a short key (cafe) registered before the longer campus-cafe
    const config = load(withScenes());

    // Then an exact "campus-cafe" hits its own entry, not the shorter cafe
    expect(
      activityForTheme(config.publishing.content.title, "campus-cafe")
    ).toBe("Study · Work · Late Night");
  });

  test("prefers the longest substring match for non-exact names", () => {
    // Given a name containing both cafe and campus-cafe
    const config = load(withScenes());

    // Then the longest key wins (campus-cafe over cafe)
    expect(
      activityForTheme(config.publishing.content.title, "nice-campus-cafe-mix")
    ).toBe("Study · Work · Late Night");
  });

  test("falls back to the shorter key when only it matches", () => {
    // Given a name that only contains the shorter key
    const config = load(withScenes());

    // Then the shorter cafe entry is used
    expect(
      activityForTheme(config.publishing.content.title, "after-midnight-cafe")
    ).toBe("Study · Work · Reading");
  });
});

// --- title: scene_for_theme -----------------------------------------------

describe("sceneForTheme", () => {
  test("returns the matched scene phrase via longest-match", () => {
    // Given theme_scenes with cafe/campus-cafe (+ matching tags.themes keys)
    const sections = minimalSections();
    const content = sections["content.json"] as {
      tags: { themes: Record<string, unknown> };
      title: Record<string, unknown>;
    };
    content.tags.themes = {
      cafe: ["cafe music"],
      "campus-cafe": ["campus cafe music"],
    };
    content.title.theme_scenes = {
      cafe: { activities: "Study", scene: "Cafe" },
      "campus-cafe": { activities: "Late Night", scene: "Campus Cafe" },
    };
    const config = load(sections);

    // Then the longest match returns its scene phrase
    expect(
      sceneForTheme(config.publishing.content.title, "nice-campus-cafe-mix")
    ).toBe("Campus Cafe");
  });

  test("returns an empty string when no theme_scenes are configured", () => {
    // Given the minimal title with no theme_scenes
    const config = load(minimalSections());

    // Then scene resolution yields an empty string (caller decides fallback)
    expect(sceneForTheme(config.publishing.content.title, "battle")).toBe("");
  });
});

// --- branding: as_api_dict -------------------------------------------------

describe("brandingAsApiDict", () => {
  test("returns an empty object when youtube_channel is absent", () => {
    // Given no youtube_channel branding
    const config = load(minimalSections());

    // Then the api dict is empty (unset keys omitted)
    expect(brandingAsApiDict(config.identity.meta.branding)).toEqual({});
  });

  test("emits only the set keys, including made_for_kids=false", () => {
    // Given a partial branding block (made_for_kids explicitly false)
    const sections = minimalSections();
    (sections["meta.json"] as Record<string, unknown>).youtube_channel = {
      description: "desc",
      keywords: ["a", "b"],
      made_for_kids: false,
    };
    const config = load(sections);

    // Then only the provided keys appear; made_for_kids=false is NOT dropped
    expect(brandingAsApiDict(config.identity.meta.branding)).toEqual({
      description: "desc",
      keywords: ["a", "b"],
      made_for_kids: false,
    });
  });
});
