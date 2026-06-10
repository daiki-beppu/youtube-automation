// overlay (#892) の「位置・最小化・表示状態の永続化」と「viewport 外に保存された位置の内側 clamp」を
// 支える純関数 + chrome.storage I/O を 1 箇所に集約する。
//
// 純関数のうち clampPosition は Overlay component と useDraggable の双方が、topRightPosition は
// Overlay component のみが import し、clamp 規約を二重定義しないための SSOT とする。
// I/O (readOverlayState / writeOverlayState) は
// @wxt-dev/storage の型付き wrapper で chrome.storage.local を読み書きする。storage.defineItem は
// 呼ぶと内部で chrome.runtime へアクセスするため、node 環境 (vitest) で純関数だけを import したときに
// 副作用を起こさないよう遅延生成する（純関数テスト overlay-state.test.ts を壊さないため。
// 既存 lib/resume-state.ts と同方針）。
import { storage } from "wxt/utils/storage";

import { OVERLAY_STATE_KEY } from "../../shared/constants";

/** 永続化する overlay の状態 (#892 要件2)。position は top-left 基準の viewport 座標。 */
export interface OverlayState {
  position: { x: number; y: number };
  minimized: boolean;
  hidden: boolean;
}

interface Point {
  x: number;
  y: number;
}

interface Size {
  width: number;
  height: number;
}

/** overlay を viewport 端から離す初期マージン (px)。topRightPosition 専用の module-private 定数。 */
const OVERLAY_MARGIN = 16;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * overlay box (top-left=pos, size) を viewport 内へ収める (#892 要件2)。
 * 規約: x ∈ [0, max(0, viewport.width - size.width)] / y ∈ [0, max(0, viewport.height - size.height)]。
 * overlay が viewport より大きい退化ケースは上限が負になるため max(0, ...) で 0 に吸い込む。
 */
export function clampPosition(pos: Point, viewport: Size, size: Size): Point {
  const maxX = Math.max(0, viewport.width - size.width);
  const maxY = Math.max(0, viewport.height - size.height);
  return { x: clamp(pos.x, 0, maxX), y: clamp(pos.y, 0, maxY) };
}

/** 初期表示位置（右上、マージン込み）を算出する (#892 要件1)。 */
export function topRightPosition(viewport: Size, size: Size): Point {
  return clampPosition({ x: viewport.width - size.width - OVERLAY_MARGIN, y: OVERLAY_MARGIN }, viewport, size);
}

/**
 * toggleOverlay 受信時の hidden 反転 (#897 要件2/5)。position / minimized は保持し、
 * 入力を変異させず新オブジェクトを返す純関数。拡張アイコンクリックで hidden:true → false に戻す本丸。
 */
export function toggleHidden(state: OverlayState): OverlayState {
  return { ...state, hidden: !state.hidden };
}

/**
 * hidden を unmount でなく CSS（display）で表現する (#897 要件1/3)。
 * `if (hidden) return null;` で OverlayShell を unmount すると toggleOverlay リスナーごと消えるため、
 * DOM に残したまま display:none で隠す。Suno UI への pointer-events 干渉も起こさない。
 */
export function hiddenStyle(hidden: boolean): { display: "none" | "block" } {
  return { display: hidden ? "none" : "block" };
}

// --- chrome.storage.local I/O（storage item は遅延生成。理由はファイル冒頭コメント参照） ---

let cachedItem: ReturnType<typeof storage.defineItem<OverlayState | null>> | null = null;

function overlayStateItem() {
  if (!cachedItem) {
    cachedItem = storage.defineItem<OverlayState | null>(`local:${OVERLAY_STATE_KEY}`, { fallback: null });
  }
  return cachedItem;
}

/** 永続化済みの overlay state を読む。未設定は null。 */
export async function readOverlayState(): Promise<OverlayState | null> {
  return overlayStateItem().getValue();
}

/** overlay state を書き込む（既存があれば上書き）。 */
export async function writeOverlayState(state: OverlayState): Promise<void> {
  await overlayStateItem().setValue(state);
}
