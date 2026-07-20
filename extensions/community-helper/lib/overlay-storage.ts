import { storage } from "@wxt-dev/storage";
import {
  createOverlayStateStorage,
  type OverlayState,
} from "@youtube-automation/extensions-shared/overlay-state";

import { COMMUNITY_OVERLAY_STATE_KEY } from "../../shared/constants";

const overlayStorage = createOverlayStateStorage(
  COMMUNITY_OVERLAY_STATE_KEY,
  (key, options) => storage.defineItem<OverlayState | null>(key, options)
);

export const readOverlayState = overlayStorage.read;
export const writeOverlayState = overlayStorage.write;
