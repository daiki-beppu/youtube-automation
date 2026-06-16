import { afterEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { REGISTRY } from "@youtube-automation/core/registry";
import * as sunoPromptsPublicApi from "@youtube-automation/core/suno-prompts";
import {
  generateSunoPromptsService,
  GenerateSunoInputSchema,
} from "@youtube-automation/core/suno-prompts";
import type {
  GenerateSunoInput,
  GenerateSunoOutput,
} from "@youtube-automation/core/suno-prompts";

const tmpDirs: string[] = [];

const makeTempDir = (prefix: string): string => {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  const realDir = realpathSync(dir);
  tmpDirs.push(realDir);
  return realDir;
};

afterEach(() => {
  while (tmpDirs.length > 0) {
    const dir = tmpDirs.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

const writeSunoOverride = (channelDir: string, yaml: string): void => {
  const configDir = join(channelDir, "config", "skills");
  mkdirSync(configDir, { recursive: true });
  writeFileSync(join(configDir, "suno.yaml"), yaml, "utf-8");
};

const writeVideoAnalysisPreset = (
  channelDir: string,
  preset: Record<string, string>
): void => {
  const dir = join(channelDir, "data", "video_analysis", "benchmark-a");
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, "sample.json"),
    JSON.stringify({ suno_preset: preset }),
    "utf-8"
  );
};

const writeMalformedVideoAnalysis = (channelDir: string): void => {
  const dir = join(channelDir, "data", "video_analysis", "benchmark-b");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "broken.json"), "{not-json", "utf-8");
};

const makeCollection = (channelDir: string, patternsYaml: string): string => {
  const collectionDir = join(channelDir, "collections", "planning", "test");
  const docsDir = join(collectionDir, "20-documentation");
  mkdirSync(docsDir, { recursive: true });
  writeFileSync(join(docsDir, "suno-patterns.yaml"), patternsYaml, "utf-8");
  return collectionDir;
};

const generateOk = async (
  input: GenerateSunoInput,
  channelDir: string
): Promise<GenerateSunoOutput> => {
  const result = await generateSunoPromptsService(input, {
    channelDir,
  });
  if (!result.ok) {
    throw new Error(
      `expected an ok Result, got error: ${JSON.stringify(result.error)}`
    );
  }
  return result.value;
};

const readGeneratedEntries = (collectionDir: string): unknown[] => {
  const jsonPath = join(collectionDir, "20-documentation", "suno-prompts.json");
  return JSON.parse(readFileSync(jsonPath, "utf-8")) as unknown[];
};

describe("suno-prompts public API — exports map", () => {
  test("should expose only service boundary runtime symbols", () => {
    expect(Object.keys(sunoPromptsPublicApi).toSorted()).toEqual([
      "GenerateSunoInputSchema",
      "GenerateSunoOutputSchema",
      "generateSunoPromptsService",
    ]);
  });
});

describe("suno.generate registry deps — contract", () => {
  test("should require only channelDir from adapters", () => {
    expect(REGISTRY["suno.generate"].deps).toEqual(["channelDir"]);
  });
});

describe("GenerateSunoInputSchema — contract", () => {
  test("should accept only the collection path as public input", () => {
    const raw = {
      path: "/tmp/channel/collections/planning/test",
    };

    const parsed = GenerateSunoInputSchema.parse(raw);

    expect(parsed).toEqual({
      path: "/tmp/channel/collections/planning/test",
    });
  });

  test("should reject an omitted path because adapters resolve CWD", () => {
    expect(() => GenerateSunoInputSchema.parse({})).toThrow();
  });

  test("should reject channel_dir because channelDir is a registry dependency", () => {
    expect(() =>
      GenerateSunoInputSchema.parse({
        channel_dir: "/tmp/channel",
        path: "/tmp/channel/collections/planning/test",
      })
    ).toThrow();
    expect(() =>
      GenerateSunoInputSchema.parse({
        channelDir: "/tmp/channel",
        path: "/tmp/channel/collections/planning/test",
      })
    ).toThrow();
  });

  test("should reject unknown keys", () => {
    const raw = { path: "/tmp/patterns.yaml", unexpected: true };

    expect(() => GenerateSunoInputSchema.parse(raw)).toThrow();
  });
});

