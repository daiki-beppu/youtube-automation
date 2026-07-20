import { hexContrastRatio } from "@youtube-automation/ui";
import { describe, expect, it } from "vitest";

import { DISTROKID_OVERLAY_BRAND } from "../lib/overlay-brand";

describe("DistroKid overlay brand colors", () => {
  it("meet WCAG AA contrast for normal text", () => {
    expect(
      hexContrastRatio(
        DISTROKID_OVERLAY_BRAND.headerBackground,
        DISTROKID_OVERLAY_BRAND.headerForeground
      )
    ).toBeGreaterThanOrEqual(4.5);
  });
});
