// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest";

vi.mock("../lib/messaging", () => ({ sendMessage: vi.fn() }));

import { sendMessage } from "../lib/messaging";
import {
  clickStudioAriaButtonUntil,
  clickStudioButtonUntil,
  commitStudioInputValue,
  dispatchStudioPointerClick,
  exportStudioMultitrack,
} from "../lib/studio-export";

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
  it("Given pointerdown で開く Studio menu When 操作 Then click() ではなく pointer sequence で開く", () => {
    const button = document.createElement("button");
    const menu = document.createElement("div");
    button.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
    button.addEventListener("pointerdown", () => {
      menu.textContent = "New Project";
      document.body.append(menu);
    });
    document.body.append(button);

    dispatchStudioPointerClick(button);

    expect(document.body.textContent).toContain("New Project");
    button.remove();
    menu.remove();
  });

  it("Given 最初の All Songs 操作が遷移中に無視される When Library を開く Then clip が出るまで再操作する", async () => {
    const button = document.createElement("button");
    button.textContent = "All Songs";
    button.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
    let attempts = 0;
    button.addEventListener("pointerdown", () => {
      attempts += 1;
      if (attempts < 2) return;
      const clip = document.createElement("div");
      clip.dataset.clipId = "clip-a";
      clip.draggable = true;
      clip.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
      document.body.append(clip);
    });
    document.body.append(button);

    const clip = await clickStudioButtonUntil(
      "All Songs",
      () => document.querySelector<HTMLElement>("[data-clip-id]"),
      "Library の clip 一覧",
      "pointer"
    );

    expect(clip.dataset.clipId).toBe("clip-a");
    expect(attempts).toBe(2);
    document.body.replaceChildren();
  });

  it("Given trusted input が必要な Studio menu item When 操作 Then background に座標を渡す", async () => {
    const button = document.createElement("button");
    button.textContent = "AudioA";
    button.setAttribute("aria-label", "Add Audio track");
    button.getBoundingClientRect = () =>
      ({ left: 30, top: 40, width: 20, height: 10 }) as DOMRect;
    vi.mocked(sendMessage).mockImplementation(async (type) => {
      if (type !== "sendTrustedClick") return undefined;
      const track = document.createElement("div");
      track.dataset.trackId = "track-2";
      track.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
      document.body.append(track);
    });
    document.body.append(button);

    await clickStudioAriaButtonUntil(
      "Add Audio track",
      () => document.querySelector<HTMLElement>("[data-track-id]"),
      "track 2 件"
    );

    expect(sendMessage).toHaveBeenCalledWith("sendTrustedClick", {
      x: 40,
      y: 45,
    });
    document.body.replaceChildren();
    vi.mocked(sendMessage).mockReset();
  });

  it("Given Add Audio の初回 click が menu を閉じるだけ When track を追加する Then menu を開き直して再試行する", async () => {
    vi.useFakeTimers();
    try {
      const firstTrack = document.createElement("div");
      firstTrack.dataset.trackId = "track-1";
      firstTrack.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
      const createMenuItem = (): HTMLButtonElement => {
        const item = document.createElement("button");
        item.setAttribute("aria-label", "Add Audio track");
        item.getBoundingClientRect = () =>
          ({ left: 30, top: 40, width: 20, height: 10 }) as DOMRect;
        document.body.append(item);
        return item;
      };
      document.body.append(firstTrack);
      createMenuItem();

      let clickAttempts = 0;
      let reopenAttempts = 0;
      vi.mocked(sendMessage).mockImplementation(async (type) => {
        if (type !== "sendTrustedClick") return undefined;
        clickAttempts += 1;
        const item = document.querySelector<HTMLButtonElement>(
          'button[aria-label="Add Audio track"]'
        );
        item?.remove();
        if (clickAttempts === 1) return undefined;
        const secondTrack = document.createElement("div");
        secondTrack.dataset.trackId = "track-2";
        secondTrack.getBoundingClientRect = () =>
          ({ left: 0, top: 20, width: 20, height: 20 }) as DOMRect;
        document.body.append(secondTrack);
        return undefined;
      });

      const resultPromise = clickStudioAriaButtonUntil(
        "Add Audio track",
        () =>
          document.querySelectorAll<HTMLElement>("[data-track-id]").length === 2
            ? document.querySelector<HTMLElement>("[data-track-id]")
            : null,
        "track 2 件",
        {
          postClickDelayMs: 500,
          recoverButton: async () => {
            reopenAttempts += 1;
            createMenuItem();
          },
        }
      );
      const assertion = expect(resultPromise).resolves.toBe(firstTrack);

      await vi.runAllTimersAsync();
      await assertion;
      expect(clickAttempts).toBe(2);
      expect(reopenAttempts).toBe(1);
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
      vi.mocked(sendMessage).mockReset();
    }
  });

  it("Given Studio の inline rename When 値を確定 Then blur で保存を発火する", () => {
    const input = document.createElement("input");
    let committed = "";
    input.addEventListener("blur", () => {
      committed = input.value;
    });
    document.body.append(input);
    input.focus();

    commitStudioInputValue(input, "collection-2026");

    expect(committed).toBe("collection-2026");
    input.remove();
  });

  it("Given 最初の Add new track 操作が無視される When menu を開く Then項目が出るまで再操作する", async () => {
    const button = document.createElement("button");
    button.setAttribute("aria-label", "Add new track");
    button.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
    let attempts = 0;
    vi.mocked(sendMessage).mockImplementation(async (type) => {
      if (type !== "sendTrustedClick") return undefined;
      attempts += 1;
      if (attempts < 2) return;
      const item = document.createElement("button");
      item.textContent = "AudioA";
      item.setAttribute("aria-label", "Add Audio track");
      item.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
      document.body.append(item);
    });
    document.body.append(button);

    const item = await clickStudioAriaButtonUntil(
      "Add new track",
      () =>
        document.querySelector<HTMLButtonElement>(
          'button[aria-label="Add Audio track"]'
        ),
      "Add Audio track ボタン"
    );

    expect(item.getAttribute("aria-label")).toBe("Add Audio track");
    expect(attempts).toBe(2);
    expect(sendMessage).toHaveBeenCalledWith("sendTrustedClick", {
      x: 10,
      y: 10,
    });
    document.body.replaceChildren();
    vi.mocked(sendMessage).mockReset();
  });

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
