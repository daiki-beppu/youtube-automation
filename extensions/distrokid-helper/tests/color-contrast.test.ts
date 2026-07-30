import { hexContrastRatio, rgbContrastRatio } from "@youtube-automation/ui";
import { describe, expect, it } from "vitest";

describe("shared color contrast", () => {
  it("returns the WCAG black/white and identical-color boundaries", () => {
    expect(hexContrastRatio("#000000", "#FFFFFF")).toBe(21);
    expect(hexContrastRatio("#336699", "#336699")).toBe(1);
    expect(rgbContrastRatio([0, 0, 0], [255, 255, 255])).toBe(21);
  });

  it("is symmetric when argument order is swapped", () => {
    expect(hexContrastRatio("#123456", "#FEDCBA")).toBe(
      hexContrastRatio("#FEDCBA", "#123456")
    );
  });

  it.each(["#fff", "ffffff00", "#gg0000", "", "#12345z"])(
    "rejects an invalid six-digit hex color: %s",
    (hex) => {
      expect(() => hexContrastRatio(hex, "#000000")).toThrow(
        "6-digit hex color required"
      );
    }
  );
});
