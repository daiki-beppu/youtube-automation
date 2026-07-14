// overlay (#892) の drag 移動を pointer イベントでカスタム実装する hook（外部 lib 不要）。
//
// 規約:
//   - drag handle 上の pointerdown で開始。ただし起点が input/textarea/contentEditable のときは
//     drag を開始しない（要件3: Suno 側のフォーム入力を奪わない）。
//   - pointermove 中は clampPosition で viewport 内へ収める。
//   - pointerup で確定し onCommit へ最終位置を渡す（永続化は呼び出し側の責務）。
//   - viewport resize 時も現在位置を再 clamp して onCommit する（要件2: resize clamp 復元）。
import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";

import { clampPosition } from "../lib/overlay-state";

interface Point {
  x: number;
  y: number;
}

interface UseDraggableOptions {
  /** 初期表示位置（top-left 基準）。 */
  initial: Point;
  /** clamp の基準サイズを実測するための overlay 要素 ref。 */
  elementRef: RefObject<HTMLElement | null>;
  /** drag 終了 / resize clamp で確定した位置を通知する（永続化用）。 */
  onCommit: (position: Point) => void;
}

interface UseDraggableResult {
  position: Point;
  dragging: boolean;
  onPointerDown: (event: ReactPointerEvent) => void;
}

/** drag を発火させてはいけない起点（フォーム入力要素）か判定する (要件3)。 */
function isInteractive(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
}

function viewportSize(): { width: number; height: number } {
  return { width: window.innerWidth, height: window.innerHeight };
}

function elementSize(element: HTMLElement | null): { width: number; height: number } {
  if (!element) {
    return { width: 0, height: 0 };
  }
  const rect = element.getBoundingClientRect();
  return { width: rect.width, height: rect.height };
}

export function useDraggable({ initial, elementRef, onCommit }: UseDraggableOptions): UseDraggableResult {
  const [position, setPosition] = useState<Point>(initial);
  const [dragging, setDragging] = useState(false);

  // 最新値を pointermove / resize リスナーから参照するための ref（リスナー再登録を避ける）。
  // ref はレンダー中に書かず commit 後の effect で同期する（react-hooks/refs。読み手は全て非同期ハンドラ）。
  const positionRef = useRef<Point>(initial);
  useEffect(() => {
    positionRef.current = position;
  }, [position]);
  const origin = useRef<Point>({ x: 0, y: 0 });
  const start = useRef<Point>(initial);

  const onPointerDown = useCallback((event: ReactPointerEvent) => {
    if (isInteractive(event.target)) {
      return;
    }
    origin.current = { x: event.clientX, y: event.clientY };
    start.current = positionRef.current;
    setDragging(true);
  }, []);

  useEffect(() => {
    if (!dragging) {
      return;
    }
    const handleMove = (event: PointerEvent) => {
      const next = {
        x: start.current.x + (event.clientX - origin.current.x),
        y: start.current.y + (event.clientY - origin.current.y),
      };
      setPosition(clampPosition(next, viewportSize(), elementSize(elementRef.current)));
    };
    const handleUp = () => {
      setDragging(false);
      onCommit(positionRef.current);
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [dragging, elementRef, onCommit]);

  // viewport が縮んだとき、現在位置を内側へ再 clamp して確定する (要件2)。
  useEffect(() => {
    const handleResize = () => {
      const clamped = clampPosition(positionRef.current, viewportSize(), elementSize(elementRef.current));
      if (clamped.x !== positionRef.current.x || clamped.y !== positionRef.current.y) {
        setPosition(clamped);
        onCommit(clamped);
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [elementRef, onCommit]);

  return { position, dragging, onPointerDown };
}
