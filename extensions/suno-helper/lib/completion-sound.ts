import {
  COMPLETION_SOUND_ENABLED_DEFAULT,
  PHASE,
  type Phase,
} from "../../shared/constants";
import type { CollectionQueueState } from "./collection-queue-state";

export type CompletionSoundKind = "success" | "error";

export interface CompletionSoundSettings {
  enabled: boolean;
}

export const DEFAULT_COMPLETION_SOUND_SETTINGS: CompletionSoundSettings = {
  enabled: COMPLETION_SOUND_ENABLED_DEFAULT,
};

export function normalizeCompletionSoundSettings(
  value: unknown
): CompletionSoundSettings {
  if (!value || typeof value !== "object") {
    return { ...DEFAULT_COMPLETION_SOUND_SETTINGS };
  }
  const candidate = value as { enabled?: unknown };
  return {
    enabled:
      typeof candidate.enabled === "boolean"
        ? candidate.enabled
        : DEFAULT_COMPLETION_SOUND_SETTINGS.enabled,
  };
}

export function completionSoundKindForPhase(
  phase: Phase
): CompletionSoundKind | null {
  if (phase === PHASE.FINISHED) return "success";
  if (phase === PHASE.ERROR) return "error";
  return null;
}

/** collection queue の途中の FINISHED は通知せず、ERROR と最終 FINISHED だけ通知する。 */
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
  kind: CompletionSoundKind,
  createContext: AudioContextFactory = createBrowserAudioContext,
  waitForPlayback: Wait = wait
): Promise<void> {
  const tone =
    kind === "success"
      ? ({ wave: "sine", frequencies: [523, 659, 784] } as const)
      : ({ wave: "triangle", frequencies: [440, 220] } as const);
  const context = createContext();
  let playbackError: unknown;
  try {
    if (context.state === "suspended") {
      await context.resume();
    }
    const noteDurationSec = 0.16;
    const noteGapSec = 0.04;
    for (const [index, frequency] of tone.frequencies.entries()) {
      const startTime =
        context.currentTime + index * (noteDurationSec + noteGapSec);
      const stopTime = startTime + noteDurationSec;
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = tone.wave;
      oscillator.frequency.setValueAtTime(frequency, startTime);
      gain.gain.setValueAtTime(0.12, startTime);
      gain.gain.exponentialRampToValueAtTime(0.001, stopTime);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(startTime);
      oscillator.stop(stopTime);
    }
    const totalDurationMs =
      (tone.frequencies.length * (noteDurationSec + noteGapSec) + 0.05) * 1000;
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
          ? "[suno-helper] 通知音の AudioContext 解放に失敗しました:"
          : "[suno-helper] 通知音の AudioContext 解放にも失敗しました:",
        closeError
      );
    }
  }
}