describe("generateSunoPromptsService — file generation", () => {
  test("should generate markdown and json from a collection directory", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "lo-fi jazz, soft piano, warm rhodes, mellow drums, slow"',
        "auto_lyrics_structure: false",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Morning Collection"',
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        '  - name_jp: "朝霧"',
        '    name_en: "Morning Haze"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "mist over a quiet river"',
      ].join("\n")
    );

    const output = await generateOk({ path: collectionDir }, channelDir);

    const markdownPath = join(
      collectionDir,
      "20-documentation",
      "suno-prompts.md"
    );
    const jsonPath = join(
      collectionDir,
      "20-documentation",
      "suno-prompts.json"
    );
    expect(output).toMatchObject({
      entryCount: 1,
      jsonPath,
      markdownPath,
      warnings: [],
    });
    expect(existsSync(markdownPath)).toBe(true);
    expect(existsSync(jsonPath)).toBe(true);
    expect(readFileSync(markdownPath, "utf-8")).toContain(
      "# Suno Prompts — Morning Collection"
    );
    const markdown = readFileSync(markdownPath, "utf-8");
    expect(markdown).toContain("## SunoAI 推奨設定");
    expect(markdown).toContain("Style Influence");
    expect(markdown).toContain("| Instrumental | ON（インストモード） |");
    expect(markdown).toContain("**Exclude Styles:**");
    expect(markdown).toContain("**Styles:**\n```");
    expect(readGeneratedEntries(collectionDir)).toEqual([
      {
        lyrics: "",
        name: "朝霧 — Morning Haze",
        style:
          "slow, lo-fi jazz, soft piano, warm rhodes, mellow drums, slow,\nmist over a quiet river",
      },
    ]);
  });

  test("should parse single-quoted YAML scalars without preserving quote marks", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        "genre_line: 'lo-fi jazz, soft piano, warm rhodes, mellow drums, slow'",
        "auto_lyrics_structure: false",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        "title: 'Single Quote Collection'",
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        "  - name_jp: '朝霧'",
        "    name_en: 'Morning Haze'",
        "    tempo: 'slow'",
        "    scenes:",
        "      - 'mist over a quiet river'",
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    expect(readGeneratedEntries(collectionDir)).toEqual([
      {
        lyrics: "",
        name: "朝霧 — Morning Haze",
        style:
          "slow, lo-fi jazz, soft piano, warm rhodes, mellow drums, slow,\nmist over a quiet river",
      },
    ]);
  });

  test("should suffix variation names when one pattern has multiple scenes", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      'genre_line: "ambient pad, soft synth, airy textures, subtle bass, slow"\n'
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Two Variations"',
        "mode: instrumental",
        "tracks: 4",
        "patterns:",
        '  - name_jp: "灯り"',
        '    name_en: "Lantern"',
        '    tempo: "gentle"',
        "    scenes:",
        '      - "paper lanterns in the rain"',
        '      - "last train lights through glass"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const entries = readGeneratedEntries(collectionDir) as {
      name: string;
    }[];
    expect(entries.map((entry) => entry.name)).toEqual([
      "灯り — Lantern (Variation 1)",
      "灯り — Lantern (Variation 2)",
    ]);
  });

  test("should use tracks_per_collection when instrumental YAML omits tracks", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "ambient pad, soft synth, airy textures, subtle bass, slow"',
        "tracks_per_collection: 4",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Config Tracks"',
        "mode: instrumental",
        "patterns:",
        '  - name_jp: "灯り"',
        '    name_en: "Lantern"',
        '    tempo: "gentle"',
        "    scenes:",
        '      - "paper lanterns in the rain"',
        '      - "last train lights through glass"',
      ].join("\n")
    );

    const output = await generateOk({ path: collectionDir }, channelDir);

    expect(output.entryCount).toBe(2);
  });

  test("should preserve vocal lyrics from pattern YAML", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "jazzhop vocal, warm piano, brushed drums, slow"',
        "auto_lyrics_structure: false",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Vocal Lyrics"',
        "mode: vocal",
        "patterns:",
        '  - name_jp: "雨音"',
        '    name_en: "Rain Notes"',
        '    tempo: "slow"',
        "    lyrics: |",
        "      ame no oto dake",
        "      mada koko ni aru",
        "    scenes:",
        '      - "rain at a window"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as {
      lyrics: string;
    }[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.lyrics).toBe("ame no oto dake\nmada koko ni aru");
  });

  test("should include only channel override advanced fields in generated json", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "lo-fi jazz, soft piano, warm rhodes, mellow drums, slow"',
        "style_influence: 0",
        "weirdness: 0",
        'exclude_styles: ""',
        'vocal_gender: ""',
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Advanced Fields"',
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        '  - name_jp: "静寂"',
        '    name_en: "Stillness"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "a desk lamp after midnight"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as Record<
      string,
      unknown
    >[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.style_influence).toBe(0);
    expect(entry.weirdness).toBe(0);
    expect(entry.exclude_styles).toBe("");
    expect("vocal_gender" in entry).toBe(false);
  });

  test("should merge default config when channel override is absent", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeVideoAnalysisPreset(channelDir, {
      exclude_styles: "noise, harsh synth",
      genre_line: "ambient pad, soft synth, airy textures, subtle bass, slow",
    });
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Default Merge"',
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        '  - name_jp: "余白"',
        '    name_en: "Open Space"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "blank pages beside coffee"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as Record<
      string,
      unknown
    >[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.style).toBe(
      "slow, ambient pad, soft synth, airy textures, subtle bass, slow,\nblank pages beside coffee"
    );
    expect(entry.lyrics).toContain("[Instrumental]");
    expect("style_influence" in entry).toBe(false);
    expect("exclude_styles" in entry).toBe(false);
  });

  test("should use style variant genre_line when pattern declares style", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "ambient pad, soft synth, airy textures, subtle bass, slow"',
        "auto_lyrics_structure: false",
        "style_variants:",
        "  piano:",
        '    name: "solo piano"',
        '    genre_line: "solo piano, felt keys, intimate room, soft pedal, slow"',
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Variant"',
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        '  - name_jp: "鍵盤"',
        '    name_en: "Felt Keys"',
        '    tempo: "slow"',
        '    style: "piano"',
        "    scenes:",
        '      - "a quiet piano beside the window"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as {
      style: string;
    }[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.style).toBe(
      "slow, solo piano, felt keys, intimate room, soft pedal, slow,\na quiet piano beside the window"
    );
  });

  test("should use core-owned default tracks_per_collection when patterns omit tracks", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "ambient pad, soft synth, airy textures, subtle bass, slow"',
        "auto_lyrics_structure: false",
      ].join("\n")
    );
    const patterns = Array.from({ length: 10 }, (_, index) =>
      [
        `  - name_jp: "情景${index + 1}"`,
        `    name_en: "Scene ${index + 1}"`,
        '    tempo: "slow"',
        "    scenes:",
        `      - "quiet scene ${index + 1}"`,
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Core Defaults"',
        "mode: instrumental",
        "patterns:",
        ...patterns,
      ].join("\n")
    );

    const result = await generateSunoPromptsService(
      { path: collectionDir },
      { channelDir }
    );

    expect(result.ok).toBe(true);
    const entries = readGeneratedEntries(collectionDir);
    expect(entries).toHaveLength(10);
  });

  test("should infer instrumental mode from genre_line when mode is omitted", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      'genre_line: "ambient pad, soft synth, airy textures, subtle bass, slow"\n'
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Implicit Instrumental"',
        "tracks: 2",
        "patterns:",
        '  - name_jp: "静けさ"',
        '    name_en: "Still Air"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "a quiet room at dawn"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as {
      lyrics: string;
    }[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.lyrics).toContain("[Instrumental]");
  });

  test("should infer vocal mode from genre_line when mode is omitted", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      'genre_line: "jazzhop vocal, warm piano, brushed drums, slow"\n'
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Implicit Vocal"',
        "patterns:",
        '  - name_jp: "雨音"',
        '    name_en: "Rain Notes"',
        '    tempo: "slow"',
        "    lyrics: |",
        "      [Verse]",
        "      ame no oto dake",
        "    scenes:",
        '      - "rain at a window"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as {
      lyrics: string;
    }[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.lyrics).toBe("[Verse]\name no oto dake\n\n[Extended Outro]");
  });

  test("should auto-fill instrumental lyrics when auto_lyrics_structure is enabled", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "lo-fi jazz, soft piano, warm rhodes, mellow drums, slow"',
        "auto_lyrics_structure: true",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Auto Lyrics"',
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        '  - name_jp: "余白"',
        '    name_en: "Open Space"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "blank pages beside coffee"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as {
      lyrics: string;
    }[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.lyrics).toContain("[Instrumental]");
    expect(entry.lyrics).toContain("[Extended Outro]");
  });

  test("should ignore instrumental pattern lyrics before adding structure tags", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "lo-fi jazz, soft piano, warm rhodes, mellow drums, slow"',
        "auto_lyrics_structure: true",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Instrument Notes"',
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        '  - name_jp: "余白"',
        '    name_en: "Open Space"',
        '    tempo: "slow"',
        "    lyrics: |",
        "      Mixing Notes: warm tape saturation",
        "      Instrument Notes: felt piano lead",
        "    scenes:",
        '      - "blank pages beside coffee"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as {
      lyrics: string;
    }[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.lyrics).toBe("[Instrumental]\n\n[Extended Outro]");
  });

  test("should ignore instrumental pattern lyrics when auto lyrics are disabled", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "lo-fi jazz, soft piano, warm rhodes, mellow drums, slow"',
        "auto_lyrics_structure: false",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Instrument Notes Disabled"',
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        '  - name_jp: "余白"',
        '    name_en: "Open Space"',
        '    tempo: "slow"',
        "    lyrics: |",
        "      Mixing Notes: warm tape saturation",
        "      Instrument Notes: felt piano lead",
        "    scenes:",
        '      - "blank pages beside coffee"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as {
      lyrics: string;
    }[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.lyrics).toBe("");
  });

  test("should append extended outro to vocal lyrics when auto_lyrics_structure is enabled", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "jazzhop vocal, warm piano, brushed drums, slow"',
        "auto_lyrics_structure: true",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Vocal Auto Lyrics"',
        "mode: vocal",
        "patterns:",
        '  - name_jp: "雨音"',
        '    name_en: "Rain Notes"',
        '    tempo: "slow"',
        "    lyrics: |",
        "      [Verse]",
        "      ame no oto dake",
        "    scenes:",
        '      - "rain at a window"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as {
      lyrics: string;
    }[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.lyrics).toBe("[Verse]\name no oto dake\n\n[Extended Outro]");
  });

  test("should return quality warnings for long styles and early tempo words", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "slow, ambient pad, soft synth, airy textures, subtle bass"',
        "style_char_limit: 40",
        "auto_lyrics_structure: false",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Quality Warning"',
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        '  - name_jp: "警告"',
        '    name_en: "Warning"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "a very long descriptive scene with rain on glass and a quiet late night desk lamp"',
      ].join("\n")
    );

    const output = await generateOk({ path: collectionDir }, channelDir);

    expect(output.warnings).toHaveLength(2);
    expect(output.warnings[0]).toContain("5-element order");
    expect(output.warnings[1]).toContain("Style text exceeds 40 char limit");
  });

  test("should skip malformed video analysis json while collecting fallback presets", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeVideoAnalysisPreset(channelDir, {
      exclude_styles: "noise, harsh synth",
      genre_line: "ambient pad, soft synth, airy textures, subtle bass, slow",
    });
    writeMalformedVideoAnalysis(channelDir);
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Malformed Analysis"',
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        '  - name_jp: "解析"',
        '    name_en: "Analysis"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "a desk with notes from benchmark analysis"',
      ].join("\n")
    );

    await generateOk({ path: collectionDir }, channelDir);

    const [entry] = readGeneratedEntries(collectionDir) as {
      style: string;
    }[];
    expect(entry).toBeDefined();
    if (entry === undefined) {
      throw new Error("expected one generated entry");
    }
    expect(entry.style).toContain(
      "ambient pad, soft synth, airy textures, subtle bass, slow"
    );
  });
});

