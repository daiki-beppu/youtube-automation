import {
  COMPLETION_SOUND_ENABLED_DEFAULT,
  COMPLETION_SOUND_PRESET_DEFAULT,
  PHASE,
  type Phase,
} from "../../shared/constants";
import type { CollectionQueueState } from "./collection-queue-state";

export const COMPLETION_SOUND_PRESETS = {
  chime: {
    label: "チャイム",
    wave: "sine",
    success: { frequencies: [523, 659, 784] },
    error: { frequencies: [392, 330, 262] },
  },
  bell: {
    label: "ベル",
    wave: "triangle",
    success: { frequencies: [659, 988] },
    error: { frequencies: [440, 220] },
  },
  soft: {
    label: "ソフト",
    wave: "sine",
    success: { frequencies: [440, 554] },
    error: { frequencies: [330, 247] },
  },
} as const;

export type CompletionSoundPresetId = keyof typeof COMPLETION_SOUND_PRESETS;
export type CompletionSoundKind = "success" | "error";

export interface CompletionSoundSettings {
  enabled: boolean;
  preset: CompletionSoundPresetId;
}

export const DEFAULT_COMPLETION_SOUND_SETTINGS: CompletionSoundSettings = {
  enabled: COMPLETION_SOUND_ENABLED_DEFAULT,
  preset: COMPLETION_SOUND_PRESET_DEFAULT,
};

const PRESET_IDS = new Set<CompletionSoundPresetId>(
  Object.keys(COMPLETION_SOUND_PRESETS) as CompletionSoundPresetId[]
);

export function normalizeCompletionSoundSettings(
  value: unknown
): CompletionSoundSettings {
  if (!value || typeof value !== "object") {
    return { ...DEFAULT_COMPLETION_SOUND_SETTINGS };
  }
  const candidate = value as { enabled?: unknown; preset?: unknown };
  return {
    enabled:
      typeof candidate.enabled === "boolean"
        ? candidate.enabled
        : DEFAULT_COMPLETION_SOUND_SETTINGS.enabled,
    preset: PRESET_IDS.has(candidate.preset as CompletionSoundPresetId)
      ? (candidate.preset as CompletionSoundPresetId)
      : DEFAULT_COMPLETION_SOUND_SETTINGS.preset,
  };
}

export function completionSoundKindForPhase(
  phase: Phase
): CompletionSoundKind | null {
  if (phase === PHASE.FINISHED) return "success";
  if (phase === PHASE.ERROR) return "error";
  return null;
}

/**
 * collection queue の途中の FINISHED は個別 collection の完了であり、
 * queue 全体の作業完了ではない。ERROR は復旧を促すため即時通知する。
 */
export function shouldNotifyCompletionSound(
  phase: Phase,
  queue: CollectionQueueState | null
): boolean {
  if (phase !== PHASE.FINISHED || queue?.status !== "running") return true;
  return queue.currentIndex >= queue.items.length - 1;
}

interface CompletionOscillator {
  type: OscillatorType;
  frequency: { setValueAtTime(value: number, startTime: number): void };
  connect(destination: unknown): void;
  start(startTime: number): void;
  stop(stopTime: number): void;
}

interface CompletionGain {
  gain: {
    setValueAtTime(value: number, startTime: number): void;
    exponentialRampToValueAtTime(value: number, endTime: number): void;
  };
  connect(destination: unknown): void;
}

interface CompletionAudioContext {
  currentTime: number;
  state: string;
  destination: unknown;
  resume(): Promise<unknown>;
  createOscillator(): CompletionOscillator;
  createGain(): CompletionGain;
  close(): Promise<unknown>;
}

type AudioContextFactory = () => CompletionAudioContext;
type Wait = (milliseconds: number) => Promise<void>;

const wait: Wait = (milliseconds) =>
  new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds));

function createBrowserAudioContext(): CompletionAudioContext {
  const AudioContextConstructor = globalThis.AudioContext;
  if (!AudioContextConstructor) {
    throw new Error("Web Audio API を利用できません。");
  }
  return new AudioContextConstructor();
}

export async function playCompletionSound(
  presetId: CompletionSoundPresetId,
  kind: CompletionSoundKind,
  createContext: AudioContextFactory = createBrowserAudioContext,
  waitForPlayback: Wait = wait
): Promise<void> {
  const preset = COMPLETION_SOUND_PRESETS[presetId];
  const context = createContext();
  let playbackError: unknown;
  try {
    if (context.state === "suspended") {
      await context.resume();
    }
    const noteDurationSec = 0.16;
    const noteGapSec = 0.04;
    const frequencies = preset[kind].frequencies;
    for (const [index, frequency] of frequencies.entries()) {
      const startTime =
        context.currentTime + index * (noteDurationSec + noteGapSec);
      const stopTime = startTime + noteDurationSec;
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = preset.wave;
      oscillator.frequency.setValueAtTime(frequency, startTime);
      gain.gain.setValueAtTime(0.12, startTime);
      gain.gain.exponentialRampToValueAtTime(0.001, stopTime);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(startTime);
      oscillator.stop(stopTime);
    }
    const totalDurationMs =
      (frequencies.length * (noteDurationSec + noteGapSec) + 0.05) * 1000;
    await waitForPlayback(totalDurationMs);
  } catch (error) {
    playbackError = error;
    throw error;
  } finally {
    try {
      await context.close();
    } catch (closeError) {
      console.warn(
        playbackError === undefined
          ? "[suno-helper] 完了音の AudioContext 解放に失敗しました:"
          : "[suno-helper] 完了音の AudioContext 解放にも失敗しました:",
        closeError
      );
    }
  }
}
