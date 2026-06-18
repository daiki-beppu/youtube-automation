// Acceptance tests for Issue #827 — the config 4-bucket reorganization.
//
// The assembled `ChannelConfig` groups the 12 responsibility sections under four
// buckets (plan §4.1):
//   identity     → { meta }
//   publishing   → { content, workflow, audio, shorts, youtube }
//   engagement   → { comments, pinnedComment, playlists, localizations }
//   integrations → { distrokid, analytics }
//
// These tests pin the *grouping contract* itself (top-level shape + per-bucket
// membership + the dropped legacy flat namespaces), separate from the
// section-level behaviour exercised in config-{loader,sections,comments}.test.ts.
// Input JSON is unchanged (the buckets are an output-only regrouping), so the
// committed examples must still parse green — that is the AC #8 regression.

import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  test,
} from "bun:test";
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";

import { loadConfig, reset } from "@tayk/core/config";

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

const load = (sections: Sections, localizations?: Record<string, unknown>) => {
  const dir = setupChannel(sections, localizations);
  process.env.CHANNEL_DIR = dir;
  return loadConfig();
};

// The four buckets, sorted (the order Object.keys(...).toSorted() yields).
const BUCKETS = ["engagement", "identity", "integrations", "publishing"];

// Every legacy flat namespace that the reorg removes from the top level (AC #6).
const LEGACY_FLAT_NAMESPACES = [
  "meta",
  "content",
  "youtube",
  "audio",
  "shorts",
  "workflow",
  "comments",
  "pinnedComment",
  "playlists",
  "localizations",
  "distrokid",
  "analytics",
];

// --- top-level shape (AC #5) -----------------------------------------------

describe("ChannelConfig — 4-bucket top-level shape", () => {
  test("exposes exactly the four buckets at the top level", () => {
    // Given a minimal channel
    const config = load(minimalSections());

    // Then the assembled root carries exactly identity/publishing/engagement/
    // integrations and nothing else (the .strict() intent: no stray top key)
    expect(Object.keys(config).toSorted()).toEqual(BUCKETS);
  });

  test("drops every legacy flat section namespace from the root", () => {
    // Given a minimal channel
    const config = load(minimalSections());

    // Then none of the pre-reorg flat namespaces remain reachable at the root
    for (const legacy of LEGACY_FLAT_NAMESPACES) {
      expect(config).not.toHaveProperty(legacy);
    }
  });
});

// --- per-bucket membership (AC #6, plan §4.1) ------------------------------

describe("ChannelConfig — bucket membership", () => {
  test("identity carries only the meta section", () => {
    const config = load(minimalSections());
    expect(Object.keys(config.identity).toSorted()).toEqual(["meta"]);
  });

  test("publishing carries content/workflow/audio/shorts/youtube", () => {
    // youtube lands in publishing per plan §5 判断 A (production/publishing
    // parameters), the one section assignment the spec left implicit.
    const config = load(minimalSections());
    expect(Object.keys(config.publishing).toSorted()).toEqual([
      "audio",
      "content",
      "shorts",
      "workflow",
      "youtube",
    ]);
  });

  test("engagement carries comments/pinnedComment/playlists/localizations", () => {
    // localizations is loader-injected (it lives in config/localizations.json,
    // outside config/channel/) but is grouped under the engagement bucket.
    const config = load(minimalSections());
    expect(Object.keys(config.engagement).toSorted()).toEqual([
      "comments",
      "localizations",
      "pinnedComment",
      "playlists",
    ]);
  });

  test("integrations carries distrokid/analytics", () => {
    const config = load(minimalSections());
    expect(Object.keys(config.integrations).toSorted()).toEqual([
      "analytics",
      "distrokid",
    ]);
  });
});

// --- grouping is non-destructive -------------------------------------------

describe("ChannelConfig — buckets are a pure grouping layer", () => {
  test("section internals keep their camelCase shape inside the bucket", () => {
    // Given a minimal channel
    const config = load(minimalSections());

    // Then a field reached via its bucket is identical to the section output —
    // the bucket only nests, it does not rename or reshape section fields
    expect(config.identity.meta.youtubeHandle).toBe("@testchannel");
    expect(config.publishing.youtube.api.language).toBe("ja");
    expect(config.publishing.content.genre.primary).toBe("chiptune");
    expect(config.engagement.localizations.exists).toBe(false);
  });

  test("localizations is nested under engagement, never at the root", () => {
    // Given a channel with a localizations.json present
    const config = load(minimalSections(), {
      default_language: "ja",
      languages: { ja: { title_template: "x" } },
      supported_languages: ["ja"],
    });

    // Then it is reachable only through engagement, not as a root key
    expect(config.engagement.localizations.exists).toBe(true);
    expect(config.engagement.localizations.supportedLanguages).toEqual(["ja"]);
    expect(config).not.toHaveProperty("localizations");
  });
});

// --- examples/channel_config.example regression (AC #8) --------------------

// Repo root is three levels up from packages/core/test/ (see config-loader.test).
const repoRoot = resolve(import.meta.dir, "..", "..", "..");
const exampleDir = join(repoRoot, "examples", "channel_config.example");

// Reads the committed example channel sections (the *.json that make up a real
// config/channel/ — excluding the community.example.json post template) into a
// Sections map suitable for setupChannel.
const readExampleSections = (): Sections => {
  const sections: Sections = {};
  for (const name of readdirSync(exampleDir)) {
    if (!name.endsWith(".json") || name.endsWith(".example.json")) {
      continue;
    }
    sections[name] = JSON.parse(readFileSync(join(exampleDir, name), "utf-8"));
  }
  return sections;
};

describe("examples/channel_config.example — parses under the 4-bucket schema", () => {
  test("the example directory ships the required section files", () => {
    // Guards the precondition for the green-load assertion below.
    const names = Object.keys(readExampleSections());
    expect(names).toContain("meta.json");
    expect(names).toContain("content.json");
    expect(names).toContain("youtube.json");
  });

  test("loads green and assembles the four buckets with the example values", () => {
    // Given the committed example sections (unchanged input contract)
    const config = load(readExampleSections());

    // Then it parses into exactly the four buckets
    expect(Object.keys(config).toSorted()).toEqual(BUCKETS);

    // And the example values surface through their new bucket paths
    expect(config.identity.meta.channelName).toBe("Test Channel");
    expect(config.publishing.youtube.api.language).toBe("ja");
    expect(config.publishing.youtube.contentModel.type).toBe("collection");
    expect(config.publishing.youtube.musicEngine).toBe("suno");
  });
});
