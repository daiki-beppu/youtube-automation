/** A viewport-relative point used by every helper overlay. */
export interface OverlayPoint {
  x: number;
  y: number;
}

/** The state persisted independently by each helper. */
export interface OverlayState {
  position: OverlayPoint;
  minimized: boolean;
  hidden: boolean;
}

export interface OverlaySize {
  width: number;
  height: number;
}

export interface OverlayStateStorage {
  read: () => Promise<OverlayState | null>;
  write: (state: OverlayState) => Promise<void>;
}

interface OverlayStorageItem {
  getValue: () => Promise<OverlayState | null>;
  setValue: (state: OverlayState) => Promise<void>;
}

export type DefineOverlayStorageItem = (
  key: `local:${string}`,
  options: { fallback: null }
) => OverlayStorageItem;

const OVERLAY_MARGIN = 16;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/** Keep the complete overlay box inside the current viewport. */
export function clampOverlayPosition(
  position: OverlayPoint,
  viewport: OverlaySize,
  overlay: OverlaySize
): OverlayPoint {
  const maxX = Math.max(0, viewport.width - overlay.width);
  const maxY = Math.max(0, viewport.height - overlay.height);
  return {
    x: clamp(position.x, 0, maxX),
    y: clamp(position.y, 0, maxY),
  };
}

/** Return the default top-right position with the shared 16px margin. */
export function topRightOverlayPosition(
  viewport: OverlaySize,
  overlay: OverlaySize
): OverlayPoint {
  return clampOverlayPosition(
    {
      x: viewport.width - overlay.width - OVERLAY_MARGIN,
      y: OVERLAY_MARGIN,
    },
    viewport,
    overlay
  );
}

export function toggleOverlayHidden(state: OverlayState): OverlayState {
  return { ...state, hidden: !state.hidden };
}

/** Hide without unmounting so the action-toggle subscription remains alive. */
export function overlayHiddenStyle(hidden: boolean): {
  display: "none" | "block";
} {
  return { display: hidden ? "none" : "block" };
}

/**
 * Create a lazy, helper-keyed WXT storage adapter.
 *
 * The storage factory is injected so this shared module stays browser-API free
 * during Node-based tests and WXT entrypoint discovery.
 */
export function createOverlayStateStorage(
  storageKey: string,
  defineItem: DefineOverlayStorageItem
): OverlayStateStorage {
  let item: OverlayStorageItem | undefined;
  const getItem = () => {
    item ??= defineItem(`local:${storageKey}`, { fallback: null });
    return item;
  };

  return {
    read: () => getItem().getValue(),
    write: (state) => getItem().setValue(state),
  };
}
