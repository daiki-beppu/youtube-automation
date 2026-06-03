// 要件9: Suno UI mock に対する DOM 注入 E2E スモーク (実 Suno 非依存)。
//
// 実 Suno に依存せず、Suno Custom Mode を模した最小 HTML を Chromium に読み込み、
// content script の中核である「React 互換ネイティブ値注入 → Generate 押下」が
// 実ブラウザ上で成立することを 1 ケースで検証する。
//
// content script は manifest の matches (`https://suno.com/*`) でしか注入されないため、
// ここでは注入ロジックの契約 (native setter + input/change 発火 + click) を mock DOM に
// 対して page.evaluate で実行し、値反映とフォーム捕捉を確認する。
//
// 役割の限定: これは「注入手法が実ブラウザで技術的に成立すること」を確認する煙テスト。
// page.evaluate に渡す関数はシリアライズされブラウザ文脈で実行されるため import 解決が
// 効かず、本番 `shared/dom.ts::setNativeValue` を直接呼べない（Playwright の制約）。
// よってここでは同手法を最小再現する。本番関数自体のリグレッション検証は jsdom 上で
// `shared/dom.ts` を直接 import する unit テスト (`tests/dom.test.ts`) が担う。
import { expect, test } from "@playwright/test";

const MOCK_SUNO_HTML = `<!doctype html>
<html>
  <body>
    <!-- 実 Suno (日本語 UI) を模す: style placeholder はジャンル語彙、lyrics は data-testid で識別する (#807)。 -->
    <textarea id="style" placeholder="地下の罠, コントラルト, リズミカルなベース"></textarea>
    <textarea id="lyrics" data-testid="lyrics-textarea" placeholder="What do you want your lyrics to be about?"></textarea>
    <button id="generate">Create</button>
    <div id="captured-style">-</div>
    <div id="captured-lyrics">-</div>
    <div id="input-events">0</div>
    <div id="clicked">no</div>
    <script>
      // React のように「onChange (input イベント) を購読して内部 state を更新する」UI を模す。
      let inputCount = 0;
      for (const ta of document.querySelectorAll('textarea')) {
        ta.addEventListener('input', (e) => {
          inputCount += 1;
          document.getElementById('input-events').textContent = String(inputCount);
          const sink = e.target.id === 'style' ? 'captured-style' : 'captured-lyrics';
          document.getElementById(sink).textContent = e.target.value;
        });
      }
      document.getElementById('generate').addEventListener('click', () => {
        document.getElementById('clicked').textContent = 'yes';
      });
    </script>
  </body>
</html>`;

test("Suno mock へ Style/Lyrics を注入し Generate を押下できる", async ({ page }) => {
  await page.setContent(MOCK_SUNO_HTML);

  await page.evaluate(() => {
    // 旧 content.js setNativeValue と同じ手法: prototype の native setter を使い、
    // React が購読する input/change を bubbling 付きで発火する。
    function setNativeValue(el: HTMLTextAreaElement, value: string): void {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }

    // 本番 resolveFields と同じ識別ロジックを再現: lyrics は data-testid 最優先、style は残り。
    const lyrics = document.querySelector('[data-testid="lyrics-textarea"]') as HTMLTextAreaElement;
    const areas = Array.from(document.querySelectorAll("textarea"));
    const style = areas.find((el) => el !== lyrics) as HTMLTextAreaElement;
    setNativeValue(style, "lofi, jazzy, rainy night");
    setNativeValue(lyrics, "la la la");
    (document.querySelector("button") as HTMLButtonElement).click();
  });

  // React 互換注入: UI 側の onChange が値を取り込めている (= input イベントが届いた)
  await expect(page.locator("#captured-style")).toHaveText("lofi, jazzy, rainy night");
  await expect(page.locator("#captured-lyrics")).toHaveText("la la la");
  await expect(page.locator("#input-events")).toHaveText("2");
  // Generate 押下が成立
  await expect(page.locator("#clicked")).toHaveText("yes");
});
