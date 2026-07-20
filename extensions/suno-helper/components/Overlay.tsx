import type { OverlayState } from "@youtube-automation/extensions-shared/overlay-state";
import { OverlayShell } from "@youtube-automation/ui";
import { useCallback, useEffect, useState } from "react";

import { onMessage, sendMessage } from "../lib/messaging";
import { readOverlayState, writeOverlayState } from "../lib/overlay-storage";
import { App } from "./App";
import { ReloadRequiredNotice } from "./ReloadRequiredNotice";

/**
 * Suno adapter for the shared overlay foundation. Messaging, copy and the
 * helper-specific storage key remain outside the service-neutral UI package.
 */
export function Overlay() {
  const [initial, setInitial] = useState<OverlayState | null | undefined>(
    undefined
  );
  const [reloadRequired, setReloadRequired] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const version = browser.runtime.getManifest().version;
        const handshake = await sendMessage("extensionVersionHandshake", {
          version,
        });
        if (!handshake.matches) {
          setReloadRequired(true);
          return;
        }
        setInitial((await readOverlayState()) ?? null);
      } catch (error) {
        console.warn(
          "[suno-helper] overlay の初期化に失敗しました（拡張更新後はタブを再読み込みしてください）:",
          error
        );
        setReloadRequired(true);
      }
    })();
  }, []);

  const subscribeToggle = useCallback(
    (toggle: () => void) => onMessage("toggleOverlay", toggle),
    []
  );

  const handlePersistenceError = useCallback((error: unknown) => {
    console.warn(
      "[suno-helper] overlay state の保存に失敗しました（拡張更新後はタブを再読み込みしてください）:",
      error
    );
    setReloadRequired(true);
  }, []);

  if (reloadRequired) {
    return <ReloadRequiredNotice />;
  }
  if (initial === undefined) {
    return null;
  }

  return (
    <OverlayShell
      title="Suno Helper"
      initialState={initial}
      onStateChange={writeOverlayState}
      subscribeToggle={subscribeToggle}
      onError={handlePersistenceError}
    >
      <App />
    </OverlayShell>
  );
}
