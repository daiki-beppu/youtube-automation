import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  spyOn,
  test,
} from "bun:test";

import { loadConfig, reset } from "@youtube-automation/core/config";

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

// Loads a channel built from `sections` (+ optional localizations) in one step.
const load = (sections: Sections, localizations?: Record<string, unknown>) => {
  const dir = setupChannel(sections, localizations);
  process.env.CHANNEL_DIR = dir;
  return loadConfig();
};

// --- youtube api flags (#605) ---------------------------------------------

describe("youtube.api synthetic-media flags", () => {
  test("default to synthetic=true / made_for_kids=false when unset", () => {
    // Given youtube.json without the AI-disclosure flags
    const config = load(minimalSections());

    // Then the upload-time defaults preserve current behaviour
    expect(config.publishing.youtube.api.containsSyntheticMedia).toBe(true);
    expect(config.publishing.youtube.api.selfDeclaredMadeForKids).toBe(false);
  });

  test("can be overridden from youtube.json", () => {
    // Given explicit overrides in youtube.json
    const sections = minimalSections();
    const yt = (
      sections["youtube.json"] as { youtube: Record<string, unknown> }
    ).youtube;
    yt.contains_synthetic_media = false;
    yt.self_declared_made_for_kids = true;

    // Then both flags flow through to the api section
    const config = load(sections);
    expect(config.publishing.youtube.api.containsSyntheticMedia).toBe(false);
    expect(config.publishing.youtube.api.selfDeclaredMadeForKids).toBe(true);
  });

  test("carries default publish schedule fields", () => {
    // Given youtube.json with channel-level default publish schedule fields
    const sections = minimalSections();
    const yt = (
      sections["youtube.json"] as { youtube: Record<string, unknown> }
    ).youtube;
    yt.default_publish_time = "20:00";
    yt.default_publish_timezone = "Asia/Tokyo";

    // Then they flow through to the api section in camelCase
    const config = load(sections);
    expect(config.publishing.youtube.api.defaultPublishTime).toBe("20:00");
    expect(config.publishing.youtube.api.defaultPublishTimezone).toBe(
      "Asia/Tokyo"
    );
  });
});

// --- music_engine warning (non-fatal) -------------------------------------

describe("youtube.musicEngine", () => {
  test("warns but does not throw on an unknown engine", () => {
    // Given an unrecognised music_engine value
    const sections = minimalSections();
    (sections["youtube.json"] as Record<string, unknown>).music_engine =
      "fairlight";
    const warnSpy = spyOn(console, "warn").mockImplementation(() => {});

    // When loaded
    const config = load(sections);

    // Then the value is preserved verbatim and a warning was emitted
    expect(config.publishing.youtube.musicEngine).toBe("fairlight");
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });
});

// --- overlays (#511) -------------------------------------------------------

