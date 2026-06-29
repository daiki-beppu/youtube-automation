// @vitest-environment jsdom
// Download all DOM 操作のユニットテスト (#1146)。
// triggerDownloadAll の各ステップを副作用注入で検証する。
// DOM を使わず mock deps のみで動作するため jsdom は不要。
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TriggerDownloadAllDeps } from "../lib/download";
import { triggerDownloadAll } from "../lib/download";

/** click() を持つ stub 要素。jsdom に依存しない。 */
function stubElement(): HTMLElement {
  return { click: vi.fn() } as unknown as HTMLElement;
}

function createMockDeps(overrides?: Partial<TriggerDownloadAllDeps>): TriggerDownloadAllDeps {
  const moreButton = stubElement();
  const downloadMenuItem = stubElement();
  const formatModal = stubElement();

  return {
    findMoreButton: vi.fn(() => moreButton),
    waitForDownloadMenuItem: vi.fn(async () => downloadMenuItem),
    waitForFormatModal: vi.fn(async () => formatModal),
    waitForModalClose: vi.fn(async () => {}),
    selectFormat: vi.fn(),
    clickConfirm: vi.fn(),
    clickElement: vi.fn(),
    sleep: vi.fn(async () => {}),
    ...overrides,
  };
}

describe("triggerDownloadAll", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
  });

  it("正常フロー: More → Download all → 形式選択 → 確認の順序で操作する", async () => {
    const moreButton = stubElement();
    const downloadMenuItem = stubElement();
    const formatModal = stubElement();

    const deps = createMockDeps({
      findMoreButton: vi.fn(() => moreButton),
      waitForDownloadMenuItem: vi.fn(async () => downloadMenuItem),
      waitForFormatModal: vi.fn(async () => formatModal),
    });

    await triggerDownloadAll("mp3", deps);

    // Step 1: More ボタンを click（simulateClick 経由）
    expect(deps.findMoreButton).toHaveBeenCalled();
    expect(deps.clickElement).toHaveBeenCalledWith(moreButton);

    // Step 2: Download all menu item を待って click
    expect(deps.waitForDownloadMenuItem).toHaveBeenCalled();
    expect(deps.clickElement).toHaveBeenCalledWith(downloadMenuItem);

    // Step 3: 形式選択モーダルを待つ
    expect(deps.waitForFormatModal).toHaveBeenCalled();

    // Step 4: 形式を選択
    expect(deps.selectFormat).toHaveBeenCalledWith(formatModal, "mp3");

    // Step 5: 確認ボタンを click
    expect(deps.clickConfirm).toHaveBeenCalledWith(formatModal);
    expect(deps.waitForModalClose).toHaveBeenCalledWith(formatModal, expect.any(Number), expect.any(Number));

    expect(deps.sleep).toHaveBeenCalled();
  });

  it("More ボタンが見つからない場合は throw する", async () => {
    const deps = createMockDeps({
      findMoreButton: vi.fn(() => null),
    });

    await expect(triggerDownloadAll("mp3", deps)).rejects.toThrow(/More メニューボタン.*見つかりませんでした/);
  });

  it("format 引数が selectFormat に正しく渡される (wav)", async () => {
    const deps = createMockDeps();
    await triggerDownloadAll("wav", deps);
    expect(deps.selectFormat).toHaveBeenCalledWith(expect.anything(), "wav");
  });

  it("format 引数が selectFormat に正しく渡される (m4a)", async () => {
    const deps = createMockDeps();
    await triggerDownloadAll("m4a", deps);
    expect(deps.selectFormat).toHaveBeenCalledWith(expect.anything(), "m4a");
  });

  it("waitForDownloadMenuItem が throw した場合はそのまま伝播する", async () => {
    const deps = createMockDeps({
      waitForDownloadMenuItem: vi.fn(async () => {
        throw new Error("Download all menu item が見つかりませんでした");
      }),
    });

    await expect(triggerDownloadAll("mp3", deps)).rejects.toThrow(/Download all menu item/);
    // selectFormat / clickConfirm は呼ばれない
    expect(deps.selectFormat).not.toHaveBeenCalled();
    expect(deps.clickConfirm).not.toHaveBeenCalled();
  });

  it("waitForFormatModal が 1 回目に throw した場合は Download all を再クリックして成功できる", async () => {
    const formatModal = stubElement();
    const deps = createMockDeps({
      waitForFormatModal: vi
        .fn()
        .mockRejectedValueOnce(new Error("format modal timed out"))
        .mockResolvedValueOnce(formatModal),
    });

    await triggerDownloadAll("mp3", deps);

    expect(deps.waitForFormatModal).toHaveBeenCalledTimes(2);
    expect(deps.clickElement).toHaveBeenCalledTimes(3);
    expect(deps.selectFormat).toHaveBeenCalledWith(formatModal, "mp3");
  });

  it("waitForFormatModal が 2 回 throw した場合はそのまま伝播する", async () => {
    const deps = createMockDeps({
      waitForFormatModal: vi.fn(async () => {
        throw new Error("format modal timed out");
      }),
    });

    await expect(triggerDownloadAll("mp3", deps)).rejects.toThrow(/format modal timed out/);
    expect(deps.waitForFormatModal).toHaveBeenCalledTimes(2);
    expect(deps.selectFormat).not.toHaveBeenCalled();
  });

  it("selectFormat が throw した場合はそのまま伝播する", async () => {
    const deps = createMockDeps({
      selectFormat: vi.fn(() => {
        throw new Error('形式 "flac" に対応するオプションがモーダル内に見つかりませんでした');
      }),
    });

    await expect(triggerDownloadAll("flac", deps)).rejects.toThrow(/形式 "flac"/);
    expect(deps.clickConfirm).not.toHaveBeenCalled();
  });

  it("waitForModalClose が throw した場合はそのまま伝播する", async () => {
    const deps = createMockDeps({
      waitForModalClose: vi.fn(async () => {
        throw new Error("形式選択モーダルが閉じませんでした");
      }),
    });

    await expect(triggerDownloadAll("mp3", deps)).rejects.toThrow(/形式選択モーダル/);
    expect(deps.clickConfirm).toHaveBeenCalled();
  });

  it("DOM fixture: default deps で More → Download all → MP3 → Download を操作する", async () => {
    const clicked: string[] = [];
    vi.stubGlobal("PointerEvent", MouseEvent);
    document.body.innerHTML = `
      <div class="clip-browser-list-scroller">
        <article>
          <img src="clip.jpg" alt="" />
          <div class="multi-select-button"><button aria-label="Deselect clip">Selected</button></div>
          <button aria-label="More options">...</button>
        </article>
      </div>
      <div data-context-menu="true">
        <button aria-label="Download all">Download all</button>
      </div>
      <div class="modal-class modal-overlay">
        <button class="flex w-full">M4A</button>
        <button class="flex w-full">MP3</button>
        <button class="flex w-full">WAV</button>
        <button class="hxc-btn-variant-primary">Download</button>
      </div>
    `;
    const more = document.querySelector<HTMLButtonElement>('button[aria-label="More options"]')!;
    const downloadAll = document.querySelector<HTMLButtonElement>('button[aria-label="Download all"]')!;
    const mp3 = Array.from(document.querySelectorAll<HTMLButtonElement>("button.flex.w-full")).find(
      (button) => button.textContent?.trim() === "MP3",
    )!;
    const confirm = document.querySelector<HTMLButtonElement>("button.hxc-btn-variant-primary")!;
    more.addEventListener("click", () => clicked.push("more"));
    downloadAll.addEventListener("click", () => clicked.push("download-all"));
    mp3.addEventListener("click", () => clicked.push("mp3"));
    confirm.addEventListener("click", () => {
      clicked.push("confirm");
      document.querySelector(".modal-class.modal-overlay")?.remove();
    });

    await triggerDownloadAll("mp3");

    expect(clicked).toEqual(["more", "download-all", "mp3", "confirm"]);
  });

  it("DOM fixture: default deps は文書先頭の無関係な More ではなく selected clip row の More を押す", async () => {
    const clicked: string[] = [];
    vi.stubGlobal("PointerEvent", MouseEvent);
    document.body.innerHTML = `
      <button aria-label="More options" data-testid="unrelated-more">...</button>
      <div class="clip-browser-list-scroller">
        <article>
          <img src="clip.jpg" alt="" />
          <div class="multi-select-button"><button aria-label="Deselect clip">Selected</button></div>
          <button aria-label="More options" data-testid="selected-row-more">...</button>
        </article>
      </div>
      <div data-context-menu="true">
        <button aria-label="Download all">Download all</button>
      </div>
      <div class="modal-class modal-overlay">
        <button class="flex w-full">MP3</button>
        <button class="hxc-btn-variant-primary">Download</button>
      </div>
    `;
    document
      .querySelector<HTMLButtonElement>('[data-testid="unrelated-more"]')!
      .addEventListener("click", () => clicked.push("unrelated-more"));
    document
      .querySelector<HTMLButtonElement>('[data-testid="selected-row-more"]')!
      .addEventListener("click", () => clicked.push("selected-row-more"));
    document
      .querySelector<HTMLButtonElement>('button[aria-label="Download all"]')!
      .addEventListener("click", () => clicked.push("download-all"));
    document
      .querySelector<HTMLButtonElement>("button.flex.w-full")!
      .addEventListener("click", () => clicked.push("mp3"));
    document.querySelector<HTMLButtonElement>("button.hxc-btn-variant-primary")!.addEventListener("click", () => {
      clicked.push("confirm");
      document.querySelector(".modal-class.modal-overlay")?.remove();
    });

    await triggerDownloadAll("mp3");

    expect(clicked).toEqual(["selected-row-more", "download-all", "mp3", "confirm"]);
  });

  it("DOM fixture: list view の clip-row 配下にある More を押す", async () => {
    const clicked: string[] = [];
    vi.stubGlobal("PointerEvent", MouseEvent);
    document.body.innerHTML = `
      <div class="clip-browser-list-scroller">
        <div class="relative">
          <div data-testid="clip-row" role="group" class="clip-row" aria-label="Smoke Test Groove">
            <div class="row-main">
              <div class="multi-select-button"><button aria-label="Deselect clip">Selected</button></div>
              <span role="button" aria-label="Play Smoke Test Groove">Smoke Test Groove</span>
            </div>
            <button aria-label="More options" data-testid="list-row-more">...</button>
          </div>
        </div>
      </div>
      <div data-context-menu="true">
        <button aria-label="Download all">Download all</button>
      </div>
      <div class="modal-class modal-overlay">
        <button class="flex w-full">M4A</button>
        <button class="hxc-btn-variant-primary">Download</button>
      </div>
    `;
    document
      .querySelector<HTMLButtonElement>('[data-testid="list-row-more"]')!
      .addEventListener("click", () => clicked.push("list-row-more"));
    document
      .querySelector<HTMLButtonElement>('button[aria-label="Download all"]')!
      .addEventListener("click", () => clicked.push("download-all"));
    document
      .querySelector<HTMLButtonElement>("button.flex.w-full")!
      .addEventListener("click", () => clicked.push("m4a"));
    document.querySelector<HTMLButtonElement>("button.hxc-btn-variant-primary")!.addEventListener("click", () => {
      clicked.push("confirm");
      document.querySelector(".modal-class.modal-overlay")?.remove();
    });

    await triggerDownloadAll("m4a");

    expect(clicked).toEqual(["list-row-more", "download-all", "m4a", "confirm"]);
  });

  it("DOM fixture: selected clip row に More が無ければ未選択 row の More を押さず throw する", async () => {
    const clicked: string[] = [];
    vi.stubGlobal("PointerEvent", MouseEvent);
    document.body.innerHTML = `
      <div class="clip-browser-list-scroller">
        <article>
          <img src="selected.jpg" alt="" />
          <div class="multi-select-button"><button aria-label="Deselect clip">Selected</button></div>
        </article>
        <article>
          <img src="unselected.jpg" alt="" />
          <div class="multi-select-button"><button aria-label="Select clip">Unselected</button></div>
          <button aria-label="More options" data-testid="unselected-more">...</button>
        </article>
      </div>
    `;
    document
      .querySelector<HTMLButtonElement>('[data-testid="unselected-more"]')!
      .addEventListener("click", () => clicked.push("unselected-more"));

    await expect(triggerDownloadAll("mp3")).rejects.toThrow(/More メニューボタン.*見つかりませんでした/);
    expect(clicked).toEqual([]);
  });

  it("DOM fixture: default deps は aria-label が無い Download all を text fallback で選ぶ", async () => {
    const clicked: string[] = [];
    vi.stubGlobal("PointerEvent", MouseEvent);
    document.body.innerHTML = `
      <div class="clip-browser-list-scroller">
        <article>
          <img src="clip.jpg" alt="" />
          <div class="multi-select-button"><button aria-label="Deselect clip">Selected</button></div>
          <button aria-label="More options">...</button>
        </article>
      </div>
      <div data-context-menu="true">
        <button>Download all</button>
      </div>
      <div class="modal-class modal-overlay">
        <button class="flex w-full">MP3</button>
        <button class="hxc-btn-variant-primary">Download</button>
      </div>
    `;
    const downloadAll = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.textContent?.trim() === "Download all",
    )!;
    downloadAll.addEventListener("click", () => clicked.push("download-all"));
    document.querySelector<HTMLButtonElement>("button.hxc-btn-variant-primary")!.addEventListener("click", () => {
      clicked.push("confirm");
      document.querySelector(".modal-class.modal-overlay")?.remove();
    });

    await triggerDownloadAll("mp3");

    expect(clicked).toEqual(["download-all", "confirm"]);
  });

  it("DOM fixture: default deps は format button が disabled なら throw する", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    document.body.innerHTML = `
      <div class="clip-browser-list-scroller">
        <article>
          <img src="clip.jpg" alt="" />
          <div class="multi-select-button"><button aria-label="Deselect clip">Selected</button></div>
          <button aria-label="More options">...</button>
        </article>
      </div>
      <div data-context-menu="true"><button>Download all</button></div>
      <div class="modal-class modal-overlay">
        <button class="flex w-full" disabled>MP3</button>
        <button class="hxc-btn-variant-primary">Download</button>
      </div>
    `;

    await expect(triggerDownloadAll("mp3")).rejects.toThrow(/形式 "mp3"/);
  });

  it("DOM fixture: default deps は format button が無ければ throw する", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    document.body.innerHTML = `
      <div class="clip-browser-list-scroller">
        <article>
          <img src="clip.jpg" alt="" />
          <div class="multi-select-button"><button aria-label="Deselect clip">Selected</button></div>
          <button aria-label="More options">...</button>
        </article>
      </div>
      <div data-context-menu="true"><button>Download all</button></div>
      <div class="modal-class modal-overlay">
        <button class="flex w-full">WAV</button>
        <button class="hxc-btn-variant-primary">Download</button>
      </div>
    `;

    await expect(triggerDownloadAll("mp3")).rejects.toThrow(/形式 "mp3"/);
  });

  it("DOM fixture: default deps は confirm button が無ければ throw する", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    document.body.innerHTML = `
      <div class="clip-browser-list-scroller">
        <article>
          <img src="clip.jpg" alt="" />
          <div class="multi-select-button"><button aria-label="Deselect clip">Selected</button></div>
          <button aria-label="More options">...</button>
        </article>
      </div>
      <div data-context-menu="true"><button>Download all</button></div>
      <div class="modal-class modal-overlay">
        <button class="flex w-full">MP3</button>
      </div>
    `;

    await expect(triggerDownloadAll("mp3")).rejects.toThrow(/ダウンロード確認ボタン/);
  });
});
