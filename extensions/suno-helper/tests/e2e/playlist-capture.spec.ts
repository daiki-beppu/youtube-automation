// #893: Suno `/me` ページの playlist 一覧 scrape の E2E スモーク (実 Suno 非依存)。
//
// content script は manifest の matches (`https://suno.com/*`) でしか注入されず、Playwright の
// page.evaluate に渡す関数はシリアライズされブラウザ文脈で実行されるため本番
// `shared/playlist-scrape.ts` を直接 import できない (既存 playlist-add.spec.ts と同じ制約)。
// よってここでは scrapePlaylistsFromMe と同手法を inline 再現し、実ブラウザの DOM 上で
// 「playlist anchor を抽出 → title fallback → dedup → host 絶対化」が成立することを示す。
// 本番関数の回帰は jsdom unit (tests/playlist-scrape.test.ts) が担う。
import { expect, test } from "@playwright/test";

// `/me` ページの mock。
//   - aria-label 付き playlist anchor / textContent fallback の anchor / 空 title の anchor
//   - 同一 url の重複 anchor（dedup 検証）
//   - playlist 以外の anchor（/me, /song）混在（フィルタ検証）
const MOCK_HTML = `<!doctype html>
<html>
  <body>
    <a href="/playlist/u1" aria-label="Graphite Hour">ignored visible text</a>
    <a href="/playlist/u2">  Deep Focus  </a>
    <a href="/playlist/u1" aria-label="Duplicate Url">dup</a>
    <a href="/playlist/empty">   </a>
    <a href="/me">My page</a>
    <a href="/song/xyz">A song</a>
  </body>
</html>`;

test("`/me` の playlist anchor を抽出し title fallback / dedup / host 絶対化する (#893)", async ({ page }) => {
  await page.setContent(MOCK_HTML);

  const result = await page.evaluate(() => {
    // --- 本番 shared/playlist-scrape.ts と同手法を inline 再現 ---
    interface Captured {
      title: string;
      url: string;
    }
    const scrape = (doc: Document): Captured[] => {
      const anchors = doc.querySelectorAll<HTMLAnchorElement>('a[href^="/playlist/"]');
      const seen = new Set<string>();
      const out: Captured[] = [];
      for (const a of Array.from(anchors)) {
        const title = (a.getAttribute("aria-label") ?? a.textContent ?? "").trim();
        if (!title) continue; // 空 title は skip
        const href = a.getAttribute("href") ?? "";
        const url = new URL(href, "https://suno.com").href; // host 絶対化
        if (seen.has(url)) continue; // url で dedup
        seen.add(url);
        out.push({ title, url });
      }
      return out;
    };

    return scrape(document);
  });

  // u1(aria-label) / u2(textContent fallback) のみ。u1 重複は dedup、empty は skip、/me /song は対象外。
  expect(result).toEqual([
    { title: "Graphite Hour", url: "https://suno.com/playlist/u1" },
    { title: "Deep Focus", url: "https://suno.com/playlist/u2" },
  ]);
});
