// Shared fixtures for the config loader tests. Mirrors the Python
// `tests/test_config_loader.py` helpers (`_minimal_sections` / `_setup_channel`)
// so the TS port is verified against the same matrix of inputs.
//
// Not a `*.test.ts` file, so bun does not run it directly; it is imported by the
// config-*.test.ts suites. It deliberately avoids importing the (not-yet-built)
// config API — it only writes JSON fixtures and manages temp dirs — so it stays
// type-clean while the implementation is still pending.

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

// JSON object written verbatim as one `config/channel/<name>.json` file. Values
// are `unknown` so a test can also write a deliberately malformed top level
// (e.g. an array) to exercise the object-shape guards.
export type Sections = Record<string, unknown>;

// Temp channel dirs created during a run, torn down by `cleanupChannels()`.
const createdDirs: string[] = [];

// The minimal meta/content/youtube trio that satisfies every required key.
// Returned fresh each call so a test can mutate its copy without bleed-through.
export const minimalSections = (): Sections => ({
  "content.json": {
    descriptions: {
      hashtags: ["#ChiptuneMusic"],
      opening: "{style} {primary} for {context}",
      perfect_for: ["Studying", "Gaming"],
    },
    genre: { context: "RPG", primary: "chiptune", style: "8-bit" },
    tags: {
      base: ["chiptune music", "8-bit"],
      themes: {
        battle: ["battle music", "boss battle"],
        village: ["village music"],
      },
    },
    title: { template: "{theme} - {activity}" },
  },
  "meta.json": {
    channel: {
      name: "Test Channel",
      short: "TC",
      tagline: "Test tagline",
      url: "https://youtube.com/@testchannel",
      youtube_handle: "@testchannel",
    },
  },
  "youtube.json": {
    youtube: { category_id: "10", language: "ja", privacy_status: "public" },
  },
});

export const writeJson = (path: string, data: unknown): void => {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(data), "utf-8");
};

// Writes `sections` into `<tmp>/config/channel/` and (optionally) a
// `<tmp>/config/localizations.json`, returning the channel root to point
// `CHANNEL_DIR` at. Registers the dir for `cleanupChannels()`.
export const setupChannel = (
  sections: Sections,
  localizations?: Record<string, unknown>
): string => {
  const dir = mkdtempSync(join(tmpdir(), "config-fixture-"));
  createdDirs.push(dir);
  for (const [filename, data] of Object.entries(sections)) {
    writeJson(join(dir, "config", "channel", filename), data);
  }
  if (localizations !== undefined) {
    writeJson(join(dir, "config", "localizations.json"), localizations);
  }
  return dir;
};

// Creates a channel root whose `config/channel/` directory exists but is empty
// (the "no JSON files" boundary case).
export const setupEmptyChannel = (): string => {
  const dir = mkdtempSync(join(tmpdir(), "config-fixture-"));
  createdDirs.push(dir);
  mkdirSync(join(dir, "config", "channel"), { recursive: true });
  return dir;
};

export const cleanupChannels = (): void => {
  while (createdDirs.length > 0) {
    const dir = createdDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
};

// Snapshot/restore of CHANNEL_DIR so config tests cannot leak the env var into
// sibling test files run in the same bun process.
let savedChannelDir: string | undefined;

export const saveChannelDirEnv = (): void => {
  savedChannelDir = process.env.CHANNEL_DIR;
};

export const restoreChannelDirEnv = (): void => {
  if (savedChannelDir === undefined) {
    Reflect.deleteProperty(process.env, "CHANNEL_DIR");
  } else {
    process.env.CHANNEL_DIR = savedChannelDir;
  }
};
