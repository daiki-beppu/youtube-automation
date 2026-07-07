import type { SunoPattern, SunoPatternsFile } from "./parser.ts";
import { SunoPromptEntriesSchema } from "./schema.ts";
import type { SunoPromptEntry } from "./schema.ts";
import type {
  BuildEntriesResult,
  ResolvedSunoConfig,
  SunoConfig,
} from "./types.ts";

const INSTRUMENTAL_LYRICS = "[Instrumental]\n\n[Extended Outro]";
const INSTRUMENTAL_TAG_PATTERN = /\[Instrumental\]/iu;
const EXTENDED_OUTRO_TAG_PATTERN = /\[Extended Outro\]/iu;
const OUTRO_END_PATTERN = /\[(Extended )?Outro\]\s*$/iu;
const STYLE_SEPARATOR = ",\n";
const TITLE_SEPARATOR = " — ";
const TEMPO_WORDS = [
  "very slow",
  "slow",
  "gentle",
  "moderate",
  "lively",
  "fast",
  "uptempo",
  "downtempo",
] as const;
const VOCAL_KEYWORDS = ["vocals", "vocal", "singing", "rap", "sings", "sung"];

const buildEntryName = (pattern: SunoPattern, sceneIndex: number): string => {
  const base = `${pattern.nameJp}${TITLE_SEPARATOR}${pattern.nameEn}`;
  return pattern.scenes.length > 1
    ? `${base} (Variation ${sceneIndex + 1})`
    : base;
};

const withAdvancedFields = (
  entry: SunoPromptEntry,
  advancedJsonFields: Partial<SunoPromptEntry>
): SunoPromptEntry => ({
  ...entry,
  ...advancedJsonFields,
});

const applyAutoLyricsStructure = (lyrics: string, isVocal: boolean): string => {
  if (lyrics === "") {
    return isVocal ? lyrics : INSTRUMENTAL_LYRICS;
  }

  let structured = lyrics.trim();
  if (!isVocal) {
    if (!INSTRUMENTAL_TAG_PATTERN.test(structured)) {
      structured = `[Instrumental]\n\n${structured}`;
    }
    if (!EXTENDED_OUTRO_TAG_PATTERN.test(structured)) {
      structured = `${structured}\n\n[Extended Outro]`;
    }
    return structured;
  }

  if (!OUTRO_END_PATTERN.test(structured)) {
    structured = `${structured}\n\n[Extended Outro]`;
  }
  return structured;
};

const resolveLyrics = (
  patternLyrics: string,
  config: SunoConfig,
  isVocal: boolean
): string => {
  const rawLyrics = isVocal ? patternLyrics : "";
  return config.autoLyricsStructure
    ? applyAutoLyricsStructure(rawLyrics, isVocal)
    : rawLyrics;
};

const buildEntry = (
  pattern: SunoPattern,
  scene: string,
  sceneIndex: number,
  config: SunoConfig,
  advancedJsonFields: Partial<SunoPromptEntry>,
  mode: "instrumental" | "vocal"
): SunoPromptEntry => {
  const variant =
    pattern.style === undefined
      ? undefined
      : config.styleVariants.get(pattern.style);
  const genreLine = variant?.genreLine ?? config.genreLine;
  const style = `${pattern.tempo}, ${genreLine}${STYLE_SEPARATOR}${scene}`;
  const isVocal = mode === "vocal";
  const lyrics = resolveLyrics(pattern.lyrics, config, isVocal);
  const entry: SunoPromptEntry = {
    lyrics,
    name: buildEntryName(pattern, sceneIndex),
    style,
  };
  return withAdvancedFields(entry, advancedJsonFields);
};

const validateTrackCount = (tracks: number, entryCount: number): void => {
  if (Math.ceil(tracks / 2) !== entryCount) {
    throw new Error(
      `config: tracks_per_collection と生成エントリ数が一致しません: tracks=${tracks}, entries=${entryCount}`
    );
  }
};

