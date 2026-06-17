import sharp from "sharp";
import { z } from "zod";

import { toServiceError } from "../errors.ts";
import type { ServiceError } from "../errors.ts";
import { err, ok } from "../result.ts";
import type { Result } from "../result.ts";

const RGB_CHANNELS = 3;
const RGBA_CHANNELS = 4;
const HUE_BUCKETS = 256;
const MAX_CHANNEL_VALUE = 255;

export const ExtractThumbnailFeaturesInput = z
  .object({
    path: z.string(),
  })
  .strict();
export type ExtractThumbnailFeaturesInput = z.infer<
  typeof ExtractThumbnailFeaturesInput
>;

export const ThumbnailFeatures = z
  .object({
    brightness: z.number(),
    colorfulness: z.number(),
    contrast: z.number(),
    dominantHue: z.number().int(),
    saturation: z.number(),
  })
  .strict();
export type ThumbnailFeatures = z.infer<typeof ThumbnailFeatures>;

interface RawRgbThumbnailInput {
  readonly channels: 3 | 4;
  readonly data: Uint8Array;
  readonly height: number;
  readonly width: number;
}

const roundHalfEven = (value: number, decimalPlaces: number): number => {
  const factor = 10 ** decimalPlaces;
  const scaled = value * factor;
  const sign = Math.sign(scaled) || 1;
  const absoluteScaled = Math.abs(scaled);
  const floor = Math.floor(absoluteScaled);
  const fraction = absoluteScaled - floor;
  const tieTolerance = Number.EPSILON * Math.max(1, absoluteScaled);
  const rounded =
    Math.abs(fraction - 0.5) <= tieTolerance
      ? floor + (floor % 2)
      : Math.round(absoluteScaled);
  return (sign * rounded) / factor;
};

const roundFeature = (value: number): number => roundHalfEven(value, 2);

const populationStddev = (
  sum: number,
  squareSum: number,
  count: number
): number => Math.sqrt(Math.max(0, squareSum / count - (sum / count) ** 2));

const grayLuminance = (red: number, green: number, blue: number): number =>
  Math.floor((red * 19_595 + green * 38_470 + blue * 7471 + 32_768) / 65_536);

const numberAt = (values: ArrayLike<number>, index: number): number => {
  const value = values[index];
  if (value === undefined) {
    throw new Error(`validation: missing numeric value at index ${index}`);
  }
  return value;
};

const hueFromRgb = (
  red: number,
  green: number,
  blue: number,
  delta: number,
  maxChannel: number
): number => {
  if (delta === 0) {
    return 0;
  }

  const chromaRange = Math.fround(delta);
  const redChroma = Math.fround(Math.fround(maxChannel - red) / chromaRange);
  const greenChroma = Math.fround(
    Math.fround(maxChannel - green) / chromaRange
  );
  const blueChroma = Math.fround(Math.fround(maxChannel - blue) / chromaRange);

  let hue: number;
  if (maxChannel === red) {
    hue = Math.fround(blueChroma - greenChroma);
  } else if (maxChannel === green) {
    hue = Math.fround(2 + redChroma - blueChroma);
  } else {
    hue = Math.fround(4 + greenChroma - redChroma);
  }
  return Math.trunc(Math.fround((hue / 6 + 1) % 1) * MAX_CHANNEL_VALUE);
};

const saturationFromRgb = (delta: number, maxChannel: number): number =>
  maxChannel === 0
    ? 0
    : Math.trunc(
        Math.fround(Math.fround(delta) / Math.fround(maxChannel)) *
          MAX_CHANNEL_VALUE
      );

const pixelHsv = (
  red: number,
  green: number,
  blue: number
): { hue: number; saturation: number; value: number } => {
  const maxChannel = Math.max(red, green, blue);
  const minChannel = Math.min(red, green, blue);
  const delta = maxChannel - minChannel;
  return {
    hue: hueFromRgb(red, green, blue, delta, maxChannel),
    saturation: saturationFromRgb(delta, maxChannel),
    value: maxChannel,
  };
};

