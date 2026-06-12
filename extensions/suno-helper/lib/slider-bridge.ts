// MAIN world での slider 注入ロジック（#973）。
//
// Suno の Weirdness / Style Influence slider は onKeyDown 内で `isTrusted` をチェックしており、
// dispatchEvent による合成 KeyboardEvent は原理的に弾かれる（#900 実機検証）。MAIN world からは
// React が DOM 要素に生やす `__reactProps$*` expando にアクセスできるため、onKeyDown ハンドラを
// **直接呼び出し**、`isTrusted: true` を持つ疑似イベントオブジェクトを渡すことでチェックを通過させる。
//
// この module は entrypoints/suno-bridge.content.ts（MAIN world）から呼ばれる。ISOLATED world では
// `__reactProps$*` が見えない（world 間で JS expando は共有されない）ため、ここに置く意味がある。
//
// 全経路 fail-soft: React props が見つからない（e2e mock の plain DOM 等）・ハンドラを呼んでも
// 値が動かない場合は false を返し、呼び出し側（shared/dom.ts の合成 dispatchEvent 経路）へ縮退する。

/** ハンドラ呼び出し 1 step 後の aria-valuenow 変化を待つ poll 間隔 (ms)。 */
const STEP_READBACK_POLL_MS = 10;
/** 1 step あたりの変化待ち poll 回数。超えても不変なら「ハンドラが効いていない」とみなし fail-soft。 */
const STEP_READBACK_MAX_POLLS = 20;
/** target 到達までの最大 step 数。Suno slider は 0-100 整数なので 100 で足りるが余裕を持たせる。 */
const MAX_STEPS = 150;
/** React props 探索で遡る祖先の最大段数。Suno は thumb（[role="slider"]）自身か近傍の root が持つ。 */
const MAX_ANCESTOR_DEPTH = 5;

/** React の onKeyDown ハンドラと、それが props として付いていた要素のペア。 */
export interface ReactKeyDownTarget {
  handler: (event: unknown) => void;
  owner: Element;
}

/**
 * 要素自身 → 祖先の順に `__reactProps$*` expando を探し、onKeyDown を持つ最初の要素を返す。
 * React は DOM node に `__reactProps$<ランダム接尾辞>` キーで現在の props を保持している
 * （接尾辞は React インスタンスごとに変わるため prefix match で探す）。
 */
export function findReactKeyDownTarget(el: Element): ReactKeyDownTarget | null {
  let node: Element | null = el;
  for (let depth = 0; node !== null && depth < MAX_ANCESTOR_DEPTH; depth++) {
    const propsKey = Object.keys(node).find((k) => k.startsWith("__reactProps$"));
    if (propsKey) {
      const props = (node as unknown as Record<string, unknown>)[propsKey] as
        | { onKeyDown?: unknown }
        | null
        | undefined;
      if (props && typeof props.onKeyDown === "function") {
        return { handler: props.onKeyDown as (event: unknown) => void, owner: node };
      }
    }
    node = node.parentElement;
  }
  return null;
}

/**
 * React ハンドラへ直接渡す疑似 keydown イベント（#973）。
 * dispatchEvent を経由しないため isTrusted を自由に設定でき、Suno の bot 検知
 * （`if (!e.isTrusted) return` 系）を通過する。ハンドラが参照しうるフィールドを一通り備える:
 * SyntheticEvent 互換（isTrusted / nativeEvent / persist）+ KeyboardEvent 互換
 * （key / code / 修飾キー / getModifierState / preventDefault / stopPropagation）。
 */
export function buildSyntheticKeydown(
  key: "ArrowRight" | "ArrowLeft",
  owner: Element,
  target: Element,
): Record<string, unknown> {
  const event: Record<string, unknown> = {
    type: "keydown",
    key,
    code: key,
    isTrusted: true,
    bubbles: true,
    cancelable: true,
    repeat: false,
    shiftKey: false,
    ctrlKey: false,
    altKey: false,
    metaKey: false,
    target,
    currentTarget: owner,
    defaultPrevented: false,
    timeStamp: performance.now(),
    nativeEvent: { type: "keydown", key, code: key, isTrusted: true },
    preventDefault(): void {
      event.defaultPrevented = true;
    },
    stopPropagation(): void {},
    stopImmediatePropagation(): void {},
    persist(): void {},
    getModifierState(): boolean {
      return false;
    },
  };
  return event;
}

/** 1 frame + microtask 分待つ。React の setState → re-render → aria-valuenow 反映を待つ最小単位。 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * React onKeyDown ハンドラの直接呼び出しで slider を target 値まで動かす（#973）。
 *   1. findReactKeyDownTarget でハンドラ解決（無ければ false = plain DOM、合成イベント経路へ縮退）
 *   2. aria-valuenow を読み、target との差分方向に ArrowRight / ArrowLeft の疑似イベントで 1 step ずつ進める
 *   3. 各 step 後に aria-valuenow の変化を poll。変化しなければ「ハンドラが効いていない」とみなし false
 *   4. target 一致で true
 *
 * step ごとに current を読み直すため、step 幅が 1 でない slider でも過走せず収束する。
 */
export async function setSliderValueViaReact(slider: HTMLElement, target: number): Promise<boolean> {
  const reactTarget = findReactKeyDownTarget(slider);
  if (!reactTarget) {
    return false;
  }
  // 属性不在は NaN（Number(null) は 0 になり「値 0 の slider」と区別できないため明示する）。
  const read = (): number => {
    const raw = slider.getAttribute("aria-valuenow");
    return raw === null ? Number.NaN : Number(raw);
  };
  for (let step = 0; step < MAX_STEPS; step++) {
    const current = read();
    if (!Number.isFinite(current)) {
      return false;
    }
    if (current === target) {
      return true;
    }
    const key = target > current ? "ArrowRight" : "ArrowLeft";
    try {
      reactTarget.handler(buildSyntheticKeydown(key, reactTarget.owner, slider));
    } catch {
      return false;
    }
    // 同期的に値が反映される実装なら sleep せず即進む。非同期 re-render は poll で待つ。
    let changed = read() !== current;
    for (let poll = 0; !changed && poll < STEP_READBACK_MAX_POLLS; poll++) {
      await sleep(STEP_READBACK_POLL_MS);
      changed = read() !== current;
    }
    if (!changed) {
      return false;
    }
  }
  return read() === target;
}

/**
 * aria-label で slider 要素を解決する（MAIN world 用の簡易版）。visible 優先、無ければ最初の要素
 * （shared/dom.ts の pickPreferVisible と同じ方針。More Options collapsed 時も DOM 上の要素を掴む）。
 */
export function findSliderElement(ariaLabel: string): HTMLElement | null {
  const candidates = Array.from(document.querySelectorAll<HTMLElement>(`[role="slider"][aria-label="${ariaLabel}"]`));
  return candidates.find((el) => el.getClientRects().length > 0) ?? candidates[0] ?? null;
}
