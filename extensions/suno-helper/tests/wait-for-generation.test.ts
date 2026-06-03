// @vitest-environment jsdom
//
// 生成完了検知 `waitForGeneration` の回帰テスト (旧 content.js:71-86)。
// 振る舞い: SETTLE 待ち → button が再度 enabled に戻るまで poll →
//   - enabled 復帰で resolve (生成完了)
//   - reCAPTCHA 検知で throw
//   - deadline 超過で timeout throw
//   - 中断 (isAborted) で即 return
//
// 純関数化に伴い、中断フラグと各タイミングは引数 (options) で注入する。
// 旧実装のモジュール変数 `aborted` / 定数 (GENERATE_TIMEOUT_MS 等) を直接参照しない。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GENERATE_TIMEOUT_MS, POLL_INTERVAL_MS, SETTLE_MS, waitForGeneration } from "../../shared/dom";

const FAST_OPTIONS = { timeoutMs: 1000, pollIntervalMs: 10, settleMs: 10 } as const;

function disabledButton(): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.disabled = true;
  document.body.appendChild(btn);
  return btn;
}

beforeEach(() => {
  document.body.innerHTML = "";
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("waitForGeneration: 完了検知", () => {
  it("Given button が enabled に戻る When 待機する Then resolve する", async () => {
    const btn = disabledButton();

    const pending = waitForGeneration(btn, { isAborted: () => false, ...FAST_OPTIONS });
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.settleMs); // SETTLE 経過、まだ disabled
    btn.disabled = false; // 生成完了 = enabled 復帰
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs); // 次の poll で検知

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given button が aria-disabled='true' のまま When 検知条件を見る Then 完了とみなさない", async () => {
    const btn = disabledButton();
    btn.disabled = false;
    btn.setAttribute("aria-disabled", "true"); // 見た目 enabled でも生成中

    const pending = waitForGeneration(btn, { isAborted: () => false, ...FAST_OPTIONS });
    const expectation = expect(pending).rejects.toThrow(/タイムアウト/);
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.timeoutMs + FAST_OPTIONS.settleMs + 50);
    await expectation;
  });
});

describe("waitForGeneration: reCAPTCHA 検知", () => {
  it("Given 待機中に reCAPTCHA 出現 When poll する Then throw する", async () => {
    const btn = disabledButton();
    document.body.innerHTML += '<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>';

    const pending = waitForGeneration(btn, { isAborted: () => false, ...FAST_OPTIONS });
    const expectation = expect(pending).rejects.toThrow(/reCAPTCHA/);
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.settleMs + FAST_OPTIONS.pollIntervalMs);
    await expectation;
  });
});

describe("waitForGeneration: タイムアウト", () => {
  it("Given button が disabled のまま When deadline 超過 Then timeout throw する", async () => {
    const btn = disabledButton(); // 永遠に disabled

    const pending = waitForGeneration(btn, { isAborted: () => false, ...FAST_OPTIONS });
    const expectation = expect(pending).rejects.toThrow(/タイムアウト/);
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.timeoutMs + FAST_OPTIONS.settleMs + 50);
    await expectation;
  });
});

describe("waitForGeneration: 中断", () => {
  it("Given isAborted が true When 待機する Then throw せず即 return する", async () => {
    const btn = disabledButton(); // disabled のままでも中断優先で return

    const pending = waitForGeneration(btn, { isAborted: () => true, ...FAST_OPTIONS });
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.settleMs);

    await expect(pending).resolves.toBeUndefined();
  });
});

describe("shared/dom: タイミング定数 (旧 content.js:18-20 を保持)", () => {
  it("Given 公開定数 When 値を読む Then 旧実装の既定値と一致する", () => {
    expect(GENERATE_TIMEOUT_MS).toBe(180000);
    expect(POLL_INTERVAL_MS).toBe(1000);
    expect(SETTLE_MS).toBe(1500);
  });
});
