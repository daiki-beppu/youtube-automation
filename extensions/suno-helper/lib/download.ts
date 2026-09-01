import { simulateClick, sleep } from "../../shared/dom";
import { CLIP_LIST_SCROLLER_SELECTOR } from "../../shared/playlist-dom";

const MORE_BUTTON_SELECTOR =
  'button[aria-label="More options"], button[aria-label="More menu contents"]';
const DESELECT_CLIP_BUTTON_SELECTOR = 'button[aria-label="Deselect clip"]';
const MULTI_SELECT_BUTTON_SELECTOR = ".multi-select-button";
const CLIP_ROW_SELECTOR =
  '[data-testid="clip-row"], .clip-row, article, [role="group"]';
const CONTEXT_MENU_SELECTOR = 'div[data-context-menu="true"]';
const DOWNLOAD_MENU_ITEM_TEXT = /download\s*all/i;
// Suno の Tailwind class はリリースごとに変わるため、形式選択モーダルは
// WAI-ARIA の dialog role だけを安定した探索契約として使う (#4747)。
const FORMAT_MODAL_CANDIDATE_SELECTOR = '[role="dialog"]';
const BUTTON_SELECTOR = "button";
const DOWNLOAD_CONFIRM_LABEL = "Download";
const FORMAT_OPTION_LABELS = ["M4A", "MP3", "WAV"] as const;
const MENU_APPEAR_POLL_MS = 10;
const MENU_APPEAR_TIMEOUT_MS = 1500;
const MAX_DOWNLOAD_MENU_ATTEMPTS = 3;
const MODAL_APPEAR_POLL_MS = 200;
const MODAL_APPEAR_TIMEOUT_MS = 10000;
const MODAL_CLOSE_POLL_MS = 200;
const MODAL_CLOSE_TIMEOUT_MS = 120000;
const SETTLE_AFTER_CLICK_MS = 500;

function findElementByTextContent<T extends HTMLElement>(
  parent: HTMLElement | Document,
  tagOrSelector: string,
  pattern: RegExp
): T | null {
  const candidates = parent.querySelectorAll<T>(tagOrSelector);
  for (const el of candidates) {
    if (el.textContent && pattern.test(el.textContent.trim())) {
      return el;
    }
  }
  return null;
}

function findButtonByExactLabel(
  parent: HTMLElement,
  label: string
): HTMLButtonElement | null {
  for (const button of parent.querySelectorAll<HTMLButtonElement>(
    BUTTON_SELECTOR
  )) {
    const accessibleLabel =
      button.getAttribute("aria-label") ?? button.textContent?.trim();
    if (accessibleLabel?.toLowerCase() === label.toLowerCase()) {
      return button;
    }
  }
  return null;
}

function isVisibleModal(modal: HTMLElement): boolean {
  if (modal.hidden || modal.getAttribute("aria-hidden") === "true") {
    return false;
  }
  const style = getComputedStyle(modal);
  return style.display !== "none" && style.visibility !== "hidden";
}

function resolveFormatModal(): HTMLElement | null {
  const matchingModals = Array.from(
    document.querySelectorAll<HTMLElement>(FORMAT_MODAL_CANDIDATE_SELECTOR)
  ).filter(
    (modal) =>
      isVisibleModal(modal) &&
      FORMAT_OPTION_LABELS.every((label) =>
        findButtonByExactLabel(modal, label)
      ) &&
      findButtonByExactLabel(modal, DOWNLOAD_CONFIRM_LABEL)
  );
  if (matchingModals.length > 1) {
    throw new Error(
      "ダウンロード形式モーダルが複数見つかりました。Suno の UI 変更の可能性があります。"
    );
  }
  return matchingModals[0] ?? null;
}

async function waitForFormatModal(
  timeoutMs: number,
  pollMs: number
): Promise<HTMLElement> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const modal = resolveFormatModal();
    if (modal) {
      return modal;
    }
    await sleep(pollMs);
  }
  throw new Error(
    `Download 確認ボタンと M4A / MP3 / WAV を持つ可視モーダルが見つかりませんでした (${timeoutMs}ms)。` +
      "Suno の UI 変更の可能性があります。"
  );
}

function resolveClipRowFromSelectButton(
  button: HTMLElement
): HTMLElement | null {
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
  const buttons = root.querySelectorAll<HTMLElement>(
    DESELECT_CLIP_BUTTON_SELECTOR
  );
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
  const scroller = document.querySelector<HTMLElement>(
    CLIP_LIST_SCROLLER_SELECTOR
  );
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

async function waitForDownloadMenuItem(
  timeoutMs: number,
  pollMs: number
): Promise<HTMLElement> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const menu = document.querySelector<HTMLElement>(CONTEXT_MENU_SELECTOR);
    if (menu) {
      const byLabel = menu.querySelector<HTMLElement>(
        'button[aria-label="Download all"]'
      );
      if (byLabel) return byLabel;
      const byText = findElementByTextContent<HTMLElement>(
        menu,
        "button",
        DOWNLOAD_MENU_ITEM_TEXT
      );
      if (byText) return byText;
    }
    await sleep(pollMs);
  }
  throw new Error(
    `"Download all" menu item が見つかりませんでした (${timeoutMs}ms)`
  );
}

