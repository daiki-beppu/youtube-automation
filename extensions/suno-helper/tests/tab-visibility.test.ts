import { describe, expect, it } from "vitest";

import {
  requireVisibleSunoTab,
  SUNO_TAB_VISIBLE_MESSAGE,
} from "../lib/tab-visibility";

describe("Suno tab visibility preflight", () => {
  it("表示中のタブだけ実行を許可する", () => {
    expect(requireVisibleSunoTab("visible")).toBeNull();
  });

  it.each(["hidden", "prerender"] as DocumentVisibilityState[])(
    "%s のタブは案内して開始しない",
    (state) => {
      expect(requireVisibleSunoTab(state)).toBe(SUNO_TAB_VISIBLE_MESSAGE);
      expect(SUNO_TAB_VISIBLE_MESSAGE).toContain("タブを表示中");
      expect(SUNO_TAB_VISIBLE_MESSAGE).toContain("Playlist");
    }
  );
});
