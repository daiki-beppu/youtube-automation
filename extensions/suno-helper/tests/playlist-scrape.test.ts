// @vitest-environment jsdom
//
// Suno `/me` ページの DOM から `[{title, url}]` を抽出する純関数 `shared/playlist-scrape.ts`
// の回帰テスト (#893 要件7)。content.ts の capturePlaylists ハンドラから DOM 抽出ロジックを
// 切り出し、jsdom unit で担保する（dom.test.ts / dom-playlist.test.ts と同方針）。
//
// 契約 (shared/playlist-scrape.ts の public API):
//   - scrapePlaylistsFromMe(doc: Document): CapturedPlaylist[]
//       * `a[href^="/playlist/"]` を走査して playlist リンクを拾う
//       * title は aria-label を優先し、無ければ textContent.trim() に fallback
//       * title が空（aria-label 無し + textContent 空白のみ）の anchor は skip
//       * url は重複排除（同一 playlist を 1 件に dedup）
//       * playlist 以外の anchor（/me, /song/... 等）は対象外
//
// url の host 絶対化（content script 上で suno.com に解決される点）は実ブラウザ依存のため、
// ここでは path 末尾と URL らしさのみを検証し、host 絶対化は e2e (tests/e2e/playlist-capture.spec.ts)
// で担保する。
import { afterEach, describe, expect, it } from "vitest";

import type { CapturedPlaylist } from "../../shared/api";
import { scrapePlaylistsFromMe } from "../../shared/playlist-scrape";

/** `<a href="/playlist/...">` を作って body に追加する。aria-label / textContent は任意。 */
function addPlaylistAnchor(href: string, opts: { ariaLabel?: string; text?: string } = {}): void {
  const a = document.createElement("a");
  a.setAttribute("href", href); // 相対属性のまま追加（`[href^="/playlist/"]` セレクタが属性値前方一致でマッチする）
  if (opts.ariaLabel !== undefined) {
    a.setAttribute("aria-label", opts.ariaLabel);
  }
  if (opts.text !== undefined) {
    a.textContent = opts.text;
  }
  document.body.appendChild(a);
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("scrapePlaylistsFromMe: playlist リンク抽出", () => {
  it("Given aria-label 付き playlist anchor When scrape する Then aria-label を title に、url を path 込みで返す", () => {
    addPlaylistAnchor("/playlist/u1", { ariaLabel: "Graphite Hour", text: "ignored visible label" });

    const result = scrapePlaylistsFromMe(document);

    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Graphite Hour");
    expect(result[0].url).toMatch(/^https?:\/\//);
    expect(result[0].url.endsWith("/playlist/u1")).toBe(true);
  });

  it("Given aria-label 無し anchor When scrape する Then textContent を trim して title にする", () => {
    addPlaylistAnchor("/playlist/u2", { text: "  Deep Focus  " });

    const result = scrapePlaylistsFromMe(document);

    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Deep Focus");
  });

  it("Given aria-label と textContent の両方がある anchor When scrape する Then aria-label を優先する", () => {
    addPlaylistAnchor("/playlist/u3", { ariaLabel: "Aria Wins", text: "text loses" });

    const result = scrapePlaylistsFromMe(document);

    expect(result[0].title).toBe("Aria Wins");
  });
});

describe("scrapePlaylistsFromMe: skip / dedup", () => {
  it("Given title が空（aria-label 無し + 空白のみ textContent）の anchor When scrape する Then skip する", () => {
    addPlaylistAnchor("/playlist/empty", { text: "   " });
    addPlaylistAnchor("/playlist/ok", { ariaLabel: "Keep Me" });

    const result = scrapePlaylistsFromMe(document);

    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Keep Me");
  });

  it("Given 同一 url の anchor が 2 件 When scrape する Then url で dedup して 1 件にする", () => {
    addPlaylistAnchor("/playlist/dup", { ariaLabel: "First" });
    addPlaylistAnchor("/playlist/dup", { ariaLabel: "Second (duplicate url)" });

    const result = scrapePlaylistsFromMe(document);

    const dupCount = result.filter((p) => p.url.endsWith("/playlist/dup")).length;
    expect(dupCount).toBe(1);
  });

  it("Given playlist 以外の anchor（/me, /song/...）混在 When scrape する Then playlist リンクのみ返す", () => {
    const me = document.createElement("a");
    me.setAttribute("href", "/me");
    me.textContent = "My page";
    document.body.appendChild(me);
    const song = document.createElement("a");
    song.setAttribute("href", "/song/xyz");
    song.textContent = "A song";
    document.body.appendChild(song);
    addPlaylistAnchor("/playlist/only", { ariaLabel: "Only Playlist" });

    const result = scrapePlaylistsFromMe(document);

    expect(result).toHaveLength(1);
    expect(result[0].title).toBe("Only Playlist");
  });
});

describe("scrapePlaylistsFromMe: 空ページ", () => {
  it("Given playlist anchor が 1 件も無い document When scrape する Then 空配列を返す", () => {
    const result: CapturedPlaylist[] = scrapePlaylistsFromMe(document);

    expect(result).toEqual([]);
  });
});
