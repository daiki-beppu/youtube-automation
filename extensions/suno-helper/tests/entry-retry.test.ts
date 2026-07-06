// entry 単位の自動リトライ + スキップ継続 (#948) の回帰テスト。
//
// 従来は 1 entry の失敗で run 全体が ERROR 停止し、55 entries の完走がほぼ不可能だった
// （失敗率 2% でも完走率 ≈ 0.98^55 ≈ 33%）。runEntryWithRetry は失敗を分類し、
//   - 一時的な失敗 → maxRetry まで同一 entry を再試行
//   - 上限超過 → "failed"（caller がスキップして継続）
//   - 投入済み → "presumed-done"（再実行すると重複生成のため生成済み扱い）
//   - FatalRunError → "fatal"（caller が run 全体を ERROR 停止）
//   - 中断 → "aborted"
import { describe, expect, it, vi } from "vitest";

import { runEntryWithRetry, type RunEntryWithRetryOptions } from "../lib/entry-retry";

function makeOptions(overrides: Partial<RunEntryWithRetryOptions> = {}): RunEntryWithRetryOptions {
  return {
    attempt: vi.fn().mockResolvedValue(undefined),
    isAborted: () => false,
    wasSubmitted: () => false,
    isFatal: () => false,
    maxRetry: 2,
    retryDelayMs: () => 0,
    sleep: vi.fn().mockResolvedValue(undefined),
    describeEntry: () => "entry 0 (pattern-1)",
    ...overrides,
  };
}

describe("runEntryWithRetry: 失敗分類と再試行", () => {
  it("Given 1 回目で成功 When 実行 Then outcome=ok・attempt 1 回", async () => {
    const attempt = vi.fn().mockResolvedValue(undefined);
    const result = await runEntryWithRetry(makeOptions({ attempt }));
    expect(result).toEqual({ outcome: "ok" });
    expect(attempt).toHaveBeenCalledTimes(1);
  });

  it("Given 1 回目失敗 → 2 回目成功 When 実行 Then outcome=ok・retry 間に sleep を挟む", async () => {
    const attempt = vi.fn().mockRejectedValueOnce(new Error("一時的失敗")).mockResolvedValueOnce(undefined);
    const sleep = vi.fn().mockResolvedValue(undefined);
    const onRetry = vi.fn();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    const result = await runEntryWithRetry(makeOptions({ attempt, sleep, retryDelayMs: () => 1234, onRetry }));

    expect(result).toEqual({ outcome: "ok" });
    expect(attempt).toHaveBeenCalledTimes(2);
    expect(sleep).toHaveBeenCalledWith(1234, expect.any(Function));
    expect(onRetry).toHaveBeenCalledWith(1, 2, expect.any(Error));
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  it("Given maxRetry=2 で全 attempt 失敗 When 実行 Then outcome=failed・attempt 3 回・error を保持", async () => {
    const error = new Error("毎回失敗");
    const attempt = vi.fn().mockRejectedValue(error);
    const onRetry = vi.fn();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    const result = await runEntryWithRetry(makeOptions({ attempt, maxRetry: 2, onRetry }));

    expect(result).toEqual({ outcome: "failed", error });
    expect(attempt).toHaveBeenCalledTimes(3); // 初回 + retry 2
    expect(onRetry).toHaveBeenNthCalledWith(1, 1, 2, error);
    expect(onRetry).toHaveBeenNthCalledWith(2, 2, 2, error);
    expect(onRetry).toHaveBeenCalledTimes(2); // 終端 attempt は予告しない
    expect(warn).toHaveBeenCalledTimes(2); // 終端 attempt は予告しない
    warn.mockRestore();
  });

  it("Given fatal エラー When 実行 Then 即 outcome=fatal（retry しない）", async () => {
    const error = new Error("DOM 不在");
    const attempt = vi.fn().mockRejectedValue(error);
    const result = await runEntryWithRetry(makeOptions({ attempt, isFatal: (e) => e === error }));
    expect(result).toEqual({ outcome: "fatal", error });
    expect(attempt).toHaveBeenCalledTimes(1);
  });

  it("Given 投入済みエラー（wasSubmitted=true） When 実行 Then outcome=presumed-done（retry せず重複生成を防ぐ）", async () => {
    const error = new Error("生成完了の検知がタイムアウトしました。");
    const attempt = vi.fn().mockRejectedValue(error);
    const result = await runEntryWithRetry(makeOptions({ attempt, wasSubmitted: (e) => e === error }));
    expect(result).toEqual({ outcome: "presumed-done", error });
    expect(attempt).toHaveBeenCalledTimes(1);
  });

  it("Given attempt 失敗時に aborted When 実行 Then outcome=aborted（retry に入らない）", async () => {
    let aborted = false;
    const attempt = vi.fn().mockImplementation(async () => {
      aborted = true;
      throw new Error("中断と同時の失敗");
    });
    const result = await runEntryWithRetry(makeOptions({ attempt, isAborted: () => aborted }));
    expect(result).toEqual({ outcome: "aborted" });
    expect(attempt).toHaveBeenCalledTimes(1);
  });

  it("Given retry 待機中に aborted When 実行 Then outcome=aborted（次 attempt に入らない）", async () => {
    let aborted = false;
    const attempt = vi.fn().mockRejectedValue(new Error("一時的失敗"));
    const sleep = vi.fn().mockImplementation(async () => {
      aborted = true; // 待機中に停止押下
    });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    const result = await runEntryWithRetry(makeOptions({ attempt, sleep, isAborted: () => aborted }));

    expect(result).toEqual({ outcome: "aborted" });
    expect(attempt).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  it("Given fatal かつ aborted When 実行 Then fatal を優先する（必ず再発する失敗を握りつぶさない）", async () => {
    const error = new Error("fatal");
    const attempt = vi.fn().mockRejectedValue(error);
    const result = await runEntryWithRetry(
      makeOptions({ attempt, isAborted: () => true, isFatal: (e) => e === error }),
    );
    expect(result).toEqual({ outcome: "fatal", error });
  });
});
