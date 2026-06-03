// Tests for packages/core/src/paths.ts — the TS port of the Python
// `utils/collection_paths.py` (CollectionPaths + resolveCollectionDir).
//
// The contract under test mirrors plan §4-A: directory getters, priority-ordered
// image/thumbnail resolution, glob+sorted master/individual lookups, numbered
// Shorts resolution with single-file fallback, collection-name prefix stripping,
// and the CWD-fallback resolver. Paths are absolute strings (path.resolve),
// matching Python `Path.resolve()`.
//
// Imported by the published package subpath so the test also exercises the
// `exports` map entry the implementation adds for "./paths".

import { afterEach, describe, expect, test } from "bun:test";
import {
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { ValidationError } from "@youtube-automation/core";
import {
  CollectionPaths,
  resolveCollectionDir,
} from "@youtube-automation/core/paths";

const tempRoots: string[] = [];

// Creates an empty temp directory and registers it for teardown. An optional
// `name` produces a deterministically named child dir (for collectionName tests).
const makeDir = (name?: string): string => {
  const base = mkdtempSync(join(tmpdir(), "paths-fixture-"));
  tempRoots.push(base);
  if (name === undefined) {
    return base;
  }
  const dir = join(base, name);
  mkdirSync(dir, { recursive: true });
  return dir;
};

const touch = (path: string): void => {
  mkdirSync(join(path, ".."), { recursive: true });
  writeFileSync(path, "", "utf-8");
};

afterEach(() => {
  while (tempRoots.length > 0) {
    const dir = tempRoots.pop();
    if (dir !== undefined) {
      rmSync(dir, { force: true, recursive: true });
    }
  }
});

// --- directory getters -----------------------------------------------------

describe("CollectionPaths — directory getters", () => {
  test("derive the standard subdirectories from the resolved root", () => {
    // Given a collection root
    const root = makeDir("collection");
    const paths = new CollectionPaths(root);

    // Then every getter is the root joined with the documented subpath
    expect(paths.masterDir).toBe(join(paths.root, "01-master"));
    expect(paths.musicDir).toBe(join(paths.root, "02-Individual-music"));
    expect(paths.movieDir).toBe(join(paths.root, "03-Individual-movie"));
    expect(paths.assetsDir).toBe(join(paths.root, "10-assets"));
    expect(paths.docsDir).toBe(join(paths.root, "20-documentation"));
    expect(paths.workflowStatePath).toBe(
      join(paths.root, "workflow-state.json")
    );
  });

  test("derive doc-scoped and shorts paths", () => {
    // Given a collection root
    const paths = new CollectionPaths(makeDir("collection"));

    // Then doc artifacts hang off 20-documentation/
    expect(paths.trackingPath).toBe(
      join(paths.docsDir, "upload_tracking.json")
    );
    expect(paths.descriptionsMdPath).toBe(
      join(paths.docsDir, "descriptions.md")
    );
    expect(paths.thumbnailPromptsPath).toBe(
      join(paths.docsDir, "thumbnail-prompts.md")
    );

    // And shorts artifacts hang off 01-master/ and 10-assets/
    expect(paths.shortsDir).toBe(join(paths.masterDir, "shorts"));
    expect(paths.shortLoop).toBe(join(paths.assetsDir, "short-loop.mp4"));
  });
});

// --- collectionName prefix stripping --------------------------------------

describe("CollectionPaths — collectionName", () => {
  test("strips a numeric date + channel prefix (split maxsplit 2)", () => {
    // Given a directory named with the date-channel-name convention
    const paths = new CollectionPaths(makeDir("20260310-clm-some-name"));

    // Then only the trailing name segment remains
    expect(paths.collectionName).toBe("some-name");
  });

  test("keeps the name verbatim when the first segment is not numeric", () => {
    const paths = new CollectionPaths(makeDir("abc-def-ghi"));
    expect(paths.collectionName).toBe("abc-def-ghi");
  });

  test("keeps the name verbatim when there are fewer than three segments", () => {
    const paths = new CollectionPaths(makeDir("plain-name"));
    expect(paths.collectionName).toBe("plain-name");
  });
});

// --- thumbnail / main image priority --------------------------------------

describe("CollectionPaths — findThumbnail", () => {
  test("prefers thumbnail.jpg over thumbnail.png over main.* ", () => {
    // Given all four candidates present
    const root = makeDir("collection");
    const assets = join(root, "10-assets");
    for (const name of [
      "thumbnail.jpg",
      "thumbnail.png",
      "main.jpg",
      "main.png",
    ]) {
      touch(join(assets, name));
    }
    const paths = new CollectionPaths(root);

    // Then the highest-priority candidate wins
    expect(paths.findThumbnail()).toBe(join(paths.assetsDir, "thumbnail.jpg"));
  });

  test("falls through the priority list to main.png", () => {
    // Given only the lowest-priority candidate present
    const root = makeDir("collection");
    touch(join(root, "10-assets", "main.png"));
    const paths = new CollectionPaths(root);

    expect(paths.findThumbnail()).toBe(join(paths.assetsDir, "main.png"));
  });

  test("returns null when no candidate exists", () => {
    const paths = new CollectionPaths(makeDir("collection"));
    expect(paths.findThumbnail()).toBeNull();
  });
});

describe("CollectionPaths — findMainImage", () => {
  test("prefers main.png over main.jpg", () => {
    const root = makeDir("collection");
    touch(join(root, "10-assets", "main.png"));
    touch(join(root, "10-assets", "main.jpg"));
    const paths = new CollectionPaths(root);

    expect(paths.findMainImage()).toBe(join(paths.assetsDir, "main.png"));
  });

  test("returns null when neither main image exists", () => {
    const paths = new CollectionPaths(makeDir("collection"));
    expect(paths.findMainImage()).toBeNull();
  });
});

describe("CollectionPaths — findLoopVideo", () => {
  test("resolves loop.mp4 only when present", () => {
    const root = makeDir("collection");
    const paths = new CollectionPaths(root);
    expect(paths.findLoopVideo()).toBeNull();

    touch(join(root, "10-assets", "loop.mp4"));
    expect(paths.findLoopVideo()).toBe(join(paths.assetsDir, "loop.mp4"));
  });
});

// --- master / individual glob + sort --------------------------------------

describe("CollectionPaths — master lookups", () => {
  test("returns the first sorted .mp4 from 01-master/", () => {
    // Given two master videos out of lexical order on disk
    const root = makeDir("collection");
    touch(join(root, "01-master", "b-second.mp4"));
    touch(join(root, "01-master", "a-first.mp4"));
    const paths = new CollectionPaths(root);

    // Then the lexicographically first one is chosen (Python sorted())
    expect(paths.findMasterVideo()).toBe(join(paths.masterDir, "a-first.mp4"));
  });

  test("returns the first sorted .mp3 from 01-master/", () => {
    const root = makeDir("collection");
    touch(join(root, "01-master", "master.mp3"));
    const paths = new CollectionPaths(root);

    expect(paths.findMasterAudio()).toBe(join(paths.masterDir, "master.mp3"));
  });

  test("returns null when 01-master/ has no matching file", () => {
    const paths = new CollectionPaths(makeDir("collection"));
    expect(paths.findMasterVideo()).toBeNull();
    expect(paths.findMasterAudio()).toBeNull();
  });
});

describe("CollectionPaths — individual file listings", () => {
  test("lists 02-Individual-music/*.mp3 sorted", () => {
    const root = makeDir("collection");
    touch(join(root, "02-Individual-music", "02-b.mp3"));
    touch(join(root, "02-Individual-music", "01-a.mp3"));
    touch(join(root, "02-Individual-music", "note.txt"));
    const paths = new CollectionPaths(root);

    expect(paths.individualMusicFiles()).toEqual([
      join(paths.musicDir, "01-a.mp3"),
      join(paths.musicDir, "02-b.mp3"),
    ]);
  });

  test("lists 03-Individual-movie/*.mp4 sorted", () => {
    const root = makeDir("collection");
    touch(join(root, "03-Individual-movie", "01-a.mp4"));
    const paths = new CollectionPaths(root);

    expect(paths.individualMovieFiles()).toEqual([
      join(paths.movieDir, "01-a.mp4"),
    ]);
  });

  test("returns an empty list when the directory is absent", () => {
    const paths = new CollectionPaths(makeDir("collection"));
    expect(paths.individualMusicFiles()).toEqual([]);
    expect(paths.individualMovieFiles()).toEqual([]);
  });
});

// --- Shorts resolution -----------------------------------------------------

describe("CollectionPaths — findShortVideo", () => {
  test("prefers a numbered shorts file when short_num is given", () => {
    // Given a numbered shorts file under 01-master/shorts/
    const root = makeDir("collection");
    touch(join(root, "01-master", "shorts", "short-01-intro.mp4"));
    const paths = new CollectionPaths(root);

    // Then the numbered match is returned for that number
    expect(paths.findShortVideo(1)).toBe(
      join(paths.shortsDir, "short-01-intro.mp4")
    );
  });

  test("falls back to the single 01-master/short.mp4", () => {
    // Given only the single-file short present
    const root = makeDir("collection");
    touch(join(root, "01-master", "short.mp4"));
    const paths = new CollectionPaths(root);

    // Then the fallback is used both with and without a number
    expect(paths.findShortVideo(2)).toBe(join(paths.masterDir, "short.mp4"));
    expect(paths.findShortVideo(null)).toBe(join(paths.masterDir, "short.mp4"));
  });

  test("returns null when neither numbered nor single short exists", () => {
    const paths = new CollectionPaths(makeDir("collection"));
    expect(paths.findShortVideo(1)).toBeNull();
  });
});

describe("CollectionPaths — shortVideoSearchPaths", () => {
  test("lists only the single-file path when short_num is null", () => {
    const paths = new CollectionPaths(makeDir("collection"));
    expect(paths.shortVideoSearchPaths(null)).toEqual([
      join(paths.masterDir, "short.mp4"),
    ]);
  });

  test("lists the numbered glob then the single-file fallback", () => {
    const paths = new CollectionPaths(makeDir("collection"));
    expect(paths.shortVideoSearchPaths(1)).toEqual([
      join(paths.shortsDir, "short-01-*.mp4"),
      join(paths.masterDir, "short.mp4"),
    ]);
  });
});

describe("CollectionPaths — short thumbnail + loop input", () => {
  test("finds the short thumbnail jpg before png", () => {
    const root = makeDir("collection");
    touch(join(root, "10-assets", "short-thumbnail.jpg"));
    touch(join(root, "10-assets", "short-thumbnail.png"));
    const paths = new CollectionPaths(root);

    expect(paths.findShortThumbnail()).toBe(
      join(paths.assetsDir, "short-thumbnail.jpg")
    );
  });

  test("lists short loop input image candidates png before jpg", () => {
    const paths = new CollectionPaths(makeDir("collection"));
    expect(paths.shortLoopInputImageSearchPaths()).toEqual([
      join(paths.assetsDir, "short.png"),
      join(paths.assetsDir, "short.jpg"),
    ]);
  });

  test("finds the short loop input image png before jpg", () => {
    const root = makeDir("collection");
    touch(join(root, "10-assets", "short.jpg"));
    const paths = new CollectionPaths(root);
    expect(paths.findShortLoopInputImage()).toBe(
      join(paths.assetsDir, "short.jpg")
    );
  });
});

// --- resolveCollectionDir --------------------------------------------------

describe("resolveCollectionDir", () => {
  test("resolves an explicit argument to an absolute path", () => {
    // Given an explicit, already-absolute collection path
    const root = makeDir("collection");

    // When resolving with the argument
    // Then path.resolve leaves an absolute input unchanged
    expect(resolveCollectionDir(root)).toBe(root);
  });

  test("returns cwd when it is a valid collection and no arg is given", () => {
    // Given a cwd holding both 01-master/ and 02-Individual-music/
    const root = makeDir("collection");
    mkdirSync(join(root, "01-master"), { recursive: true });
    mkdirSync(join(root, "02-Individual-music"), { recursive: true });
    const originalCwd = process.cwd();
    try {
      process.chdir(root);

      // When resolving with no argument
      // Then the cwd is accepted as the collection dir
      expect(realpathSync(resolveCollectionDir(null))).toBe(realpathSync(root));
    } finally {
      process.chdir(originalCwd);
    }
  });

  test("throws ValidationError when cwd is not a collection and no arg is given", () => {
    // Given a cwd missing the required subdirectories
    const root = makeDir("collection");
    const originalCwd = process.cwd();
    try {
      process.chdir(root);

      // When/Then resolution fails fast
      expect(() => resolveCollectionDir(null)).toThrow(ValidationError);
    } finally {
      process.chdir(originalCwd);
    }
  });
});
