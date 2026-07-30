// Vitest セットアップ: 拡張 API グローバルを fakeBrowser でスタブする。
//
// lib/messaging.ts が静的 import する webextension-polyfill はロード時に
// globalThis.chrome.runtime.id を要求し、lib/storage.ts の @wxt-dev/storage は
// @wxt-dev/browser 経由で globalThis.browser/chrome を参照する。テスト本体（node）には
// これらが無いため、テストモジュール評価前にフェイク拡張環境を注入する（WXT 公式の手法）。

import { vi } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";

vi.stubGlobal("chrome", fakeBrowser);
vi.stubGlobal("browser", fakeBrowser);
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

interface PointerEventWindow {
  MouseEvent: typeof MouseEvent;
  PointerEvent?: typeof PointerEvent;
}

export function installPointerEventFallback(target: PointerEventWindow): void {
  if (target.PointerEvent) {
    return;
  }
  Object.defineProperty(target, "PointerEvent", {
    configurable: true,
    value: target.MouseEvent,
    writable: true,
  });
}

// jsdom does not implement PointerEvent, while Base UI dispatches one through
// hidden native form controls to preserve browser form semantics.
if (typeof window !== "undefined") {
  installPointerEventFallback(window);
}
