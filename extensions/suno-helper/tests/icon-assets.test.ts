import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];
const ICON_SIZES = [16, 32, 48, 128] as const;

describe("extension icon assets", () => {
  it.each(ICON_SIZES)("provides a transparent %ipx PNG", (size) => {
    const path = fileURLToPath(
      new URL(`../public/icon/${size}.png`, import.meta.url)
    );
    const png = readFileSync(path);

    expect([...png.subarray(0, 8)]).toEqual(PNG_SIGNATURE);
    expect(png.readUInt32BE(16)).toBe(size);
    expect(png.readUInt32BE(20)).toBe(size);
    expect(png[25]).toBe(6); // PNG color type 6: truecolor with alpha
  });
});
