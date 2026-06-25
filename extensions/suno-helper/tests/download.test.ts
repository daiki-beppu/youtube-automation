// Download all DOM 操作のユニットテスト (#1146)。
// triggerDownloadAll の各ステップを副作用注入で検証する。
// DOM を使わず mock deps のみで動作するため jsdom は不要。
import { describe, expect, it, vi } from "vitest";

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
    selectFormat: vi.fn(),
    clickConfirm: vi.fn(),
    sleep: vi.fn(async () => {}),
    ...overrides,
  };
}

describe("triggerDownloadAll", () => {
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

    // Step 1: More ボタンを click
    expect(deps.findMoreButton).toHaveBeenCalled();
    expect(moreButton.click).toHaveBeenCalled();

    // Step 2: Download all menu item を待って click
    expect(deps.waitForDownloadMenuItem).toHaveBeenCalled();
    expect(downloadMenuItem.click).toHaveBeenCalled();

    // Step 3: 形式選択モーダルを待つ
    expect(deps.waitForFormatModal).toHaveBeenCalled();

    // Step 4: 形式を選択
    expect(deps.selectFormat).toHaveBeenCalledWith(formatModal, "mp3");

    // Step 5: 確認ボタンを click
    expect(deps.clickConfirm).toHaveBeenCalledWith(formatModal);

    // settle sleep が各ステップ間で呼ばれる（5 回: More 後 / Download all 後 / modal 後 / format 選択後 / 確認後は無し → 4 回）
    expect(deps.sleep).toHaveBeenCalled();
  });

  it("More ボタンが見つからない場合は throw する", async () => {
    const deps = createMockDeps({
      findMoreButton: vi.fn(() => null),
    });

    await expect(triggerDownloadAll("mp3", deps)).rejects.toThrow(
      /More メニューボタン.*見つかりませんでした/,
    );
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

    await expect(triggerDownloadAll("mp3", deps)).rejects.toThrow(
      /Download all menu item/,
    );
    // selectFormat / clickConfirm は呼ばれない
    expect(deps.selectFormat).not.toHaveBeenCalled();
    expect(deps.clickConfirm).not.toHaveBeenCalled();
  });

  it("waitForFormatModal が throw した場合はそのまま伝播する", async () => {
    const deps = createMockDeps({
      waitForFormatModal: vi.fn(async () => {
        throw new Error("format modal timed out");
      }),
    });

    await expect(triggerDownloadAll("mp3", deps)).rejects.toThrow(
      /format modal timed out/,
    );
    expect(deps.selectFormat).not.toHaveBeenCalled();
  });

  it("selectFormat が throw した場合はそのまま伝播する", async () => {
    const deps = createMockDeps({
      selectFormat: vi.fn(() => {
        throw new Error('形式 "flac" に対応するオプションがモーダル内に見つかりませんでした');
      }),
    });

    await expect(triggerDownloadAll("flac", deps)).rejects.toThrow(
      /形式 "flac"/,
    );
    expect(deps.clickConfirm).not.toHaveBeenCalled();
  });
});
