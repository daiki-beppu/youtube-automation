// jsdom 用テストヘルパ。
//
// jsdom はレイアウトを行わず `getBoundingClientRect` が常に 0×0 を返すため、strict 可視判定
// (`detectRecaptcha`, #810) を検証するには bbox を擬似的に与える必要がある。`markBbox` /
// `addCaptchaIframe` は dom.test.ts と wait-for-generation.test.ts の双方が同一ロジックで
// 必要とするため、ここに 1 箇所だけ定義して両者から import する (DRY)。

import type { PromptEntry } from "../../shared/api";

/**
 * テスト用の PromptEntry 配列を生成する (#852)。name は `pattern-1..N`。
 * snapshot 系テスト (query-progress / phase-to-status / use-suno-runner-restore) が
 * 同一の entries 形を必要とするため、ここに 1 箇所だけ定義して各テストから import する (DRY)。
 */
export function makePromptEntries(count: number): PromptEntry[] {
  return Array.from({ length: count }, (_, i) => ({
    name: `pattern-${i + 1}`,
    style: `style ${i + 1}`,
    lyrics: `lyrics ${i + 1}`,
  }));
}

/** strict 可視判定用に getBoundingClientRect を擬似的に与える (jsdom は常に 0×0 を返すため)。 */
export function markBbox(el: HTMLElement, width: number, height: number, y = 0): void {
  Object.defineProperty(el, "getBoundingClientRect", {
    configurable: true,
    value: () => ({
      width,
      height,
      top: y,
      left: 0,
      right: width,
      bottom: y + height,
      x: 0,
      y,
      toJSON: () => ({}),
    }),
  });
}

/**
 * recaptcha/hcaptcha 類似 iframe を body に挿入する。
 * `width`/`height` は strict 可視判定が見る bbox、`display`/`visibility`/`opacity` は親 walk が見る
 * インライン style。order.md の実 DOM 表 (iframe[0] display:none/0×0, iframe[4] visibility:hidden/300×150)
 * を写像できるよう、bbox と style を独立に指定できる。
 */
export function addCaptchaIframe(opts: {
  src?: string;
  title?: string;
  display?: string;
  visibility?: string;
  opacity?: string;
  width?: number;
  height?: number;
  /** bbox の y 座標。検証完了後の駐機 iframe（y:-9999）を写像する。 */
  y?: number;
}): HTMLIFrameElement {
  const f = document.createElement("iframe");
  if (opts.src !== undefined) f.src = opts.src;
  if (opts.title !== undefined) f.title = opts.title;
  if (opts.display !== undefined) f.style.display = opts.display;
  if (opts.visibility !== undefined) f.style.visibility = opts.visibility;
  if (opts.opacity !== undefined) f.style.opacity = opts.opacity;
  document.body.appendChild(f);
  markBbox(f, opts.width ?? 300, opts.height ?? 150, opts.y ?? 0);
  return f;
}

/** aria-label 付き <button> を生成する。findCardRoot の構造判定 (Select/Remix/Edit) に使う。 */
function makeAriaButton(label: string, opts: { disabled?: boolean; ariaDisabled?: boolean } = {}): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.setAttribute("aria-label", label);
  if (opts.disabled) btn.disabled = true;
  if (opts.ariaDisabled) btn.setAttribute("aria-disabled", "true");
  return btn;
}

/**
 * Suno の clip カード (#866) を模した DOM を生成する（body には append しない detached 要素）。
 * order.md 実機検証で確定した「Select clip / Remix clip / Edit title を各 1 つずつ含む card root」を
 * 写像する。findCardRoot のネスト構造テスト（複数カードを 1 つの container に入れる）では本関数で
 * detached card を組んでから任意の親へ append する。
 *   - generating=true: Remix btn を disabled にする（= 生成中。音源未完成で Remix 不可）
 *   - generating=false: Remix btn enabled（= 完了。Remix 可能）
 *   - generatingVia="aria-disabled": disabled 属性ではなく aria-disabled="true" で生成中を表す
 *   - visible=false: display:none + bbox 0×0（strict isVisible で除外される card）
 */
export function buildClipCard(
  opts: {
    generating?: boolean;
    visible?: boolean;
    generatingVia?: "disabled" | "aria-disabled";
  } = {},
): HTMLElement {
  const via = opts.generatingVia ?? "disabled";
  const card = document.createElement("div");
  card.append(
    makeAriaButton("Select clip"),
    makeAriaButton("Remix clip", {
      disabled: opts.generating === true && via === "disabled",
      ariaDisabled: opts.generating === true && via === "aria-disabled",
    }),
    makeAriaButton("Edit title"),
  );
  const title = document.createElement("span");
  title.textContent = opts.generating ? "Untitled" : "Orchestral Test Verification";
  card.appendChild(title);

  if (opts.visible === false) {
    card.style.display = "none";
    markBbox(card, 0, 0);
  } else {
    markBbox(card, 240, 80);
  }
  return card;
}

/** buildClipCard で作った clip カードを body に挿入して返す（単純な単一カード用）。 */
export function addClipCard(
  opts: {
    generating?: boolean;
    visible?: boolean;
    generatingVia?: "disabled" | "aria-disabled";
  } = {},
): HTMLElement {
  const card = buildClipCard(opts);
  document.body.appendChild(card);
  return card;
}

/** generating な card の Remix btn を enabled に戻し「完了」状態にする（poll 中に slot が空く状況を作る）。 */
export function completeClipCard(card: HTMLElement): void {
  const remix = card.querySelector<HTMLButtonElement>('button[aria-label="Remix clip"]');
  if (!remix) {
    throw new Error("test fixture 不整合: card 内に Remix btn がありません。");
  }
  remix.disabled = false;
  remix.removeAttribute("aria-disabled");
}

/**
 * Suno の queue 上限エラー toast (#847) を模した `[role="dialog"]` を body に挿入する。
 * order.md 実 DOM 検証の構造 (H2.sr-only + P.sr-only + H3 可視見出し + SPAN 補足) を写像する。
 * `text` を変えれば非該当 dialog（他種 toast）も作れる。`dom.test.ts` (isQueueLimitErrorVisible) と
 * `queue.test.ts` (waitForQueueSlot の toast 検知) の双方が同一構造を必要とするため、ここに 1 箇所
 * だけ定義して両者から import する (DRY)。
 *   - visible=false: display:none + bbox 0×0（strict isVisible で除外される toast を作る）
 */
export function addQueueErrorDialog(opts: { text?: string; japanese?: string; visible?: boolean } = {}): HTMLElement {
  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");

  const srH2 = document.createElement("h2");
  srH2.className = "sr-only";
  const srP = document.createElement("p");
  srP.className = "sr-only";
  const h3 = document.createElement("h3");
  h3.className = "text-base font-medium";
  h3.textContent = opts.text ?? "Generation in progress";
  const span = document.createElement("span");
  span.className = "text-sm opacity-70";
  span.textContent = opts.japanese ?? "他の曲の生成が完了するまでお待ちいただき、その後もう一度お試しください。";
  dialog.append(srH2, srP, h3, span);

  document.body.appendChild(dialog);
  if (opts.visible === false) {
    dialog.style.display = "none";
    markBbox(dialog, 0, 0);
  } else {
    markBbox(dialog, 360, 120);
  }
  return dialog;
}
