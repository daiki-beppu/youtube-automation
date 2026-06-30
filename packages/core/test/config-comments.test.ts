import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
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

const load = (sections: Sections) => {
  const dir = setupChannel(sections);
  process.env.CHANNEL_DIR = dir;
  return loadConfig();
};

// Builds a comments.json wrapping a single catch-all gemini rule + the given
// generator block (mirrors the Python `_comments_with_generator` helper).
const commentsWithGenerator = (
  generator: Record<string, unknown>
): Sections => {
  const sections = minimalSections();
  sections["comments.json"] = {
    comments: {
      enabled: true,
      generator,
      rules: [
        { name: "catch_all", pattern: ".+", priority: 0, provider: "gemini" },
      ],
    },
  };
  return sections;
};

// --- defaults --------------------------------------------------------------

describe("comments — defaults", () => {
  test("absent comments.json yields a disabled codex default", () => {
    // Given no comments.json
    const config = load(minimalSections());

    // Then the section is disabled with codex generator + documented defaults
    expect(config.engagement.comments.enabled).toBe(false);
    expect(config.engagement.comments.rules).toEqual([]);
    expect(config.engagement.comments.language).toBeNull();
    expect(config.engagement.comments.generator.provider).toBe("codex");
    expect(config.engagement.comments.maxRepliesPerRun).toBe(20);
    expect(config.engagement.comments.generator.maxLength).toBe(280);
    expect(config.engagement.comments.generator.requestsPerMinute).toBe(30);
  });

  test("comments with no generator block defaults to codex", () => {
    // Given comments.json without a generator section
    const sections = minimalSections();
    sections["comments.json"] = { comments: { enabled: true, rules: [] } };

    // Then the generator defaults to codex/skip
    const { generator } = load(sections).engagement.comments;
    expect(generator.provider).toBe("codex");
    expect(generator.fallbackOnError).toBe("skip");
  });

  test("rejects null comments section", () => {
    const sections = minimalSections();
    sections["comments.json"] = { comments: null };

    expect(() => load(sections)).toThrow(/comments セクション/u);
  });
});

// --- full happy path -------------------------------------------------------

describe("comments — full configuration", () => {
  test("maps enabled comments, rules and generator to camelCase", () => {
    // Given a fully-specified comments block
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: {
        delay_between_replies_sec: 1,
        enabled: true,
        generator: {
          channel_persona: "Warm lo-fi jazz host",
          fallback_on_error: "retry",
          max_length: 300,
          model: "gemini-3.5-flash",
          provider: "gemini",
          requests_per_minute: 10,
        },
        language: "ja",
        max_replies_per_run: 5,
        ng_words: ["spam"],
        rules: [
          {
            keywords: ["こんにちは"],
            language: "ja",
            name: "greet_ja",
            priority: 10,
            provider: "gemini",
          },
        ],
      },
    };

    // Then every field is mapped through (snake JSON → camel field)
    const { comments } = load(sections).engagement;
    expect(comments.enabled).toBe(true);
    expect(comments.maxRepliesPerRun).toBe(5);
    expect(comments.delayBetweenRepliesSec).toBe(1);
    expect(comments.language).toBe("ja");
    expect(comments.ngWords).toEqual(["spam"]);
    expect(comments.rules).toEqual([]);
    const { generator } = comments;
    expect(generator.provider).toBe("gemini");
    expect(generator.model).toBe("gemini-3.5-flash");
    expect(generator.channelPersona).toBe("Warm lo-fi jazz host");
    expect(generator.maxLength).toBe(300);
    expect(generator.fallbackOnError).toBe("retry");
    expect(generator.requestsPerMinute).toBe(10);
  });
});

// --- generator validation --------------------------------------------------

