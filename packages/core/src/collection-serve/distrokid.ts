import {
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { basename, dirname, extname, join, resolve, sep } from "node:path";

import { CollectionPaths } from "../paths.ts";

const DISTROKID_DIR = "30-distrokid";
const METADATA_FILE = "metadata.md";
const SPEC_FILE = "spec.json";
const COVER_FILE = "cover_art_3000.jpg";
const RELEASES_FILE = join("config", "distrokid-releases.json");

interface DistrokidConfig {
  readonly enabled: boolean;
  readonly profile: unknown;
}

type ReleasedDiscs = ReadonlySet<string>;

export interface DistrokidCollectionSummary {
  readonly album_title: string;
  readonly collection_id: string;
  readonly disc: string;
  readonly name: string;
  readonly released: boolean;
  readonly track_count: number;
}

type NodeError = Error & { code?: string };

const isNotFound = (error: unknown): boolean =>
  typeof error === "object" &&
  error !== null &&
  (error as NodeError).code === "ENOENT";

const kebabToTitle = (value: string): string =>
  value
    .split("-")
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");

const isMp3 = (name: string): boolean => extname(name).toLowerCase() === ".mp3";

const isMeaningfulMetadataValue = (value: string | null): value is string =>
  value !== null && !/^<!--.*-->$/u.test(value);

const readJsonObject = async (
  path: string
): Promise<Record<string, unknown>> => {
  const raw = await readFile(path, "utf-8");
  const parsed: unknown = JSON.parse(raw);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new TypeError(`validation: JSON object expected: ${path}`);
  }
  return parsed as Record<string, unknown>;
};

export const findDistrokidDiscs = async (
  collectionDir: string
): Promise<string[]> => {
  const distrokidDir = join(collectionDir, DISTROKID_DIR);
  let entries;
  try {
    entries = await readdir(distrokidDir, { withFileTypes: true });
  } catch (error) {
    if (isNotFound(error)) {
      return [];
    }
    throw error;
  }
  const discs = await Promise.all(
    entries
      .filter((entry) => entry.isDirectory())
      .map(async (entry) => {
        const files = await readdir(join(distrokidDir, entry.name));
        return files.some(isMp3) ? entry.name : null;
      })
  );
  return discs.filter((disc): disc is string => disc !== null).toSorted();
};

const distrokidReleasesOutputPath = (root: string): string =>
  join(root, RELEASES_FILE);

export const readReleasedDiscs = async (
  root: string
): Promise<ReleasedDiscs> => {
  try {
    return new Set(
      Object.keys(await readJsonObject(distrokidReleasesOutputPath(root)))
    );
  } catch (error) {
    if (isNotFound(error) || error instanceof SyntaxError) {
      return new Set();
    }
    throw error;
  }
};

export const writeDistrokidRelease = async (
  root: string,
  collectionId: string,
  disc: string,
  albumTitle: string
): Promise<{ path: string; recorded: true }> => {
  const target = distrokidReleasesOutputPath(root);
  await mkdir(join(root, "config"), { recursive: true });
  let data: Record<string, unknown>;
  try {
    data = await readJsonObject(target);
  } catch (error) {
    if (isNotFound(error) || error instanceof SyntaxError) {
      data = {};
    } else {
      throw error;
    }
  }
  const updated = {
    ...data,
    [`${collectionId}/${disc}`]: {
      album_title: albumTitle,
      recorded_at: new Date().toISOString(),
    },
  };
  const tmp = join(
    dirname(target),
    `.distrokid-releases-${process.pid}-${Date.now()}.json`
  );
  try {
    await writeFile(tmp, JSON.stringify(updated, null, 2), "utf-8");
    await rename(tmp, target);
  } catch (error) {
    await rm(tmp, { force: true });
    throw error;
  }
  return { path: target, recorded: true };
};

const readMetadataAlbumTitle = async (
  collectionDir: string,
  disc: string
): Promise<string | null> => {
  try {
    const text = await readFile(
      join(collectionDir, DISTROKID_DIR, disc, METADATA_FILE),
      "utf-8"
    );
    const row = text
      .split(/\r?\n/u)
      .map((line) => line.trim())
      .find((line) => line.startsWith("| アルバムタイトル |"));
    const value = row?.split("|")[2]?.trim();
    return value === undefined || value.length === 0 ? null : value;
  } catch (error) {
    if (isNotFound(error)) {
      return null;
    }
    throw error;
  }
};

