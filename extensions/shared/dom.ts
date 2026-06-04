// Suno Custom Mode への Style / Lyrics 注入と Generate 連続実行に使う DOM 操作群。
// 旧 `content.js` の振る舞いを 1:1 で保持しつつ純関数化する。
// Suno の DOM は変わりうるため、セレクタはこの 1 箇所に集約する（壊れたら README 参照で更新）。

import { isVisible } from "./visibility";

// Suno の DOM セレクタ SSOT。#807 で判明したとおり placeholder は UI ロケールで変わるため、
// Lyrics は言語非依存の data-testid で識別する（Style は「Lyrics でない可視 textarea」）。
const SELECTORS = {
  textareas: "textarea",
  lyrics: '[data-testid="lyrics-textarea"]',
  // Song Title 欄は testid/aria/label を持たず placeholder のみ安定 (#844 実 DOM 検証)。
  // 表記変更 ((Optional) の有無等) に耐えるよう "Song Title" の弱い case-insensitive substring match。
  title: 'input[placeholder*="Song Title" i]',
  generateLabel: /^(create|generate|生成)$/i,
  recaptcha:
    'iframe[src*="recaptcha"], iframe[title*="recaptcha" i], iframe[src*="hcaptcha"]',
} as const;

/** Suno 生成キューの 1 clip 行を示す安定識別子（#816、実 DOM 検証: 1 タブで 16 件確認）。 */
export const CLIP_ROW_SELECTOR = '[data-testid="clip-row"]';
/** clip-row が「生成中」を示すスピナー（#816、完了 row には現れず duration テキストになる）。 */
const CLIP_SPINNER_SELECTOR = "svg.animate-spin";

/**
 * queue 上限エラー toast の安定識別子（#847、実 DOM 検証）。testid/aria-label を持たないため
 * `[role="dialog"]` + 英語見出しテキストの substring match で識別する（多言語耐性）。
 */
export const QUEUE_LIMIT_ERROR_SELECTOR = '[role="dialog"]';
/** queue 上限エラー toast の英語見出し（case-insensitive substring match。日本語並列テキストには依存しない）。 */
const QUEUE_LIMIT_ERROR_TEXT = "generation in progress";

/** 1 曲の生成完了待ち上限 (ms)。 */
export const GENERATE_TIMEOUT_MS = 180000;
/** 生成完了 poll 間隔 (ms)。短くすると停止反応性と Generate ボタン再 enable 検知が早まる。 */
export const POLL_INTERVAL_MS = 500;
/** 注入後・クリック後の安定化待ち (ms)。 */
export const SETTLE_MS = 1500;

