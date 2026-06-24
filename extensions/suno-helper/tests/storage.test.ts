import { describe, expect, it, vi } from "vitest";

import { DEFAULT_URL, DOWNLOAD_FORMAT_DEFAULT, DOWNLOAD_FORMAT_KEY, STORAGE_KEY } from "../../shared/constants";

const storageMock = vi.hoisted(() => ({
  defineItem: vi.fn((key: string, options: { fallback: unknown }) => ({
    key,
    options,
    getValue: vi.fn(),
    setValue: vi.fn(),
  })),
}));

vi.mock("wxt/utils/storage", () => ({
  storage: storageMock,
}));

describe("lib/storage: chrome.storage.local wrapper", () => {
  it("Given storage module When import する Then serverUrlItem は server URL key と fallback を使う", async () => {
    const { serverUrlItem } = await import("../lib/storage");

    expect(storageMock.defineItem).toHaveBeenCalledWith(`local:${STORAGE_KEY}`, {
      fallback: DEFAULT_URL,
    });
    expect(serverUrlItem).toMatchObject({
      key: `local:${STORAGE_KEY}`,
      options: { fallback: DEFAULT_URL },
    });
  });

  it("Given storage module When import する Then downloadFormatItem は download format key と fallback を使う", async () => {
    const { downloadFormatItem } = await import("../lib/storage");

    expect(storageMock.defineItem).toHaveBeenCalledWith(`local:${DOWNLOAD_FORMAT_KEY}`, {
      fallback: DOWNLOAD_FORMAT_DEFAULT,
    });
    expect(downloadFormatItem).toMatchObject({
      key: `local:${DOWNLOAD_FORMAT_KEY}`,
      options: { fallback: DOWNLOAD_FORMAT_DEFAULT },
    });
  });
});
