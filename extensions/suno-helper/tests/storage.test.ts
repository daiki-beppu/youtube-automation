// `lib/storage.ts` の候補復元契約テスト。

import { beforeEach, describe, expect, it, vi } from "vitest";

const storageMocks = vi.hoisted(() => ({
  getValue: vi.fn(),
  setValue: vi.fn(),
}));

vi.mock("wxt/utils/storage", () => ({
  storage: {
    defineItem: vi.fn(() => storageMocks),
  },
}));

import { readServerSources } from "../lib/storage";

describe("local server source storage", () => {
  beforeEach(() => {
    storageMocks.getValue.mockReset();
    storageMocks.setValue.mockReset();
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