export interface ResolvedFields {
  style: HTMLTextAreaElement;
  lyrics: HTMLTextAreaElement | null;
  // Song Title 欄 (#844)。不在は throw せず undefined（fail-soft: style/lyrics の fail-loud とは非対称）。
  title?: HTMLInputElement;
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

/** abortableSleep の中断検知 poll 間隔 (ms)。停止押下から resolve までの粒度（受け入れ条件: 3 秒以内停止に十分小さい）。 */
const ABORTABLE_SLEEP_POLL_MS = 250;

/**
 * 中断可能な sleep (#847)。`ms` 経過 または `isAborted()` が true になった時点（内部 poll で検知）の
 * 早い方で resolve する。`sleep` と同じく throw / reject しない。連続実行フローの固定待機を本関数に
 * 置き換えることで、長い待機の途中でも停止押下に素早く反応できる。
 */
export function abortableSleep(
  ms: number,
  isAborted: () => boolean,
): Promise<void> {
  return new Promise((resolve) => {
    const deadline = Date.now() + ms;
    const tick = (): void => {
      if (isAborted() || Date.now() >= deadline) {
        resolve();
        return;
      }
      // 残り時間と poll 間隔の短い方を待つ（最終 tick が deadline をオーバーランしないように）。
      setTimeout(
        tick,
        Math.min(ABORTABLE_SLEEP_POLL_MS, deadline - Date.now()),
      );
    };
    tick();
  });
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

/**
 * 可視な recaptcha / hcaptcha challenge iframe を検知する（#810）。
 * Suno は hCaptcha challenge を非表示プリロード iframe として常駐させるため、
 * querySelector の hit だけでは常に true になってしまう。strict 可視判定で
 * 実 challenge UI が表示された時のみ true を返す。
 */
export function detectRecaptcha(): boolean {
  const iframes = document.querySelectorAll<HTMLIFrameElement>(
    SELECTORS.recaptcha,
  );
  return Array.from(iframes).some((f) => isVisible(f));
}

/**
 * queue 上限エラー toast が表示中かを検知する（#847）。
 * 可視な `[role="dialog"]` のうち英語見出し "generation in progress" を case-insensitive
 * substring match で含むものがあれば true。detectRecaptcha (#810) と同じ strict isVisible で
 * 非表示の toast 残骸を弾く。Create→clip-row 反映ラグで Suno が投入を reject した時に出る toast を
 * 検知し、空きスロットがあっても投入を止めるために使う。
 */
export function isQueueLimitErrorVisible(): boolean {
  const dialogs = document.querySelectorAll<HTMLElement>(
    QUEUE_LIMIT_ERROR_SELECTOR,
  );
  return Array.from(dialogs).some(
    (el) =>
      isVisible(el) &&
      (el.textContent ?? "").toLowerCase().includes(QUEUE_LIMIT_ERROR_TEXT),
  );
}

/**
 * Style / Lyrics の textarea を解決する（#807）。
 *   - Lyrics: `data-testid="lyrics-textarea"` を最優先で識別（UI 言語非依存）。無ければ null。
 *   - Style:  Lyrics 以外の strict visible textarea（この述語が Style==Lyrics の silent 上書きを構造的に禁ずる）。
 *   - Style が解決できない場合は throw（silent スキップを禁ずる）。
 *   - Title:  placeholder substring match の strict visible input（#844）。不在は undefined（fail-soft）。
 */
export function resolveFields(): ResolvedFields {
  const areas = Array.from(
    document.querySelectorAll<HTMLTextAreaElement>(SELECTORS.textareas),
  ).filter(isVisible);
  if (areas.length === 0) {
    throw new Error(
      "textarea が見つかりません。Suno の Custom Mode 画面を開いてください。",
    );
  }

  const lyrics = areas.find((el) => el.matches(SELECTORS.lyrics)) ?? null;
  // Style は「Lyrics でない可視 textarea」。この述語が silent な上書き（Style==Lyrics）を構造的に禁ずる。
  const style = areas.find((el) => el !== lyrics);
  if (!style) {
    throw new Error(
      "Style 欄が見つかりません。Lyrics 以外の可視 textarea を検出できませんでした。",
    );
  }

  // Title は style/lyrics と別クエリ（<input>）。不在でも throw しない fail-soft で undefined を返す。
  const title = Array.from(
    document.querySelectorAll<HTMLInputElement>(SELECTORS.title),
  ).find(isVisible);

  return { style, lyrics, title };
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

export interface WaitForQueueSlotOptions {
  /** 中断フラグ。true を返した時点で待機を打ち切り resolve する（throw しない）。 */
  isAborted: () => boolean;
  pollIntervalMs: number;
  timeoutMs: number;
  /** queue 上限エラー toast 消失後に投入再開まで待つ安全マージン (ms、#847)。 */
  queueErrorWaitMs: number;
}

/**
 * 1 行の clip が「生成中」か判定する（#816）。
 * strict isVisible() で row 自体を filter したうえで `svg.animate-spin` を含むか見る。
 * 非可視 row（display:none / bbox 0 / 親 walk で隠れ）は生成中とみなさない。
 */
export function isClipGenerating(row: HTMLElement): boolean {
  return isVisible(row) && row.querySelector(CLIP_SPINNER_SELECTOR) !== null;
}

/** 可視な clip-row のうち生成中（in-flight）な clip 数を数える（#816）。 */
export function getInFlightClipCount(): number {
  const rows = document.querySelectorAll<HTMLElement>(CLIP_ROW_SELECTOR);
  return Array.from(rows).filter(isClipGenerating).length;
}

export interface WaitForInFlightIncreaseOptions {
  /** 中断フラグ。true を返した時点で未達でも resolve true する（停止優先）。 */
  isAborted: () => boolean;
  pollIntervalMs: number;
  timeoutMs: number;
}

/**
 * inject 後に in-flight clip 数が `beforeCount + delta` 以上へ増えるまで poll で待機する（#864 root cause 3）。
 *   - isAborted() が true なら未達でも最優先で即 resolve `true`（停止優先。waitForQueueSlot と同じ中断優先）
 *   - getInFlightClipCount() >= beforeCount + delta になったら resolve `true`（受理確認）
 *   - deadline 超過で resolve `false`（throw しない。retry 判断は caller=injectWithVerification 側に委ねる）
 * waitForQueueSlot と異なり throw せず boolean を返す。Create→clip-row 反映ラグで Suno が inject を
 * silent drop しても Generate ボタンは再 enabled になるため、実際に clip が受理されたかを増分で検証する。
 */
export async function waitForInFlightIncrease(
  beforeCount: number,
  delta: number,
  options: WaitForInFlightIncreaseOptions,
): Promise<boolean> {
  const target = beforeCount + delta;
  const deadline = Date.now() + options.timeoutMs;
  while (Date.now() < deadline) {
    if (options.isAborted()) {
      return true;
    }
    if (getInFlightClipCount() >= target) {
      return true;
    }
    await sleep(options.pollIntervalMs);
  }
  return false;
}

/**
 * in-flight clip 数が `maxClips` 未満になるまで poll で待機する（#816, #847）。
 *   - isAborted() が true なら（toast 中・上限超でも）最優先で即 resolve（throw しない）
 *   - queue 上限エラー toast 表示中は、空きスロットがあっても投入せず待機を継続する（#847）
 *   - toast が消えたら `queueErrorWaitMs` の安全マージンを待ってから判定を再開する（#847）
 *   - in-flight < maxClips になったら resolve（投入再開）
 *   - deadline 超過で timeout throw
 * Suno は同時 10 リクエスト = 20 clip までしか積めず、超過すると後続が silent fail するため、
 * 各リクエスト投入前にこの関数で空きスロットを待つ。Create→clip-row 反映ラグで Suno が投入を
 * reject すると toast が出るため、toast 検知中は投入を止め、消失後に buffer を取ってから再開する。
 */
export async function waitForQueueSlot(
  maxClips: number,
  options: WaitForQueueSlotOptions,
): Promise<void> {
  const deadline = Date.now() + options.timeoutMs;
  let sawQueueError = false;
  while (Date.now() < deadline) {
    if (options.isAborted()) {
      return;
    }
    if (isQueueLimitErrorVisible()) {
      // toast 中はスロットが空いていても投入しない。消失を待つ。
      sawQueueError = true;
      await sleep(options.pollIntervalMs);
      continue;
    }
    if (sawQueueError) {
      // toast が消えた直後は反映ラグが残るため、安全マージンを取ってから判定を再開する。
      // buffer 待機中の停止押下にも 3 秒以内で反応できるよう中断可能な abortableSleep を使う（#847）。
      sawQueueError = false;
      await abortableSleep(options.queueErrorWaitMs, options.isAborted);
      continue;
    }
    if (getInFlightClipCount() < maxClips) {
      return;
    }
    await sleep(options.pollIntervalMs);
  }
  throw new Error("生成キューの空きスロット待ちがタイムアウトしました。");
}