const splitMarkdownRow = (line: string): string[] | null => {
  if (!line.startsWith("|") || !line.endsWith("|")) {
    return null;
  }
  const cells = line
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());
  return cells.length < 3 ? null : cells;
};

const stripInlineCode = (value: string): string =>
  value.startsWith("`") && value.endsWith("`") ? value.slice(1, -1) : value;

const readMetadataTrackTitles = async (
  collectionDir: string,
  disc: string
): Promise<Map<string, string>> => {
  try {
    const text = await readFile(
      join(collectionDir, DISTROKID_DIR, disc, METADATA_FILE),
      "utf-8"
    );
    const rows = text
      .split(/\r?\n/u)
      .map((line) => splitMarkdownRow(line.trim()))
      .filter((cells): cells is string[] => cells !== null);
    return new Map(
      rows.flatMap((cells) => {
        const [number, title, filename] = cells;
        if (
          number === undefined ||
          title === undefined ||
          filename === undefined ||
          !/^\d+$/u.test(number) ||
          title.length === 0
        ) {
          return [];
        }
        const normalizedFilename = stripInlineCode(filename);
        return normalizedFilename.length === 0
          ? []
          : [[normalizedFilename, title]];
      })
    );
  } catch (error) {
    if (isNotFound(error)) {
      return new Map();
    }
    throw error;
  }
};

const readSpecDiscEntry = async (
  collectionDir: string,
  disc: string
): Promise<Record<string, unknown> | null> => {
  try {
    const spec = await readJsonObject(
      join(collectionDir, DISTROKID_DIR, SPEC_FILE)
    );
    const { discs } = spec;
    if (!Array.isArray(discs)) {
      return null;
    }
    const entry = discs.find(
      (item): item is Record<string, unknown> =>
        typeof item === "object" &&
        item !== null &&
        (item as Record<string, unknown>).slug === disc
    );
    return entry ?? null;
  } catch (error) {
    if (isNotFound(error)) {
      return null;
    }
    throw error;
  }
};

const readDiscAlbumTitle = async (
  collectionDir: string,
  disc: string
): Promise<string> => {
  const entry = await readSpecDiscEntry(collectionDir, disc);
  const specTitle = entry?.album_title;
  if (typeof specTitle === "string" && specTitle.length > 0) {
    return specTitle;
  }
  const metadataTitle = await readMetadataAlbumTitle(collectionDir, disc);
  return isMeaningfulMetadataValue(metadataTitle)
    ? metadataTitle
    : kebabToTitle(disc);
};

const readIndexAlbumTitle = async (
  collectionDir: string,
  disc: string
): Promise<string> => {
  try {
    return await readDiscAlbumTitle(collectionDir, disc);
  } catch (error) {
    if (error instanceof SyntaxError) {
      return (
        (await readMetadataAlbumTitle(collectionDir, disc)) ??
        kebabToTitle(disc)
      );
    }
    throw error;
  }
};

export const buildDistrokidCollectionsIndex = async (
  root: string,
  releasedDiscs: ReleasedDiscs
): Promise<DistrokidCollectionSummary[]> => {
  const entries = await readdir(root, { withFileTypes: true });
  const collectionIds = entries
    .filter(
      (entry) => entry.isDirectory() && entry.name.endsWith("-collection")
    )
    .map((entry) => entry.name)
    .toSorted();
  const rows = await Promise.all(
    collectionIds.map(async (collectionId) => {
      const collectionDir = join(root, collectionId);
      const paths = new CollectionPaths(collectionDir);
      const discs = await findDistrokidDiscs(collectionDir);
      return Promise.all(
        discs.map(async (disc): Promise<DistrokidCollectionSummary> => {
          const discDir = join(collectionDir, DISTROKID_DIR, disc);
          const files = await readdir(discDir);
          return {
            album_title: await readIndexAlbumTitle(collectionDir, disc),
            collection_id: collectionId,
            disc,
            name: paths.collectionName,
            released: releasedDiscs.has(`${collectionId}/${disc}`),
            track_count: files.filter(isMp3).length,
          };
        })
      );
    })
  );
  return rows.flat();
};

const relativeAssetPath = (
  root: string,
  target: string,
  prefix: string
): string => {
  const rel = target
    .slice(resolve(root).length + 1)
    .split(sep)
    .join("/");
  return `${prefix}${rel}`;
};