const assertRawRgbInput = (input: RawRgbThumbnailInput): void => {
  if (input.channels !== RGB_CHANNELS && input.channels !== RGBA_CHANNELS) {
    throw new Error("validation: channels must be 3 or 4");
  }
  if (!Number.isInteger(input.width) || input.width <= 0) {
    throw new Error("validation: width must be a positive integer");
  }
  if (!Number.isInteger(input.height) || input.height <= 0) {
    throw new Error("validation: height must be a positive integer");
  }
  const expectedLength = input.width * input.height * input.channels;
  if (input.data.length !== expectedLength) {
    throw new Error(
      `validation: raw RGB data length ${input.data.length} does not match ${expectedLength}`
    );
  }
};

class HueHistogram {
  readonly #counts = new Map<number, number>();

  add(hue: number): void {
    const count = this.#counts.get(hue);
    this.#counts.set(hue, count === undefined ? 1 : count + 1);
  }

  dominantHue(): number {
    let selectedHue = 0;
    let selectedCount = this.#counts.get(0) ?? 0;
    for (let hue = 1; hue < HUE_BUCKETS; hue += 1) {
      const count = this.#counts.get(hue) ?? 0;
      if (count > selectedCount) {
        selectedHue = hue;
        selectedCount = count;
      }
    }
    return selectedHue;
  }
}

const colorfulness = (
  rgSum: number,
  rgSquareSum: number,
  ybSum: number,
  ybSquareSum: number,
  pixelCount: number
): number => {
  const chromaStddev = Math.hypot(
    populationStddev(rgSum, rgSquareSum, pixelCount),
    populationStddev(ybSum, ybSquareSum, pixelCount)
  );
  const chromaMean = Math.hypot(rgSum / pixelCount, ybSum / pixelCount);
  return chromaStddev + 0.3 * chromaMean;
};

const extractThumbnailFeaturesFromRgb = (
  input: RawRgbThumbnailInput
): ThumbnailFeatures => {
  assertRawRgbInput(input);
  const pixelCount = input.width * input.height;
  const histogram = new HueHistogram();
  let valueSum = 0;
  let saturationSum = 0;
  let graySum = 0;
  let graySquareSum = 0;
  let rgSum = 0;
  let rgSquareSum = 0;
  let ybSum = 0;
  let ybSquareSum = 0;

  for (let pixel = 0; pixel < pixelCount; pixel += 1) {
    const offset = pixel * input.channels;
    const red = numberAt(input.data, offset);
    const green = numberAt(input.data, offset + 1);
    const blue = numberAt(input.data, offset + 2);
    const hsv = pixelHsv(red, green, blue);
    const gray = grayLuminance(red, green, blue);
    const rg = Math.abs(red - green);
    const yb = Math.min(
      MAX_CHANNEL_VALUE,
      Math.floor(Math.abs(0.5 * (red + green) - blue))
    );

    histogram.add(hsv.hue);
    valueSum += hsv.value;
    saturationSum += hsv.saturation;
    graySum += gray;
    graySquareSum += gray ** 2;
    rgSum += rg;
    rgSquareSum += rg ** 2;
    ybSum += yb;
    ybSquareSum += yb ** 2;
  }

  return ThumbnailFeatures.parse({
    brightness: roundFeature(valueSum / pixelCount),
    colorfulness: roundFeature(
      colorfulness(rgSum, rgSquareSum, ybSum, ybSquareSum, pixelCount)
    ),
    contrast: roundFeature(
      populationStddev(graySum, graySquareSum, pixelCount)
    ),
    dominantHue: histogram.dominantHue(),
    saturation: roundFeature(saturationSum / pixelCount),
  });
};

export const extractThumbnailFeaturesService = async (
  input: ExtractThumbnailFeaturesInput
): Promise<Result<ThumbnailFeatures, ServiceError>> => {
  try {
    const request = ExtractThumbnailFeaturesInput.parse(input);
    const { data, info } = await sharp(request.path)
      .toColorspace("srgb")
      .removeAlpha()
      .raw()
      .toBuffer({ resolveWithObject: true });
    const features = extractThumbnailFeaturesFromRgb({
      channels: info.channels as 3 | 4,
      data,
      height: info.height,
      width: info.width,
    });
    return ok(ThumbnailFeatures.parse(features));
  } catch (error) {
    return err(toServiceError(error));
  }
};
