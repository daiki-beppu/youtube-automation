import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelScheduledRunCompleteReload,
  scheduleRunCompleteReload,
} from "../lib/page-reload";

// REQ-2916-01: reload scheduling is delayed, replaceable, and cancellable.
describe("run complete reload scheduler", () => {
  const reload = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("location", { reload });
    cancelScheduledRunCompleteReload();
  });

  afterEach(() => {
    cancelScheduledRunCompleteReload();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("1 秒未満では発火せず、1 秒後に一回だけ reload する", () => {
    scheduleRunCompleteReload();

    vi.advanceTimersByTime(999);
    expect(reload).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(reload).toHaveBeenCalledOnce();
    vi.runAllTimers();
    expect(reload).toHaveBeenCalledOnce();
  });

  it("二重予約では旧 timer を取り消して最後の予約だけを発火する", () => {
    scheduleRunCompleteReload();
    vi.advanceTimersByTime(500);
    scheduleRunCompleteReload();

    vi.advanceTimersByTime(500);
    expect(reload).not.toHaveBeenCalled();
    vi.advanceTimersByTime(500);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("cancel 後は予約時刻を過ぎても発火しない", () => {
    scheduleRunCompleteReload();
    cancelScheduledRunCompleteReload();

    vi.runAllTimers();

    expect(reload).not.toHaveBeenCalled();
  });
});
