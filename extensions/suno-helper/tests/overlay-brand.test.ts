import { describe, expect, it } from "vitest";

import { SUNO_OVERLAY_BRAND } from "../lib/overlay-brand";

describe("Suno overlay brand colors", () => {
  it("uses the approved OKLCH color for header and primary", () => {
    expect(SUNO_OVERLAY_BRAND).toEqual({
      headerBackground: "oklch(0.753 0.2067 57.6 / 96.4%)",
      headerForeground: "oklch(0.205 0 0)",
      primary: "oklch(0.753 0.2067 57.6 / 96.4%)",
      primaryForeground: "oklch(0.205 0 0)",
    });
  });
});
