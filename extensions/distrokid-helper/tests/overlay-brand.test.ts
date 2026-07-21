import { describe, expect, it } from "vitest";

import { DISTROKID_OVERLAY_BRAND } from "../lib/overlay-brand";

describe("DistroKid overlay brand colors", () => {
  it("uses the approved OKLCH color for header and primary", () => {
    expect(DISTROKID_OVERLAY_BRAND).toEqual({
      headerBackground: "oklch(0.8703 0.1962 116.38)",
      headerForeground: "oklch(0.205 0 0)",
      primary: "oklch(0.8703 0.1962 116.38)",
      primaryForeground: "oklch(0.205 0 0)",
    });
  });
});
