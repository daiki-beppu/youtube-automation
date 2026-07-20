import {
  createOverlayStateStorage,
  type OverlayState,
} from "@youtube-automation/extensions-shared/overlay-state";
import { storage } from "wxt/utils/storage";

import { OVERLAY_STATE_KEY } from "../../shared/constants";

const overlayStorage = createOverlayStateStorage(
  OVERLAY_STATE_KEY,
  (key, options) => storage.defineItem<OverlayState | null>(key, options)
);

export function readOverlayState(): Promise<OverlayState | null> {
  return overlayStorage.read();
}

export function writeOverlayState(state: OverlayState): Promise<void> {
  return overlayStorage.write(state);
}
