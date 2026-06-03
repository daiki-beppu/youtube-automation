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

// recaptcha/hcaptcha 検知 selector。Playwright は shared/dom.ts を import できないため再掲する
// (既存の setNativeValue 同様 inline 再現)。本番 SELECTORS.recaptcha と一致させること。
const RECAPTCHA_SELECTOR = 'iframe[src*="recaptcha"], iframe[title*="recaptcha" i], iframe[src*="hcaptcha"]';

// Suno は hCaptcha challenge UI をプリロード iframe として常駐させる (#810)。
// display:none / visibility:hidden の 2 種を含め、可視判定で弾かれることを担保する。
const MOCK_SUNO_HTML = `<!doctype html>
<html>
  <body>
    <!-- 実 Suno (日本語 UI) を模す: style placeholder はジャンル語彙、lyrics は data-testid で識別する (#807)。 -->
    <textarea id="style" placeholder="地下の罠, コントラルト, リズミカルなベース"></textarea>
    <textarea id="lyrics" data-testid="lyrics-textarea" placeholder="What do you want your lyrics to be about?"></textarea>
    <!-- Song Title 欄は <input> で placeholder substring match で識別する (#844)。 -->
    <input id="title" placeholder="Song Title (Optional)" />
    <button id="generate">Create</button>
    <iframe id="hcaptcha-none" src="https://hcaptcha-assets-prod.suno.com/captcha/v1/0" style="display:none;width:0;height:0;border:0"></iframe>
    <iframe id="hcaptcha-hidden" src="https://hcaptcha-assets-prod.suno.com/captcha/v1/4" title="hCaptchaチャレンジ" style="visibility:hidden;width:300px;height:150px;border:0"></iframe>
    <div id="captured-style">-</div>
    <div id="captured-lyrics">-</div>
    <div id="captured-title">-</div>
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
      document.getElementById('title').addEventListener('input', (e) => {
        document.getElementById('captured-title').textContent = e.target.value;
      });
      document.getElementById('generate').addEventListener('click', () => {
        document.getElementById('clicked').textContent = 'yes';
      });
    </script>
  </body>
</html>`;

