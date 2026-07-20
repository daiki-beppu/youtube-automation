import { hexContrastRatio } from "@youtube-automation/ui";
import { describe, expect, it } from "vitest";

import { SUNO_OVERLAY_BRAND } from "../lib/overlay-brand";

describe("Suno overlay brand colors", () => {
  it("meet WCAG AA contrast for normal text", () => {
    expect(
      hexContrastRatio(
        SUNO_OVERLAY_BRAND.headerBackground,
        SUNO_OVERLAY_BRAND.headerForeground
      )
    ).toBeGreaterThanOrEqual(4.5);
  });
});
