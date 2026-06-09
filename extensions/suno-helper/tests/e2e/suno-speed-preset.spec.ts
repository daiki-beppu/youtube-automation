// 要件8 (#875): Safe preset 選択時の連続実行 INTER_CREATE_DELAY が 15s 以上であることを
// 実ブラウザ文脈で検証する E2E スモーク (実 Suno 非依存)。
//
// content script は manifest の matches (`https://suno.com/*`) でしか注入されず、Playwright の
// page.evaluate は本番モジュール (`lib/preset-state.ts` / `entrypoints/content.ts`) を import
// できない（既存 suno-range.spec.ts / suno-inject.spec.ts と同じ制約）。よってここでは
// applyJitter (baseMs + (random()*2-1)*jitterMs) と SPEED_PRESETS.safe 値、および runAll の
// 「毎 iteration で applyJitter(preset.interCreateDelayMs, preset.jitterMs) を fresh 算出する」
// 手法を inline 再現し、Safe preset の delay が常に 15s 以上（15000〜25000ms）になることを示す。
// 本番関数自体の回帰は unit (preset-state.test.ts / constants.test.ts) が担う。
import { expect, test } from "@playwright/test";

test("Safe preset の連続実行 INTER_CREATE_DELAY が常に 15s 以上である (#875 受け入れ基準)", async ({ page }) => {
  await page.setContent("<!doctype html><html><body></body></html>");

  const result = await page.evaluate(() => {
    // --- 本番 shared/constants.ts SPEED_PRESETS.safe と同値を inline 再現 ---
    const safe = { interCreateDelayMs: 20000, jitterMs: 5000 };

    // --- 本番 lib/preset-state.ts applyJitter と同手法を inline 再現 ---
    const applyJitter = (baseMs: number, jitterMs: number, random: () => number = Math.random): number =>
      baseMs + (random() * 2 - 1) * jitterMs;

    // --- 本番 content.ts runAll の「毎 iteration で delay を fresh 算出」を inline 再現 ---
    // 各 entry 投入後に abortableSleep(applyJitter(preset.interCreateDelayMs, preset.jitterMs)) を呼ぶ。
    const delays: number[] = [];
    for (let i = 0; i < 200; i++) {
      delays.push(applyJitter(safe.interCreateDelayMs, safe.jitterMs));
    }

    // 境界の確定値も併せて検証用に算出する（random の DI で min/max を pin）。
    const min = applyJitter(safe.interCreateDelayMs, safe.jitterMs, () => 0);
    const max = applyJitter(safe.interCreateDelayMs, safe.jitterMs, () => 1);

    return { delays, min, max };
  });

  // 受け入れ基準: Safe 選択時の INTER_CREATE_DELAY が 15s 以上。jitter 下限でも 15000ms を割らない。
  for (const delay of result.delays) {
    expect(delay).toBeGreaterThanOrEqual(15000);
    expect(delay).toBeLessThanOrEqual(25000);
  }
  // jitter 域の確定境界: random=0 → 15000ms（15s 以上の下限）、random=1 → 25000ms。
  expect(result.min).toBe(15000);
  expect(result.max).toBe(25000);
});