describe("generateSunoPromptsService — error contract", () => {
  test("should return a config error when tracks_per_collection mismatches entries", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      'genre_line: "lo-fi jazz, soft piano, warm rhodes, mellow drums, slow"\n'
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Mismatch"',
        "mode: instrumental",
        "tracks: 4",
        "patterns:",
        '  - name_jp: "朝"',
        '    name_en: "Morning"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "one scene only"',
      ].join("\n")
    );

    const result = await generateSunoPromptsService(
      { path: collectionDir },
      { channelDir }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("tracks_per_collection");
    }
  });

  test("should return a config error when style text contains a banned artist", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "lo-fi jazz like Drake"',
        "banned_artists:",
        "  - Drake",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Banned Artist"',
        "mode: instrumental",
        "tracks: 2",
        "patterns:",
        '  - name_jp: "夜"',
        '    name_en: "Night"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "quiet neon street"',
      ].join("\n")
    );

    const result = await generateSunoPromptsService(
      { path: collectionDir },
      { channelDir }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("Drake");
    }
  });

  test("should return a config error when final entry names are duplicated", async () => {
    const channelDir = makeTempDir("suno-channel-");
    writeSunoOverride(
      channelDir,
      [
        'genre_line: "lo-fi jazz, soft piano, warm rhodes, mellow drums, slow"',
        "auto_lyrics_structure: false",
      ].join("\n")
    );
    const collectionDir = makeCollection(
      channelDir,
      [
        'title: "Duplicate Names"',
        "mode: instrumental",
        "tracks: 4",
        "patterns:",
        '  - name_jp: "雨"',
        '    name_en: "Rain"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "first rain scene"',
        '  - name_jp: "雨"',
        '    name_en: "Rain"',
        '    tempo: "slow"',
        "    scenes:",
        '      - "second rain scene"',
      ].join("\n")
    );

    const result = await generateSunoPromptsService(
      { path: collectionDir },
      { channelDir }
    );

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.domain).toBe("config");
      expect(result.error.message).toContain("雨 — Rain");
    }
  });
});

describe("core registry — suno.generate entry", () => {
  test("should declare channelDir dependency and run through the registry", () => {
    const entry = REGISTRY["suno.generate"];

    expect(entry.deps).toEqual(["channelDir"]);
    expect(entry.description.length).toBeGreaterThan(0);
    expect(() =>
      entry.inputSchema.parse({ path: "/tmp/collection" })
    ).not.toThrow();
    expect(() => entry.inputSchema.parse({})).toThrow();
  });
});
