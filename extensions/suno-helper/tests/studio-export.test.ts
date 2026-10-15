// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/messaging", () => ({ sendMessage: vi.fn() }));

import { SUNO_LABELS } from "../../shared/suno-labels";
import { sendMessage } from "../lib/messaging";
import {
  clickStudioAriaButtonUntil,
  clickStudioButtonUntil,
  commitStudioInputValue,
  dispatchStudioContextMenu,
  dispatchStudioPointerClick,
  exportStudioMultitrack,
  findLibraryClip,
  openStudioLibraryAllSongs,
  renameTrack,
  verifyPlacedClipLength,
} from "../lib/studio-export";

function visibleButton(label: string, text?: string): HTMLButtonElement {
  const button = document.createElement("button");
  button.textContent = text ?? label;
  button.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
  return button;
}

function libraryClip(clipId: string): HTMLElement {
  const clip = document.createElement("div");
  clip.dataset.clipId = clipId;
  clip.draggable = true;
  clip.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
  return clip;
}

const TITLE_BY_CLIP = new Map([
  ["clip-a", "Song A"],
  ["clip-b", "Song B"],
]);

beforeEach(() => {
  document.body.replaceChildren();
  Object.defineProperty(globalThis, "CSS", {
    configurable: true,
    value: { escape: (value: string) => value },
  });
});

afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});

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
  function appendLibraryClip(
    scroller: HTMLElement,
    clipId: string
  ): HTMLElement {
    const clip = document.createElement("div");
    clip.dataset.clipId = clipId;
    clip.draggable = true;
    clip.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
    scroller.append(clip);
    return clip;
  }

  function createLibrary(): {
    scroller: HTMLElement;
    setScrollHeight: (height: number) => void;
  } {
    const scroller = document.createElement("div");
    scroller.style.overflowY = "auto";
    let scrollHeight = 400;
    let scrollTop = 0;
    Object.defineProperties(scroller, {
      clientHeight: { value: 200 },
      scrollHeight: { get: () => scrollHeight },
      scrollTop: {
        get: () => scrollTop,
        set: (value: number) => {
          scrollTop = Math.min(value, scrollHeight - 200);
        },
      },
    });
    document.body.append(scroller);
    return {
      scroller,
      setScrollHeight: (height: number) => {
        scrollHeight = height;
      },
    };
  }

  it("Given 遅延読み込み境界の clip When 行が追加される Then スクロールを再開して見つける", async () => {
    vi.useFakeTimers();
    try {
      const { scroller, setScrollHeight } = createLibrary();
      appendLibraryClip(scroller, "visible-clip");
      let lazyLoadScheduled = false;
      scroller.addEventListener("scroll", () => {
        if (lazyLoadScheduled || scroller.scrollTop < 200) return;
        lazyLoadScheduled = true;
        setTimeout(() => {
          setScrollHeight(800);
          appendLibraryClip(scroller, "lazy-clip");
        }, 600);
      });

      const resultPromise = findLibraryClip("lazy-clip");
      const assertion = expect(resultPromise).resolves.toHaveProperty(
        "dataset.clipId",
        "lazy-clip"
      );
      await vi.runAllTimersAsync();
      await assertion;
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
    }
  });

  it("Given 存在しない clip When Library が増えない Then 遅延読み込み待ち後に失敗する", async () => {
    vi.useFakeTimers();
    try {
      const { scroller } = createLibrary();
      appendLibraryClip(scroller, "visible-clip");

      const resultPromise = findLibraryClip("missing-clip");
      const assertion = expect(resultPromise).rejects.toThrow(
        "Studio Library に clip missing-clip が見つかりません"
      );
      await vi.advanceTimersByTimeAsync(2_400);
      await assertion;
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
    }
  });

  it("Given 最初の表示範囲に対象 clip When 探索 Then スクロールせず即座に返す", async () => {
    const { scroller } = createLibrary();
    const clip = appendLibraryClip(scroller, "visible-clip");

    await expect(findLibraryClip("visible-clip")).resolves.toBe(clip);
    expect(scroller.scrollTop).toBe(0);
    document.body.replaceChildren();
  });

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
      SUNO_LABELS.studioAllSongs,
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
      SUNO_LABELS.studioAddAudioTrack,
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
        SUNO_LABELS.studioAddAudioTrack,
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
      SUNO_LABELS.studioAddNewTrack,
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

  it("Given ボタン文言の大小文字が揺れた UI When 名前でボタンを探す Then case-insensitive に一致する", async () => {
    // "Rename Track" → "Rename track" のような Suno 側の表記揺れ (#5198)
    const button = visibleButton("unused", "rename track");
    document.body.append(button);
    const target = document.createElement("div");
    target.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
    button.addEventListener("pointerdown", () => document.body.append(target));

    const found = await clickStudioButtonUntil(
      SUNO_LABELS.studioRenameTrack,
      () => (document.body.contains(target) ? target : null),
      "対象要素",
      "pointer"
    );

    expect(found).toBe(target);
    document.body.replaceChildren();
  });

  it("Given Library がトップで開く When openStudioLibraryAllSongs Then Go back を押さずに All Songs へ進む", async () => {
    vi.mocked(sendMessage).mockImplementation(async (type) => {
      if (type !== "sendTrustedClick") return undefined;
      if (!document.querySelector('button[aria-label="All Songs"]')) {
        document.body.append(visibleButton("All Songs", "All Songs"));
      }
      return undefined;
    });
    document.body.append(visibleButton("Open library"));

    const goBack = visibleButton("Go back");
    goBack.setAttribute("aria-label", "Go back");
    goBack.addEventListener("pointerdown", () => {
      throw new Error("Go back は押されないはず");
    });
    document.body.append(goBack);

    const result = openStudioLibraryAllSongs();
    // All Songs が出た段階で pointer click 経路へ進む
    const allSongs = () =>
      Array.from(document.querySelectorAll("button")).find(
        (b) => b.textContent?.trim() === "All Songs"
      );
    const poll = setInterval(() => {
      const b = allSongs();
      if (b && !document.querySelector("[data-clip-id]")) {
        document.body.append(libraryClip("clip-a"));
      }
    }, 50);
    await expect(result).resolves.toHaveProperty("dataset.clipId", "clip-a");
    clearInterval(poll);
    document.body.replaceChildren();
    vi.mocked(sendMessage).mockReset();
  });

  it("Given Library が記憶した workspace 内で開く When openStudioLibraryAllSongs Then Go back で戻ってから All Songs を押す", async () => {
    // 観測された遷移: Open library → workspace 一覧（Go back のみ）→ Go back → All Songs (#5198)
    const phase = { current: "closed" as "closed" | "workspace" | "top" };
    vi.mocked(sendMessage).mockImplementation(async (type) => {
      if (type !== "sendTrustedClick") return undefined;
      return undefined;
    });

    const openLibrary = visibleButton("Open library");
    openLibrary.setAttribute("aria-label", "Open library");
    document.body.append(openLibrary);

    // pointerdown で遷移を模擬: Open library → workspace、Go back → top、All Songs → clip
    openLibrary.addEventListener("pointerdown", () => {
      phase.current = "workspace";
      document.body.replaceChildren();
      const back = visibleButton("Go back");
      back.setAttribute("aria-label", "Go back");
      back.addEventListener("pointerdown", () => {
        phase.current = "top";
        document.body.replaceChildren();
        const allSongs = visibleButton("All Songs");
        allSongs.addEventListener("pointerdown", () => {
          document.body.append(libraryClip("clip-a"));
        });
        document.body.append(allSongs);
      });
      document.body.append(back);
    });

    // trusted click は背景経由で pointerdown と同等の効果として扱うため、
    // テストでは sendTrustedClick 呼び出し時に対象座標の pointerdown を代理させる
    vi.mocked(sendMessage).mockImplementation(async (type, payload) => {
      if (type !== "sendTrustedClick") return undefined;
      const { x, y } = payload as { x: number; y: number };
      void x;
      void y;
      // 前面にある該当 aria-label ボタンの pointerdown を発火させる
      const target = document.querySelector<HTMLButtonElement>(
        phase.current === "closed"
          ? 'button[aria-label="Open library"]'
          : 'button[aria-label="Go back"]'
      );
      target?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
      return undefined;
    });

    await expect(openStudioLibraryAllSongs()).resolves.toHaveProperty(
      "dataset.clipId",
      "clip-a"
    );
    expect(phase.current).toBe("top");
    document.body.replaceChildren();
    vi.mocked(sendMessage).mockReset();
  });

  it("Given 対象が timeout で見つからない When 診断 Then エラーに要素なしが付く", async () => {
    vi.useFakeTimers();
    try {
      const promise = clickStudioButtonUntil(
        "Missing",
        () => null,
        "Missing ボタン",
        "pointer"
      );
      const assertion = expect(promise).rejects.toThrow(/要素なし/);
      await vi.runAllTimersAsync();
      await assertion;
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
    }
  });

  it("Given 対象ボタンが display:none When 診断 Then エラーに非表示理由が付く", async () => {
    vi.useFakeTimers();
    try {
      const button = visibleButton("Hidden");
      button.style.display = "none";
      document.body.append(button);
      const promise = clickStudioButtonUntil(
        "Hidden",
        () => null,
        "Hidden ボタン",
        "pointer"
      );
      const assertion = expect(promise).rejects.toThrow(/display:none/);
      await vi.runAllTimersAsync();
      await assertion;
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
    }
  });

  it("Given 対象ボタンが他要素に遮蔽される When 診断 Then エラーに遮蔽物が付く", async () => {
    vi.useFakeTimers();
    try {
      const button = visibleButton("Occluded");
      document.body.append(button);
      const occluder = document.createElement("div");
      occluder.id = "modal-backdrop";
      document.body.append(occluder);
      const original = document.elementFromPoint;
      document.elementFromPoint = () => occluder;

      const promise = clickStudioButtonUntil(
        "Occluded",
        () => null,
        "Occluded ボタン",
        "pointer"
      );
      const assertion = expect(promise).rejects.toThrow(
        /他要素に遮蔽.*modal-backdrop/
      );
      await vi.runAllTimersAsync();
      await assertion;
      document.elementFromPoint = original;
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
    }
  });

  it("Given 対象ボタンが拡張パネルに遮蔽される When 診断 Then エラーが suno-helper パネルを指す", async () => {
    vi.useFakeTimers();
    try {
      const button = visibleButton("BehindPanel");
      document.body.append(button);
      const panel = document.createElement("suno-helper-overlay");
      document.body.append(panel);
      const original = document.elementFromPoint;
      document.elementFromPoint = () => panel;

      const promise = clickStudioButtonUntil(
        "BehindPanel",
        () => null,
        "BehindPanel ボタン",
        "pointer"
      );
      const assertion = expect(promise).rejects.toThrow(
        /suno-helper パネルに遮蔽/
      );
      await vi.runAllTimersAsync();
      await assertion;
      document.elementFromPoint = original;
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
    }
  });
});

