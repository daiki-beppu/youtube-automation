import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { parseTopLevelJson } from "./parser.ts";
import { SUNO_CONFIG_FILENAME } from "./schema.ts";
import type { SunoPromptEntry } from "./schema.ts";
import type {
  ResolvedSunoConfig,
  SunoConfig,
  SunoStyleVariant,
} from "./types.ts";
import { collectVideoAnalysisPresets } from "./video-analysis.ts";

const CONFIG_DIR = "config";
const SKILLS_DIR = "skills";
const ADVANCED_JSON_KEYS = [
  "exclude_styles",
  "style_influence",
  "vocal_gender",
  "weirdness",
] as const;

const DEFAULT_SUNO_CONFIG: Record<string, unknown> = {
  auto_lyrics_structure: true,
  banned_artists: [
    "Drake",
    "Taylor Swift",
    "The Weeknd",
    "Beyonce",
    "Kanye West",
    "Eminem",
    "Rihanna",
    "Ed Sheeran",
    "Ariana Grande",
    "Justin Bieber",
    "Billie Eilish",
    "Post Malone",
    "Dua Lipa",
    "Bad Bunny",
    "Travis Scott",
    "BTS",
    "Adele",
    "Bruno Mars",
    "Lady Gaga",
    "Coldplay",
    "Imagine Dragons",
    "The Beatles",
    "Pink Floyd",
    "Led Zeppelin",
    "Radiohead",
    "Daft Punk",
    "Aphex Twin",
    "Boards of Canada",
    "Nujabes",
    "J Dilla",
  ],
  exclude_styles:
    "heavy metal, aggressive, EDM, dubstep, techno, industrial, white noise, orchestral, rain sounds, vinyl crackle, ambient noise",
  genre_line: "",
  style_char_limit: 120,
  style_influence: 95,
  tracks_per_collection: 20,
  weirdness: 10,
};

const stringValue = (data: Record<string, unknown>, key: string): string => {
  const value = data[key];
  if (value === undefined) {
    return "";
  }
  if (typeof value !== "string") {
    throw new TypeError(`config: ${key} は文字列でなければなりません`);
  }
  return value;
};

const optionalNumber = (
  data: Record<string, unknown>,
  key: string
): number | undefined => {
  const value = data[key];
  if (value === undefined) {
    return undefined;
  }
  if (typeof value !== "number") {
    throw new TypeError(`config: ${key} は数値でなければなりません`);
  }
  return value;
};

const optionalBoolean = (
  data: Record<string, unknown>,
  key: string
): boolean | undefined => {
  const value = data[key];
  if (value === undefined) {
    return undefined;
  }
  if (typeof value !== "boolean") {
    throw new TypeError(`config: ${key} は真偽値でなければなりません`);
  }
  return value;
};

const optionalStringArray = (
  data: Record<string, unknown>,
  key: string
): readonly string[] | undefined => {
  const value = data[key];
  if (value === undefined) {
    return undefined;
  }
  if (
    !Array.isArray(value) ||
    !value.every((item) => typeof item === "string")
  ) {
    throw new TypeError(`config: ${key} は文字列配列でなければなりません`);
  }
  return value;
};

const deepMergeRecords = (
  base: Record<string, unknown>,
  override: Record<string, unknown>
): Record<string, unknown> =>
  Object.fromEntries(
    [...new Set([...Object.keys(base), ...Object.keys(override)])].map(
      (key) => {
        const baseValue = base[key];
        const overrideValue = override[key];
        if (overrideValue === undefined) {
          return [key, baseValue];
        }
        if (
          typeof baseValue === "object" &&
          baseValue !== null &&
          !Array.isArray(baseValue) &&
          typeof overrideValue === "object" &&
          overrideValue !== null &&
          !Array.isArray(overrideValue)
        ) {
          return [
            key,
            deepMergeRecords(
              baseValue as Record<string, unknown>,
              overrideValue as Record<string, unknown>
            ),
          ];
        }
        return [key, overrideValue];
      }
    )
  );

const readOptionalJsonRecord = async (
  path: string
): Promise<Record<string, unknown>> => {
  if (!existsSync(path)) {
    return {};
  }
  return parseTopLevelJson(await readFile(path, "utf-8"));
};

const parseStyleVariants = (
  data: Record<string, unknown>
): ReadonlyMap<string, SunoStyleVariant> => {
  const raw = data.style_variants;
  if (raw === undefined) {
    return new Map();
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new TypeError(
      "config: style_variants は mapping でなければなりません"
    );
  }
  return new Map(
    Object.entries(raw as Record<string, unknown>).map(([key, value]) => {
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        throw new TypeError(
          `config: style_variants.${key} は mapping でなければなりません`
        );
      }
      const variant = value as Record<string, unknown>;
      return [
        key,
        {
          genreLine: stringValue(variant, "genre_line"),
          name: stringValue(variant, "name"),
        },
      ];
    })
  );
};

const buildAdvancedJsonFields = (
  override: Record<string, unknown>
): Partial<SunoPromptEntry> =>
  Object.fromEntries(
    ADVANCED_JSON_KEYS.flatMap((key) => {
      if (!(key in override)) {
        return [];
      }
      const value = override[key];
      if (key === "vocal_gender" && value === "") {
        return [];
      }
      if (
        (key === "exclude_styles" || key === "vocal_gender") &&
        typeof value !== "string"
      ) {
        throw new TypeError(`config: ${key} は文字列でなければなりません`);
      }
      if (
        (key === "style_influence" || key === "weirdness") &&
        typeof value !== "number"
      ) {
        throw new TypeError(`config: ${key} は数値でなければなりません`);
      }
      return [[key, value]];
    })
  ) as Partial<SunoPromptEntry>;

const buildSunoConfig = (
  merged: Record<string, unknown>,
  fallback: { excludeStyles: string; genreLine: string }
): SunoConfig => {
  const genreLine = stringValue(merged, "genre_line") || fallback.genreLine;
  const moodDescriptors = stringValue(merged, "mood_descriptors");
  const baseGenreLine =
    moodDescriptors.length > 0 ? `${genreLine}, ${moodDescriptors}` : genreLine;
  const excludeStyles =
    stringValue(merged, "exclude_styles") || fallback.excludeStyles;
  return {
    autoLyricsStructure:
      optionalBoolean(merged, "auto_lyrics_structure") ?? false,
    bannedArtists: optionalStringArray(merged, "banned_artists") ?? [],
    ...(excludeStyles.length > 0 ? { excludeStyles } : {}),
    genreLine: baseGenreLine,
    styleCharLimit: optionalNumber(merged, "style_char_limit") ?? 120,
    styleInfluence: optionalNumber(merged, "style_influence") ?? 50,
    styleVariants: parseStyleVariants(merged),
    tracksPerCollection: optionalNumber(merged, "tracks_per_collection"),
    vocalGender:
      typeof merged.vocal_gender === "string" ? merged.vocal_gender : undefined,
    weirdness: optionalNumber(merged, "weirdness") ?? 10,
  };
};

export const readSunoConfig = async (
  channelDir: string
): Promise<ResolvedSunoConfig> => {
  const path = join(channelDir, CONFIG_DIR, SKILLS_DIR, SUNO_CONFIG_FILENAME);
  const [override, fallback] = await Promise.all([
    readOptionalJsonRecord(path),
    collectVideoAnalysisPresets(channelDir),
  ]);
  const merged = deepMergeRecords(DEFAULT_SUNO_CONFIG, override);
  return {
    advancedJsonFields: buildAdvancedJsonFields(override),
    config: buildSunoConfig(merged, fallback),
  };
};
