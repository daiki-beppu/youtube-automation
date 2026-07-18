// @vitest-environment jsdom
//
// 生成完了検知 `waitForGeneration` と captcha 解消待ち `waitForCaptchaClear` の回帰テスト。
// waitForGeneration の振る舞い: SETTLE 待ち → button が再度 enabled に戻るまで poll →
//   - enabled 復帰で resolve (生成完了)
//   - captcha 検知で waitForCaptchaClear へ移行し、解消後に待機を続行（deadline は待機分延長）
//   - captcha が captchaWaitTimeoutMs 以内に解消されなければ throw
//   - deadline 超過で timeout throw
//   - 中断 (isAborted) で即 return
//
// 純関数化に伴い、中断フラグと各タイミングは引数 (options) で注入する。
// 旧実装のモジュール変数 `aborted` / 定数 (GENERATE_TIMEOUT_MS 等) を直接参照しない。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CAPTCHA_WAIT_TIMEOUT_MS,
  GENERATE_TIMEOUT_MS,
  POLL_INTERVAL_MS,
  SETTLE_MS,
  waitForCaptchaClear,
  waitForGeneration,
} from "../../shared/dom";
import { addCaptchaIframe } from "./_helpers";

const FAST_OPTIONS = {
  timeoutMs: 1000,
  pollIntervalMs: 10,
  settleMs: 10,
} as const;

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

    const pending = waitForGeneration(btn, {
      isAborted: () => false,
      ...FAST_OPTIONS,
    });
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.settleMs); // SETTLE 経過、まだ disabled
    btn.disabled = false; // 生成完了 = enabled 復帰
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs); // 次の poll で検知

    await expect(pending).resolves.toBeUndefined();
  });

  it("Given button が aria-disabled='true' のまま When 検知条件を見る Then 完了とみなさない", async () => {
    const btn = disabledButton();
    btn.disabled = false;
    btn.setAttribute("aria-disabled", "true"); // 見た目 enabled でも生成中

    const pending = waitForGeneration(btn, {
      isAborted: () => false,
      ...FAST_OPTIONS,
    });
    const expectation = expect(pending).rejects.toThrow(/タイムアウト/);
    await vi.advanceTimersByTimeAsync(
      FAST_OPTIONS.timeoutMs + FAST_OPTIONS.settleMs + 50
    );
    await expectation;
  });
});

describe("waitForGeneration: captcha 検知で待機し解消後に続行する", () => {
  it("Given 待機中に可視 captcha 出現 → 自動 verify で消滅 When poll する Then throw せず生成完了まで待って resolve する", async () => {
    const btn = disabledButton();
    const captcha = addCaptchaIframe({
      src: "https://www.google.com/recaptcha/api2/anchor",
    });
    const phases: boolean[] = [];

    const pending = waitForGeneration(btn, {
      isAborted: () => false,
      ...FAST_OPTIONS,
      captchaWaitTimeoutMs: 500,
      onCaptchaWait: (waiting) => phases.push(waiting),
    });
    await vi.advanceTimersByTimeAsync(
      FAST_OPTIONS.settleMs + FAST_OPTIONS.pollIntervalMs
    );
    captcha.remove(); // 自動 verify で challenge が閉じた
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs * 2);
    btn.disabled = false; // 生成完了 = enabled 復帰
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs * 2);

    await expect(pending).resolves.toBeUndefined();
    expect(phases).toEqual([true, false]); // waiting-captcha 開始 → 解消で終了
  });

  it("Given captcha の解消待ち中 When 生成 deadline 相当の時間が経過する Then 待機分は deadline を消費しない (延長される)", async () => {
    const btn = disabledButton();
    const captcha = addCaptchaIframe({
      src: "https://www.google.com/recaptcha/api2/anchor",
    });

    const pending = waitForGeneration(btn, {
      isAborted: () => false,
      ...FAST_OPTIONS, // timeoutMs: 1000
      captchaWaitTimeoutMs: 5000,
    });
    // 生成 deadline (1000ms) を大きく超える 3000ms を captcha 待ちで消費させる
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.settleMs + 3000);
    captcha.remove();
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs * 2);
    btn.disabled = false;
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs * 2);

    await expect(pending).resolves.toBeUndefined(); // 生成タイムアウトに食い込まず完了を検知できる
  });

  it("Given captcha が captchaWaitTimeoutMs を超えて残留 When poll する Then fail-loud で throw する", async () => {
    const btn = disabledButton();
    addCaptchaIframe({ src: "https://www.google.com/recaptcha/api2/anchor" }); // 消えない challenge

    const pending = waitForGeneration(btn, {
      isAborted: () => false,
      ...FAST_OPTIONS,
      captchaWaitTimeoutMs: 300,
    });
    const expectation = expect(pending).rejects.toThrow(/captcha challenge/);
    await vi.advanceTimersByTimeAsync(
      FAST_OPTIONS.settleMs + 300 + FAST_OPTIONS.pollIntervalMs * 2
    );
    await expectation;
  });
});

