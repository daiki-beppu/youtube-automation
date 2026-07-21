export type RgbColor = readonly [red: number, green: number, blue: number];

function relativeLuminance([red, green, blue]: RgbColor): number {
  const [linearRed, linearGreen, linearBlue] = [red, green, blue]
    .map((channel) => channel / 255)
    .map((channel) =>
      channel <= 0.040_45 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
    );
  return 0.2126 * linearRed + 0.7152 * linearGreen + 0.0722 * linearBlue;
}

function hexToRgb(hex: string): RgbColor {
  const normalized = hex.replace(/^#/, "");
  if (!/^[0-9a-f]{6}$/i.test(normalized)) {
    throw new Error(`6-digit hex color required: ${hex}`);
  }

  const [red, green, blue] = normalized
    .match(/.{2}/g)!
    .map((channel) => Number.parseInt(channel, 16));
  return [red, green, blue];
}

/** WCAG 2.x contrast ratio for two painted sRGB colors. */
export function rgbContrastRatio(first: RgbColor, second: RgbColor): number {
  const luminances = [relativeLuminance(first), relativeLuminance(second)].sort(
    (left, right) => right - left
  );
  return (luminances[0] + 0.05) / (luminances[1] + 0.05);
}

/** WCAG 2.x contrast ratio for two six-digit sRGB hex colors. */
export function hexContrastRatio(first: string, second: string): number {
  return rgbContrastRatio(hexToRgb(first), hexToRgb(second));
}
