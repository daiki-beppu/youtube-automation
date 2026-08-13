import {
  PHASE,
  type Phase,
  type RunTimingEvent,
  type RunTimingOutcome,
  type RunTimingReceipt,
} from "../../shared/constants";

const RUN_TIMING_RECEIPT_VERSION = 1 as const;

export type { RunTimingReceipt } from "../../shared/constants";

const TERMINAL_PHASES = new Set<Phase>([
  PHASE.FINISHED,
  PHASE.STOPPED,
  PHASE.ERROR,
]);

function assertTimestamp(now: number, previous: number): void {
  if (!Number.isFinite(now) || now < previous) {
    throw new Error("timing timestamp must be finite and monotonic");
  }
}

function attemptFor(events: RunTimingEvent[], phase: Phase): number {
  return events.filter((event) => event.phase === phase).length + 1;
}

function closeEvent(event: RunTimingEvent, now: number): RunTimingEvent {
  assertTimestamp(now, event.started_at_ms);
  return {
    ...event,
    ended_at_ms: now,
    duration_ms: now - event.started_at_ms,
  };
}

function deriveReceipt(
  receipt: Omit<RunTimingReceipt, "active_duration_ms" | "unmeasured_gap_ms">
): RunTimingReceipt {
  const activeDuration = receipt.sessions.reduce(
    (total, session) =>
      total +
      (session.ended_at_ms === null
        ? 0
        : session.ended_at_ms - session.started_at_ms),
    0
  );
  const measuredDuration = receipt.events.reduce(
    (total, event) => total + (event.duration_ms ?? 0),
    0
  );
  return {
    ...receipt,
    active_duration_ms: activeDuration,
    unmeasured_gap_ms: Math.max(0, activeDuration - measuredDuration),
  };
}

function openEvent(phase: Phase, now: number, attempt: number): RunTimingEvent {
  if (TERMINAL_PHASES.has(phase)) {
    throw new Error("terminal phase cannot be a timing event");
  }
  return {
    phase,
    attempt,
    started_at_ms: now,
    ended_at_ms: null,
    duration_ms: null,
  };
}

export function beginRunTiming(phase: Phase, now: number): RunTimingReceipt {
  assertTimestamp(now, 0);
  return deriveReceipt({
    version: RUN_TIMING_RECEIPT_VERSION,
    started_at_ms: now,
    ended_at_ms: null,
    outcome: "running",
    failed_phase: null,
    sessions: [{ started_at_ms: now, ended_at_ms: null }],
    events: [openEvent(phase, now, 1)],
  });
}

export function transitionRunTiming(
  receipt: RunTimingReceipt,
  phase: Phase,
  now: number,
  forceNewAttempt = false
): RunTimingReceipt {
  if (receipt.outcome !== "running") {
    throw new Error("cannot transition a finalized timing receipt");
  }
  const current = receipt.events.at(-1);
  if (!current || current.ended_at_ms !== null) {
    throw new Error("running timing receipt must have an open event");
  }
  if (current.phase === phase && !forceNewAttempt) return receipt;
  return deriveReceipt({
    ...receipt,
    events: [
      ...receipt.events.slice(0, -1),
      closeEvent(current, now),
      openEvent(phase, now, attemptFor(receipt.events, phase)),
    ],
  });
}

export function finalizeRunTiming(
  receipt: RunTimingReceipt,
  outcome: Exclude<RunTimingOutcome, "running">,
  now: number
): RunTimingReceipt {
  if (receipt.outcome !== "running") {
    throw new Error("timing receipt is already finalized");
  }
  const current = receipt.events.at(-1);
  const session = receipt.sessions.at(-1);
  if (!current || current.ended_at_ms !== null || !session) {
    throw new Error("running timing receipt is incomplete");
  }
  assertTimestamp(now, session.started_at_ms);
  return deriveReceipt({
    ...receipt,
    ended_at_ms: now,
    outcome,
    failed_phase: outcome === "error" ? current.phase : null,
    sessions: [
      ...receipt.sessions.slice(0, -1),
      { ...session, ended_at_ms: now },
    ],
    events: [...receipt.events.slice(0, -1), closeEvent(current, now)],
  });
}

export function resumeRunTiming(
  receipt: RunTimingReceipt,
  phase: Phase,
  now: number
): RunTimingReceipt {
  if (receipt.outcome === "running" || receipt.ended_at_ms === null) {
    throw new Error("only a finalized timing receipt can resume");
  }
  assertTimestamp(now, receipt.ended_at_ms);
  return deriveReceipt({
    ...receipt,
    ended_at_ms: null,
    outcome: "running",
    failed_phase: null,
    sessions: [...receipt.sessions, { started_at_ms: now, ended_at_ms: null }],
    events: [
      ...receipt.events,
      openEvent(phase, now, attemptFor(receipt.events, phase)),
    ],
  });
}

function seconds(milliseconds: number): string {
  return `${(milliseconds / 1000).toFixed(2)}s`;
}

export function formatRunTiming(receipt: RunTimingReceipt): {
  lines: string[];
  json: string;
} {
  const lines = receipt.events.map(
    (event) =>
      `${event.phase} #${event.attempt}: ${seconds(event.duration_ms ?? 0)}`
  );
  lines.push(
    `total: ${seconds(receipt.active_duration_ms)}`,
    `unmeasured gap: ${seconds(receipt.unmeasured_gap_ms)}`
  );
  return { lines, json: JSON.stringify(receipt, null, 2) };
}
