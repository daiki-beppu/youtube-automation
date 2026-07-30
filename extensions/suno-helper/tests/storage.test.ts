import { beforeEach, describe, expect, it, vi } from "vitest";

const storageItems = vi.hoisted(() => {
  const serverUrl = {
    getValue: vi.fn(),
    setValue: vi.fn(),
    removeValue: vi.fn(),
  };
  const legacySources = {
    getValue: vi.fn(),
    setValue: vi.fn(),
    removeValue: vi.fn(),
  };
  const downloadFormat = {
    getValue: vi.fn(),
    setValue: vi.fn(),
    removeValue: vi.fn(),
  };
  return { serverUrl, legacySources, downloadFormat, defineItem: vi.fn() };
});

vi.mock("wxt/utils/storage", () => {
  storageItems.defineItem.mockImplementation((key: string) => {
    if (key === "local:sunoServerUrl") return storageItems.serverUrl;
    if (key === "local:sunoDownloadFormat") return storageItems.downloadFormat;
    return storageItems.legacySources;
  });
  return { storage: { defineItem: storageItems.defineItem } };
});

import {
  migrateServerSourcesStorage,
  readDownloadFormat,
  serverUrlItem,
} from "../lib/storage";

describe("Suno server source storage migration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    storageItems.serverUrl.getValue.mockResolvedValue(
      "http://selected.localhost:49152"
    );
    storageItems.legacySources.getValue.mockResolvedValue(
      Array.from({ length: 8 }, (_, port) => ({
        url: `http://localhost:${7873 + port}`,
      }))
    );
    storageItems.legacySources.removeValue.mockResolvedValue(undefined);
    storageItems.downloadFormat.getValue.mockResolvedValue("mp3");
    storageItems.downloadFormat.setValue.mockResolvedValue(undefined);
  });

  it("should remove only the legacy candidate key and preserve the selected URL", async () => {
    await migrateServerSourcesStorage();

    expect(storageItems.legacySources.removeValue).toHaveBeenCalledOnce();
    expect(serverUrlItem.removeValue).not.toHaveBeenCalled();
    await expect(serverUrlItem.getValue()).resolves.toBe(
      "http://selected.localhost:49152"
    );
    expect(storageItems.legacySources.setValue).not.toHaveBeenCalled();
  });

  it("should remain idempotent when the legacy candidate key is absent", async () => {
    await migrateServerSourcesStorage();
    await migrateServerSourcesStorage();

    expect(storageItems.legacySources.removeValue).toHaveBeenCalledTimes(2);
    expect(storageItems.legacySources.setValue).not.toHaveBeenCalled();
  });

  it("should reject when deleting the legacy candidate key fails", async () => {
    storageItems.legacySources.removeValue.mockRejectedValueOnce(
      new Error("storage unavailable")
    );

    await expect(migrateServerSourcesStorage()).rejects.toThrow(
      "storage unavailable"
    );
  });
});

describe("download format normalization and self-heal (#2907)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    storageItems.downloadFormat.setValue.mockResolvedValue(undefined);
  });

  it.each(["mp3", "m4a", "wav"] as const)(
    "valid %s はそのまま返して storage を変更しない",
    async (format) => {
      storageItems.downloadFormat.getValue.mockResolvedValueOnce(format);

      await expect(readDownloadFormat()).resolves.toBe(format);
      expect(storageItems.downloadFormat.setValue).not.toHaveBeenCalled();
    }
  );

  it.each(["flac", "", null, undefined, 42])(
    "invalid persisted value %j は mp3 を返して一度だけ自己修復保存する",
    async (value) => {
      storageItems.downloadFormat.getValue.mockResolvedValueOnce(value);

      await expect(readDownloadFormat()).resolves.toBe("mp3");
      expect(storageItems.downloadFormat.setValue).toHaveBeenCalledOnce();
      expect(storageItems.downloadFormat.setValue).toHaveBeenCalledWith("mp3");
    }
  );

  it("自己修復保存の失敗を reject として伝播する", async () => {
    const failure = new Error("download format storage unavailable");
    storageItems.downloadFormat.getValue.mockResolvedValueOnce("flac");
    storageItems.downloadFormat.setValue.mockRejectedValueOnce(failure);

    await expect(readDownloadFormat()).rejects.toBe(failure);
  });
});
