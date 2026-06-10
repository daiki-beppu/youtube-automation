// 要件1-4 (#892): Suno UI 上の draggable overlay を実ブラウザ文脈で検証する E2E スモーク (実 Suno 非依存)。
//
// content script は manifest の matches (`https://suno.com/*`) でしか注入されず、Playwright の
// page.evaluate は本番モジュール (`components/useDraggable.ts` / `lib/overlay-state.ts`) を import
// できない（既存 suno-inject.spec.ts / suno-range.spec.ts と同じ制約）。よってここでは
// useDraggable の pointer ハンドリングと clampPosition を inline 再現し、
// 「drag handle で移動できる / input フォーカス中は drag を発火しない / viewport 外は内側へ clamp /
//  最小化で handle 以外は pointer-events:none」ことを実 DOM / 実 PointerEvent で示す。
// 本番関数自体の純ロジック回帰は unit (overlay-state.test.ts) が担う。
import { expect, test } from "@playwright/test";

// useDraggable の本番ロジックと同手法を inline 再現するブートストラップ。
// handle を pointerdown → pointermove で overlay を移動。focus 中の input/textarea を
// 起点にした pointerdown では drag を開始しない（要件3）。
const SETUP = `
  const clampPosition = (pos, viewport, size) => ({
    x: Math.min(Math.max(pos.x, 0), Math.max(0, viewport.width - size.width)),
    y: Math.min(Math.max(pos.y, 0), Math.max(0, viewport.height - size.height)),
  });

  const overlay = document.getElementById('overlay');
  const handle = document.getElementById('handle');

  let dragging = false;
  let originX = 0, originY = 0, startLeft = 0, startTop = 0;

  // 要件3: drag を発火させてはいけない起点（フォーム入力要素）か判定する。
  const isInteractive = (el) =>
    !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);

  handle.addEventListener('pointerdown', (e) => {
    if (isInteractive(e.target)) return; // input/textarea 起点では drag を開始しない
    dragging = true;
    originX = e.clientX;
    originY = e.clientY;
    startLeft = parseFloat(overlay.style.left) || 0;
    startTop = parseFloat(overlay.style.top) || 0;
  });

  window.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    overlay.style.left = (startLeft + (e.clientX - originX)) + 'px';
    overlay.style.top = (startTop + (e.clientY - originY)) + 'px';
  });

  window.addEventListener('pointerup', () => { dragging = false; });

  window.clampPosition = clampPosition;
`;

const PAGE = `<!doctype html><html><body>
  <div id="overlay" style="position:fixed; left:100px; top:100px; width:200px; height:150px;">
    <div id="handle" style="width:200px; height:24px;">
      <input id="field" type="text" />
    </div>
    <div id="panel">body</div>
  </div>
</body></html>`;

test("drag handle を pointerdown→move すると overlay が delta 分だけ移動する (要件1)", async ({ page }) => {
  await page.setContent(PAGE);
  await page.addScriptTag({ content: SETUP });

  const result = await page.evaluate(() => {
    const handle = document.getElementById("handle")!;
    const overlay = document.getElementById("overlay")!;
    // handle 自体（input 以外）を起点に pointerdown。
    handle.dispatchEvent(new PointerEvent("pointerdown", { clientX: 150, clientY: 110, bubbles: true }));
    window.dispatchEvent(new PointerEvent("pointermove", { clientX: 230, clientY: 170, bubbles: true }));
    window.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    return { left: overlay.style.left, top: overlay.style.top };
  });

  // 起点 (150,110) → (230,170)、delta=(+80,+60)。初期 (100,100) → (180,160)。
  expect(result.left).toBe("180px");
  expect(result.top).toBe("160px");
});

test("input にフォーカスがある起点では pointerdown しても drag を発火しない (要件3)", async ({ page }) => {
  await page.setContent(PAGE);
  await page.addScriptTag({ content: SETUP });

  const result = await page.evaluate(() => {
    const field = document.getElementById("field") as HTMLInputElement;
    const overlay = document.getElementById("overlay")!;
    field.focus();
    // input 要素を起点にした pointerdown → drag は始まらない。
    field.dispatchEvent(new PointerEvent("pointerdown", { clientX: 150, clientY: 110, bubbles: true }));
    window.dispatchEvent(new PointerEvent("pointermove", { clientX: 400, clientY: 400, bubbles: true }));
    window.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
    return { left: overlay.style.left, top: overlay.style.top, active: document.activeElement?.id };
  });

  // overlay は初期位置のまま動かず、フォーカスは input に残る（文字入力を奪わない）。
  expect(result.left).toBe("100px");
  expect(result.top).toBe("100px");
  expect(result.active).toBe("field");
});

test("viewport の外に出る移動は clampPosition で内側へ引き戻される (要件2)", async ({ page }) => {
  await page.setContent(PAGE);
  await page.addScriptTag({ content: SETUP });

  const result = await page.evaluate(() => {
    type Point = { x: number; y: number };
    type Size = { width: number; height: number };
    const clampPosition = (
      window as unknown as {
        clampPosition: (pos: Point, viewport: Size, size: Size) => Point;
      }
    ).clampPosition;
    const viewport = { width: 1000, height: 800 };
    const size = { width: 200, height: 150 };
    // 右下と左上に大きくはみ出した位置を clamp する。
    return {
      bottomRight: clampPosition({ x: 5000, y: 5000 }, viewport, size),
      topLeft: clampPosition({ x: -300, y: -300 }, viewport, size),
    };
  });

  expect(result.bottomRight).toEqual({ x: 800, y: 650 }); // viewport - size
  expect(result.topLeft).toEqual({ x: 0, y: 0 });
});

test("最小化すると handle のみ pointer-events:auto、panel は none で Suno 操作を邪魔しない (要件4)", async ({
  page,
}) => {
  await page.setContent(PAGE);

  const result = await page.evaluate(() => {
    const handle = document.getElementById("handle")!;
    const panel = document.getElementById("panel")!;
    // 本番 Overlay.tsx の最小化トグルと同手法: minimized 時は panel を pointer-events:none、
    // handle は auto を維持して再展開操作だけ受け付ける。
    const applyMinimized = (minimized: boolean) => {
      handle.style.pointerEvents = "auto"; // handle は常に操作可能
      panel.style.pointerEvents = minimized ? "none" : "auto";
      panel.style.display = minimized ? "none" : "block";
    };

    applyMinimized(true);
    const minimized = {
      handle: handle.style.pointerEvents,
      panel: panel.style.pointerEvents,
      display: panel.style.display,
    };
    applyMinimized(false);
    const restored = {
      handle: handle.style.pointerEvents,
      panel: panel.style.pointerEvents,
      display: panel.style.display,
    };
    return { minimized, restored };
  });

  expect(result.minimized).toEqual({ handle: "auto", panel: "none", display: "none" });
  expect(result.restored).toEqual({ handle: "auto", panel: "auto", display: "block" });
});
