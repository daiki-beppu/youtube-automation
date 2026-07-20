import type { OverlayState } from "@youtube-automation/extensions-shared/overlay-state";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  OverlayShell,
} from "@youtube-automation/ui";
import { useCallback, useEffect, useState } from "react";

import { onMessage } from "@/lib/messaging";
import { DISTROKID_OVERLAY_BRAND } from "@/lib/overlay-brand";
import { readOverlayState, writeOverlayState } from "@/lib/overlay-storage";

import { App } from "./App";

export function Overlay() {
  const [initial, setInitial] = useState<OverlayState | null | undefined>();
  const [error, setError] = useState<string>();

  const handleError = useCallback((cause: unknown) => {
    setError(cause instanceof Error ? cause.message : String(cause));
  }, []);

  useEffect(() => {
    void readOverlayState()
      .then((state) => setInitial(state))
      .catch(handleError);
  }, [handleError]);

  const subscribeToggle = useCallback(
    (toggle: () => void) => onMessage("toggleOverlay", toggle),
    []
  );

  if (error !== undefined) {
    return (
      <Alert
        variant="destructive"
        className="fixed top-4 right-4 w-[360px]"
        style={{ zIndex: 2_147_483_647 }}
      >
        <AlertTitle>再読み込みが必要です</AlertTitle>
        <AlertDescription>
          DistroKid Helper を更新しました。ページを再読み込みしてください。
        </AlertDescription>
      </Alert>
    );
  }
  if (initial === undefined) {
    return null;
  }

  return (
    <OverlayShell
      title="DistroKid Helper"
      initialState={initial}
      onStateChange={writeOverlayState}
      subscribeToggle={subscribeToggle}
      onError={handleError}
      brandColors={DISTROKID_OVERLAY_BRAND}
    >
      <App />
    </OverlayShell>
  );
}
