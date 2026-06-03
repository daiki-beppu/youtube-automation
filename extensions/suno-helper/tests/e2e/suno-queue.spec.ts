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
