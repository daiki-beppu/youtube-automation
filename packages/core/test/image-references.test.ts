import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { readReferenceFiles } from "../src/image/references.ts";

let workdir: string;

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "img-references-"));
});

afterEach(() => {
  rmSync(workdir, { force: true, recursive: true });
});

describe("readReferenceFiles", () => {
  test("returns reference images with paths and bytes in input order", () => {
    const firstPath = join(workdir, "first.png");
    const secondPath = join(workdir, "second.png");
    writeFileSync(firstPath, new Uint8Array([0x01, 0x02]));
    writeFileSync(secondPath, new Uint8Array([0x03, 0x04]));

    const refs = readReferenceFiles([firstPath, secondPath]);

    expect(refs).toHaveLength(2);
    const [first, second] = refs;
    if (first === undefined || second === undefined) {
      throw new Error("expected two reference images");
    }
    expect(first.path).toBe(firstPath);
    expect([...first.bytes]).toEqual([0x01, 0x02]);
    expect(second.path).toBe(secondPath);
    expect([...second.bytes]).toEqual([0x03, 0x04]);
  });

  test("returns an empty list when no paths are supplied", () => {
    expect(readReferenceFiles([])).toEqual([]);
  });

  test("includes the failed path and original filesystem error as cause", () => {
    const missingPath = join(workdir, "missing.png");

    let thrown: unknown;
    try {
      readReferenceFiles([missingPath]);
    } catch (error) {
      thrown = error;
    }

    expect(thrown).toBeInstanceOf(Error);
    const error = thrown as Error;
    expect(error.message).toContain(missingPath);
    expect(error.cause).toBeInstanceOf(Error);
    const cause = error.cause as NodeJS.ErrnoException;
    expect(cause.message).toContain(missingPath);
    expect(cause.code).toBe("ENOENT");
  });

  test("stops at the first unreadable path with that path in the error", () => {
    const firstPath = join(workdir, "first.png");
    const missingPath = join(workdir, "missing.png");
    const laterPath = join(workdir, "later.png");
    writeFileSync(firstPath, new Uint8Array([0x01]));
    writeFileSync(laterPath, new Uint8Array([0x02]));

    expect(() =>
      readReferenceFiles([firstPath, missingPath, laterPath])
    ).toThrow(missingPath);
  });
});
