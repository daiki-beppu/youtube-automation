import { describe, expect, it, vi } from "vitest";

import { migrateLegacyServerSources } from "../../shared/server-source-migration";

describe("shared legacy server source migration", () => {
  it("should use the shared removal contract without reading or rewriting history", async () => {
    const legacyItem = {
      getValue: vi.fn(),
      setValue: vi.fn(),
      removeValue: vi.fn(async () => undefined),
    };

    await migrateLegacyServerSources(legacyItem);

    expect(legacyItem.removeValue).toHaveBeenCalledOnce();
    expect(legacyItem.getValue).not.toHaveBeenCalled();
    expect(legacyItem.setValue).not.toHaveBeenCalled();
  });

  it("should propagate removal failures to its caller", async () => {
    const failure = new Error("extension context invalidated");
    const legacyItem = { removeValue: vi.fn(async () => Promise.reject(failure)) };

    await expect(migrateLegacyServerSources(legacyItem)).rejects.toBe(failure);
  });
});
