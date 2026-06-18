import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { extractThumbnailFeaturesService } from "@youtube-automation/core/image";
import { REGISTRY } from "@youtube-automation/core/registry";

interface ThumbnailFeatures {
  brightness: number;
  colorfulness: number;
  contrast: number;
  dominantHue: number;
  saturation: number;
}

const expectCloseFeatures = (
  actual: ThumbnailFeatures,
  expected: ThumbnailFeatures
) => {
  expect(actual.brightness).toBeCloseTo(expected.brightness, 2);
  expect(actual.contrast).toBeCloseTo(expected.contrast, 2);
  expect(actual.saturation).toBeCloseTo(expected.saturation, 2);
  expect(actual.dominantHue).toBe(expected.dominantHue);
  expect(actual.colorfulness).toBeCloseTo(expected.colorfulness, 2);
};

const solidRgb = (rgb: readonly [number, number, number]): Uint8Array =>
  new Uint8Array(rgb);

const rgbRows = (
  pixels: readonly (readonly [number, number, number])[]
): Uint8Array => new Uint8Array(pixels.flat());

const fixturePath = (name: string): string =>
  fileURLToPath(new URL(`fixtures/${name}`, import.meta.url));

const sourcePath = (relativePath: string): string =>
  fileURLToPath(new URL(`../src/${relativePath}`, import.meta.url));

const patternedRgb = (width: number, height: number): Uint8Array => {
  const data = new Uint8Array(width * height * 3);
  for (let pixel = 0; pixel < width * height; pixel += 1) {
    const offset = pixel * 3;
    data.set(
      [(pixel * 17) % 256, (pixel * 31) % 256, (pixel * 47) % 256],
      offset
    );
  }
  return data;
};

let workdir: string;

beforeAll(() => {
  workdir = mkdtempSync(join(tmpdir(), "thumbnail-features-"));
});

afterAll(() => {
  rmSync(workdir, { force: true, recursive: true });
});

const writePng = async (
  name: string,
  data: Uint8Array,
  width: number,
  height: number
): Promise<string> => {
  const sharpModule = await import("sharp");
  const sharp = sharpModule.default;
  const path = join(workdir, name);
  await sharp(Buffer.from(data), { raw: { channels: 3, height, width } })
    .png()
    .toFile(path);
  return path;
};

const writeRgbaPng = async (
  name: string,
  data: Uint8Array,
  width: number,
  height: number
): Promise<string> => {
  const sharpModule = await import("sharp");
  const sharp = sharpModule.default;
  const path = join(workdir, name);
  await sharp(Buffer.from(data), { raw: { channels: 4, height, width } })
    .png()
    .toFile(path);
  return path;
};

const writeSvg = (name: string, width: number, height: number): string => {
  const path = join(workdir, name);
  writeFileSync(
    path,
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"></svg>`
  );
  return path;
};

const extractOkFeatures = async (path: string): Promise<ThumbnailFeatures> => {
  const result = await extractThumbnailFeaturesService({ path });
  expect(result.ok).toBe(true);
  if (!result.ok) {
    throw new Error(`expected ok, got ${result.error.domain}`);
  }
  return result.value;
};

describe("extractThumbnailFeaturesService — Pillow parity", () => {
  test("returns zeroed features for a pure black RGB pixel", async () => {
    const data = solidRgb([0, 0, 0]);
    const path = await writePng("black.png", data, 1, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 0,
      colorfulness: 0,
      contrast: 0,
      dominantHue: 0,
      saturation: 0,
    });
  });

  test("keeps white brightness while saturation and contrast remain zero", async () => {
    const data = solidRgb([255, 255, 255]);
    const path = await writePng("white.png", data, 1, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 255,
      colorfulness: 0,
      contrast: 0,
      dominantHue: 0,
      saturation: 0,
    });
  });

  test("matches Pillow for a saturated red pixel, including colorfulness", async () => {
    const data = solidRgb([255, 0, 0]);
    const path = await writePng("red.png", data, 1, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 255,
      colorfulness: 85.46,
      contrast: 0,
      dominantHue: 0,
      saturation: 255,
    });
  });

  test("matches Pillow for a non-primary sample color", async () => {
    const data = solidRgb([128, 64, 200]);
    const path = await writePng("sample-rgb.png", data, 1, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 200,
      colorfulness: 36.63,
      contrast: 0,
      dominantHue: 190,
      saturation: 173,
    });
  });

  test("matches Pillow for mixed pixels across every feature", async () => {
    const data = rgbRows([
      [0, 0, 0],
      [255, 255, 255],
      [255, 0, 0],
      [0, 128, 255],
    ]);
    const path = await writePng("mixed.png", data, 4, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 191.25,
      colorfulness: 171.56,
      contrast: 92.62,
      dominantHue: 0,
      saturation: 127.5,
    });
  });

  test("uses population standard deviation for half black and half white", async () => {
    const data = rgbRows([
      [0, 0, 0],
      [255, 255, 255],
    ]);
    const path = await writePng("black-white.png", data, 2, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 127.5,
      colorfulness: 0,
      contrast: 127.5,
      dominantHue: 0,
      saturation: 0,
    });
  });

  test("matches Python round half-even for two-decimal feature values", async () => {
    const data = rgbRows([
      [1, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ]);
    const path = await writePng("round-half-even.png", data, 8, 1);

    const features = await extractOkFeatures(path);

    expect(features.brightness).toBe(0.12);
  });

  test("ignores alpha bytes after sharp removes the alpha channel", async () => {
    const data = new Uint8Array([128, 64, 200, 0]);
    const path = await writeRgbaPng("rgba.png", data, 1, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 200,
      colorfulness: 36.63,
      contrast: 0,
      dominantHue: 190,
      saturation: 173,
    });
  });

  test("uses the smallest hue bucket when the histogram is tied", async () => {
    const data = rgbRows([
      [255, 0, 0],
      [0, 0, 255],
    ]);
    const path = await writePng("hue-tie.png", data, 2, 1);

    const features = await extractOkFeatures(path);

    expect(features.dominantHue).toBe(0);
  });

  test("matches Pillow hue conversion for cyan-leaning colors", async () => {
    const data = solidRgb([0, 154, 187]);
    const path = await writePng("cyan-leaning.png", data, 1, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 187,
      colorfulness: 56.78,
      contrast: 0,
      dominantHue: 134,
      saturation: 255,
    });
  });

  test("matches Pillow hue conversion for low-value cyan ties", async () => {
    const data = rgbRows([
      [0, 1, 1],
      [0, 5, 5],
    ]);
    const path = await writePng("low-value-cyan-ties.png", data, 2, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 3,
      colorfulness: 3.18,
      contrast: 1.5,
      dominantHue: 127,
      saturation: 255,
    });
  });

  test("matches Pillow grayscale rounding for low-value contrast", async () => {
    const data = rgbRows([
      [0, 0, 0],
      [1, 2, 3],
    ]);
    const path = await writePng("low-value-contrast.png", data, 2, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 1.5,
      colorfulness: 0.92,
      contrast: 1,
      dominantHue: 0,
      saturation: 85,
    });
  });

  test("matches Pillow grayscale rounding for blue contrast", async () => {
    const data = rgbRows([
      [0, 0, 0],
      [0, 0, 250],
    ]);
    const path = await writePng("blue-contrast.png", data, 2, 1);

    const features = await extractOkFeatures(path);

    expectCloseFeatures(features, {
      brightness: 125,
      colorfulness: 162.5,
      contrast: 14,
      dominantHue: 0,
      saturation: 127.5,
    });
  });
});

