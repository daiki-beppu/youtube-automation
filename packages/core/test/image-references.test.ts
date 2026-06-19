import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { readReferenceFiles } from "../src/image/references.ts";

let workdir: string;

beforeAll(() => {
  workdir = mkdtempSync(join(tmpdir(), "img-refs-"));
});

afterAll(() => {
  rmSync(workdir, { force: true, recursive: true });
});

const catchThrown = (act: () => void): unknown => {
  try {
    act();
  } catch (error) {
    return error;
  }
  throw new Error("Expected function to throw");
};

describe("readReferenceFiles", () => {
  test("returns each reference path and bytes in input order", () => {
    const firstPath = join(workdir, "first.png");
    const secondPath = join(workdir, "second.jpg");
    const firstBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
    const secondBytes = new Uint8Array([0xff, 0xd8, 0xff, 0xdb]);
    writeFileSync(firstPath, firstBytes);
    writeFileSync(secondPath, secondBytes);

    const references = readReferenceFiles([firstPath, secondPath]);

    expect(
      references.map(({ bytes, path }) => ({ bytes: [...bytes], path }))
    ).toEqual([
      { bytes: [...firstBytes], path: firstPath },
      { bytes: [...secondBytes], path: secondPath },
    ]);
  });

  test("returns an empty array for an empty reference list", () => {
    const paths: string[] = [];

    const references = readReferenceFiles(paths);

    expect(references).toEqual([]);
  });

  test("throws an error with the missing reference path", () => {
    const missingPath = join(workdir, "missing.png");

    const error = catchThrown(() => readReferenceFiles([missingPath]));

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain(
      "Failed to read reference image"
    );
    expect((error as Error).message).toContain(missingPath);
    expect((error as Error).cause).toBeInstanceOf(Error);
    const cause = (error as Error).cause as NodeJS.ErrnoException;
    expect(cause.message).toContain(missingPath);
    expect(cause.code).toBe("ENOENT");
  });

  test("reports the second path when reading fails after an earlier success", () => {
    const firstPath = join(workdir, "before-missing.png");
    const missingPath = join(workdir, "second-missing.png");
    writeFileSync(firstPath, new Uint8Array([1, 2, 3, 4]));

    const error = catchThrown(() =>
      readReferenceFiles([firstPath, missingPath])
    );

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain(
      "Failed to read reference image"
    );
    expect((error as Error).message).toContain(missingPath);
    expect((error as Error).message).not.toContain(firstPath);
  });
});
