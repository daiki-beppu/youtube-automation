import { hexContrastRatio } from "@youtube-automation/ui";
import { describe, expect, it } from "vitest";

import { YOUTUBE_OVERLAY_BRAND } from "../lib/overlay-brand";

describe("YouTube overlay brand colors", () => {
  it("meet WCAG AA contrast for normal text", () => {
    expect(
      hexContrastRatio(
        YOUTUBE_OVERLAY_BRAND.headerBackground,
        YOUTUBE_OVERLAY_BRAND.headerForeground
      )
    ).toBeGreaterThanOrEqual(4.5);
  });
});
