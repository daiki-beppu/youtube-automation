// トラック名サニタイズと構造化タイムスタンプ整形（metadata_generator.py の
// `_extract_pattern_key` / `_clean_track_title` / `generate_timestamps` +
// `format_timestamps_text` の pure 部分）。
//
// afinfo / workflow-state.json への I/O は呼び出し側の責務とし、ここでは解析済みの
// トラック列とテーマ表示名・装飾を引数で受け取る純関数として移植する。

import { titleCase } from "../config/content.ts";

export type PatternKey = "a" | "b" | "c" | "d";

// `pattern-b1-` のような variation 接尾辞も許容する。末尾 `(?![a-z])` で
// `pattern-e-`（範囲外）や `pattern-ab-`（2 文字目あり）を明示的に reject する。
const PATTERN_KEY_RE = /^\d+-pattern-([a-d])(?![a-z])/iu;

/** ファイル名から pattern_key（'a'|'b'|'c'|'d'）を抽出する。マッチしなければ null。 */
export const extractPatternKey = (filename: string): PatternKey | null => {
  const match = PATTERN_KEY_RE.exec(filename);
  const letter = match?.[1];
  if (letter === undefined) {
    return null;
  }
  return letter.toLowerCase() as PatternKey;
};

// 冠詞・前置詞は小文字維持（先頭語は常に大文字）。Python 版 SMALL_WORDS と同一。
const SMALL_WORDS = new Set([
  "a",
  "an",
  "the",
  "at",
  "by",
  "in",
  "of",
  "on",
  "to",
  "and",
  "but",
  "or",
  "for",
  "nor",
]);

/** ファイル名から表示用トラックタイトルへサニタイズする。 */
export const cleanTrackTitle = (filename: string): string => {
  let title = filename
    .replace(/^8bit\s+/iu, "")
    .replace(/^\d{2}-/u, "")
    .replace(/^pattern-[a-z]\d?-/iu, "")
    .replace(/\s*\([^)]+\)\s*$/u, "")
    .replaceAll("_", " ")
    .replaceAll("-", " ");
  title = title.split(/\s+/u).filter(Boolean).join(" ");
  const words = titleCase(title).split(" ");
  return words
    .map((word, index) =>
      index > 0 && SMALL_WORDS.has(word.toLowerCase())
        ? word.toLowerCase()
        : word
    )
    .join(" ");
};

/** タイムスタンプ整形の入力トラック（解析済み）。 */
export interface TimestampTrack {
  readonly patternKey?: string | null;
  readonly timestamp: string;
  readonly title: string;
}

/** テーマ見出し行の装飾（`section_headers.theme_inline` 由来）。 */
export interface ThemeInline {
  readonly prefix: string;
  readonly suffix: string;
}

/**
 * 構造化トラック列を YouTube 概要欄用テキストへ整形する。
 *
 * pattern_key の切り替わりごとにテーマ見出し行を挿入する。見出し行は
 * YouTube チャプター仕様（timestamps が strictly ascending）を壊さないよう
 * leading timestamp を載せない。トラックが無ければ空文字。
 */
export const buildTimestampsText = (
  tracks: readonly TimestampTrack[],
  themeNames: Readonly<Record<string, string>>,
  themeInline: ThemeInline
): string => {
  if (tracks.length === 0) {
    return "";
  }
  const lines: string[] = [];
  let lastPattern: string | null = null;
  for (const track of tracks) {
    const pattern = track.patternKey ?? null;
    if (pattern && pattern !== lastPattern) {
      const label = themeNames[pattern] ?? `Pattern ${pattern.toUpperCase()}`;
      lines.push(`${themeInline.prefix}${label}${themeInline.suffix}`);
      lastPattern = pattern;
    }
    lines.push(`${track.timestamp} ${track.title}`);
  }
  return lines.join("\n");
};