describe("youtube.overlays", () => {
  test("default to disabled with nested defaults when unset", () => {
    // Given youtube.json without an overlays key
    const config = load(minimalSections());

    // Then overlays is disabled but nested structure is still safe to read
    expect(config.publishing.youtube.overlays.enabled).toBe(false);
    expect(config.publishing.youtube.overlays.audioVisualizer.enabled).toBe(
      false
    );
    expect(config.publishing.youtube.overlays.subscribePopup.enabled).toBe(
      false
    );
    expect(config.publishing.youtube.overlays.encoder.codec).toBe("libx264");
    expect(config.publishing.youtube.overlays.encoder.framerate).toBe(24);
    expect(config.publishing.youtube.overlays.audioVisualizer.opacity).toBe(
      0.85
    );
  });

  test("full override flows every nested field through", () => {
    // Given a fully-specified overlays block
    const sections = minimalSections();
    (sections["youtube.json"] as Record<string, unknown>).overlays = {
      audio_visualizer: {
        colors: "0xff66ccff",
        enabled: true,
        glow_opacity: 0.5,
        glow_sigma: 14,
        opacity: 0.9,
        position: "(W-w)/2:H-h-80",
        rate: "30",
        size: "1920x240",
        win_size: 4096,
      },
      enabled: true,
      encoder: {
        bufsize: "12M",
        crf: 18,
        framerate: 30,
        maxrate: "6M",
        preset: "slow",
      },
      subscribe_popup: {
        duration_sec: 10,
        enabled: true,
        fade_sec: 0.8,
        image: "popup.png",
        opacity: 0.95,
        position: "W-w-32:32",
        start_sec: 8.5,
      },
    };

    // Then nested fields are mapped (snake JSON → camel field) without loss
    const ov = load(sections).publishing.youtube.overlays;
    expect(ov.enabled).toBe(true);
    expect(ov.audioVisualizer.size).toBe("1920x240");
    expect(ov.audioVisualizer.winSize).toBe(4096);
    expect(ov.audioVisualizer.glowSigma).toBe(14);
    expect(ov.subscribePopup.image).toBe("popup.png");
    expect(ov.subscribePopup.startSec).toBe(8.5);
    expect(ov.subscribePopup.fadeSec).toBe(0.8);
    expect(ov.encoder.preset).toBe("slow");
    expect(ov.encoder.crf).toBe(18);
    expect(ov.encoder.framerate).toBe(30);
  });

  test("rejects a non-object overlays section", () => {
    // Given overlays declared as an array
    const sections = minimalSections();
    (sections["youtube.json"] as Record<string, unknown>).overlays = [
      "enabled",
      "true",
    ];

    // When/Then the object-shape guard fires
    expect(() => load(sections)).toThrow(/overlays/u);
  });

  test("rejects a non-object overlays.audio_visualizer", () => {
    // Given a nested overlay block of the wrong shape
    const sections = minimalSections();
    (sections["youtube.json"] as Record<string, unknown>).overlays = {
      audio_visualizer: "bar",
    };

    // When/Then the nested guard fires
    expect(() => load(sections)).toThrow(/audio_visualizer/u);
  });
});

// --- shorts ----------------------------------------------------------------

describe("shorts", () => {
  test("default to disabled with documented defaults when absent", () => {
    // Given no shorts.json (opt-in section)
    const config = load(minimalSections());

    // Then shorts collapses to the opt-out defaults
    expect(config.publishing.shorts.enabled).toBe(false);
    expect(config.publishing.shorts.publishTime).toBe("08:00");
    expect(config.publishing.shorts.minHoursBetweenShortsPerCollection).toBe(
      24
    );
    expect(config.publishing.shorts.mode).toBe("auto");
    expect(config.publishing.shorts.collection.defaultCount).toBe(3);
    expect(config.publishing.shorts.release.languages).toEqual(["jp", "en"]);
  });

  test("full override flows every field through", () => {
    // Given a fully-specified shorts block
    const sections = minimalSections();
    sections["shorts.json"] = {
      shorts: {
        collection: { chapter_offset_sec: 45, default_count: 5 },
        enabled: true,
        min_hours_between_shorts_per_collection: 12,
        mode: "collection",
        publish_time: "09:30",
        release: { duration_sec: 30, languages: ["jp"], start_sec: 20 },
      },
    };

    // Then all fields land in the shorts section
    const { shorts } = load(sections).publishing;
    expect(shorts.enabled).toBe(true);
    expect(shorts.publishTime).toBe("09:30");
    expect(shorts.minHoursBetweenShortsPerCollection).toBe(12);
    expect(shorts.mode).toBe("collection");
    expect(shorts.collection.defaultCount).toBe(5);
    expect(shorts.collection.chapterOffsetSec).toBe(45);
    expect(shorts.release.languages).toEqual(["jp"]);
    expect(shorts.release.startSec).toBe(20);
    expect(shorts.release.durationSec).toBe(30);
  });
});

// --- audio -----------------------------------------------------------------

describe("audio", () => {
  test("defaults to null durations and chapterMax=100", () => {
    // Given no audio.json
    const config = load(minimalSections());

    // Then optional durations stay null and chapterMax uses the documented 100
    expect(config.publishing.audio.targetDurationMin).toBeNull();
    expect(config.publishing.audio.targetDurationMax).toBeNull();
    expect(config.publishing.audio.chapterMax).toBe(100);
  });

  test("reads overrides from audio.json", () => {
    // Given audio overrides
    const sections = minimalSections();
    sections["audio.json"] = {
      audio: { chapter_max: 50, target_duration_min: 120 },
    };

    // Then values flow through
    const { audio } = load(sections).publishing;
    expect(audio.targetDurationMin).toBe(120);
    expect(audio.chapterMax).toBe(50);
  });
});

