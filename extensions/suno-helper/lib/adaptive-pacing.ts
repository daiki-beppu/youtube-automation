import {
  ADAPTIVE_BURST_COOLDOWN_MS,
  ADAPTIVE_BURST_CREATE_THRESHOLD,
  ADAPTIVE_BURST_WINDOW_MS,
  ADAPTIVE_CHALLENGE_BACKOFF_MAX_MS,
  ADAPTIVE_CHALLENGE_BACKOFF_STEP_MS,
  ADAPTIVE_HEALTHY_CREATES_PER_RECOVERY,
} from "../../shared/constants";

export interface AdaptivePacingState {
  recentCreateTimestamps: number[];
  challengeLevel: number;
  healthyCreatesSinceChallenge: number;
}

export interface AdaptivePacingDecision {
  delayMs: number;
  reasons: Array<"burst" | "challenge">;
}

export function createAdaptivePacingState(): AdaptivePacingState {
  return {
    recentCreateTimestamps: [],
    challengeLevel: 0,
    healthyCreatesSinceChallenge: 0,
  };
}

function recentCreates(state: AdaptivePacingState, now: number): number[] {
  const cutoff = now - ADAPTIVE_BURST_WINDOW_MS;
  return state.recentCreateTimestamps.filter(
    (timestamp) => timestamp >= cutoff
  );
}

export function decideAdaptivePacing(
  state: AdaptivePacingState,
  now: number
): AdaptivePacingDecision {
  const reasons: AdaptivePacingDecision["reasons"] = [];
  const burstDelay =
    recentCreates(state, now).length >= ADAPTIVE_BURST_CREATE_THRESHOLD
      ? ADAPTIVE_BURST_COOLDOWN_MS
      : 0;
  if (burstDelay > 0) reasons.push("burst");
  const challengeDelay = Math.min(
    state.challengeLevel * ADAPTIVE_CHALLENGE_BACKOFF_STEP_MS,
    ADAPTIVE_CHALLENGE_BACKOFF_MAX_MS
  );
  if (challengeDelay > 0) reasons.push("challenge");
  return { delayMs: Math.max(burstDelay, challengeDelay), reasons };
}

export async function waitForAdaptivePacing(
  decision: AdaptivePacingDecision,
  abortableSleep: (ms: number, isAborted: () => boolean) => Promise<void>,
  isAborted: () => boolean
): Promise<AdaptivePacingDecision> {
  if (decision.delayMs > 0 && !isAborted()) {
    await abortableSleep(decision.delayMs, isAborted);
  }
  return decision;
}

export function recordChallenge(
  state: AdaptivePacingState
): AdaptivePacingState {
  return {
    ...state,
    challengeLevel: Math.min(
      state.challengeLevel + 1,
      Math.ceil(
        ADAPTIVE_CHALLENGE_BACKOFF_MAX_MS / ADAPTIVE_CHALLENGE_BACKOFF_STEP_MS
      )
    ),
    healthyCreatesSinceChallenge: 0,
  };
}

export function recordSuccessfulCreate(
  state: AdaptivePacingState,
  now: number
): AdaptivePacingState {
  const healthyCreatesSinceChallenge =
    state.challengeLevel > 0 ? state.healthyCreatesSinceChallenge + 1 : 0;
  const recovered =
    state.challengeLevel > 0 &&
    healthyCreatesSinceChallenge >= ADAPTIVE_HEALTHY_CREATES_PER_RECOVERY;
  return {
    recentCreateTimestamps: [...recentCreates(state, now), now],
    challengeLevel: recovered
      ? Math.max(0, state.challengeLevel - 1)
      : state.challengeLevel,
    healthyCreatesSinceChallenge: recovered ? 0 : healthyCreatesSinceChallenge,
  };
}
