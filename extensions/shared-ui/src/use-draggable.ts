import { clampOverlayPosition } from "@youtube-automation/extensions-shared/overlay-state";
import type { OverlayPoint } from "@youtube-automation/extensions-shared/overlay-state";
import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";

export interface UseDraggableOptions {
  initial: OverlayPoint;
  elementRef: RefObject<HTMLElement | null>;
  onCommit: (position: OverlayPoint) => void;
}

export interface UseDraggableResult {
  position: OverlayPoint;
  dragging: boolean;
  onPointerDown: (event: ReactPointerEvent) => void;
}

function isInteractive(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.isContentEditable
  );
}

function viewportSize() {
  return { width: window.innerWidth, height: window.innerHeight };
}

function elementSize(element: HTMLElement | null) {
  if (!element) {
    return { width: 0, height: 0 };
  }
  const rect = element.getBoundingClientRect();
  return { width: rect.width, height: rect.height };
}

/** Shared pointer-drag behavior with viewport clamping and resize recovery. */
export function useDraggable({
  initial,
  elementRef,
  onCommit,
}: UseDraggableOptions): UseDraggableResult {
  const [position, setPosition] = useState<OverlayPoint>(initial);
  const [dragging, setDragging] = useState(false);
  const positionRef = useRef(initial);
  const origin = useRef<OverlayPoint>({ x: 0, y: 0 });
  const start = useRef(initial);

  useEffect(() => {
    positionRef.current = position;
  }, [position]);

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
        x: start.current.x + event.clientX - origin.current.x,
        y: start.current.y + event.clientY - origin.current.y,
      };
      setPosition(
        clampOverlayPosition(
          next,
          viewportSize(),
          elementSize(elementRef.current)
        )
      );
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

  useEffect(() => {
    const handleResize = () => {
      const clamped = clampOverlayPosition(
        positionRef.current,
        viewportSize(),
        elementSize(elementRef.current)
      );
      if (
        clamped.x !== positionRef.current.x ||
        clamped.y !== positionRef.current.y
      ) {
        setPosition(clamped);
        onCommit(clamped);
      }
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [elementRef, onCommit]);

  return { position, dragging, onPointerDown };
}