// --- analytics -------------------------------------------------------------

describe("analytics", () => {
  test("defaults to empty keywords and benchmark channels", () => {
    // Given no analytics.json
    const config = load(minimalSections());

    // Then both collections are empty
    expect(config.integrations.analytics.collectionFilterKeywords).toEqual([]);
    expect(config.integrations.analytics.benchmark.channels).toEqual([]);
  });

  test("reads keywords and benchmark channels", () => {
    // Given analytics + benchmark data
    const sections = minimalSections();
    sections["analytics.json"] = {
      analytics: { collection_filter_keywords: ["collection", "complete"] },
      benchmark: { channels: [{ id: "UC123", name: "Rival" }] },
    };

    // Then both flow through verbatim
    const { analytics } = load(sections).integrations;
    expect(analytics.collectionFilterKeywords).toEqual([
      "collection",
      "complete",
    ]);
    expect(analytics.benchmark.channels).toEqual([
      { id: "UC123", name: "Rival" },
    ]);
  });
});

// --- playlists (#275 / #419) ----------------------------------------------
//
// Inner playlist entries keep snake_case JSON keys: dict entries are passed
// through verbatim (e.g. `auto_add_themes`), so a string entry must normalise
// to the SAME snake_case shape — `{ playlist_id, auto_add, title }` — for the
// items map to stay internally consistent (matches Python `_build_playlists`).

describe("playlists", () => {
  test("normalises a string entry to a snake_case dict", () => {
    // Given a string playlist id
    const sections = minimalSections();
    sections["playlists.json"] = { playlists: { main: "PL_X" } };

    // Then it expands to the canonical dict shape
    const config = load(sections);
    expect(config.engagement.playlists.items.main).toEqual({
      auto_add: true,
      playlist_id: "PL_X",
      title: null,
    });
  });

  test("passes a dict entry through verbatim", () => {
    // Given a dict playlist entry with extra keys
    const sections = minimalSections();
    sections["playlists.json"] = {
      playlists: {
        battle: {
          auto_add_themes: ["fight"],
          playlist_id: "PL_B",
          title: "Battle Music",
        },
      },
    };

    // Then the entry is preserved as-is
    const entry = load(sections).engagement.playlists.items.battle;
    expect(entry).toEqual({
      auto_add_themes: ["fight"],
      playlist_id: "PL_B",
      title: "Battle Music",
    });
  });

  test("rejects a non-object playlists section", () => {
    // Given playlists declared as an array
    const sections = minimalSections();
    sections["playlists.json"] = { playlists: [1] };

    // When/Then the section-shape guard fires
    expect(() => load(sections)).toThrow(/playlists/u);
  });

  test("rejects a per-key value that is neither string nor object", () => {
    // Given a numeric playlist value (silent pass-through is forbidden, #419)
    const sections = minimalSections();
    sections["playlists.json"] = { playlists: { main: 42 } };

    // When/Then the per-key guard fires, naming the offending key
    expect(() => load(sections)).toThrow(/playlists\.main/u);
  });
});

// --- workflow (#508) -------------------------------------------------------

