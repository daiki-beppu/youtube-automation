// Suno `/me` ページの DOM から playlist 一覧 `[{title, url}]` を抽出する純関数 (#893 要件7)。
// content.ts の capturePlaylists ハンドラから DOM 抽出を切り出し、jsdom unit で回帰担保する。
import type { CapturedPlaylist } from "./api";

/** playlist リンクを示す anchor の href 前方一致セレクタ（Suno `/me` の一覧 DOM 契約）。 */
const PLAYLIST_ANCHOR_SELECTOR = 'a[href^="/playlist/"]';

/**
 * `/me` ページの `a[href^="/playlist/"]` を走査して playlist を抽出する。
 *   - title は aria-label を優先し、無ければ textContent.trim() に fallback
 *   - title が空（aria-label 無し + 空白のみ textContent）の anchor は skip
 *   - url は base に suno.com を固定して host 絶対化し、重複 url を dedup
 *     （content script は常に suno.com 上で動くため base を固定して決定的にする）
 *   - playlist 以外の anchor（/me, /song/... 等）はセレクタにより対象外
 */
export function scrapePlaylistsFromMe(doc: Document): CapturedPlaylist[] {
  const anchors = doc.querySelectorAll<HTMLAnchorElement>(
    PLAYLIST_ANCHOR_SELECTOR,
  );
  const seen = new Set<string>();
  const out: CapturedPlaylist[] = [];
  for (const a of Array.from(anchors)) {
    const title = (a.getAttribute("aria-label") ?? a.textContent ?? "").trim();
    if (!title) {
      continue;
    }
    const href = a.getAttribute("href") ?? "";
    const url = new URL(href, "https://suno.com").href;
    if (seen.has(url)) {
      continue;
    }
    seen.add(url);
    out.push({ title, url });
  }
  return out;
}
