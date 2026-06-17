import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";

const PLAYLISTS_OUTPUT_PATH = ["config", "suno-playlists.json"] as const;
const COLLECTION_SUFFIX = "-collection";

export interface CapturedPlaylist {
  readonly captured_at?: string;
  readonly title: string;
  readonly url: string;
}

interface LegacyCapturedPlaylist {
  readonly captured_at?: string;
  readonly slug: string;
  readonly suno_title: string;
  readonly suno_url: string;
}

const slugify = (value: string): string =>
  value
    .trim()
    .toLowerCase()
    .replaceAll(/\s+/gu, "-")
    .replaceAll(/-+/gu, "-")
    .replaceAll(/^-|-$/gu, "");

const normalizePlaylistTitle = (
  title: string,
  prefix: string
): string | null => {
  const match = /^([^|]+)\|(.+)$/u.exec(title);
  if (match === null) {
    return null;
  }
  const [, titlePrefix, titleTheme] = match;
  if (titlePrefix === undefined || titleTheme === undefined) {
    return null;
  }
  const actualPrefix = slugify(titlePrefix);
  if (actualPrefix !== slugify(prefix)) {
    return null;
  }
  const theme = slugify(titleTheme);
  return theme.length > 0 ? `${actualPrefix}-${theme}` : null;
};

const escapeRegExp = (value: string): string =>
  value.replaceAll(/[.*+?^${}()|[\]\\]/gu, "\\$&");

const prefixPattern = (prefix: string): string =>
  prefix
    .trim()
    .split(/[\s-]+/u)
    .filter((segment) => segment.length > 0)
    .map(escapeRegExp)
    .join("[\\s-]+");

const playlistsOutputPath = (root: string): string =>
  join(root, ...PLAYLISTS_OUTPUT_PATH);

const isLegacyPlaylist = (item: unknown): item is LegacyCapturedPlaylist =>
  typeof item === "object" &&
  item !== null &&
  typeof (item as LegacyCapturedPlaylist).slug === "string" &&
  typeof (item as LegacyCapturedPlaylist).suno_title === "string" &&
  typeof (item as LegacyCapturedPlaylist).suno_url === "string";

const legacyPlaylistsToDict = (
  items: readonly unknown[]
): Record<string, CapturedPlaylist> =>
  Object.fromEntries(
    items.filter(isLegacyPlaylist).map((item) => [
      item.slug,
      {
        captured_at: item.captured_at,
        title: item.suno_title,
        url: item.suno_url,
      },
    ])
  );

const readExistingPlaylists = (
  path: string
): Record<string, CapturedPlaylist> => {
  if (!existsSync(path)) {
    return {};
  }
  const parsed: unknown = JSON.parse(readFileSync(path, "utf-8"));
  if (Array.isArray(parsed)) {
    return legacyPlaylistsToDict(parsed);
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("validation: suno-playlists.json must be an object");
  }
  return parsed as Record<string, CapturedPlaylist>;
};

const atomicWriteJson = (path: string, data: unknown): void => {
  const tmp = join(
    dirname(path),
    `.suno-playlists-${process.pid}-${Date.now()}.json`
  );
  try {
    writeFileSync(tmp, JSON.stringify(data, null, 2), "utf-8");
    renameSync(tmp, path);
  } catch (error) {
    rmSync(tmp, { force: true });
    throw error;
  }
};

const collectionNameWithoutSuffix = (collectionId: string): string =>
  collectionId.endsWith(COLLECTION_SUFFIX)
    ? collectionId.slice(0, -COLLECTION_SUFFIX.length)
    : collectionId;

const collectionNameWithoutDate = (collectionId: string): string => {
  const name = collectionNameWithoutSuffix(collectionId);
  const [first, rest] = name.split(/-(.*)/su);
  if (first !== undefined && rest !== undefined && /^\d+$/u.test(first)) {
    return rest;
  }
  return name;
};

const deriveCollectionTheme = (
  collectionId: string,
  prefix: string
): string | null => {
  const name = collectionNameWithoutDate(collectionId);
  const pattern = prefixPattern(prefix);
  if (pattern.length === 0) {
    return null;
  }
  const prefixMatch = new RegExp(`^${pattern}-`, "iu").exec(name);
  if (prefixMatch !== null) {
    return name.slice(prefixMatch[0].length);
  }
  const [, theme] = name.split(/-(.*)/su);
  return theme ?? null;
};

export const deriveCollectionSlug = (
  collectionId: string,
  prefix: string
): string | null => {
  const normalizedPrefix = slugify(prefix);
  const theme = deriveCollectionTheme(collectionId, prefix);
  if (normalizedPrefix.length === 0 || theme === null) {
    return null;
  }
  const themeSlug = slugify(theme);
  return themeSlug.length > 0 ? `${normalizedPrefix}-${themeSlug}` : null;
};

export const deriveCollectionPlaylistName = (
  collectionId: string,
  prefix: string
): string | null => {
  const normalizedPrefix = slugify(prefix);
  const theme = deriveCollectionTheme(collectionId, prefix)?.trim();
  if (
    normalizedPrefix.length === 0 ||
    theme === undefined ||
    theme.length === 0
  ) {
    return null;
  }
  return `${normalizedPrefix} | ${theme}`;
};

export const readMappedPlaylistSlugs = (root: string): Set<string> =>
  new Set(Object.keys(readExistingPlaylists(playlistsOutputPath(root))));

export const writeCapturedPlaylists = (
  root: string,
  prefix: string,
  items: readonly CapturedPlaylist[]
): { path: string; written: number } => {
  const path = playlistsOutputPath(root);
  mkdirSync(join(root, "config"), { recursive: true });
  const existing = readExistingPlaylists(path);
  const updates = Object.fromEntries(
    items
      .map(
        (item) => [normalizePlaylistTitle(item.title, prefix), item] as const
      )
      .filter((entry): entry is [string, CapturedPlaylist] => entry[0] !== null)
  );
  atomicWriteJson(path, { ...existing, ...updates });
  return { path, written: Object.keys(updates).length };
};

export const parseCapturedPlaylists = async (
  request: Request
): Promise<CapturedPlaylist[] | null> => {
  let parsed: unknown;
  try {
    parsed = await request.json();
  } catch {
    return null;
  }
  if (!Array.isArray(parsed)) {
    return null;
  }
  if (
    !parsed.every(
      (item) =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as CapturedPlaylist).title === "string" &&
        typeof (item as CapturedPlaylist).url === "string"
    )
  ) {
    return null;
  }
  return parsed as CapturedPlaylist[];
};
