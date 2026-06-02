// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行に使う DOM 操作群。
// 旧 `content.js` の振る舞いを 1:1 で保持しつつ純関数化する。
// Suno の DOM は変わりうるため、セレクタはこの 1 箇所に集約する（壊れたら README 参照で更新）。

const SELECTORS = {
  textareas: "textarea",
  stylePlaceholder: /style|genre|描述|スタイル/i,
  lyricsPlaceholder: /lyric|歌詞|歌词/i,
  generateLabel: /^(create|generate|生成)$/i,
  recaptcha:
    'iframe[src*="recaptcha"], iframe[title*="recaptcha" i], iframe[src*="hcaptcha"]',
} as const;

/** 1 曲の生成完了待ち上限 (ms)。 */
export const GENERATE_TIMEOUT_MS = 180000;
/** 生成完了 poll 間隔 (ms)。 */
export const POLL_INTERVAL_MS = 1000;
/** 注入後・クリック後の安定化待ち (ms)。 */
export const SETTLE_MS = 1500;

export interface ResolvedFields {
  style: HTMLTextAreaElement;
  lyrics: HTMLTextAreaElement | null;
}

export interface WaitForGenerationOptions {
  /** 中断フラグ。true を返した時点で待機を打ち切り resolve する。 */
  isAborted: () => boolean;
  timeoutMs: number;
  pollIntervalMs: number;
  settleMs: number;
}

/** 指定 ms 待機する。注入フローと生成完了待ちの共通 timing util。 */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isVisible(el: HTMLElement): boolean {
  return el.offsetParent !== null;
}

/** React 互換のネイティブ値セット + input/change イベント発火。 */
export function setNativeValue(
  el: HTMLTextAreaElement | HTMLInputElement,
  value: string,
): void {
  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (!setter) {
    throw new Error("native value setter を取得できませんでした。");
  }
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

/** recaptcha / hcaptcha iframe の存在を検知する。 */
export function detectRecaptcha(): boolean {
  return document.querySelector(SELECTORS.recaptcha) !== null;
}

/** Style / Lyrics の textarea を解決する。可視 textarea が無ければ throw（fail-loud）。 */
export function resolveFields(): ResolvedFields {
  const areas = Array.from(
    document.querySelectorAll<HTMLTextAreaElement>(SELECTORS.textareas),
  ).filter(isVisible);
  if (areas.length === 0) {
    throw new Error(
      "textarea が見つかりません。Suno の Custom Mode 画面を開いてください。",
    );
  }

  const byPlaceholder = (re: RegExp): HTMLTextAreaElement | undefined =>
    areas.find((el) =>
      re.test(el.placeholder || el.getAttribute("aria-label") || ""),
    );

  const style = byPlaceholder(SELECTORS.stylePlaceholder) ?? areas[0];
  const lyrics =
    byPlaceholder(SELECTORS.lyricsPlaceholder) ??
    (areas.length > 1 ? areas[1] : null);

  return { style, lyrics };
}

/** Generate ボタンを解決する。可視ボタンに該当ラベルが無ければ throw。 */
export function resolveGenerateButton(): HTMLButtonElement {
  const buttons = Array.from(
    document.querySelectorAll<HTMLButtonElement>("button"),
  ).filter(isVisible);
  const btn = buttons.find((el) =>
    SELECTORS.generateLabel.test((el.textContent || "").trim()),
  );
  if (!btn) {
    throw new Error(
      "Generate ボタンが見つかりません。Suno の UI 変更の可能性があります。",
    );
  }
  return btn;
}

/**
 * クリック後、ボタンが一旦 disabled になり再度 enabled に戻るまで（= 生成完了）待つ。
 *   - enabled 復帰で resolve
 *   - reCAPTCHA 検知で throw
 *   - deadline 超過で timeout throw
 *   - 中断 (isAborted) で即 return
 */
export async function waitForGeneration(
  button: HTMLButtonElement,
  options: WaitForGenerationOptions,
): Promise<void> {
  const deadline = Date.now() + options.timeoutMs;
  // disabled に変わるのを少し待つ（生成開始の検知）
  await sleep(options.settleMs);
  while (Date.now() < deadline) {
    if (options.isAborted()) {
      return;
    }
    if (detectRecaptcha()) {
      throw new Error(
        "reCAPTCHA を検知しました。手動で解決してから再開してください。",
      );
    }
    if (!button.disabled && button.getAttribute("aria-disabled") !== "true") {
      return;
    }
    await sleep(options.pollIntervalMs);
  }
  throw new Error("生成完了の検知がタイムアウトしました。");
}
