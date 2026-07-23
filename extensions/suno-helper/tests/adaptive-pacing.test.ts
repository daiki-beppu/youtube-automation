import { describe, expect, it, vi } from "vitest";

import {
  ADAPTIVE_BURST_COOLDOWN_MS,
  ADAPTIVE_CHALLENGE_BACKOFF_MAX_MS,
  BALANCED_RUN_PACING,
  MAX_INFLIGHT_REQUESTS,
} from "../../shared/constants";
import {
  createAdaptivePacingState,
  decideAdaptivePacing,
  recordChallenge,
  recordSuccessfulCreate,
  waitForAdaptivePacing,
} from "../lib/adaptive-pacing";

describe("adaptive pacing policy", () => {
  it("keeps the existing 3–9 second baseline and max 10 requests", () => {
    expect(BALANCED_RUN_PACING.interCreateDelayMs).toBe(6000);
    expect(BALANCED_RUN_PACING.jitterMs).toBe(3000);
    expect(BALANCED_RUN_PACING.maxInflightRequests).toBe(MAX_INFLIGHT_REQUESTS);
    expect(MAX_INFLIGHT_REQUESTS).toBe(10);
    expect(decideAdaptivePacing(createAdaptivePacingState(), 0)).toEqual({
      delayMs: 0,
      reasons: [],
    });
  });

  it("adds a finite cooldown only after four creates inside 30 seconds", () => {
    let state = createAdaptivePacingState();
    for (const now of [0, 6000, 12_000, 18_000]) {
      state = recordSuccessfulCreate(state, now);
    }

    expect(decideAdaptivePacing(state, 20_000)).toEqual({
      delayMs: ADAPTIVE_BURST_COOLDOWN_MS,
      reasons: ["burst"],
    });
    expect(decideAdaptivePacing(state, 48_001)).toEqual({
      delayMs: 0,
      reasons: [],
    });
  });

  it("steps challenge backoff to a cap and recovers after healthy creates", () => {
    let state = createAdaptivePacingState();
    for (let index = 0; index < 10; index += 1) {
      state = recordChallenge(state);
    }
    expect(decideAdaptivePacing(state, 0).delayMs).toBe(
      ADAPTIVE_CHALLENGE_BACKOFF_MAX_MS
    );

    state = recordSuccessfulCreate(state, 0);
    state = recordSuccessfulCreate(state, 40_000);
    expect(state.challengeLevel).toBe(4);
    state = recordSuccessfulCreate(state, 80_000);
    expect(state.challengeLevel).toBe(3);
    expect(decideAdaptivePacing(state, 80_001).delayMs).toBe(45_000);
  });

  it("uses the larger delay when burst and challenge overlap", () => {
    let state = recordChallenge(createAdaptivePacingState());
    for (const now of [0, 1000, 2000, 3000]) {
      state = recordSuccessfulCreate(state, now);
    }
    state = recordChallenge(state);
    state = recordChallenge(state);

    expect(decideAdaptivePacing(state, 4000)).toEqual({
      delayMs: 30_000,
      reasons: ["burst", "challenge"],
    });
  });

  it("uses abortable sleep so Stop interrupts a cooldown before Create", async () => {
    const state = recordChallenge(createAdaptivePacingState());
    let aborted = false;
    const sleep = vi.fn(async (_ms: number, _isAborted: () => boolean) => {
      aborted = true;
    });

    const decision = await waitForAdaptivePacing(
      decideAdaptivePacing(state, 0),
      sleep,
      () => aborted
    );

    expect(decision.delayMs).toBe(15_000);
    expect(sleep).toHaveBeenCalledWith(15_000, expect.any(Function));
    expect(aborted).toBe(true);
  });
});
