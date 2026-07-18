import { describe, expect, it, vi } from "vitest";

import { PHASE } from "../../shared/constants";
import {
  COMPLETION_SOUND_PRESETS,
  completionSoundKindForPhase,
  normalizeCompletionSoundSettings,
  playCompletionSound,
  shouldNotifyCompletionSound,
} from "../lib/completion-sound";

describe("completion sound terminal policy (#2077)", () => {
  it("FINISHED は success、ERROR は error、STOPPED は無音にする", () => {
    expect(completionSoundKindForPhase(PHASE.FINISHED)).toBe("success");
    expect(completionSoundKindForPhase(PHASE.ERROR)).toBe("error");
    expect(completionSoundKindForPhase(PHASE.STOPPED)).toBeNull();
    expect(completionSoundKindForPhase(PHASE.DONE)).toBeNull();
  });

  it("collection queue は最終 item の FINISHED だけを作業完了として通知する", () => {
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

  it("未設定・不正値を default ON + chime へ正規化する", () => {
    expect(normalizeCompletionSoundSettings(undefined)).toEqual({
      enabled: true,
      preset: "chime",
    });
    expect(
      normalizeCompletionSoundSettings({ enabled: "yes", preset: "noise" })
    ).toEqual({ enabled: true, preset: "chime" });
    expect(
      normalizeCompletionSoundSettings({ enabled: false, preset: "soft" })
    ).toEqual({ enabled: false, preset: "soft" });
  });

  it("success と error は同じ preset でも異なる音程列を持つ", () => {
    for (const preset of Object.values(COMPLETION_SOUND_PRESETS)) {
      expect(preset.success.frequencies).not.toEqual(preset.error.frequencies);
    }
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

    await expect(
      playCompletionSound("chime", "success", () => context)
    ).rejects.toBe(resumeError);
    expect(context.close).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith(
      "[suno-helper] 完了音の AudioContext 解放にも失敗しました:",
      closeError
    );
    warn.mockRestore();
  });
});

describe("playCompletionSound (#2077)", () => {
  it("AudioContext を resume し oscillator を preset の音数だけ鳴らして close する", async () => {
    const starts: number[] = [];
    const frequencies: number[] = [];
    const oscillator = {
      type: "sine" as OscillatorType,
      frequency: {
        setValueAtTime: vi.fn((value: number) => frequencies.push(value)),
      },
      connect: vi.fn(),
      start: vi.fn((time: number) => starts.push(time)),
      stop: vi.fn(),
    };
    const gain = {
      gain: {
        setValueAtTime: vi.fn(),
        exponentialRampToValueAtTime: vi.fn(),
      },
      connect: vi.fn(),
    };
    const context = {
      currentTime: 10,
      state: "suspended",
      destination: {},
      resume: vi.fn(async () => undefined),
      createOscillator: vi.fn(() => ({ ...oscillator })),
      createGain: vi.fn(() => gain),
      close: vi.fn(async () => undefined),
    };

    await playCompletionSound(
      "chime",
      "success",
      () => context,
      async () => undefined
    );

    expect(context.resume).toHaveBeenCalledOnce();
    expect(context.createOscillator).toHaveBeenCalledTimes(
      COMPLETION_SOUND_PRESETS.chime.success.frequencies.length
    );
    expect(frequencies).toEqual(
      COMPLETION_SOUND_PRESETS.chime.success.frequencies
    );
    expect(starts[0]).toBe(10);
    expect(context.close).toHaveBeenCalledOnce();
  });
});
