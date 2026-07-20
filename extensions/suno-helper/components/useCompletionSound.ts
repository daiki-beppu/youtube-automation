import { useCallback, useEffect, useRef, useState } from "react";

import type { Phase } from "../../shared/constants";
import {
  completionSoundKindForPhase,
  DEFAULT_COMPLETION_SOUND_SETTINGS,
  playCompletionSound,
  type CompletionSoundSettings,
} from "../lib/completion-sound";
import { sendMessage } from "../lib/messaging";
import {
  completionSoundSettingsItem,
  readCompletionSoundSettings,
} from "../lib/storage";

interface UseCompletionSoundOptions {
  onStorageError: (error: unknown) => void;
}

interface PendingNotification {
  phase: Phase;
  message: string;
}

export interface CompletionSoundController {
  completionSoundSettings: CompletionSoundSettings;
  completionSoundSettingsLoaded: boolean;
  setCompletionSoundEnabled: (enabled: boolean) => void;
  notifyCompletionSoundPhase: (phase: Phase, message: string) => void;
}

export function useCompletionSound(
  options: UseCompletionSoundOptions
): CompletionSoundController {
  const { onStorageError } = options;
  const [completionSoundSettings, setCompletionSoundSettings] =
    useState<CompletionSoundSettings>(DEFAULT_COMPLETION_SOUND_SETTINGS);
  const [completionSoundSettingsLoaded, setCompletionSoundSettingsLoaded] =
    useState(false);
  const settingsRef = useRef(completionSoundSettings);
  const soundedTerminalPhaseRef = useRef<Phase | null>(null);
  const settingsLoadedRef = useRef(false);
  const pendingNotificationRef = useRef<PendingNotification | null>(null);

  const playTerminalPhase = useCallback(
    (phase: Phase, message: string): void => {
      const soundKind = completionSoundKindForPhase(phase);
      if (!soundKind || soundedTerminalPhaseRef.current === phase) return;
      soundedTerminalPhaseRef.current = phase;
      if (!settingsRef.current.enabled) return;

      void playCompletionSound(soundKind).catch((error) =>
        console.warn("[suno-helper] 通知音の再生に失敗しました:", error)
      );
      void sendMessage("showSunoNotification", {
        kind: soundKind,
        message,
      }).catch((error) =>
        console.warn("[suno-helper] OS 通知の表示に失敗しました:", error)
      );
    },
    []
  );

  useEffect(() => {
    void readCompletionSoundSettings()
      .then((settings) => {
        settingsRef.current = settings;
        setCompletionSoundSettings(settings);
        settingsLoadedRef.current = true;
        setCompletionSoundSettingsLoaded(true);
        const pending = pendingNotificationRef.current;
        pendingNotificationRef.current = null;
        if (pending) playTerminalPhase(pending.phase, pending.message);
      })
      .catch(onStorageError);
  }, [onStorageError, playTerminalPhase]);

  const setCompletionSoundEnabled = useCallback(
    (enabled: boolean): void => {
      const settings = { enabled };
      settingsRef.current = settings;
      setCompletionSoundSettings(settings);
      void completionSoundSettingsItem.setValue(settings).catch(onStorageError);
    },
    [onStorageError]
  );

  const notifyCompletionSoundPhase = useCallback(
    (phase: Phase, message: string): void => {
      const soundKind = completionSoundKindForPhase(phase);
      if (!soundKind) {
        soundedTerminalPhaseRef.current = null;
        pendingNotificationRef.current = null;
        return;
      }
      if (!settingsLoadedRef.current) {
        pendingNotificationRef.current = { phase, message };
        return;
      }
      playTerminalPhase(phase, message);
    },
    [playTerminalPhase]
  );

  return {
    completionSoundSettings,
    completionSoundSettingsLoaded,
    setCompletionSoundEnabled,
    notifyCompletionSoundPhase,
  };
}
