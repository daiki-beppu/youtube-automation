import type { SunoPromptEntry } from "./schema.ts";

export interface SunoConfig {
  readonly autoLyricsStructure: boolean;
  readonly bannedArtists: readonly string[];
  readonly excludeStyles?: string;
  readonly genreLine: string;
  readonly styleCharLimit: number;
  readonly styleInfluence: number;
  readonly styleVariants: ReadonlyMap<string, SunoStyleVariant>;
  readonly tracksPerCollection?: number;
  readonly vocalGender?: string;
  readonly weirdness: number;
}

export interface SunoStyleVariant {
  readonly genreLine: string;
  readonly name: string;
}

export interface ResolvedSunoConfig {
  readonly advancedJsonFields: Partial<SunoPromptEntry>;
  readonly config: SunoConfig;
}

export interface BuildEntriesResult {
  readonly entries: SunoPromptEntry[];
  readonly mode: "instrumental" | "vocal";
  readonly warnings: string[];
}
