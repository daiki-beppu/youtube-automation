import { simulateClick, sleep } from "../../shared/dom";
import { CLIP_LIST_SCROLLER_SELECTOR } from "../../shared/playlist-dom";

const MORE_BUTTON_SELECTOR = 'button[aria-label="More options"], button[aria-label="More menu contents"]';
const DESELECT_CLIP_BUTTON_SELECTOR = 'button[aria-label="Deselect clip"]';
const MULTI_SELECT_BUTTON_SELECTOR = ".multi-select-button";
const CLIP_ROW_SELECTOR = '[data-testid="clip-row"], .clip-row, article, [role="group"]';
const CONTEXT_MENU_SELECTOR = 'div[data-context-menu="true"]';
const DOWNLOAD_MENU_ITEM_TEXT = /download\s*all/i;
const FORMAT_MODAL_SELECTOR = "div.modal-class.modal-overlay";
const FORMAT_OPTION_SELECTOR = "button.flex.w-full";
const DOWNLOAD_CONFIRM_SELECTOR = "button.hxc-btn-variant-primary";
const MENU_APPEAR_POLL_MS = 10;
const MENU_APPEAR_TIMEOUT_MS = 1500;
const MAX_DOWNLOAD_MENU_ATTEMPTS = 3;
const MODAL_APPEAR_POLL_MS = 200;
const MODAL_APPEAR_TIMEOUT_MS = 10000;
const MODAL_CLOSE_POLL_MS = 200;
const MODAL_CLOSE_TIMEOUT_MS = 120000;
const SETTLE_AFTER_CLICK_MS = 500;

async function waitForElement<T extends HTMLElement>(
  selector: string,
  timeoutMs: number,
  pollMs: number,
  filter?: (el: T) => boolean,
): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const candidates = document.querySelectorAll<T>(selector);
    for (const el of candidates) {
      if (!filter || filter(el)) {
        return el;
      }
    }
    await sleep(pollMs);
  }
  throw new Error(`waitForElement timed out: selector="${selector}" (${timeoutMs}ms)`);
}

function findElementByTextContent<T extends HTMLElement>(
  parent: HTMLElement | Document,
  tagOrSelector: string,
  pattern: RegExp,
): T | null {
  const candidates = parent.querySelectorAll<T>(tagOrSelector);
  for (const el of candidates) {
    if (el.textContent && pattern.test(el.textContent.trim())) {
      return el;
    }
  }
  return null;
}

function resolveClipRowFromSelectButton(button: HTMLElement): HTMLElement | null {
  const explicitRow = button.closest<HTMLElement>(CLIP_ROW_SELECTOR);
  if (explicitRow) {
    return explicitRow;
  }
  const multiSelectWrapper = button.closest(MULTI_SELECT_BUTTON_SELECTOR);
  if (multiSelectWrapper?.parentElement) {
    const parent = multiSelectWrapper.parentElement;
    if (parent.querySelector("img") || parent.querySelector("a[href]")) {
      return parent;
    }
    return parent.parentElement ?? parent;
  }
  return button.closest<HTMLElement>("article");
}

function resolveClipRowFromMoreButton(button: HTMLElement): HTMLElement | null {
  return button.closest<HTMLElement>(CLIP_ROW_SELECTOR);
}

function collectSelectedClipRows(root: ParentNode): HTMLElement[] {
  const buttons = root.querySelectorAll<HTMLElement>(DESELECT_CLIP_BUTTON_SELECTOR);
  const rows: HTMLElement[] = [];
  const seen = new Set<HTMLElement>();
  for (const button of buttons) {
    const row = resolveClipRowFromSelectButton(button);
    if (row && !seen.has(row)) {
      seen.add(row);
      rows.push(row);
    }
  }
  return rows;
}

function findScopedMoreButton(): HTMLElement | null {
  const scroller = document.querySelector<HTMLElement>(CLIP_LIST_SCROLLER_SELECTOR);
  const root = scroller ?? document;
  for (const row of collectSelectedClipRows(root)) {
    const button = row.querySelector<HTMLElement>(MORE_BUTTON_SELECTOR);
    if (button) {
      return button;
    }
  }
  const moreButtons = root.querySelectorAll<HTMLElement>(MORE_BUTTON_SELECTOR);
  for (const button of moreButtons) {
    const row = resolveClipRowFromMoreButton(button);
    if (row?.querySelector(DESELECT_CLIP_BUTTON_SELECTOR)) {
      return button;
    }
  }
  return null;
}

async function waitForDownloadMenuItem(timeoutMs: number, pollMs: number): Promise<HTMLElement> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const menu = document.querySelector<HTMLElement>(CONTEXT_MENU_SELECTOR);
    if (menu) {
      const byLabel = menu.querySelector<HTMLElement>('button[aria-label="Download all"]');
      if (byLabel) return byLabel;
      const byText = findElementByTextContent<HTMLElement>(menu, "button", DOWNLOAD_MENU_ITEM_TEXT);
      if (byText) return byText;
    }
    await sleep(pollMs);
  }
  throw new Error(`"Download all" menu item が見つかりませんでした (${timeoutMs}ms)`);
}

