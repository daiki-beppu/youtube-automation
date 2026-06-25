// Suno の "Download all" 機能を DOM 操作で起動するヘルパモジュール (#1146)。
// 全 clip が multi-select された状態で、任意の clip row の "More" メニューから
// "Download all" を選び、形式選択モーダルで指定形式を選んで ZIP ダウンロードを開始する。
//
// DOM 操作フロー:
//   1. multi-selected な clip row の "More menu contents" ボタン（三点リーダー）を click
//   2. context menu が表示されるのを待機
//   3. "Download all" menu item を click
//   4. 形式選択モーダル（M4A / MP3 / WAV）が表示されるのを待機
//   5. chrome.storage の設定形式に対応するラジオボタンを選択
//   6. Download / 確認ボタンを click → ZIP ダウンロード開始
//
// セレクタは Suno UI の実 DOM に依存するため、壊れたら TODO コメントの指示に従って更新する。
// shared/dom.ts の waitForElement / click 系パターンと shared/playlist-dom.ts の
// multi-step DOM 操作パターンを踏襲する。

import { sleep } from "../../shared/dom";

// --- DOM セレクタ SSOT (2026-06-25 実測) ---
// Suno の DOM は頻繁に変わるため、セレクタを 1 箇所に集約する。

/** More menu ボタン。各 clip row に出現する三点リーダー。
 * aria-label="More options" で完全一致（"More from Suno" 等を除外）。 */
const MORE_BUTTON_SELECTOR = 'button[aria-label="More options"]';

/** context menu コンテナ。More ボタン click 後に body 末尾へポータル描画される。
 * role="menu" は付かず data-context-menu 属性で識別する。 */
const CONTEXT_MENU_SELECTOR = 'div[data-context-menu="true"]';

/** "Download all" menu item。context menu 内の button を aria-label で識別する。 */
const DOWNLOAD_MENU_ITEM_TEXT = /download\s*all/i;

/** 形式選択モーダル。Download all click 後に出現する。
 * div.modal-class.modal-overlay で識別（OneTrust cookie dialog の [role="dialog"] と区別）。 */
const FORMAT_MODAL_SELECTOR = "div.modal-class.modal-overlay";

/** 形式選択モーダル内のフォーマットボタン。
 * button.flex.w-full で M4A / MP3 / WAV のテキストを含む（radio ではなく通常ボタン）。 */
const FORMAT_OPTION_SELECTOR = "button.flex.w-full";

/** ダウンロード確認ボタン。hxc-btn-variant-primary クラスで確実に識別できる。 */
const DOWNLOAD_CONFIRM_SELECTOR = "button.hxc-btn-variant-primary";

// --- poll / timeout 定数 ---
const MENU_APPEAR_POLL_MS = 100;
const MENU_APPEAR_TIMEOUT_MS = 5000;
const MODAL_APPEAR_POLL_MS = 200;
const MODAL_APPEAR_TIMEOUT_MS = 10000;
const SETTLE_AFTER_CLICK_MS = 500;

/**
 * 指定セレクタの要素が DOM に出現するまで poll する。timeout で throw (fail-loud)。
 */
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

/**
 * DOM 内のすべての要素を走査し、textContent が正規表現にマッチするものを返す。
 * menu item / button など testid を持たない要素の識別に使う。
 */
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

/**
 * context menu 内から "Download all" menu item が出現するまで poll する。
 * Suno は data-context-menu="true" ポータルを body 末尾に描画する。
 * 内部の button[aria-label="Download all"] または テキスト照合で探す。
 */
async function waitForDownloadMenuItem(timeoutMs: number, pollMs: number): Promise<HTMLElement> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const menu = document.querySelector<HTMLElement>(CONTEXT_MENU_SELECTOR);
    if (menu) {
      // aria-label で直接探す（最も安定）
      const byLabel = menu.querySelector<HTMLElement>('button[aria-label="Download all"]');
      if (byLabel) return byLabel;
      // フォールバック: テキスト照合
      const byText = findElementByTextContent<HTMLElement>(menu, "button", DOWNLOAD_MENU_ITEM_TEXT);
      if (byText) return byText;
    }
    await sleep(pollMs);
  }
  throw new Error(`"Download all" menu item が見つかりませんでした (${timeoutMs}ms)`);
}

/**
 * 形式選択モーダル内で指定形式のオプションを探して click する。
 * Suno は button.flex.w-full で M4A / MP3 / WAV の選択肢を描画する（radio ではない）。
 * 選択済み: bg-foreground-primary、未選択: bg-background-glass-thin。
 */
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

/**
 * 形式選択モーダル内のダウンロード確認ボタンを探して click する。
 * Suno は hxc-btn-variant-primary クラスの大ボタン (テキスト "Download") を使う。
 */
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
  sleep: (ms: number) => Promise<void>;
}

/** デフォルトの DOM 実装。 */
export function defaultDownloadDeps(): TriggerDownloadAllDeps {
  return {
    findMoreButton: () => document.querySelector<HTMLElement>(MORE_BUTTON_SELECTOR),
    waitForDownloadMenuItem: (timeoutMs, pollMs) => waitForDownloadMenuItem(timeoutMs, pollMs),
    waitForFormatModal: (timeoutMs, pollMs) => waitForElement<HTMLElement>(FORMAT_MODAL_SELECTOR, timeoutMs, pollMs),
    selectFormat: selectFormatInModal,
    clickConfirm: clickDownloadConfirm,
    sleep,
  };
}

/**
 * multi-select 済みの clip に対して "Download all" を実行する (#1146)。
 * More menu → Download all → 形式選択 → ダウンロード開始の一連の DOM 操作を行う。
 *
 * @param format ダウンロード形式 ("mp3" | "m4a" | "wav")
 * @param deps テスト時に差し替え可能な副作用注入点
 * @throws DOM 操作の各ステップで要素が見つからない / timeout した場合
 */
export async function triggerDownloadAll(
  format: string,
  deps: TriggerDownloadAllDeps = defaultDownloadDeps(),
): Promise<void> {
  // Step 1: More ボタン（三点リーダー）を click
  const moreBtn = deps.findMoreButton();
  if (!moreBtn) {
    throw new Error(
      `More メニューボタン (${MORE_BUTTON_SELECTOR}) が見つかりませんでした。` +
        "clip が multi-select されているか確認してください。",
    );
  }
  moreBtn.click();
  await deps.sleep(SETTLE_AFTER_CLICK_MS);

  // Step 2: context menu 内の "Download all" を待って click
  const downloadItem = await deps.waitForDownloadMenuItem(MENU_APPEAR_TIMEOUT_MS, MENU_APPEAR_POLL_MS);
  downloadItem.click();
  await deps.sleep(SETTLE_AFTER_CLICK_MS);

  // Step 3: 形式選択モーダルを待つ
  const modal = await deps.waitForFormatModal(MODAL_APPEAR_TIMEOUT_MS, MODAL_APPEAR_POLL_MS);
  await deps.sleep(SETTLE_AFTER_CLICK_MS);

  // Step 4: 指定形式を選択
  deps.selectFormat(modal, format);
  await deps.sleep(SETTLE_AFTER_CLICK_MS);

  // Step 5: ダウンロード確認ボタンを click
  deps.clickConfirm(modal);
}
