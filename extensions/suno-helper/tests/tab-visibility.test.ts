import { describe, expect, it } from "vitest";

import {
  currentTabVisibility,
  requireVisibleSunoTab,
  SUNO_TAB_VISIBLE_MESSAGE,
} from "../lib/tab-visibility";

describe("Suno tab visibility preflight", () => {
  it("表示中のタブだけ実行を許可する", () => {
    expect(requireVisibleSunoTab("visible")).toBeNull();
  });

  it("背面のタブは案内して開始しない", () => {
    expect(requireVisibleSunoTab("hidden")).toBe(SUNO_TAB_VISIBLE_MESSAGE);
    expect(SUNO_TAB_VISIBLE_MESSAGE).toContain("タブを表示中");
    expect(SUNO_TAB_VISIBLE_MESSAGE).toContain("Playlist");
  });

  // このファイルは node 環境（document なし）で動くため、fallback をそのまま検証できる。
  it("document を持たない環境では visible として扱う", () => {
    expect(currentTabVisibility()).toBe("visible");
  });
});