describe("workflow.wfNext.approvalGates", () => {
  test("default both gates to false (fully automatic)", () => {
    // Given no workflow.json
    const config = load(minimalSections());

    // Then both approval gates are off
    expect(config.publishing.workflow.wfNext.approvalGates.audio).toBe(false);
    expect(config.publishing.workflow.wfNext.approvalGates.upload).toBe(false);
  });

  test("read explicit and partial gate overrides", () => {
    // Given only the audio gate enabled
    const sections = minimalSections();
    sections["workflow.json"] = {
      workflow: { wf_next: { approval_gates: { audio: true } } },
    };

    // Then audio is on and the unspecified upload defaults off
    const gates = load(sections).publishing.workflow.wfNext.approvalGates;
    expect(gates.audio).toBe(true);
    expect(gates.upload).toBe(false);
  });

  test("silently ignore legacy workflow.post_upload keys", () => {
    // Given a stale workflow.post_upload.short_publish_time
    const sections = minimalSections();
    sections["workflow.json"] = {
      workflow: { post_upload: { short_publish_time: "09:30" } },
    };

    // Then it is ignored and shorts.publish_time keeps its default
    expect(load(sections).publishing.shorts.publishTime).toBe("08:00");
  });

  test("rejects a non-object workflow section", () => {
    // Given workflow declared as a string
    const sections = minimalSections();
    sections["workflow.json"] = { workflow: "not-an-object" };

    // When/Then the section guard fires
    expect(() => load(sections)).toThrow(/workflow/u);
  });

  test("rejects a non-object workflow.wf_next", () => {
    // Given workflow.wf_next of the wrong shape
    const sections = minimalSections();
    sections["workflow.json"] = { workflow: { wf_next: ["bad"] } };

    // When/Then the nested guard fires
    expect(() => load(sections)).toThrow(/wf_next/u);
  });
});

// --- pinned comment --------------------------------------------------------

describe("pinnedComment", () => {
  test("defaults to disabled with empty templates", () => {
    // Given no pinned-comment.json
    const config = load(minimalSections());

    // Then the opt-in section collapses to its disabled default
    expect(config.engagement.pinnedComment.enabled).toBe(false);
    expect(config.engagement.pinnedComment.templates).toEqual({});
    expect(config.engagement.pinnedComment.historyFile).toBe(
      "pinned_comment_history.json"
    );
    expect(config.engagement.pinnedComment.defaultLanguage).toBe("en");
  });

  test("reads enabled config with templates", () => {
    // Given a configured pinned comment block
    const sections = minimalSections();
    sections["pinned-comment.json"] = {
      pinned_comment: {
        default_language: "ja",
        delay_between_posts_sec: 1.5,
        enabled: true,
        history_file: "pins.json",
        templates: { en: "{scene_phrase}", ja: "{scene_phrase} {scene_emoji}" },
      },
    };

    // Then the fields are mapped to camelCase
    const pc = load(sections).engagement.pinnedComment;
    expect(pc.enabled).toBe(true);
    expect(pc.historyFile).toBe("pins.json");
    expect(pc.delayBetweenPostsSec).toBe(1.5);
    expect(pc.defaultLanguage).toBe("ja");
    expect(pc.templates.ja).toBe("{scene_phrase} {scene_emoji}");
  });

  test("rejects non-object templates", () => {
    // Given templates declared as an array
    const sections = minimalSections();
    sections["pinned-comment.json"] = {
      pinned_comment: { templates: ["not", "an", "object"] },
    };

    // When/Then the templates-shape guard fires
    expect(() => load(sections)).toThrow(/pinned_comment\.templates/u);
  });
});

// --- distrokid (#698) ------------------------------------------------------

const fullDistrokidProfile = (): Record<string, unknown> => ({
  ai_disclosure: {
    apply_to_all: true,
    artist_persona: true,
    enabled: true,
    lyrics: true,
    music: true,
    partial_audio_type: null,
    recording_scope: "full",
  },
  artist: "City Nights",
  credits: {
    performer_role: "Synthesizer",
    producer_role: "Producer",
  },
  language: "English",
  main_genre: "Electronic",
  songwriter: { first: "Jane", last: "Doe" },
  sub_genre: "Ambient",
});