const resolveInstrumentalTracks = (
  patternsFile: SunoPatternsFile,
  config: SunoConfig
): number => {
  const tracks = patternsFile.tracks ?? config.tracksPerCollection;
  if (tracks === undefined) {
    throw new Error(
      "config: instrumental mode requires tracks or tracks_per_collection"
    );
  }
  return tracks;
};

const escapeRegExp = (value: string): string =>
  value.replaceAll(/[.*+?^${}()|[\]\\]/gu, "\\$&");

const validateBannedArtists = (
  entries: readonly SunoPromptEntry[],
  bannedArtists: readonly string[]
): void => {
  for (const artist of bannedArtists) {
    const pattern = new RegExp(`\\b${escapeRegExp(artist)}\\b`, "iu");
    if (entries.some((entry) => pattern.test(entry.style))) {
      throw new Error(
        `config: banned artist is included in style text: ${artist}`
      );
    }
  }
};

const validateUniqueEntryNames = (
  entries: readonly SunoPromptEntry[]
): void => {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const entry of entries) {
    if (seen.has(entry.name)) {
      duplicates.add(entry.name);
    }
    seen.add(entry.name);
  }
  if (duplicates.size > 0) {
    throw new Error(
      `config: entry names must be unique: ${[...duplicates].toSorted().join(", ")}`
    );
  }
};

const validateStyleCharLimit = (
  style: string,
  limit: number
): readonly string[] =>
  style.length > limit
    ? [
        `Style text exceeds ${limit} char limit (${style.length} chars): ${style.slice(0, 80)}...`,
      ]
    : [];

const validateFiveElementOrder = (genreLine: string): readonly string[] => {
  const lowerGenreLine = genreLine.toLowerCase();
  const threshold = Math.max(Math.floor(lowerGenreLine.length / 3), 10);
  const tempoWord = TEMPO_WORDS.find((word) => {
    const index = lowerGenreLine.indexOf(word);
    return index !== -1 && index < threshold;
  });
  return tempoWord === undefined
    ? []
    : [
        `Tempo word '${tempoWord}' appears early in Style text (position ${lowerGenreLine.indexOf(
          tempoWord
        )}). 5-element order: genre -> acoustics -> key instrument -> rhythm/bass -> tempo`,
      ];
};

const buildQualityWarnings = (
  entries: readonly SunoPromptEntry[],
  config: SunoConfig
): string[] => [
  ...validateFiveElementOrder(config.genreLine),
  ...entries.flatMap((entry) =>
    validateStyleCharLimit(entry.style, config.styleCharLimit)
  ),
];

const resolveMode = (
  patternsFile: SunoPatternsFile,
  config: SunoConfig
): "instrumental" | "vocal" => {
  if (patternsFile.mode !== undefined) {
    return patternsFile.mode;
  }
  const lowerGenreLine = config.genreLine.toLowerCase();
  return VOCAL_KEYWORDS.some((keyword) => lowerGenreLine.includes(keyword))
    ? "vocal"
    : "instrumental";
};

export const buildEntries = (
  patternsFile: SunoPatternsFile,
  resolvedConfig: ResolvedSunoConfig
): BuildEntriesResult => {
  const { advancedJsonFields, config } = resolvedConfig;
  const mode = resolveMode(patternsFile, config);
  const entries = patternsFile.patterns.flatMap((pattern) =>
    pattern.scenes.map((scene, index) =>
      buildEntry(pattern, scene, index, config, advancedJsonFields, mode)
    )
  );
  if (mode === "instrumental") {
    validateTrackCount(
      resolveInstrumentalTracks(patternsFile, config),
      entries.length
    );
  }
  validateBannedArtists(entries, config.bannedArtists);
  validateUniqueEntryNames(entries);
  return {
    entries: SunoPromptEntriesSchema.parse(entries),
    mode,
    warnings: buildQualityWarnings(entries, config),
  };
};
