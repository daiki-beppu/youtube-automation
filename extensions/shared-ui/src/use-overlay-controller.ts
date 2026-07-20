import {
  clampOverlayPosition,
  toggleOverlayHidden,
  topRightOverlayPosition,
} from "@youtube-automation/extensions-shared/overlay-state";
import type {
  OverlayPoint,
  OverlayState,
} from "@youtube-automation/extensions-shared/overlay-state";
import { useCallback, useEffect, useRef, useState } from "react";

import { useDraggable } from "./use-draggable";

interface OverlayControllerOptions {
  initialState: OverlayState | null;
  width: number;
  onStateChange: (state: OverlayState) => void | Promise<void>;
  subscribeToggle: (toggle: () => void) => () => void;
  onError?: (error: unknown) => void;
}

function resolveInitialPosition(
  initialState: OverlayState | null,
  width: number
): OverlayPoint {
  const viewport = { width: window.innerWidth, height: window.innerHeight };
  const size = { width, height: 0 };
  return initialState
    ? clampOverlayPosition(initialState.position, viewport, size)
    : topRightOverlayPosition(viewport, size);
}

export function useOverlayController({
  initialState,
  width,
  onStateChange,
  subscribeToggle,
  onError,
}: OverlayControllerOptions) {
  const initial = resolveInitialPosition(initialState, width);
  const containerRef = useRef<HTMLDivElement>(null);
  const positionRef = useRef(initial);
  const minimizedRef = useRef(initialState?.minimized ?? false);
  const hiddenRef = useRef(initialState?.hidden ?? false);
  const [minimized, setMinimized] = useState(minimizedRef.current);
  const [hidden, setHidden] = useState(hiddenRef.current);

  const persist = useCallback(
    (state: OverlayState) => {
      void Promise.resolve(onStateChange(state)).catch((error: unknown) => {
        onError?.(error);
      });
    },
    [onError, onStateChange]
  );

  const onCommit = useCallback(
    (position: OverlayPoint) => {
      positionRef.current = position;
      persist({
        position,
        minimized: minimizedRef.current,
        hidden: hiddenRef.current,
      });
    },
    [persist]
  );

  const draggable = useDraggable({
    initial,
    elementRef: containerRef,
    onCommit,
  });

  useEffect(() => {
    positionRef.current = draggable.position;
  }, [draggable.position]);

  useEffect(
    () =>
      subscribeToggle(() => {
        const next = toggleOverlayHidden({
          position: positionRef.current,
          minimized: minimizedRef.current,
          hidden: hiddenRef.current,
        });
        hiddenRef.current = next.hidden;
        setHidden(next.hidden);
        persist(next);
      }),
    [persist, subscribeToggle]
  );

  const toggleMinimized = useCallback(() => {
    const next = !minimizedRef.current;
    minimizedRef.current = next;
    setMinimized(next);
    persist({
      position: positionRef.current,
      minimized: next,
      hidden: hiddenRef.current,
    });
  }, [persist]);

  return {
    containerRef,
    minimized,
    hidden,
    toggleMinimized,
    ...draggable,
  };
}