// title input を欠いた mock。Suno UI 改装で Song Title 欄が消えたケースを模す (#844 fail-soft)。
const MOCK_SUNO_HTML_NO_TITLE = `<!doctype html>
<html>
  <body>
    <textarea id="style" placeholder="地下の罠, コントラルト, リズミカルなベース"></textarea>
    <textarea id="lyrics" data-testid="lyrics-textarea" placeholder="What do you want your lyrics to be about?"></textarea>
    <button id="generate">Create</button>
    <div id="captured-style">-</div>
    <div id="captured-lyrics">-</div>
    <div id="clicked">no</div>
    <script>
      for (const ta of document.querySelectorAll('textarea')) {
        ta.addEventListener('input', (e) => {
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
    // 本番 shared/dom.ts setNativeValue と同じ手法: 要素型に応じた prototype の native setter を使い、
    // React が購読する input/change を bubbling 付きで発火する。title は <input>、style/lyrics は
    // <textarea> なので、textarea 固定の setter を input に流用すると "Illegal invocation" になる。
    function setNativeValue(el: HTMLTextAreaElement | HTMLInputElement, value: string): void {
      const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }

    // 本番 resolveFields と同じ識別ロジックを再現: lyrics は data-testid 最優先、style は残り。
    const lyrics = document.querySelector('[data-testid="lyrics-textarea"]') as HTMLTextAreaElement;
    const areas = Array.from(document.querySelectorAll("textarea"));
    const style = areas.find((el) => el !== lyrics) as HTMLTextAreaElement;
    // title は <input>、placeholder substring match で識別する (#844)。
    const title = document.querySelector('input[placeholder*="Song Title" i]') as HTMLInputElement;
    setNativeValue(style, "lofi, jazzy, rainy night");
    setNativeValue(lyrics, "la la la");
    setNativeValue(title, "Midnight Cafe");
    (document.querySelector("button") as HTMLButtonElement).click();
  });

  // React 互換注入: UI 側の onChange が値を取り込めている (= input イベントが届いた)
  await expect(page.locator("#captured-style")).toHaveText("lofi, jazzy, rainy night");
  await expect(page.locator("#captured-lyrics")).toHaveText("la la la");
  await expect(page.locator("#captured-title")).toHaveText("Midnight Cafe");
  await expect(page.locator("#input-events")).toHaveText("2");
  // Generate 押下が成立
  await expect(page.locator("#clicked")).toHaveText("yes");
});

test("title 省略時は name が Song Title 欄に入る (entry.title ?? entry.name, #844)", async ({ page }) => {
  await page.setContent(MOCK_SUNO_HTML);

  await page.evaluate(() => {
    function setNativeValue(el: HTMLInputElement, value: string): void {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
    // content.ts の注入規則を inline 再現: entry.title が undefined なら name を使う (?? 意味論)。
    const entry = { name: "夜更けのカフェ", style: "ambient", lyrics: "" } as {
      name: string;
      title?: string;
      style: string;
      lyrics: string;
    };
    const title = document.querySelector('input[placeholder*="Song Title" i]') as HTMLInputElement;
    setNativeValue(title, entry.title ?? entry.name);
  });

  await expect(page.locator("#captured-title")).toHaveText("夜更けのカフェ");
});

test("Song Title 欄が無い UI でも style/lyrics 注入と Generate は成立する (#844 fail-soft)", async ({ page }) => {
  await page.setContent(MOCK_SUNO_HTML_NO_TITLE);

  // content.ts の fail-soft 分岐を inline 再現: title 解決不能なら注入を skip し処理続行する。
  const titleResolved = await page.evaluate(() => {
    function setNativeValue(el: HTMLTextAreaElement, value: string): void {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const lyrics = document.querySelector('[data-testid="lyrics-textarea"]') as HTMLTextAreaElement;
    const areas = Array.from(document.querySelectorAll("textarea"));
    const style = areas.find((el) => el !== lyrics) as HTMLTextAreaElement;
    const title = document.querySelector('input[placeholder*="Song Title" i]') as HTMLInputElement | null;
    setNativeValue(style, "lofi, jazzy, rainy night");
    setNativeValue(lyrics, "la la la");
    // title が無い → 注入 skip（本番では console.warn のみ）。throw せず Generate へ進む。
    if (title) {
      setNativeValue(title as unknown as HTMLTextAreaElement, "should-not-run");
    }
    (document.querySelector("button") as HTMLButtonElement).click();
    return title !== null;
  });

  // title 欄が解決できないこと自体を担保（fail-soft の前提条件）。
  expect(titleResolved).toBe(false);
  // title 不在でも style/lyrics 注入と Generate 押下は壊れない。
  await expect(page.locator("#captured-style")).toHaveText("lofi, jazzy, rainy night");
  await expect(page.locator("#captured-lyrics")).toHaveText("la la la");
  await expect(page.locator("#clicked")).toHaveText("yes");
});

test("常駐 hCaptcha プリロード iframe は可視判定で除外され誤検知しない (#810)", async ({ page }) => {
  await page.setContent(MOCK_SUNO_HTML);

  // 実ブラウザでは layout が走るため、strict 可視判定 (detectRecaptcha と同手法) を inline 再現する。
  // selector には 2 個マッチするが、いずれも非表示なので可視数は 0 = 中断されない。
  const counts = await page.evaluate((selector) => {
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
    const matched = Array.from(document.querySelectorAll<HTMLIFrameElement>(selector));
    return {
      matched: matched.length,
      visible: matched.filter(isVisible).length,
    };
  }, RECAPTCHA_SELECTOR);

  // order.md 期待値: recaptcha-like iframes: 2 / visible: 0 (challenge 未表示時)
  expect(counts.matched).toBe(2);
  expect(counts.visible).toBe(0);
});

test("instrumental パターン (lyrics='') で前パターンの歌詞をクリアする", async ({ page }) => {
  await page.setContent(MOCK_SUNO_HTML);

  // 実機シナリオ: 1 パターン目を投入 → そのまま 2 パターン目 (instrumental, lyrics="") を投入する。
  // content.ts の修正前は `if (entry.lyrics)` ガードで lyrics="" が skip され、Lyrics 欄に前歌詞が残る。
  await page.evaluate(() => {
    function setNativeValue(el: HTMLTextAreaElement, value: string): void {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
    const lyrics = document.querySelector('[data-testid="lyrics-textarea"]') as HTMLTextAreaElement;
    const areas = Array.from(document.querySelectorAll("textarea"));
    const style = areas.find((el) => el !== lyrics) as HTMLTextAreaElement;

    // 1 パターン目: 歌詞あり。
    setNativeValue(style, "ambient lofi");
    setNativeValue(lyrics, "verse one stays");

    // 2 パターン目 (instrumental): content.ts の修正後ロジックを inline 再現。
    //   if (lyrics) setNativeValue(lyrics, entry.lyrics); → 空文字でも上書きする。
    const entry = { style: "cinematic instrumental", lyrics: "" };
    setNativeValue(style, entry.style);
    if (lyrics) {
      setNativeValue(lyrics, entry.lyrics);
    }
  });

  // 2 パターン目投入後: Lyrics 欄は空、Style 欄は新しい値、UI 側の onChange も最新値を取り込んでいる。
  await expect(page.locator("#captured-style")).toHaveText("cinematic instrumental");
  await expect(page.locator("#captured-lyrics")).toHaveText("");
});
