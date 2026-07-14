// `lib/storage.ts` の契約テスト。

import { beforeEach, describe, expect, it, vi } from "vitest";

const storageMocks = vi.hoisted(() => ({
  getValue: vi.fn(),
  setValue: vi.fn(),
}));

vi.mock("@wxt-dev/storage", () => ({
  storage: {
    defineItem: vi.fn(() => storageMocks),
  },
}));

import { DEFAULT_URL } from "../../shared/constants";
import { readServerSources } from "../lib/storage";

describe("DEFAULT_URL (shared constants)", () => {
  beforeEach(() => {
    storageMocks.getValue.mockReset();
    storageMocks.setValue.mockReset();
  });

  it("yt-collection-serve の既定ポート 7873 を指す", () => {
    expect(DEFAULT_URL).toBe("http://youtube-automation.localhost:7873");
  });

  it("保存済み候補の label と id が欠損しても、既存の URL を接続先として復元する", async () => {
    storageMocks.getValue.mockResolvedValue([{ url: "http://localhost:7878" }]);

    const sources = await readServerSources();

    expect(sources).toContainEqual({
      id: "localhost-7878",
      label: "localhost:7878",
      url: "http://localhost:7878",
    });
    expect(storageMocks.setValue).toHaveBeenCalledWith(sources);
  });
});