describe("Studio export の日本語 UI ラベル (#5209)", () => {
  it.each([
    ["プロジェクトメニュー", SUNO_LABELS.studioProjectMenu],
    ["ライブラリを開く", SUNO_LABELS.studioOpenLibrary],
    ["新しいトラックを追加", SUNO_LABELS.studioAddNewTrack],
    ["エクスポートメニュー", SUNO_LABELS.studioExportMenu],
  ])(
    "Given aria-label=%s のボタン When clickStudioAriaButtonUntil Then 一致して trusted click される",
    async (label, labels) => {
      const button = visibleButton("unused");
      button.setAttribute("aria-label", label);
      document.body.append(button);
      const target = document.createElement("div");
      target.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
      vi.mocked(sendMessage).mockImplementation(async (type) => {
        if (type === "sendTrustedClick") document.body.append(target);
        return undefined;
      });

      const found = await clickStudioAriaButtonUntil(
        labels,
        () => (document.body.contains(target) ? target : null),
        "対象要素"
      );

      expect(found).toBe(target);
      document.body.replaceChildren();
      vi.mocked(sendMessage).mockReset();
    }
  );

  it.each([
    ["新規プロジェクト", SUNO_LABELS.studioNewProject],
    ["新しい空のプロジェクト", SUNO_LABELS.studioNewEmptyProject],
    ["名前を変更", SUNO_LABELS.studioRename],
    ["すべての曲", SUNO_LABELS.studioAllSongs],
    ["トラック名を変更", SUNO_LABELS.studioRenameTrack],
    ["プロジェクトで", SUNO_LABELS.studioInProject],
    ["マルチトラック", SUNO_LABELS.studioMultitrack],
  ])(
    "Given textContent=%s のボタン When clickStudioButtonUntil Then 一致してクリックされる",
    async (label, labels) => {
      const button = visibleButton(label);
      document.body.append(button);
      const target = document.createElement("div");
      target.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
      button.addEventListener("pointerdown", () =>
        document.body.append(target)
      );

      const found = await clickStudioButtonUntil(
        labels,
        () => (document.body.contains(target) ? target : null),
        "対象要素",
        "pointer"
      );

      expect(found).toBe(target);
      document.body.replaceChildren();
    }
  );

  it("Given 日本語 UI の Studio Library When openStudioLibraryAllSongs Then ja ラベルで clip 一覧まで辿る", async () => {
    const openLibrary = visibleButton("ライブラリを開く");
    openLibrary.setAttribute("aria-label", "ライブラリを開く");
    document.body.append(openLibrary);

    // trusted click を送ったら対象座標の pointerdown と同等の遷移を起こす扱いにする。
    vi.mocked(sendMessage).mockImplementation(async (type) => {
      if (type !== "sendTrustedClick") return undefined;
      openLibrary.dispatchEvent(
        new PointerEvent("pointerdown", { bubbles: true })
      );
      return undefined;
    });
    openLibrary.addEventListener("pointerdown", () => {
      const allSongs = visibleButton("すべての曲");
      allSongs.addEventListener("pointerdown", () => {
        document.body.append(libraryClip("clip-a"));
      });
      document.body.append(allSongs);
    });

    await expect(openStudioLibraryAllSongs()).resolves.toHaveProperty(
      "dataset.clipId",
      "clip-a"
    );
    document.body.replaceChildren();
    vi.mocked(sendMessage).mockReset();
  });
});

