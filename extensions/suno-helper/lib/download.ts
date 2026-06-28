import { simulateClick, sleep } from "../../shared/dom";

const MORE_BUTTON_SELECTOR = 'button[aria-label="More options"]';
const CONTEXT_MENU_SELECTOR = 'div[data-context-menu="true"]';
const DOWNLOAD_MENU_ITEM_TEXT = /download\s*all/i;
const FORMAT_MODAL_SELECTOR = "div.modal-class.modal-overlay";
const FORMAT_OPTION_SELECTOR = "button.flex.w-full";
const DOWNLOAD_CONFIRM_SELECTOR = "button.hxc-btn-variant-primary";
const MENU_APPEAR_POLL_MS = 100;
const MENU_APPEAR_TIMEOUT_MS = 5000;
const MODAL_APPEAR_POLL_MS = 200;
const MODAL_APPEAR_TIMEOUT_MS = 10000;
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

/** triggerDownloadAll の副作用注入点。テスタビリティのため DOM 操作を差し替え可能にする。 */
export interface TriggerDownloadAllDeps {
  findMoreButton: () => HTMLElement | null;
  waitForDownloadMenuItem: (timeoutMs: number, pollMs: number) => Promise<HTMLElement>;
  waitForFormatModal: (timeoutMs: number, pollMs: number) => Promise<HTMLElement>;
  selectFormat: (modal: HTMLElement, format: string) => void;
  clickConfirm: (modal: HTMLElement) => void;
  clickElement: (el: HTMLElement) => void;
  sleep: (ms: number) => Promise<void>;
}

/** デフォルトの DOM 実装。 */
function defaultDownloadDeps(): TriggerDownloadAllDeps {
  return {
    findMoreButton: () => document.querySelector<HTMLElement>(MORE_BUTTON_SELECTOR),
    waitForDownloadMenuItem: (timeoutMs, pollMs) => waitForDownloadMenuItem(timeoutMs, pollMs),
    waitForFormatModal: (timeoutMs, pollMs) => waitForElement<HTMLElement>(FORMAT_MODAL_SELECTOR, timeoutMs, pollMs),
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
  const moreBtn = deps.findMoreButton();
  if (!moreBtn) {
    throw new Error(
      `More メニューボタン (${MORE_BUTTON_SELECTOR}) が見つかりませんでした。` +
        "clip が multi-select されているか確認してください。",
    );
  }
  deps.clickElement(moreBtn);
  await deps.sleep(SETTLE_AFTER_CLICK_MS);

  const downloadItem = await deps.waitForDownloadMenuItem(MENU_APPEAR_TIMEOUT_MS, MENU_APPEAR_POLL_MS);
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
}