describe("extractThumbnailFeaturesService — sharp boundary", () => {
  test("reads the thumbnail fixture and returns Pillow-compatible features", async () => {
    const features = await extractOkFeatures(
      fixturePath("thumbnail-parity.svg")
    );

    expectCloseFeatures(features, {
      brightness: 95,
      colorfulness: 122.53,
      contrast: 55,
      dominantHue: 134,
      saturation: 212.5,
    });
  });

  test("keeps histogram accumulation bounded for thumbnail-sized input", async () => {
    const path = await writePng(
      "thumbnail-sized.png",
      patternedRgb(1280, 720),
      1280,
      720
    );

    const features = await extractOkFeatures(path);

    expect(features.dominantHue).toBeGreaterThanOrEqual(0);
    expect(features.dominantHue).toBeLessThan(256);
  });

  test("does not hide histogram updates behind typed-array atomic mutation", () => {
    const source = readFileSync(
      sourcePath("image/thumbnail-features.ts"),
      "utf-8"
    );

    expect(source).not.toContain("Atomics.");
    expect(source).not.toContain("Uint32Array");
  });

  test("reads an image file and returns Pillow-compatible features", async () => {
    const path = await writePng("sample.png", solidRgb([128, 64, 200]), 1, 1);

    const result = await extractThumbnailFeaturesService({ path });

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expectCloseFeatures(result.value, {
      brightness: 200,
      colorfulness: 36.63,
      contrast: 0,
      dominantHue: 190,
      saturation: 173,
    });
  });

  test("returns a validation error for non-string path input", async () => {
    const input = { path: 123 } as unknown as { path: string };

    const result = await extractThumbnailFeaturesService(input);

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation failure");
    }
    expect(result.error.domain).toBe("validation");
  });

  test("returns a validation error before raw decode for too many pixels", async () => {
    const path = writeSvg("too-many-pixels.svg", 1281, 720);

    const result = await extractThumbnailFeaturesService({ path });

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation failure");
    }
    expect(result.error.domain).toBe("validation");
    expect(result.error.message).toContain("pixel count");
  });

  test("returns a validation error before sharp reads oversized files", async () => {
    const path = join(workdir, "too-large.bin");
    writeFileSync(path, Buffer.alloc(5 * 1024 * 1024 + 1));

    const result = await extractThumbnailFeaturesService({ path });

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected validation failure");
    }
    expect(result.error.domain).toBe("validation");
    expect(result.error.message).toContain("file size");
  });

  test("returns an io error when sharp cannot read the file path", async () => {
    const path = join(workdir, "missing.png");

    const result = await extractThumbnailFeaturesService({ path });

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("expected io failure");
    }
    expect(result.error.domain).toBe("io");
  });
});

describe("registry entry image.thumbnail.features", () => {
  test("is registered as a dependency-free core image service", () => {
    const entry = REGISTRY["image.thumbnail.features"];

    expect(entry.deps).toEqual([]);
    expect(entry.description).toContain("サムネイル");
  });

  test("runs through the registry using the declared root input shape", async () => {
    const path = await writePng("registry.png", solidRgb([255, 0, 0]), 1, 1);
    const entry = REGISTRY["image.thumbnail.features"];
    const input = entry.inputSchema.parse({ path });

    const result = await entry.run(input, {});

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error(`expected ok, got ${result.error.domain}`);
    }
    expectCloseFeatures(result.value, {
      brightness: 255,
      colorfulness: 85.46,
      contrast: 0,
      dominantHue: 0,
      saturation: 255,
    });
  });
});
