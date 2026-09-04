import { sendMessage } from "./messaging";

const STUDIO_CLIP_DRAG_TYPE = "application/x-suno-studio-clip";
const DOM_TIMEOUT_MS = 30_000;
const DOM_POLL_MS = 200;

export interface StudioExportRequest {
  collectionId: string;
  clipIds: string[];
}

export interface StudioExportDeps {
  createEmptyProject: () => Promise<void>;
  renameProject: (name: string) => Promise<void>;
  openLibrary: () => Promise<void>;
  placeClipOnTrackAtStart: (
    clipId: string,
    trackIndex: number
  ) => Promise<string>;
  countPlacedClips: () => Promise<number>;
  readTrackNames: () => Promise<string[]>;
  openExportMenu: () => Promise<void>;
  clickMultitrackExport: () => Promise<void>;
}

type Button = HTMLButtonElement;

function isVisible(element: Element): boolean {
  if (!(element instanceof HTMLElement) || element.hidden) return false;
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return (
    element.getAttribute("aria-hidden") !== "true" &&
    style.display !== "none" &&
    style.visibility !== "hidden" &&
    rect.width > 0 &&
    rect.height > 0
  );
}

async function waitForElement<T extends Element>(
  find: () => T | null,
  description: string
): Promise<T> {
  const deadline = Date.now() + DOM_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const element = find();
    if (element && isVisible(element)) return element;
    await new Promise((resolve) => setTimeout(resolve, DOM_POLL_MS));
  }
  throw new Error(`Studio の ${description} が見つかりません`);
}

function buttonByName(name: string): Button | null {
  return (
    Array.from(document.querySelectorAll<Button>("button")).find(
      (button) => button.textContent?.trim() === name && isVisible(button)
    ) ?? null
  );
}

function buttonByAriaLabel(label: string): Button | null {
  const element = document.querySelector<Button>(
    `button[aria-label="${label}"]`
  );
  return element && isVisible(element) ? element : null;
}

async function clickButtonByName(name: string): Promise<void> {
  const button = await waitForElement(
    () => buttonByName(name),
    `${name} ボタン`
  );
  if (button.disabled) {
    throw new Error(`Studio の ${name} ボタンが無効です`);
  }
  button.click();
}

async function clickButtonByAriaLabel(label: string): Promise<void> {
  const button = await waitForElement(
    () => buttonByAriaLabel(label),
    `${label} ボタン`
  );
  if (button.disabled) {
    throw new Error(`Studio の ${label} ボタンが無効です`);
  }
  button.click();
}

async function waitForTrackCount(expected: number): Promise<HTMLElement[]> {
  await waitForElement(
    () =>
      document.querySelectorAll<HTMLElement>("[data-track-id]").length ===
      expected
        ? document.querySelector<HTMLElement>("[data-track-id]")
        : null,
    `track ${expected} 件`
  );
  return Array.from(document.querySelectorAll<HTMLElement>("[data-track-id]"));
}

function setInputValue(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value"
  )?.set;
  if (!setter) throw new Error("Studio の入力値を更新できません");
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function dispatchPointerClick(element: HTMLElement): void {
  const rect = element.getBoundingClientRect();
  const common = {
    bubbles: true,
    cancelable: true,
    composed: true,
    clientX: rect.left + rect.width / 2,
    clientY: rect.top + rect.height / 2,
    button: 0,
  };
  const pointer = {
    ...common,
    pointerId: 1,
    pointerType: "mouse",
    isPrimary: true,
  };
  element.dispatchEvent(new PointerEvent("pointerover", pointer));
  element.dispatchEvent(new PointerEvent("pointerenter", pointer));
  element.dispatchEvent(new MouseEvent("mouseover", common));
  element.dispatchEvent(new MouseEvent("mouseenter", common));
  element.dispatchEvent(
    new PointerEvent("pointerdown", { ...pointer, buttons: 1 })
  );
  element.dispatchEvent(new MouseEvent("mousedown", { ...common, buttons: 1 }));
  element.dispatchEvent(new PointerEvent("pointerup", pointer));
  element.dispatchEvent(new MouseEvent("mouseup", common));
  element.dispatchEvent(new MouseEvent("click", common));
}