const resolveAssetPath = async (
  collectionDir: string,
  relpath: string
): Promise<string | null> => {
  const root = resolve(collectionDir);
  const candidate = resolve(root, relpath);
  if (candidate !== root && !candidate.startsWith(`${root}${sep}`)) {
    return null;
  }
  try {
    const info = await stat(candidate);
    return info.isFile() ? candidate : null;
  } catch (error) {
    if (isNotFound(error)) {
      return null;
    }
    throw error;
  }
};

const readReleaseDate = async (
  collectionDir: string
): Promise<string | null> => {
  try {
    const state = await readJsonObject(
      join(collectionDir, "workflow-state.json")
    );
    const { planning } = state;
    if (
      typeof planning !== "object" ||
      planning === null ||
      Array.isArray(planning)
    ) {
      return null;
    }
    const raw = (planning as Record<string, unknown>).publish_target_at;
    if (raw === undefined || raw === null) {
      return null;
    }
    if (typeof raw !== "string") {
      throw new TypeError(
        "validation: planning.publish_target_at must be a string"
      );
    }
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) {
      throw new TypeError(
        "validation: planning.publish_target_at must be ISO 8601"
      );
    }
    return raw.includes("T") ? date.toISOString().slice(0, 10) : raw;
  } catch (error) {
    if (isNotFound(error)) {
      return null;
    }
    throw error;
  }
};

const titleMapFromSpec = (
  entry: Record<string, unknown> | null
): Map<string, string> => {
  const tracks = entry?.tracks;
  if (!Array.isArray(tracks)) {
    return new Map();
  }
  return new Map(
    tracks.flatMap((track) => {
      if (typeof track !== "object" || track === null) {
        return [];
      }
      const row = track as Record<string, unknown>;
      return typeof row.filename === "string" && typeof row.title === "string"
        ? [[row.filename, row.title]]
        : [];
    })
  );
};

const titleMapForDisc = async (
  collectionDir: string,
  disc: string | undefined
): Promise<Map<string, string>> => {
  if (disc === undefined) {
    return new Map();
  }
  const entry = await readSpecDiscEntry(collectionDir, disc);
  const specTitles = titleMapFromSpec(entry);
  return specTitles.size > 0
    ? specTitles
    : readMetadataTrackTitles(collectionDir, disc);
};

const resolveExplicitDistrokidSource = (
  collectionDir: string,
  source: string
): { disc: string; sourceDir: string } => {
  const root = resolve(collectionDir);
  const sourceDir = resolve(root, source);
  if (sourceDir === root || !sourceDir.startsWith(`${root}${sep}`)) {
    throw new Error(
      `validation: distrokid_source escapes collection: ${source}`
    );
  }
  return { disc: basename(sourceDir), sourceDir };
};

export const buildDistrokidReleasePayload = async (
  collectionDir: string,
  distrokid: DistrokidConfig,
  options: {
    readonly assetsPrefix: string;
    readonly disc?: string;
    readonly source?: string;
  }
): Promise<unknown> => {
  const paths = new CollectionPaths(collectionDir);
  const explicitSource =
    options.source === undefined
      ? undefined
      : resolveExplicitDistrokidSource(collectionDir, options.source);
  const disc = explicitSource?.disc ?? options.disc;
  const sourceDir =
    explicitSource?.sourceDir ??
    (disc === undefined
      ? paths.musicDir
      : join(collectionDir, DISTROKID_DIR, disc));
  const titleByFilename = await titleMapForDisc(collectionDir, disc);
  const sourceFiles = await readdir(sourceDir);
  const files = sourceFiles.filter(isMp3).toSorted();
  const coverPath = await resolveAssetPath(
    collectionDir,
    join(DISTROKID_DIR, COVER_FILE)
  );
  const fallbackCover = paths.findThumbnail();
  const cover = coverPath ?? fallbackCover;
  return {
    profile: distrokid.profile,
    release: {
      album_title:
        disc === undefined
          ? paths.collectionName
          : await readDiscAlbumTitle(collectionDir, disc),
      cover:
        cover === null
          ? null
          : {
              asset_path: relativeAssetPath(
                collectionDir,
                cover,
                options.assetsPrefix
              ),
              filename: basename(cover),
            },
      release_date: await readReleaseDate(collectionDir),
      tracks: files.map((filename) => ({
        asset_path: relativeAssetPath(
          collectionDir,
          join(sourceDir, filename),
          options.assetsPrefix
        ),
        filename,
        title: titleByFilename.get(filename) ?? basename(filename, ".mp3"),
      })),
    },
  };
};

export const resolveDistrokidAssetPath = resolveAssetPath;
