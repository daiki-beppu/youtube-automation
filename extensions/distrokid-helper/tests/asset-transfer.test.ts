// `lib/asset-transfer.ts` の直列化契約テスト。
//
// asset fetch は popup 側（`chrome-extension://` origin）で行い、取得した File を base64 で
// content へ転送して復元する（SUP-NEW-asset-fetch-cors の修正）。#896 でサーバーが
// distrokid.com origin もデフォルト許可したが、content script fetch への書き換えは
// #896 のスコープ外のため popup fetch 構成を維持する。
// ここでは「転送往復でバイト列が壊れないこと」と「fetch 経路が content に残っていないこと」を固定する。

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { encodeAsset, decodeAsset } from "../lib/asset-transfer";

const here = dirname(fileURLToPath(import.meta.url));

describe("encodeAsset / decodeAsset 往復", () => {
  it("バイナリ全域（0..255）を往復しても完全一致する", async () => {
    // Given: 非 ASCII を含む全バイト値の blob（base64 化で壊れやすい領域）
    const original = new Uint8Array(256);
    for (let i = 0; i < 256; i += 1) {
      original[i] = i;
    }
    const blob = new Blob([original], { type: "image/png" });

    // When: popup 側で直列化 → content 側で復元
    const serialized = await encodeAsset("main.png", blob);
    const file = decodeAsset(serialized);

    // Then: メタと全バイトが保たれる
    expect(file.name).toBe("main.png");
    expect(file.type).toBe("image/png");
    const restored = new Uint8Array(await file.arrayBuffer());
    expect(Array.from(restored)).toEqual(Array.from(original));
  });

  it("CHUNK 境界（0x8000）を跨ぐサイズでも壊れない", async () => {
    // Given: bytesToBase64 の chunk 処理が複数回走るサイズ
    const size = 0x8000 * 2 + 123;
    const original = new Uint8Array(size);
    for (let i = 0; i < size; i += 1) {
      original[i] = i % 256;
    }
    const blob = new Blob([original], { type: "audio/mpeg" });

    // When
    const file = decodeAsset(await encodeAsset("track-01.mp3", blob));

    // Then
    const restored = new Uint8Array(await file.arrayBuffer());
    expect(restored.length).toBe(size);
    expect(Array.from(restored)).toEqual(Array.from(original));
  });
});

describe("fetch 経路の境界（CORS 回帰防止）", () => {
  // content script は asset を直接 fetch してはならない（ページ origin で CORS 遮断されるため）。
  // popup 側で fetch した直列化 asset を受け取るだけにする。
  it("content.ts は API client を import せず fetch も呼ばない", () => {
    const source = readFileSync(
      join(here, "..", "entrypoints", "content.ts"),
      "utf8",
    );
    expect(source).not.toContain("@/lib/api");
    expect(source).not.toContain("fetchAsset");
    expect(source).not.toMatch(/\bfetch\s*\(/);
  });
});
