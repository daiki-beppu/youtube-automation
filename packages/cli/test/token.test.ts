// Tests for the CLI token.json persistence helpers (ADR-0003 §6; Python
// oauth_handler._save_credentials parity, oauth_handler.py:205-226). token WRITE
// lives in the CLI layer — symmetric with secret READ (#822) — so core stays
// string-in / string-out. The security contract is 0o600: the token must never
// be group/other readable, on a fresh create AND on overwrite. A plain write /
// O_TRUNC keeps an existing file's mode, so an explicit chmod is the insurance
// (oauth_handler.py:220). The helpers are awaited so the tests pass whether the
// implementation is sync or async (ADR-0003 §6 awaits both).

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
  chmodSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { readTokenJson, writeTokenJson } from "../lib/token.ts";
import { permissionBits } from "./permission-bits.ts";

let workdir: string;

beforeEach(() => {
  workdir = mkdtempSync(join(tmpdir(), "cli-token-"));
});

afterEach(() => {
  rmSync(workdir, { force: true, recursive: true });
});

describe("writeTokenJson", () => {
  test("writes the content and locks the file to 0o600 on a fresh create", async () => {
    // Given a token path inside a not-yet-created auth directory
    const path = join(workdir, "auth", "token.json");
    const json = '{"access_token":"a","refresh_token":"r"}';

    // When writing the token
    await writeTokenJson(path, json);

    // Then the content round-trips and the file is owner-only (0o600)
    expect(readFileSync(path, "utf-8")).toBe(json);
    expect(permissionBits(path)).toBe(0o600);
  });

  test("tightens an existing world-readable file back to 0o600 on overwrite", async () => {
    // Given an existing token file left at a permissive 0o644 mode
    const path = join(workdir, "token.json");
    writeFileSync(path, '{"old":true}', "utf-8");
    chmodSync(path, 0o644);

    // When overwriting it through the helper
    await writeTokenJson(path, '{"new":true}');

    // Then the new content is stored and the mode is forced back to 0o600
    expect(readFileSync(path, "utf-8")).toBe('{"new":true}');
    expect(permissionBits(path)).toBe(0o600);
  });
});

describe("readTokenJson", () => {
  test("returns the file content when the token file exists", async () => {
    // Given an existing token file
    const path = join(workdir, "token.json");
    const json = '{"access_token":"a"}';
    writeFileSync(path, json, "utf-8");

    // When reading it
    // Then the raw JSON content string is returned
    expect(await readTokenJson(path)).toBe(json);
  });

  test("returns null when the token file is absent", async () => {
    // Given a path with no file (first run, before any auth)
    const path = join(workdir, "missing", "token.json");

    // When reading it
    // Then null signals 'no token yet' (ADR-0003 §6 triggers interactive auth)
    expect(await readTokenJson(path)).toBeNull();
  });
});