function selectFormatInModal(modal: HTMLElement, format: string): void {
  const formatPattern = new RegExp(`^${format}$`, "i");
  const candidates = modal.querySelectorAll<HTMLButtonElement>(BUTTON_SELECTOR);
  for (const btn of candidates) {
    if (btn.disabled) continue;
    if (btn.textContent && formatPattern.test(btn.textContent.trim())) {
      btn.click();
      return;
    }
  }
  throw new Error(
    `形式 "${format}" に対応するオプションがモーダル内に見つかりませんでした。` +
      "Suno の UI 変更の可能性があります。"
  );
}

function clickDownloadConfirm(modal: HTMLElement): void {
  const btn = findButtonByExactLabel(modal, DOWNLOAD_CONFIRM_LABEL);
  if (!btn) {
    throw new Error(
      "ダウンロード確認ボタンが見つかりませんでした。Suno の UI 変更の可能性があります。"
    );
  }
  btn.click();
}

async function waitForFormatModalClose(
  modal: HTMLElement,
  timeoutMs: number,
  pollMs: number
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!modal.isConnected || !document.contains(modal)) {
      return;
    }
    await sleep(pollMs);
  }
  throw new Error(
    `形式選択モーダルが閉じませんでした (${timeoutMs}ms)。` +
      "Suno 側のダウンロード準備が長引いているか、UI が変更された可能性があります。"
  );
}

export interface TriggerDownloadAllDeps {
  findMoreButton: () => HTMLElement | null;
  waitForDownloadMenuItem: (
    timeoutMs: number,
    pollMs: number
  ) => Promise<HTMLElement>;
  waitForFormatModal: (
    timeoutMs: number,
    pollMs: number
  ) => Promise<HTMLElement>;
  waitForModalClose: (
    modal: HTMLElement,
    timeoutMs: number,
    pollMs: number
  ) => Promise<void>;
  selectFormat: (modal: HTMLElement, format: string) => void;
  clickConfirm: (modal: HTMLElement) => void;
  clickElement: (el: HTMLElement) => void;
  sleep: (ms: number) => Promise<void>;
}

function defaultDownloadDeps(): TriggerDownloadAllDeps {
  return {
    findMoreButton: findScopedMoreButton,
    waitForDownloadMenuItem: (timeoutMs, pollMs) =>
      waitForDownloadMenuItem(timeoutMs, pollMs),
    waitForFormatModal,
    waitForModalClose: waitForFormatModalClose,
    selectFormat: selectFormatInModal,
    clickConfirm: clickDownloadConfirm,
    clickElement: simulateClick,
    sleep,
  };
}

export async function triggerDownloadAll(
  format: string,
  deps: TriggerDownloadAllDeps = defaultDownloadDeps()
): Promise<void> {
  let downloadItem: HTMLElement | undefined;
  for (let attempt = 0; attempt < MAX_DOWNLOAD_MENU_ATTEMPTS; attempt += 1) {
    const moreBtn = deps.findMoreButton();
    if (!moreBtn) {
      throw new Error(
        `More メニューボタン (${MORE_BUTTON_SELECTOR}) が見つかりませんでした。` +
          "clip が multi-select されているか確認してください。"
      );
    }
    deps.clickElement(moreBtn);
    try {
      downloadItem = await deps.waitForDownloadMenuItem(
        MENU_APPEAR_TIMEOUT_MS,
        MENU_APPEAR_POLL_MS
      );
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
    modal = await deps.waitForFormatModal(
      MODAL_APPEAR_TIMEOUT_MS,
      MODAL_APPEAR_POLL_MS
    );
  } catch {
    deps.clickElement(downloadItem);
    await deps.sleep(SETTLE_AFTER_CLICK_MS);
    modal = await deps.waitForFormatModal(
      MODAL_APPEAR_TIMEOUT_MS,
      MODAL_APPEAR_POLL_MS
    );
  }
  await deps.sleep(SETTLE_AFTER_CLICK_MS);

  deps.selectFormat(modal, format);
  await deps.sleep(SETTLE_AFTER_CLICK_MS);

  deps.clickConfirm(modal);
  await deps.waitForModalClose(
    modal,
    MODAL_CLOSE_TIMEOUT_MS,
    MODAL_CLOSE_POLL_MS
  );
}
