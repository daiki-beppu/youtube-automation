// 要件 (#816): Suno 生成キュー監視と collection 選択 UI の E2E スモーク (実 Suno 非依存)。
//
// content script は manifest の matches (`https://suno.com/*`) でしか注入されず、Playwright の
// page.evaluate に渡す関数はシリアライズされブラウザ文脈で実行されるため本番 `shared/dom.ts` を
// 直接 import できない (既存 suno-inject.spec.ts と同じ制約)。よってここでは
// isClipGenerating / getInFlightClipCount / waitForQueueSlot と同手法を inline 再現し、
// 「11 件目は queue 待ちで停止 → 1 完了で投入される」が実ブラウザの layout 上で成立することを示す。
// 本番関数自体の回帰は jsdom 上で `shared/dom.ts` を import する unit (`tests/queue.test.ts`) が担う。
import { expect, test } from "@playwright/test";

// clip-row を 20 行 (= 10 リクエスト in-flight = 上限) 並べた Suno 生成キューの mock。
// 各 row は生成中を表す svg.animate-spin を持つ。
const MOCK_QUEUE_HTML = `<!doctype html>
<html>
  <body>
    <div id="grid">
      ${Array.from({ length: 20 })
        .map(
          (_, i) =>
            `<div data-testid="clip-row" id="clip-${i}" style="width:200px;height:60px">` +
            `<svg class="animate-spin" width="16" height="16"></svg></div>`,
        )
        .join("\n")}
    </div>
  </body>
</html>`;

test("11 件目は in-flight 上限 (20 clip) で待機し、1 clip 完了で投入が再開する", async ({ page }) => {
  await page.setContent(MOCK_QUEUE_HTML);

  const result = await page.evaluate(async () => {
    // 本番 shared/dom.ts と同じ strict 可視判定 / 生成中判定 / queue 待機を inline 再現する。
    const isVisible = (el: HTMLElement): boolean => {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false;
      let node: HTMLElement | null = el;
      while (node) {
        const style = getComputedStyle(node);
        if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
          return false;
        }
        node = node.parentElement;
      }
      return true;
    };
    const isClipGenerating = (row: HTMLElement): boolean =>
      isVisible(row) && row.querySelector("svg.animate-spin") !== null;
    const getInFlightClipCount = (): number =>
      Array.from(document.querySelectorAll<HTMLElement>('[data-testid="clip-row"]')).filter(isClipGenerating).length;
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const waitForQueueSlot = async (maxClips: number): Promise<void> => {
      const deadline = Date.now() + 5000;
      while (Date.now() < deadline) {
        if (getInFlightClipCount() < maxClips) return;
        await sleep(20);
      }
      throw new Error("queue slot 待ちがタイムアウトしました。");
    };

    const before = getInFlightClipCount();

    let resolved = false;
    const pending = waitForQueueSlot(20).then(() => {
      resolved = true;
    });

    // 上限のままでは投入を待つ (resolve しない)。
    await sleep(80);
    const blockedWhileFull = !resolved;

    // 1 clip 完了 (spinner 除去) → in-flight 19 < 20 → 投入再開。
    document.querySelector('[data-testid="clip-row"] svg.animate-spin')?.remove();
    await pending;

    return { before, blockedWhileFull, resolvedAfterFree: resolved, after: getInFlightClipCount() };
  });

  expect(result.before).toBe(20); // 10 リクエスト = 20 clip が in-flight (上限)
  expect(result.blockedWhileFull).toBe(true); // 上限の間は 11 件目を待たせる
  expect(result.resolvedAfterFree).toBe(true); // 1 完了で待機解除
  expect(result.after).toBe(19);
});

// collection 選択ドロップダウン UI のスモーク。popup の React 実装は unpacked 拡張ロードを要するため、
// ここでは「fetchCollections の結果から <select> を populate し、has_prompts=false を disabled、
// 初期値を最初の has_prompts=true にする」契約を mock DOM へ inline 再現して検証する。
const MOCK_POPUP_HTML = `<!doctype html>
<html><body><select id="collection"></select></body></html>`;

test("collection ドロップダウンは populate され、has_prompts=false は disabled・初期値は最初の有効 entry", async ({
  page,
}) => {
  await page.setContent(MOCK_POPUP_HTML);

  const result = await page.evaluate(() => {
    type CollectionSummary = {
      id: string;
      name: string;
      has_prompts: boolean;
      pattern_count: number | null;
    };
    const collections: CollectionSummary[] = [
      { id: "c1", name: "midnight-mood", has_prompts: false, pattern_count: null },
      { id: "c2", name: "sunset-drive", has_prompts: true, pattern_count: 12 },
      { id: "c3", name: "dawn-chorus", has_prompts: true, pattern_count: 8 },
    ];
    // pickInitialCollectionId と同ルール: 最初の has_prompts=true。
    const initialId = collections.find((c) => c.has_prompts)?.id ?? "";

    const select = document.getElementById("collection") as HTMLSelectElement;
    for (const c of collections) {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name;
      opt.disabled = !c.has_prompts; // has_prompts=false は選べない
      select.appendChild(opt);
    }
    select.value = initialId;

    return {
      optionCount: select.options.length,
      firstDisabled: select.options[0].disabled,
      secondDisabled: select.options[1].disabled,
      selectedValue: select.value,
    };
  });

  expect(result.optionCount).toBe(3);
  expect(result.firstDisabled).toBe(true); // c1 (has_prompts=false)
  expect(result.secondDisabled).toBe(false); // c2 (has_prompts=true)
  expect(result.selectedValue).toBe("c2"); // 初期値 = 最初の有効 entry
});