function findLibraryScroller(element: Element): HTMLElement | null {
  let current: HTMLElement | null = element.parentElement;
  while (current) {
    if (
      getComputedStyle(current).overflowY === "auto" &&
      current.clientHeight > 0
    ) {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

async function findLibraryClip(clipId: string): Promise<HTMLElement> {
  const selector = `[draggable="true"][data-clip-id="${CSS.escape(clipId)}"]`;
  const firstVisibleClip = await waitForElement(
    () =>
      document.querySelector<HTMLElement>('[draggable="true"][data-clip-id]'),
    "Library の clip 一覧"
  );
  const scroller = findLibraryScroller(firstVisibleClip);
  if (!scroller)
    throw new Error("Studio の Library scroll 領域が見つかりません");
  const deadline = Date.now() + DOM_TIMEOUT_MS;
  scroller.scrollTop = 0;
  while (Date.now() < deadline) {
    const clip = document.querySelector<HTMLElement>(selector);
    if (clip && isVisible(clip)) return clip;
    const before = scroller.scrollTop;
    scroller.scrollTop = Math.min(
      scroller.scrollHeight,
      before + Math.max(200, scroller.clientHeight * 0.8)
    );
    scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, DOM_POLL_MS));
    if (scroller.scrollTop === before) break;
  }
  throw new Error(`Studio Library に clip ${clipId} が見つかりません`);
}

function dispatchClipDrop(
  source: HTMLElement,
  track: HTMLElement,
  clipId: string
): void {
  const dropTarget = document.querySelector<HTMLElement>(
    "[data-studio-main-canvas]"
  )?.parentElement;
  if (!dropTarget) throw new Error("Studio の timeline が見つかりません");
  const dataTransfer = new DataTransfer();
  const trackRect = track.getBoundingClientRect();
  const dropTargetRect = dropTarget.getBoundingClientRect();
  const clientX = dropTargetRect.left + trackRect.width + 10;
  const clientY = trackRect.top + trackRect.height / 2;
  const event = (type: string, target: HTMLElement): void => {
    target.dispatchEvent(
      new DragEvent(type, {
        bubbles: true,
        cancelable: true,
        dataTransfer,
        clientX,
        clientY,
      })
    );
  };
  event("dragstart", source);
  if (dataTransfer.getData(STUDIO_CLIP_DRAG_TYPE) !== clipId) {
    throw new Error(`Studio clip ${clipId} の drag data を作成できません`);
  }
  event("dragenter", dropTarget);
  event("dragover", dropTarget);
  event("drop", dropTarget);
  event("dragend", source);
}

function libraryClipTitle(source: HTMLElement, clipId: string): string {
  const playButton = source.querySelector<HTMLButtonElement>(
    'button[aria-label="Play"]'
  );
  const title = playButton?.parentElement?.nextElementSibling
    ?.querySelector<HTMLElement>(":scope > span")
    ?.textContent?.trim();
  if (!title) {
    throw new Error(`Studio Library の clip ${clipId} から曲名を読めません`);
  }
  return title;
}

function trackName(track: HTMLElement): string | null {
  return (
    Array.from(track.querySelectorAll<HTMLElement>('[role="button"]'))
      .find((element) => element.textContent?.trim())
      ?.textContent?.trim() ?? null
  );
}

async function renameTrack(track: HTMLElement, name: string): Promise<void> {
  const currentName = trackName(track);
  if (!currentName) throw new Error("Studio の track 名を読めません");
  const menu = track.querySelector<HTMLButtonElement>(
    'button.track-menu-reveal[data-context-menu-trigger="true"]'
  );
  if (!menu) throw new Error("Studio の track menu が見つかりません");
  dispatchPointerClick(menu);
  const renameButton = await waitForElement(
    () => buttonByName("Rename Track"),
    "Rename Track ボタン"
  );
  dispatchPointerClick(renameButton);
  const input = await waitForElement(
    () =>
      Array.from(document.body.children).find(
        (element): element is HTMLInputElement =>
          element instanceof HTMLInputElement &&
          element.value === currentName &&
          isVisible(element)
      ) ?? null,
    "track 名入力"
  );
  setInputValue(input, name);
  input.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Enter", bubbles: true })
  );
  input.dispatchEvent(
    new KeyboardEvent("keyup", { key: "Enter", bubbles: true })
  );
  await waitForElement(
    () => (trackName(track) === name ? track : null),
    `track 名 ${name}`
  );
}