describe("Studio track の rename (#5199)", () => {
  function createTrack(name: string): {
    track: HTMLElement;
    heading: HTMLElement;
  } {
    const track = document.createElement("div");
    track.dataset.trackId = "track-1";
    const heading = document.createElement("div");
    heading.setAttribute("role", "button");
    heading.textContent = name;
    heading.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 100, height: 20 }) as DOMRect;
    track.append(heading);
    track.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 100, height: 40 }) as DOMRect;
    document.body.append(track);
    return { track, heading };
  }

  function appendRenameMenuItem(
    label: string,
    onClick: () => void
  ): HTMLButtonElement {
    const item = document.createElement("button");
    item.textContent = label;
    item.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
    item.addEventListener("pointerdown", onClick);
    document.body.append(item);
    return item;
  }

  it("Given contextmenu sequence When track 見出しを右クリック Then button=2 で pointerdown→mouseup を送る", () => {
    const { heading } = createTrack("Audio Track");
    const seen: Array<{ type: string; button: number }> = [];
    for (const type of ["pointerdown", "mousedown", "contextmenu", "mouseup"]) {
      heading.addEventListener(type, (event) => {
        seen.push({ type, button: (event as MouseEvent).button });
      });
    }

    dispatchStudioContextMenu(heading);

    expect(seen).toEqual([
      { type: "pointerdown", button: 2 },
      { type: "mousedown", button: 2 },
      { type: "contextmenu", button: 2 },
      { type: "mouseup", button: 2 },
    ]);
    document.body.replaceChildren();
  });

  it("Given 右クリックで Rename track menu が開く When renameTrack Then ︙ ボタンを押さず rename する", async () => {
    const { track, heading } = createTrack("Audio Track");
    heading.addEventListener("contextmenu", () => {
      appendRenameMenuItem("Rename track", () => {
        const input = document.createElement("input");
        input.value = "Audio Track";
        input.getBoundingClientRect = () =>
          ({ left: 0, top: 0, width: 100, height: 20 }) as DOMRect;
        input.addEventListener("blur", () => {
          heading.textContent = input.value;
        });
        document.body.append(input);
        input.focus();
      });
    });
    const contextMenuButton = document.createElement("button");
    contextMenuButton.className = "track-menu-reveal";
    contextMenuButton.dataset.contextMenuTrigger = "true";
    contextMenuButton.addEventListener("pointerdown", () => {
      throw new Error("︙ ボタンは押されないはず");
    });
    track.append(contextMenuButton);

    await renameTrack(track, "Song A");

    expect(heading.textContent).toBe("Song A");
    document.body.replaceChildren();
  });

  it("Given 右クリックで menu が開かない When renameTrack Then ︙ ボタン click にフォールバックする", async () => {
    vi.useFakeTimers();
    try {
      const { track, heading } = createTrack("Audio Track");
      const contextMenuButton = document.createElement("button");
      contextMenuButton.className = "track-menu-reveal";
      contextMenuButton.dataset.contextMenuTrigger = "true";
      contextMenuButton.getBoundingClientRect = () =>
        ({ left: 0, top: 0, width: 20, height: 20 }) as DOMRect;
      contextMenuButton.addEventListener("pointerdown", () => {
        appendRenameMenuItem("Rename track", () => {
          const input = document.createElement("input");
          input.value = "Audio Track";
          input.getBoundingClientRect = () =>
            ({ left: 0, top: 0, width: 100, height: 20 }) as DOMRect;
          input.addEventListener("blur", () => {
            heading.textContent = input.value;
          });
          document.body.append(input);
          input.focus();
        });
      });
      track.append(contextMenuButton);

      const pending = renameTrack(track, "Song A");
      await vi.runAllTimersAsync();
      await pending;

      expect(heading.textContent).toBe("Song A");
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
    }
  });
});

