import { describe, expect, it, vi } from "vitest";

import { PHASE } from "../../shared/constants";
import {
  completionSoundKindForPhase,
  normalizeCompletionSoundSettings,
  playCompletionSound,
  shouldNotifyCompletionSound,
} from "../lib/completion-sound";

describe("terminal notification policy", () => {
  it("FINISHED は success、ERROR は error、STOPPED は無音にする", () => {
    expect(completionSoundKindForPhase(PHASE.FINISHED)).toBe("success");
    expect(completionSoundKindForPhase(PHASE.ERROR)).toBe("error");
    expect(completionSoundKindForPhase(PHASE.STOPPED)).toBeNull();
    expect(completionSoundKindForPhase(PHASE.DONE)).toBeNull();
  });

  it("collection queue は最終 item の FINISHED だけを通知する", () => {
    const queue = {
      version: 1 as const,
      queueId: "queue-1",
      baseUrl: "http://localhost:7873",
      items: [
        { collectionId: "first", status: "pending" as const },
        { collectionId: "last", status: "pending" as const },
      ],
      currentIndex: 0,
      status: "running" as const,
      runMode: "serial" as const,
      regenerateDurationOutliers: false,
      createdAt: 1,
      updatedAt: 1,
    };
    expect(shouldNotifyCompletionSound(PHASE.FINISHED, queue)).toBe(false);
    expect(
      shouldNotifyCompletionSound(PHASE.FINISHED, {
        ...queue,
        currentIndex: 1,
      })
    ).toBe(true);
    expect(shouldNotifyCompletionSound(PHASE.ERROR, queue)).toBe(true);
    expect(shouldNotifyCompletionSound(PHASE.FINISHED, null)).toBe(true);
  });

  it("旧 preset を捨てつつ enabled を維持する", () => {
    expect(normalizeCompletionSoundSettings(undefined)).toEqual({
      enabled: true,
    });
    expect(
      normalizeCompletionSoundSettings({ enabled: "yes", preset: "noise" })
    ).toEqual({ enabled: true });
    expect(
      normalizeCompletionSoundSettings({ enabled: false, preset: "soft" })
    ).toEqual({ enabled: false });
  });

  it("resume に失敗しても AudioContext を close し、元の失敗を維持する", async () => {
    const resumeError = new Error("autoplay blocked");
    const closeError = new Error("close failed");
    const context = {
      currentTime: 0,
      state: "suspended",
      destination: {},
      resume: vi.fn(async () => Promise.reject(resumeError)),
      createOscillator: vi.fn(),
      createGain: vi.fn(),
      close: vi.fn(async () => Promise.reject(closeError)),
    };
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    await expect(playCompletionSound("success", () => context)).rejects.toBe(
      resumeError
    );
    expect(context.close).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith(
      "[suno-helper] 通知音の AudioContext 解放にも失敗しました:",
      closeError
    );
    warn.mockRestore();
  });
});

describe("playCompletionSound", () => {
  function makeContext() {
    const frequencies: number[] = [];
    const waves: OscillatorType[] = [];
    const context = {
      currentTime: 10,
      state: "suspended",
      destination: {},
      resume: vi.fn(async () => undefined),
      createOscillator: vi.fn(() => {
        const oscillator = {
          type: "sine" as OscillatorType,
          frequency: {
            setValueAtTime: vi.fn((value: number) => frequencies.push(value)),
          },
          connect: vi.fn(),
          start: vi.fn(),
          stop: vi.fn(),
        };
        Object.defineProperty(oscillator, "type", {
          get: () => waves.at(-1) ?? "sine",
          set: (wave: OscillatorType) => waves.push(wave),
        });
        return oscillator;
      }),
      createGain: vi.fn(() => ({
        gain: {
          setValueAtTime: vi.fn(),
          exponentialRampToValueAtTime: vi.fn(),
        },
        connect: vi.fn(),
      })),
      close: vi.fn(async () => undefined),
    };
    return { context, frequencies, waves };
  }

  it.each([
    ["success", [523, 659, 784], "sine"],
    ["error", [440, 220], "triangle"],
  ] as const)("%s は固定波形と音程列を鳴らす", async (kind, expected, wave) => {
    const { context, frequencies, waves } = makeContext();
    await playCompletionSound(
      kind,
      () => context,
      async () => undefined
    );

    expect(frequencies).toEqual(expected);
    expect(waves).toEqual(expected.map(() => wave));
    expect(context.close).toHaveBeenCalledOnce();
  });
});