describe("comments.generator — validation", () => {
  test("codex provider is valid with a null model", () => {
    // Given an explicit codex generator
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: { enabled: true, generator: { provider: "codex" }, rules: [] },
    };

    // Then it loads with model null and documented defaults
    const { generator } = load(sections).engagement.comments;
    expect(generator.provider).toBe("codex");
    expect(generator.model).toBeNull();
    expect(generator.fallbackOnError).toBe("skip");
  });

  test("rejects an unknown provider", () => {
    // Given an unsupported provider
    // When/Then load fails naming the provider key
    expect(() => load(commentsWithGenerator({ provider: "openai" }))).toThrow(
      /comments\.generator\.provider/u
    );
  });

  test("rejects gemini provider without a model", () => {
    // Given gemini with no model
    // When/Then the model-required rule fires
    expect(() => load(commentsWithGenerator({ provider: "gemini" }))).toThrow(
      /model/u
    );
  });

  test("rejects an invalid fallback_on_error", () => {
    // Given an unsupported fallback value
    const sections = commentsWithGenerator({
      fallback_on_error: "template",
      model: "gemini-3.5-flash",
      provider: "gemini",
    });

    // When/Then the fallback enum guard fires
    expect(() => load(sections)).toThrow(/fallback_on_error/u);
  });

  test("rejects a non-object generator", () => {
    // Given generator declared as a string
    const sections = minimalSections();
    sections["comments.json"] = { comments: { generator: "gemini" } };

    // When/Then the object-shape guard fires
    expect(() => load(sections)).toThrow(/comments\.generator/u);
  });
});

// --- rule validation -------------------------------------------------------

describe("comments.rules — legacy compatibility", () => {
  test("rejects non-array rules", () => {
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: { enabled: true, rules: "legacy" },
    };

    expect(() => load(sections)).toThrow(/comments\.rules/u);
  });

  test("normalizes legacy rule entries to an empty list", () => {
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: {
        enabled: true,
        rules: [
          { keywords: ["hi"] },
          { keywords: ["hi"], name: "bad_rule", provider: "openai" },
          "legacy-string",
        ],
      },
    };

    expect(load(sections).engagement.comments.rules).toEqual([]);
  });

  test("normalizes legacy rules with missing scope to an empty list (#524)", () => {
    // Given a rule with no scope
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: { enabled: true, rules: [{ keywords: ["hi"], name: "g" }] },
    };

    expect(load(sections).engagement.comments.rules).toEqual([]);
  });

  test("normalizes legacy rules with explicit scopes to an empty list (#524)", () => {
    // Given rules with explicit scopes
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: {
        enabled: true,
        rules: [
          { keywords: ["hi"], name: "top", scope: "top_level" },
          { keywords: ["bye"], name: "rep", scope: "reply" },
        ],
      },
    };

    expect(load(sections).engagement.comments.rules).toEqual([]);
  });

  test("normalizes legacy rules with invalid scope to an empty list (#524)", () => {
    // Given a rule with an unsupported scope
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: {
        enabled: true,
        rules: [{ keywords: ["hi"], name: "bad", scope: "thread" }],
      },
    };

    expect(load(sections).engagement.comments.rules).toEqual([]);
  });
});

describe("comments.language — validation", () => {
  test("rejects an empty language", () => {
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: { enabled: true, language: "" },
    };

    expect(() => load(sections)).toThrow(/comments\.language/u);
  });

  test("rejects a non-string language", () => {
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: { enabled: true, language: ["ja"] },
    };

    expect(() => load(sections)).toThrow(/comments\.language/u);
  });
});

// --- deprecated keys -------------------------------------------------------

describe("comments — deprecated section keys and legacy rule data", () => {
  test("rejects comments.generator.type", () => {
    // Given the retired generator.type key
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: { generator: { type: "template" } },
    };

    // When/Then it is rejected rather than auto-converted
    expect(() => load(sections)).toThrow(/comments\.generator\.type/u);
  });

  test("rejects comments.templates", () => {
    // Given the retired comments.templates key
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: { templates: { ja: { default: "hello" } } },
    };

    // When/Then it is rejected
    expect(() => load(sections)).toThrow(/comments\.templates/u);
  });

  test("normalizes comments.rules[].template_key as legacy rule data", () => {
    // Given a rule carrying the retired template_key
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: {
        rules: [{ keywords: ["hi"], name: "legacy", template_key: "default" }],
      },
    };

    expect(load(sections).engagement.comments.rules).toEqual([]);
  });

  test("normalizes comments.rules[].generator as legacy rule data", () => {
    // Given a rule carrying the retired generator key
    const sections = minimalSections();
    sections["comments.json"] = {
      comments: {
        rules: [{ generator: "gemini", keywords: ["hi"], name: "legacy" }],
      },
    };

    expect(load(sections).engagement.comments.rules).toEqual([]);
  });
});
