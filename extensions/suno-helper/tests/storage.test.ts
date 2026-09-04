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
  const downloadEnabled = {
    getValue: vi.fn(),
    setValue: vi.fn(),
    removeValue: vi.fn(),
    fallback: undefined as unknown,
  };
  return { serverUrl, legacySources, downloadEnabled, defineItem: vi.fn() };
});

vi.mock("wxt/utils/storage", () => {
  storageItems.defineItem.mockImplementation(
    (key: string, options?: { fallback?: unknown }) => {
      if (key === "local:sunoServerUrl") return storageItems.serverUrl;
      if (key === "local:sunoDownloadEnabled") {
        storageItems.downloadEnabled.fallback = options?.fallback;
        return storageItems.downloadEnabled;
      }
      return storageItems.legacySources;
    }
  );
  return { storage: { defineItem: storageItems.defineItem } };
});

import {
  downloadEnabledItem,
  migrateServerSourcesStorage,
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

describe("download preference storage", () => {
  it("defaults the local download preference to enabled", () => {
    expect(storageItems.downloadEnabled.fallback).toBe(true);
    expect(downloadEnabledItem).toBe(storageItems.downloadEnabled);
  });
});