describe("配置済み clip の長さ検証 (#5199)", () => {
  function createTrackWithClip(
    clipId: string,
    placedDurationText?: string
  ): HTMLElement {
    const track = document.createElement("div");
    track.dataset.trackId = "track-1";
    if (placedDurationText !== undefined) {
      const clip = document.createElement("div");
      clip.dataset.clipId = clipId;
      clip.textContent = placedDurationText;
      track.append(clip);
    }
    document.body.append(track);
    return track;
  }

  it("Given 配置済み clip が library と同じ長さ When verifyPlacedClipLength Then true を返す", async () => {
    const track = createTrackWithClip("clip-a", "Song A 3:20");

    await expect(verifyPlacedClipLength(track, "clip-a", 200)).resolves.toBe(
      true
    );
    document.body.replaceChildren();
  });

  it("Given 配置済み clip が short なまま When verifyPlacedClipLength Then 明示的なエラーで停止する", async () => {
    vi.useFakeTimers();
    try {
      const track = createTrackWithClip("clip-a", "2:00");
      const pending = verifyPlacedClipLength(track, "clip-a", 240);
      const expectation = expect(pending).rejects.toThrow(
        /ライブラリの曲長より短いまま/
      );
      await vi.runAllTimersAsync();
      await expectation;
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
    }
  });

  it("Given 配置直後は短いが伸びる clip When verifyPlacedClipLength Then 再計測で照合する", async () => {
    vi.useFakeTimers();
    try {
      const track = createTrackWithClip("clip-a", "2:00");
      const clip = track.querySelector<HTMLElement>("[data-clip-id]")!;
      setTimeout(() => {
        clip.textContent = "3:20";
      }, 1_000);

      const pending = verifyPlacedClipLength(track, "clip-a", 200);
      await vi.runAllTimersAsync();
      await expect(pending).resolves.toBe(true);
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
    }
  });

  it("Given 曲長表示を持たない clip When verifyPlacedClipLength Then 検証不能で false を返す", async () => {
    vi.useFakeTimers();
    try {
      const track = createTrackWithClip("clip-a", "Song A");
      const pending = verifyPlacedClipLength(track, "clip-a", 200);
      await vi.runAllTimersAsync();
      await expect(pending).resolves.toBe(false);
    } finally {
      vi.useRealTimers();
      document.body.replaceChildren();
    }
  });

  it("Given library 曲長が読めない When verifyPlacedClipLength Then false を返す", async () => {
    const track = createTrackWithClip("clip-a", "3:20");
    await expect(verifyPlacedClipLength(track, "clip-a", null)).resolves.toBe(
      false
    );
    document.body.replaceChildren();
  });
});
