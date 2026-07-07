import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

import {
  SUNO_DOCS_DIR,
  SUNO_PROMPTS_JSON_FILENAME,
  SUNO_PROMPTS_MD_FILENAME,
} from "./schema.ts";
import type { SunoPromptEntry } from "./schema.ts";

export interface WrittenSunoPromptFiles {
  readonly jsonPath: string;
  readonly markdownPath: string;
}

export const writeSunoPromptFiles = async (
  collectionDir: string,
  markdown: string,
  entries: readonly SunoPromptEntry[]
): Promise<WrittenSunoPromptFiles> => {
  const docsDir = join(collectionDir, SUNO_DOCS_DIR);
  await mkdir(docsDir, { recursive: true });
  const jsonPath = join(docsDir, SUNO_PROMPTS_JSON_FILENAME);
  const markdownPath = join(docsDir, SUNO_PROMPTS_MD_FILENAME);
  await writeFile(markdownPath, markdown, "utf-8");
  await writeFile(jsonPath, `${JSON.stringify(entries, null, 2)}\n`, "utf-8");
  return { jsonPath, markdownPath };
};