function selectFormatInModal(modal: HTMLElement, format: string): void {
  const formatPattern = new RegExp(`^${format}$`, "i");
  const candidates = modal.querySelectorAll<HTMLButtonElement>(FORMAT_OPTION_SELECTOR);
  for (const btn of candidates) {
    if (btn.disabled) continue;
    if (btn.textContent && formatPattern.test(btn.textContent.trim())) {
      btn.click();
      return;
    }
  }
  throw new Error(
    `形式 "${format}" に対応するオプションがモーダル内に見つかりませんでした。` + "Suno の UI 変更の可能性があります。",
  );
}

function clickDownloadConfirm(modal: HTMLElement): void {
  const btn = modal.querySelector<HTMLButtonElement>(DOWNLOAD_CONFIRM_SELECTOR);
  if (!btn) {
    throw new Error("ダウンロード確認ボタンが見つかりませんでした。Suno の UI 変更の可能性があります。");
  }
  btn.click();
}

async function waitForFormatModalClose(modal: HTMLElement, timeoutMs: number, pollMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!modal.isConnected || !document.contains(modal) || !document.querySelector(FORMAT_MODAL_SELECTOR)) {
      return;
    }
    await sleep(pollMs);
  }
  throw new Error(
    `形式選択モーダルが閉じませんでした (${timeoutMs}ms)。` +
      "Suno 側のダウンロード準備が長引いているか、UI が変更された可能性があります。",
  );
}

export interface TriggerDownloadAllDeps {
  findMoreButton: () => HTMLElement | null;
  waitForDownloadMenuItem: (timeoutMs: number, pollMs: number) => Promise<HTMLElement>;
  waitForFormatModal: (timeoutMs: number, pollMs: number) => Promise<HTMLElement>;
  waitForModalClose: (modal: HTMLElement, timeoutMs: number, pollMs: number) => Promise<void>;
  selectFormat: (modal: HTMLElement, format: string) => void;
  clickConfirm: (modal: HTMLElement) => void;
  clickElement: (el: HTMLElement) => void;
  sleep: (ms: number) => Promise<void>;
}

function defaultDownloadDeps(): TriggerDownloadAllDeps {
  return {
    findMoreButton: findScopedMoreButton,
    waitForDownloadMenuItem: (timeoutMs, pollMs) => waitForDownloadMenuItem(timeoutMs, pollMs),
    waitForFormatModal: (timeoutMs, pollMs) => waitForElement<HTMLElement>(FORMAT_MODAL_SELECTOR, timeoutMs, pollMs),
    waitForModalClose: waitForFormatModalClose,
    selectFormat: selectFormatInModal,
    clickConfirm: clickDownloadConfirm,
    clickElement: simulateClick,
    sleep,
  };
}

export async function triggerDownloadAll(
  format: string,
  deps: TriggerDownloadAllDeps = defaultDownloadDeps(),
): Promise<void> {
  let downloadItem: HTMLElement | undefined;
  for (let attempt = 0; attempt < MAX_DOWNLOAD_MENU_ATTEMPTS; attempt += 1) {
    const moreBtn = deps.findMoreButton();
    if (!moreBtn) {
      throw new Error(
        `More メニューボタン (${MORE_BUTTON_SELECTOR}) が見つかりませんでした。` +
          "clip が multi-select されているか確認してください。",
      );
    }
    deps.clickElement(moreBtn);
    try {
      downloadItem = await deps.waitForDownloadMenuItem(MENU_APPEAR_TIMEOUT_MS, MENU_APPEAR_POLL_MS);
      break;
    } catch (error) {
      if (attempt === MAX_DOWNLOAD_MENU_ATTEMPTS - 1) {
        throw error;
      }
    }
  }
  if (!downloadItem) {
    throw new Error('"Download all" menu item が見つかりませんでした');
  }
  deps.clickElement(downloadItem);
  await deps.sleep(SETTLE_AFTER_CLICK_MS);

  let modal: HTMLElement;
  try {
    modal = await deps.waitForFormatModal(MODAL_APPEAR_TIMEOUT_MS, MODAL_APPEAR_POLL_MS);
  } catch {
    deps.clickElement(downloadItem);
    await deps.sleep(SETTLE_AFTER_CLICK_MS);
    modal = await deps.waitForFormatModal(MODAL_APPEAR_TIMEOUT_MS, MODAL_APPEAR_POLL_MS);
  }
  await deps.sleep(SETTLE_AFTER_CLICK_MS);

  deps.selectFormat(modal, format);
  await deps.sleep(SETTLE_AFTER_CLICK_MS);

  deps.clickConfirm(modal);
  await deps.waitForModalClose(modal, MODAL_CLOSE_TIMEOUT_MS, MODAL_CLOSE_POLL_MS);
}
