import { describe, expect, it, vi } from "vitest";

vi.mock("../lib/messaging", () => ({ sendMessage: vi.fn() }));

import { exportStudioMultitrack } from "../lib/studio-export";

const TITLE_BY_CLIP = new Map([
  ["clip-a", "Song A"],
  ["clip-b", "Song B"],
]);

function createDeps(
  trackCount = 2,
  trackNames: string[] = ["Song A", "Song B"]
) {
  return {
    createEmptyProject: vi.fn(async () => undefined),
    renameProject: vi.fn(async () => undefined),
    openLibrary: vi.fn(async () => undefined),
    placeClipOnTrackAtStart: vi.fn(async (clipId: string) => {
      const title = TITLE_BY_CLIP.get(clipId);
      if (!title) throw new Error(`unexpected clip: ${clipId}`);
      return title;
    }),
    countPlacedClips: vi.fn(async () => trackCount),
    readTrackNames: vi.fn(async () => trackNames),
    openExportMenu: vi.fn(async () => undefined),
    clickMultitrackExport: vi.fn(async () => undefined),
  };
}

describe("Studio multitrack export", () => {
  it("Given clip IDs When export Then collection 名の project に各 clip を配置して Multitrack を開始する", async () => {
    const deps = createDeps();

    await exportStudioMultitrack(
      { collectionId: "collection-2026", clipIds: ["clip-a", "clip-b"] },
      deps
    );

    expect(deps.createEmptyProject).toHaveBeenCalledOnce();
    expect(deps.renameProject).toHaveBeenCalledWith("collection-2026");
    expect(deps.placeClipOnTrackAtStart.mock.calls).toEqual([
      ["clip-a", 0],
      ["clip-b", 1],
    ]);
    expect(deps.openExportMenu).toHaveBeenCalledOnce();
    expect(deps.clickMultitrackExport).toHaveBeenCalledOnce();
  });

  it("Given 配置数不足 When export Then 期待数と実数を示して export しない", async () => {
    const deps = createDeps(1);

    await expect(
      exportStudioMultitrack(
        { collectionId: "collection-2026", clipIds: ["clip-a", "clip-b"] },
        deps
      )
    ).rejects.toThrow("Studio track 数が一致しません: expected 2, got 1");

    expect(deps.openExportMenu).not.toHaveBeenCalled();
    expect(deps.clickMultitrackExport).not.toHaveBeenCalled();
  });

  it("Given clip 配置後も既定 track 名のまま When export Then 曲名不一致を示して export しない", async () => {
    const deps = createDeps(2, ["Audio Track", "Audio Track"]);

    await expect(
      exportStudioMultitrack(
        { collectionId: "collection-2026", clipIds: ["clip-a", "clip-b"] },
        deps
      )
    ).rejects.toThrow(
      "Studio track 名が一致しません: track 1 expected Song A, got Audio Track"
    );

    expect(deps.openExportMenu).not.toHaveBeenCalled();
    expect(deps.clickMultitrackExport).not.toHaveBeenCalled();
  });

  it("Given Multitrack が利用不能 When export Then 理由を保持して失敗する", async () => {
    const deps = createDeps();
    deps.clickMultitrackExport.mockRejectedValueOnce(
      new Error(
        "Studio の Multitrack export が利用できません。Premier プランを確認してください"
      )
    );

    await expect(
      exportStudioMultitrack(
        { collectionId: "collection-2026", clipIds: ["clip-a", "clip-b"] },
        deps
      )
    ).rejects.toThrow("Premier プラン");
  });
});