// #847: queue 上限エラー toast ([role="dialog"] + "Generation in progress") 検知中は、
// 空きスロットがあっても投入を止め、toast 消失後に再開する挙動を実ブラウザ layout 上で再現検証する。
// 本番 isQueueLimitErrorVisible / waitForQueueSlot の回帰は jsdom unit (tests/queue.test.ts) が担う。
const MOCK_TOAST_HTML = `<!doctype html>
<html>
  <body>
    <div id="grid">
      <div data-testid="clip-row" id="clip-0" style="width:200px;height:60px"><span>2:02</span></div>
    </div>
    <div id="toast" role="dialog" style="width:360px;height:120px">
      <h3>Generation in progress</h3>
      <span>他の曲の生成が完了するまでお待ちいただき、その後もう一度お試しください。</span>
    </div>
  </body>
</html>`;

test("queue 上限 toast 検知中は空きスロットでも待機し、toast 消失で投入を再開する (#847)", async ({ page }) => {
  await page.setContent(MOCK_TOAST_HTML);

  const result = await page.evaluate(async () => {
    // 本番 shared/dom.ts と同じ strict 可視判定 / toast 検知 / queue 待機を inline 再現する。
    const isVisible = (el: HTMLElement): boolean => {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return false;
      let node: HTMLElement | null = el;
      while (node) {
        const style = getComputedStyle(node);
        if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
          return false;
        }
        node = node.parentElement;
      }
      return true;
    };
    const isClipGenerating = (row: HTMLElement): boolean =>
      isVisible(row) && row.querySelector("svg.animate-spin") !== null;
    const getInFlightClipCount = (): number =>
      Array.from(document.querySelectorAll<HTMLElement>('[data-testid="clip-row"]')).filter(isClipGenerating).length;
    const isQueueLimitErrorVisible = (): boolean =>
      Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]')).some(
        (el) => isVisible(el) && (el.textContent ?? "").toLowerCase().includes("generation in progress"),
      );
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const QUEUE_ERROR_WAIT_MS = 120; // テスト短縮した安全マージン
    const waitForQueueSlot = async (maxClips: number): Promise<void> => {
      const deadline = Date.now() + 5000;
      let sawToast = false;
      while (Date.now() < deadline) {
        if (isQueueLimitErrorVisible()) {
          sawToast = true;
          await sleep(20);
          continue;
        }
        if (sawToast) {
          await sleep(QUEUE_ERROR_WAIT_MS);
          sawToast = false;
          continue;
        }
        if (getInFlightClipCount() < maxClips) return;
        await sleep(20);
      }
      throw new Error("queue slot 待ちがタイムアウトしました。");
    };

    // 前提: スロットは空いている (in-flight 0 < 20) のに toast が出ている状況。
    const slotFreeButToastUp = getInFlightClipCount() < 20 && isQueueLimitErrorVisible();

    let resolved = false;
    const pending = waitForQueueSlot(20).then(() => {
      resolved = true;
    });

    await sleep(80);
    const blockedWhileToast = !resolved; // toast 中は空きでも投入を待つ

    document.getElementById("toast")?.remove(); // toast 消失
    await pending;

    return { slotFreeButToastUp, blockedWhileToast, resolvedAfterToastGone: resolved };
  });

  expect(result.slotFreeButToastUp).toBe(true); // スロットは空きなのに toast が出ている
  expect(result.blockedWhileToast).toBe(true); // toast 中は待機（誤投入しない）
  expect(result.resolvedAfterToastGone).toBe(true); // 消失で再開
});

// #847 受け入れ条件「停止押下後 3 秒以内にフロー停止」。固定 sleep を abortableSleep に置換することで
// 長い待機 (SETTLE_MS=1500 等) の途中でも中断できることを実ブラウザの real timer 上で再現検証する。
test("abortableSleep は中断フラグで長い待機の途中でも 3 秒以内に抜ける (#847)", async ({ page }) => {
  await page.setContent("<!doctype html><html><body></body></html>");

  const result = await page.evaluate(async () => {
    // 本番 abortableSleep と同じ「ms 経過 or 中断 の早い方で resolve、内部 poll で中断検知」を inline 再現。
    const abortableSleep = (ms: number, isAborted: () => boolean): Promise<void> =>
      new Promise((resolve) => {
        const poll = 50;
        const deadline = Date.now() + ms;
        const tick = () => {
          if (isAborted() || Date.now() >= deadline) {
            resolve();
            return;
          }
          setTimeout(tick, Math.min(poll, deadline - Date.now()));
        };
        tick();
      });

    let aborted = false;
    const start = Date.now();
    const pending = abortableSleep(10000, () => aborted).then(() => Date.now() - start);
    setTimeout(() => {
      aborted = true; // 100ms 後に停止押下相当
    }, 100);
    const elapsed = await pending;
    return { elapsed };
  });

  expect(result.elapsed).toBeGreaterThanOrEqual(100); // 中断フラグが立つまでは待つ
  expect(result.elapsed).toBeLessThan(3000); // 受け入れ条件: 停止後 3 秒以内に抜ける
});
