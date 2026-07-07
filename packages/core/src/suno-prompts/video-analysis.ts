import { existsSync } from "node:fs";
import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";

const DATA_DIR = "data";
const TOP_GENRE_PHRASES = 8;
const VIDEO_ANALYSIS_DIR = "video_analysis";

const splitCsv = (value: string): string[] =>
  value
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);

const isNodeReadError = (error: unknown): boolean =>
  error instanceof Error && "code" in error;

const readVideoAnalysisJson = async (path: string): Promise<unknown> => {
  try {
    return JSON.parse(await readFile(path, "utf-8")) as unknown;
  } catch (error) {
    if (error instanceof SyntaxError || isNodeReadError(error)) {
      return undefined;
    }
    throw error;
  }
};

export const collectVideoAnalysisPresets = async (
  channelDir: string
): Promise<{ excludeStyles: string; genreLine: string }> => {
  const base = join(channelDir, DATA_DIR, VIDEO_ANALYSIS_DIR);
  if (!existsSync(base)) {
    return { excludeStyles: "", genreLine: "" };
  }

  const excludeStyles = new Map<string, null>();
  const genreCounts = new Map<string, number>();
  const slugDirs = await readdir(base, { withFileTypes: true });
  for (const slugDir of slugDirs.filter((item) => item.isDirectory())) {
    const dir = join(base, slugDir.name);
    const files = await readdir(dir, { withFileTypes: true });
    for (const file of files.filter(
      (item) => item.isFile() && item.name.endsWith(".json")
    )) {
      const data = await readVideoAnalysisJson(join(dir, file.name));
      if (typeof data !== "object" || data === null || Array.isArray(data)) {
        continue;
      }
      const preset = (data as Record<string, unknown>).suno_preset;
      if (
        typeof preset !== "object" ||
        preset === null ||
        Array.isArray(preset)
      ) {
        continue;
      }
      const record = preset as Record<string, unknown>;
      for (const phrase of splitCsv(
        typeof record.genre_line === "string" ? record.genre_line : ""
      )) {
        genreCounts.set(phrase, (genreCounts.get(phrase) ?? 0) + 1);
      }
      for (const phrase of splitCsv(
        typeof record.exclude_styles === "string" ? record.exclude_styles : ""
      )) {
        excludeStyles.set(phrase, null);
      }
    }
  }

  const genreLine = [...genreCounts.entries()]
    .toSorted((a, b) => b[1] - a[1])
    .slice(0, TOP_GENRE_PHRASES)
    .map(([phrase]) => phrase)
    .join(", ");
  return { excludeStyles: [...excludeStyles.keys()].join(", "), genreLine };
};