describe("distrokid", () => {
  test("defaults to disabled with empty profile when absent", () => {
    // Given no distrokid.json
    const config = load(minimalSections());

    // Then the opt-in section is disabled with blank profile fields
    expect(config.integrations.distrokid.enabled).toBe(false);
    expect(config.integrations.distrokid.profile.artist).toBe("");
    expect(config.integrations.distrokid.profile.songwriter).toBeNull();
    expect(config.integrations.distrokid.profile.aiDisclosure.enabled).toBe(
      true
    );
    expect(config.integrations.distrokid.profile.credits.performerRole).toBe(
      "Synthesizer"
    );
  });

  test("loads an enabled profile through to camelCase fields", () => {
    // Given enabled distrokid with a complete profile
    const sections = minimalSections();
    sections["distrokid.json"] = {
      distrokid: { enabled: true, profile: fullDistrokidProfile() },
    };

    // Then all six profile fields are mapped
    const dk = load(sections).integrations.distrokid;
    expect(dk.enabled).toBe(true);
    expect(dk.profile.artist).toBe("City Nights");
    expect(dk.profile.language).toBe("English");
    expect(dk.profile.mainGenre).toBe("Electronic");
    expect(dk.profile.subGenre).toBe("Ambient");
    expect(dk.profile.songwriter).toEqual({
      first: "Jane",
      last: "Doe",
      middle: null,
    });
    expect(dk.profile.aiDisclosure.recordingScope).toBe("full");
    expect(dk.profile.aiDisclosure.partialAudioType).toBeNull();
    expect(dk.profile.credits.producerRole).toBe("Producer");
  });

  test("rejects enabled=true with a missing profile field", () => {
    // Given enabled distrokid missing main_genre (conditional-required)
    const sections = minimalSections();
    const profile = fullDistrokidProfile();
    Reflect.deleteProperty(profile, "main_genre");
    sections["distrokid.json"] = { distrokid: { enabled: true, profile } };

    // When/Then the conditional validation names the missing field
    expect(() => load(sections)).toThrow(/main_genre/u);
  });

  test("enabled=true accepts minimal required profile fields", () => {
    // Given enabled distrokid with only the Python-side required fields
    const sections = minimalSections();
    sections["distrokid.json"] = {
      distrokid: {
        enabled: true,
        profile: { language: "ja", main_genre: "Electronic" },
      },
    };

    // Then optional fields fall back to documented defaults
    const dk = load(sections).integrations.distrokid;
    expect(dk.enabled).toBe(true);
    expect(dk.profile.artist).toBe("");
    expect(dk.profile.songwriter).toBeNull();
    expect(dk.profile.subGenre).toBeNull();
    expect(dk.profile.aiDisclosure.applyToAll).toBe(true);
    expect(dk.profile.credits.performerRole).toBe("Synthesizer");
  });

  test("rejects partial audio type unless recording scope is partial", () => {
    // Given enabled distrokid with Python-incompatible AI disclosure settings
    const sections = minimalSections();
    const profile = fullDistrokidProfile();
    const aiDisclosure = profile.ai_disclosure as Record<string, unknown>;
    sections["distrokid.json"] = {
      distrokid: {
        enabled: true,
        profile: {
          ...profile,
          ai_disclosure: {
            ...aiDisclosure,
            partial_audio_type: "vocals",
            recording_scope: "full",
          },
        },
      },
    };

    // When/Then core rejects the same invalid cross-field combination as Python
    expect(() => load(sections)).toThrow(/partial_audio_type/u);
  });

  test("accepts partial audio type when recording scope is partial", () => {
    // Given enabled distrokid with a valid partial recording disclosure
    const sections = minimalSections();
    const profile = fullDistrokidProfile();
    const aiDisclosure = profile.ai_disclosure as Record<string, unknown>;
    sections["distrokid.json"] = {
      distrokid: {
        enabled: true,
        profile: {
          ...profile,
          ai_disclosure: {
            ...aiDisclosure,
            partial_audio_type: "vocals",
            recording_scope: "partial",
          },
        },
      },
    };

    // Then core maps the valid partial configuration to camelCase
    const ai = load(sections).integrations.distrokid.profile.aiDisclosure;
    expect(ai.recordingScope).toBe("partial");
    expect(ai.partialAudioType).toBe("vocals");
  });

  test.each([[null], [{ name: "City Nights" }], [["City Nights"]]])(
    "rejects enabled=true with non-string artist %p",
    (artist) => {
      // Given enabled distrokid with invalid artist shape
      const sections = minimalSections();
      sections["distrokid.json"] = {
        distrokid: {
          enabled: true,
          profile: { ...fullDistrokidProfile(), artist },
        },
      };

      // When/Then the profile schema rejects it before it can flow into payloads
      expect(() => load(sections)).toThrow(/artist/u);
    }
  );

  test("skips profile validation when disabled", () => {
    // Given disabled distrokid with an incomplete legacy profile
    const sections = minimalSections();
    sections["distrokid.json"] = {
      distrokid: {
        enabled: false,
        profile: {
          apple_music_credit: "Jane Doe",
          artist_name: "x",
          language: "ja",
          main_genre: "Electronic",
          songwriter: "Jane Doe",
          track_type: "Instrumental",
        },
      },
    };

    // Then it loads without validating the profile and ignores unknown legacy keys
    const dk = load(sections).integrations.distrokid;
    expect(dk.enabled).toBe(false);
    expect(dk.profile.artist).toBe("");
    expect(dk.profile.language).toBe("ja");
  });

  test.each([[null], [{ name: "City Nights" }], [["City Nights"]]])(
    "rejects enabled=false with non-string artist %p",
    (artist) => {
      // Given disabled distrokid still declares an invalid current-schema artist key
      const sections = minimalSections();
      sections["distrokid.json"] = {
        distrokid: {
          enabled: false,
          profile: { artist },
        },
      };

      // When/Then artist keeps the same string-only contract even when the integration is disabled
      expect(() => load(sections)).toThrow(/artist/u);
    }
  );

  test("rejects a non-object distrokid section", () => {
    // Given distrokid declared as an array
    const sections = minimalSections();
    sections["distrokid.json"] = { distrokid: ["not", "an", "object"] };

    // When/Then the section guard fires
    expect(() => load(sections)).toThrow(/^config:/u);
  });

  test("rejects a non-object distrokid.profile via the shared isPlainObject guard", () => {
    // Given profile declared as an array (regression guard for the superRefine
    // boundary check that delegates to internal.isPlainObject)
    const sections = minimalSections();
    sections["distrokid.json"] = {
      distrokid: { enabled: false, profile: ["not", "an", "object"] },
    };

    // When/Then the profile guard fires with the same contextual message
    expect(() => load(sections)).toThrow(
      "distrokid.profile は object でなければなりません"
    );
  });
});

