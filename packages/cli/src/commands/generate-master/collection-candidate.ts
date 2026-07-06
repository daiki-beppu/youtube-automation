import { statSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";

interface CollectionCandidateInput {
  channel_dir?: string;
}

interface CollectionCandidateOptions {
  channelDir?: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isNodeErrorCode = (error: unknown, code: string): boolean =>
  isRecord(error) && error.code === code;

const isDirectory = (path: string): boolean => {
  try {
    return statSync(path).isDirectory();
  } catch (error) {
    if (isNodeErrorCode(error, "ENOENT")) {
      return false;
    }
    throw error;
  }
};

const resolveCollectionCandidate = (
  input: CollectionCandidateInput,
  value: string,
  options: CollectionCandidateOptions
): string | undefined => {
  if (isAbsolute(value)) {
    return resolve(value);
  }
  const channelDir = input.channel_dir ?? options.channelDir;
  return channelDir === undefined || channelDir.length === 0
    ? undefined
    : resolve(channelDir, value);
};

export const isCollectionCandidate = (
  input: CollectionCandidateInput,
  value: string,
  options: CollectionCandidateOptions
): boolean => {
  const candidate = resolveCollectionCandidate(input, value, options);
  return candidate !== undefined && isDirectory(candidate);
};

export const isPathLikeCollectionToken = (value: string): boolean =>
  value === "." ||
  value === ".." ||
  value.startsWith("./") ||
  value.startsWith("../") ||
  value.includes("/") ||
  value.includes("\\");
