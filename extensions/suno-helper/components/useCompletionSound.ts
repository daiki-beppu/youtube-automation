import { useCallback, useEffect, useRef, useState } from "react";

import type { Phase } from "../../shared/constants";
import {
  completionSoundKindForPhase,
  DEFAULT_COMPLETION_SOUND_SETTINGS,
  playCompletionSound,
  type CompletionSoundPresetId,
  type CompletionSoundSettings,
} from "../lib/completion-sound";
import {
  completionSoundSettingsItem,
  readCompletionSoundSettings,
} from "../lib/storage";

interface UseCompletionSoundOptions {
  onStorageError: (error: unknown) => void;
  onPreviewError: (message: string) => void;
}

export interface CompletionSoundController {
  completionSoundSettings: CompletionSoundSettings;
  completionSoundSettingsLoaded: boolean;
  setCompletionSoundEnabled: (enabled: boolean) => void;
  setCompletionSoundPreset: (preset: CompletionSoundPresetId) => void;
  previewCompletionSound: () => Promise<void>;
  notifyCompletionSoundPhase: (phase: Phase) => void;
}

export function useCompletionSound(
  options: UseCompletionSoundOptions
): CompletionSoundController {
  const { onStorageError, onPreviewError } = options;
  const [completionSoundSettings, setCompletionSoundSettings] =
    useState<CompletionSoundSettings>(DEFAULT_COMPLETION_SOUND_SETTINGS);
  const [completionSoundSettingsLoaded, setCompletionSoundSettingsLoaded] =
    useState(false);
  const settingsRef = useRef(completionSoundSettings);
  const soundedTerminalPhaseRef = useRef<Phase | null>(null);
  const settingsLoadedRef = useRef(false);
  const pendingTerminalPhaseRef = useRef<Phase | null>(null);

  const playTerminalPhase = useCallback((phase: Phase): void => {
    const soundKind = completionSoundKindForPhase(phase);
    if (!soundKind || soundedTerminalPhaseRef.current === phase) return;
    soundedTerminalPhaseRef.current = phase;
    const settings = settingsRef.current;
    if (!settings.enabled) return;
    void playCompletionSound(settings.preset, soundKind).catch((error) =>
      console.warn("[suno-helper] 完了音の再生に失敗しました:", error)
    );
  }, []);

  useEffect(() => {
    void readCompletionSoundSettings()
      .then((settings) => {
        settingsRef.current = settings;
        setCompletionSoundSettings(settings);
        settingsLoadedRef.current = true;
        setCompletionSoundSettingsLoaded(true);
        const pendingPhase = pendingTerminalPhaseRef.current;
        pendingTerminalPhaseRef.current = null;
        if (pendingPhase) playTerminalPhase(pendingPhase);
      })
      .catch(onStorageError);
  }, [onStorageError, playTerminalPhase]);

  const persistSettings = useCallback(
    (settings: CompletionSoundSettings): void => {
      settingsRef.current = settings;
      setCompletionSoundSettings(settings);
      void completionSoundSettingsItem.setValue(settings).catch(onStorageError);
    },
    [onStorageError]
  );

  const setCompletionSoundEnabled = useCallback(
    (enabled: boolean): void => {
      persistSettings({ ...settingsRef.current, enabled });
    },
    [persistSettings]
  );

  const setCompletionSoundPreset = useCallback(
    (preset: CompletionSoundPresetId): void => {
      persistSettings({ ...settingsRef.current, preset });
    },
    [persistSettings]
  );

  const previewCompletionSound = useCallback(async (): Promise<void> => {
    try {
      await playCompletionSound(settingsRef.current.preset, "success");
    } catch (error) {
      onPreviewError(error instanceof Error ? error.message : String(error));
    }
  }, [onPreviewError]);

  const notifyCompletionSoundPhase = useCallback(
    (phase: Phase): void => {
      const soundKind = completionSoundKindForPhase(phase);
      if (!soundKind) {
        soundedTerminalPhaseRef.current = null;
        pendingTerminalPhaseRef.current = null;
        return;
      }
      if (!settingsLoadedRef.current) {
        pendingTerminalPhaseRef.current = phase;
        return;
      }
      playTerminalPhase(phase);
    },
    [playTerminalPhase]
  );

  return {
    completionSoundSettings,
    completionSoundSettingsLoaded,
    setCompletionSoundEnabled,
    setCompletionSoundPreset,
    previewCompletionSound,
    notifyCompletionSoundPhase,
  };
}
