import { realpathSync, statSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";

const isNodeErrorCode = (error: unknown, code: string): boolean =>
  typeof error === "object" &&
  error !== null &&
  "code" in error &&
  error.code === code;

const isMissingPathError = (error: unknown): boolean =>
  isNodeErrorCode(error, "ENOENT") || isNodeErrorCode(error, "ENOTDIR");

const realpathIfExists = (path: string): string | undefined => {
  try {
    return realpathSync(path);
  } catch (error) {
    if (isNodeErrorCode(error, "ENOENT")) {
      return undefined;
    }
    throw error;
  }
};

const isPathInsideOrSame = (root: string, path: string): boolean => {
  const rel = relative(root, path);
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
};

const isDirectory = (path: string): boolean => {
  try {
    return statSync(path).isDirectory();
  } catch (error) {
    if (isMissingPathError(error)) {
      return false;
    }
    throw error;
  }
};

const hasChannelConfigDirectory = (path: string): boolean =>
  isDirectory(join(path, "config", "channel"));

const findChannelRootForCollection = (
  collection: string
): string | undefined => {
  let current = resolve(collection);
  for (;;) {
    if (hasChannelConfigDirectory(current)) {
      return current;
    }
    const parent = dirname(current);
    if (parent === current) {
      return undefined;
    }
    current = parent;
  }
};

export const tryFindChannelRootForCollection = (
  collection: string
): string | undefined => {
  try {
    return findChannelRootForCollection(collection);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`io: failed to inspect channel root: ${message}`, {
      cause: error,
    });
  }
};

export const resolveCollectionPathForChannel = (
  channelDir: string,
  collection: string
): string => {
  const channelRoot = resolve(channelDir);
  let canonicalChannelRoot: string;
  try {
    canonicalChannelRoot = realpathSync(channelRoot);
  } catch (error) {
    if (isNodeErrorCode(error, "ENOENT")) {
      throw new Error(`validation: channel_dir not found: ${channelRoot}`, {
        cause: error,
      });
    }
    throw error;
  }
  const collectionPath = isAbsolute(collection)
    ? resolve(collection)
    : resolve(channelRoot, collection);
  const collectionPathRelativeToRoot = relative(channelRoot, collectionPath);
  const unresolvedContainmentPath = isPathInsideOrSame(
    channelRoot,
    collectionPath
  )
    ? resolve(canonicalChannelRoot, collectionPathRelativeToRoot)
    : collectionPath;
  const containmentPath =
    realpathIfExists(collectionPath) ?? unresolvedContainmentPath;
  if (!isPathInsideOrSame(canonicalChannelRoot, containmentPath)) {
    throw new Error(
      `validation: collection escapes channel_dir: ${collection}`
    );
  }
  return collectionPath;
};
