// Blob URL を content 側で File に復元する境界の契約テスト。
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import { blobUrlToFile } from "../lib/asset-transfer";

const here = dirname(fileURLToPath(import.meta.url));
afterEach(() => vi.unstubAllGlobals());

describe("Blob URL asset transfer", () => {
  it("Blob URL の byte と metadata を File に復元する", async () => {
    const original = Uint8Array.from({ length: 256 }, (_, index) => index);
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(original, { headers: { "Content-Type": "audio/flac" } })
      )
    );
    const file = await blobUrlToFile("blob:track", "track.flac");
    expect(file.name).toBe("track.flac");
    expect(file.type).toBe("audio/flac");
    expect(new Uint8Array(await file.arrayBuffer())).toEqual(original);
  });

  it("content.ts は API client と base64 経路を持たない", () => {
    const source = readFileSync(
      join(here, "..", "entrypoints", "content.ts"),
      "utf8"
    );
    expect(source).not.toContain("@/lib/api");
    expect(source).not.toContain("base64");
    expect(source).not.toMatch(/\bfetch\s*\(/);
  });
});
