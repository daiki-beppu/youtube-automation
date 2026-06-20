import { existsSync } from "node:fs";
import { realpath } from "node:fs/promises";
import { isAbsolute, join, resolve } from "node:path";

import { SUNO_DOCS_DIR, SUNO_PATTERNS_FILENAME } from "./schema.ts";

const COLLECTIONS_DIR = "collections";
const PLANNING_DIR = "planning";

const absoluteInputPath = (channelDir: string, inputPath: string): string =>
  isAbsolute(inputPath) ? inputPath : resolve(channelDir, inputPath);

const resolvePatternsPath = (channelDir: string, inputPath: string): string => {
  const absolutePath = absoluteInputPath(channelDir, inputPath);
  const direct = absolutePath.endsWith(SUNO_PATTERNS_FILENAME);
  if (direct) {
    return absolutePath;
  }
  return join(absolutePath, SUNO_DOCS_DIR, SUNO_PATTERNS_FILENAME);
};

const collectionDirFromPatternsPath = (patternsPath: string): string => {
  if (!patternsPath.endsWith(join(SUNO_DOCS_DIR, SUNO_PATTERNS_FILENAME))) {
    throw new Error(
      `config: patterns path must end with ${SUNO_PATTERNS_FILENAME}`
    );
  }
  return patternsPath.slice(
    0,
    -join(SUNO_DOCS_DIR, SUNO_PATTERNS_FILENAME).length - 1
  );
};

const validateCollectionLocation = (
  channelDir: string,
  collectionDir: string
): void => {
  const planningRoot = join(channelDir, COLLECTIONS_DIR, PLANNING_DIR);
  if (!collectionDir.startsWith(`${planningRoot}/`)) {
    throw new Error(
      `config: collection path must be under ${join(COLLECTIONS_DIR, PLANNING_DIR)}`
    );
  }
};

export interface ResolvedSunoPaths {
  readonly collectionDir: string;
  readonly patternsPath: string;
}

export const resolveSunoPaths = async (
  channelDir: string,
  inputPath: string
): Promise<ResolvedSunoPaths> => {
  const patternsPath = resolvePatternsPath(channelDir, inputPath);
  if (!existsSync(patternsPath)) {
    throw new Error(`config: suno patterns file not found: ${patternsPath}`);
  }
  const canonicalPatternsPath = await realpath(patternsPath);
  const collectionDir = collectionDirFromPatternsPath(canonicalPatternsPath);
  validateCollectionLocation(channelDir, collectionDir);
  return { collectionDir, patternsPath };
};