// --- localizations ---------------------------------------------------------

describe("localizations", () => {
  test("falls back to [api.language] when the file is absent", () => {
    // Given no localizations.json
    const config = load(minimalSections());

    // Then exists=false and supported languages fall back to the api language
    expect(config.engagement.localizations.exists).toBe(false);
    expect(config.engagement.localizations.data).toEqual({});
    expect(config.engagement.localizations.supportedLanguages).toEqual(["ja"]);
    expect(config.engagement.localizations.defaultLanguage).toBe("");
  });

  test("reads supported + default languages when present", () => {
    // Given a localizations.json with ja/en and the content languages within it
    const sections = minimalSections();
    (sections["youtube.json"] as Record<string, unknown>).content_model = {
      languages: ["ja"],
      type: "collection",
    };
    const config = load(sections, {
      default_language: "ja",
      languages: { ja: { title_template: "x" } },
      supported_languages: ["ja", "en"],
    });

    // Then exists=true and both language lists are read
    expect(config.engagement.localizations.exists).toBe(true);
    expect(config.engagement.localizations.supportedLanguages).toEqual([
      "ja",
      "en",
    ]);
    expect(config.engagement.localizations.defaultLanguage).toBe("ja");
  });

  test("preserves the raw snake_case passthrough map in data verbatim", () => {
    // Given a localizations.json whose nested language entries use snake_case
    // keys that downstream metadata (loc-data) reads verbatim
    const sections = minimalSections();
    const localizations = {
      default_language: "ja",
      languages: {
        en: { short_title_template: "{theme} #Shorts", title_template: "{x}" },
      },
      supported_languages: ["ja", "en"],
    };

    // When the channel is loaded
    const config = load(sections, localizations);

    // Then `data` carries the JSON through untouched — the snake_case keys are
    // NOT folded to camelCase (the passthrough map bypasses snakeToCamel, so a
    // regression that wrapped it would surface here, not only downstream).
    expect(config.engagement.localizations.data).toEqual(localizations);
    const langs = (
      config.engagement.localizations.data as {
        languages: typeof localizations.languages;
      }
    ).languages;
    expect(langs.en.short_title_template).toBe("{theme} #Shorts");
  });
});