describe("waitForCaptchaClear", () => {
  it("Given captcha 不在 When 呼ぶ Then 即 resolve し onWaitStart も呼ばない", async () => {
    const onWaitStart = vi.fn();

    await waitForCaptchaClear({
      isAborted: () => false,
      pollIntervalMs: 10,
      timeoutMs: 1000,
      onWaitStart,
    });

    expect(onWaitStart).not.toHaveBeenCalled();
  });

  it("Given captcha が後から消える When 待つ Then onWaitStart を 1 回呼んで resolve する", async () => {
    const captcha = addCaptchaIframe({
      src: "https://www.google.com/recaptcha/api2/anchor",
    });
    const onWaitStart = vi.fn();

    const pending = waitForCaptchaClear({
      isAborted: () => false,
      pollIntervalMs: 10,
      timeoutMs: 1000,
      onWaitStart,
    });
    await vi.advanceTimersByTimeAsync(50);
    captcha.remove();
    await vi.advanceTimersByTimeAsync(20);

    await expect(pending).resolves.toBeUndefined();
    expect(onWaitStart).toHaveBeenCalledTimes(1);
  });

  it("Given captcha が timeoutMs を超えて残留 When 待つ Then throw する", async () => {
    addCaptchaIframe({ src: "https://www.google.com/recaptcha/api2/anchor" });

    const pending = waitForCaptchaClear({
      isAborted: () => false,
      pollIntervalMs: 10,
      timeoutMs: 100,
    });
    const expectation = expect(pending).rejects.toThrow(
      /手動で解決してから再開/
    );
    await vi.advanceTimersByTimeAsync(200);
    await expectation;
  });

  it("Given 待機中に isAborted が true になる When 待つ Then throw せず即 return する", async () => {
    addCaptchaIframe({ src: "https://www.google.com/recaptcha/api2/anchor" });
    let aborted = false;

    const pending = waitForCaptchaClear({
      isAborted: () => aborted,
      pollIntervalMs: 10,
      timeoutMs: 1000,
    });
    await vi.advanceTimersByTimeAsync(30);
    aborted = true;
    await vi.advanceTimersByTimeAsync(20);

    await expect(pending).resolves.toBeUndefined();
  });
});

describe("waitForGeneration: プリロード hCaptcha 誤検知の回帰ガード (#810)", () => {
  it("Given 非表示プリロード hCaptcha が常駐 (visibility:hidden) When button が enabled に戻る Then 中断せず resolve する", async () => {
    const btn = disabledButton();
    // Suno は hCaptcha challenge UI をプリロード iframe として常駐させる。可視判定で弾けないと
    // detectRecaptcha が常に true になり、生成完了待ち直後に誤って throw していた (#810)。
    addCaptchaIframe({
      src: "https://hcaptcha-assets-prod.suno.com/captcha/v1/x",
      visibility: "hidden",
      width: 300,
      height: 150,
    });

    const pending = waitForGeneration(btn, {
      isAborted: () => false,
      ...FAST_OPTIONS,
    });
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.settleMs);
    btn.disabled = false; // 生成完了 = enabled 復帰
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.pollIntervalMs);

    await expect(pending).resolves.toBeUndefined();
  });
});

describe("waitForGeneration: タイムアウト", () => {
  it("Given button が disabled のまま When deadline 超過 Then timeout throw する", async () => {
    const btn = disabledButton(); // 永遠に disabled

    const pending = waitForGeneration(btn, {
      isAborted: () => false,
      ...FAST_OPTIONS,
    });
    const expectation = expect(pending).rejects.toThrow(/タイムアウト/);
    await vi.advanceTimersByTimeAsync(
      FAST_OPTIONS.timeoutMs + FAST_OPTIONS.settleMs + 50
    );
    await expectation;
  });
});

describe("waitForGeneration: 中断", () => {
  it("Given isAborted が true When 待機する Then throw せず即 return する", async () => {
    const btn = disabledButton(); // disabled のままでも中断優先で return

    const pending = waitForGeneration(btn, {
      isAborted: () => true,
      ...FAST_OPTIONS,
    });
    await vi.advanceTimersByTimeAsync(FAST_OPTIONS.settleMs);

    await expect(pending).resolves.toBeUndefined();
  });
});

describe("shared/dom: タイミング定数", () => {
  it("Given 公開定数 When 値を読む Then 規定値と一致する", () => {
    expect(GENERATE_TIMEOUT_MS).toBe(180000);
    // POLL_INTERVAL_MS は 1000→500 に短縮（停止反応性 + Generate 再 enable 検知向上）。
    expect(POLL_INTERVAL_MS).toBe(500);
    expect(SETTLE_MS).toBe(1500);
    expect(CAPTCHA_WAIT_TIMEOUT_MS).toBe(600000);
  });
});