function createBrowserStudioExportDeps(): StudioExportDeps {
  return {
    async createEmptyProject() {
      const location = new URL(window.location.href);
      if (
        location.origin !== "https://suno.com" ||
        location.pathname !== "/studio"
      ) {
        throw new Error("Studio ページを開けませんでした");
      }
      await clickButtonByAriaLabel("Project menu");
      await clickButtonByName("New Project");
      await clickButtonByName("New empty project");
      await waitForElement(
        () =>
          buttonByAriaLabel("Project menu")?.textContent?.trim() ===
          "Untitled Project"
            ? buttonByAriaLabel("Project menu")
            : null,
        "空 project"
      );
    },
    async renameProject(name) {
      await clickButtonByAriaLabel("Project menu");
      await clickButtonByName("Rename");
      const input = await waitForElement(
        () =>
          document.querySelector<HTMLInputElement>(
            'input[aria-label="Project name"]'
          ),
        "Project name 入力"
      );
      setInputValue(input, name);
      input.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true })
      );
      input.dispatchEvent(
        new KeyboardEvent("keyup", { key: "Enter", bubbles: true })
      );
      await waitForElement(
        () =>
          buttonByAriaLabel("Project menu")?.textContent?.trim() === name
            ? buttonByAriaLabel("Project menu")
            : null,
        `project 名 ${name}`
      );
    },
    async openLibrary() {
      await clickButtonByAriaLabel("Open library");
      await clickButtonByName("All Songs");
      await waitForElement(
        () =>
          document.querySelector<HTMLElement>(
            '[draggable="true"][data-clip-id]'
          ),
        "Library の clip 一覧"
      );
    },
    async placeClipOnTrackAtStart(clipId, trackIndex) {
      if (trackIndex > 0) {
        await clickButtonByAriaLabel("Add new track");
        await clickButtonByName("Add Audio track");
      }
      const tracks = await waitForTrackCount(trackIndex + 1);
      const source = await findLibraryClip(clipId);
      const title = libraryClipTitle(source, clipId);
      dispatchClipDrop(source, tracks[trackIndex], clipId);
      await renameTrack(tracks[trackIndex], title);
      return title;
    },
    async countPlacedClips() {
      await clickButtonByName("In Project");
      await new Promise((resolve) => setTimeout(resolve, DOM_POLL_MS));
      return document.querySelectorAll('[draggable="true"][data-clip-id]')
        .length;
    },
    async readTrackNames() {
      return Array.from(
        document.querySelectorAll<HTMLElement>("[data-track-id]")
      ).map((track, index) => {
        const name = trackName(track);
        if (!name) {
          throw new Error(`Studio の track ${index + 1} 名を読めません`);
        }
        return name;
      });
    },
    async openExportMenu() {
      await clickButtonByAriaLabel("Export menu");
    },
    async clickMultitrackExport() {
      const button = await waitForElement(
        () => buttonByName("Multitrack"),
        "Multitrack export ボタン"
      );
      if (button.disabled || button.getAttribute("aria-disabled") === "true") {
        throw new Error(
          "Studio の Multitrack export が利用できません。Premier プランを確認してください"
        );
      }
      button.click();
    },
  };
}

export async function exportStudioMultitrack(
  request: StudioExportRequest,
  deps: StudioExportDeps
): Promise<void> {
  if (request.clipIds.length === 0) {
    throw new Error("Studio export に必要な clip ID がありません");
  }
  await deps.createEmptyProject();
  await deps.renameProject(request.collectionId);
  await deps.openLibrary();
  const expectedTrackNames: string[] = [];
  for (const [trackIndex, clipId] of request.clipIds.entries()) {
    expectedTrackNames.push(
      await deps.placeClipOnTrackAtStart(clipId, trackIndex)
    );
  }
  const placedCount = await deps.countPlacedClips();
  if (placedCount !== request.clipIds.length) {
    throw new Error(
      `Studio track 数が一致しません: expected ${request.clipIds.length}, got ${placedCount}`
    );
  }
  const actualTrackNames = await deps.readTrackNames();
  for (const [index, expectedName] of expectedTrackNames.entries()) {
    const actualName = actualTrackNames[index];
    if (actualName !== expectedName) {
      throw new Error(
        `Studio track 名が一致しません: track ${index + 1} expected ${expectedName}, got ${actualName}`
      );
    }
  }
  await deps.openExportMenu();
  await deps.clickMultitrackExport();
}

export function performStudioMultitrackExport(
  request: StudioExportRequest
): Promise<void> {
  return exportStudioMultitrack(request, createBrowserStudioExportDeps());
}

export async function requestStudioMultitrackExport(
  request: StudioExportRequest
): Promise<void> {
  const result = await sendMessage("startStudioExport", request);
  if (!result?.ok) {
    throw new Error(result?.message ?? "Studio export を開始できませんでした");
  }
}
