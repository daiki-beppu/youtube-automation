// background.ts は wxt の defineBackground globals を伴い node 環境の vitest から import できない。
// playlist URL 解決用 bg `/me` tab の scrape retry ロジックをここへ切り出し、副作用（送信 / sleep / clock）を
// 引数注入にして tester surface とする。
import type { CapturedPlaylist } from "../../shared/api";

/** captureFromTab がリトライ判断に使う時刻・待機・送信の注入点。 */
export interface CaptureFromTabDeps {
  /** 指定 tab の runner content へ capturePlaylists を送って scrape 結果を受け取る。 */
  sendCapture: (tabId: number) => Promise<CapturedPlaylist[]>;
  sleep: (ms: number) => Promise<void>;
  now: () => number;
  /** content script 応答待ちの上限。 */
  timeoutMs: number;
  /** リトライ間隔。 */
  pollMs: number;
}

/**
 * bg `/me` tab の content script が応答するまでリトライしつつ playlist を scrape する。
 * tab 生成直後は content script 未注入で sendCapture が reject されるため、deadline まで poll する。
 * SPA 未描画で scrape 結果が空の場合もリトライする（React hydration + API fetch 待ち）。
 * deadline 超過時:
 *   - 一度でも空応答があった場合: [] を返す（fail-soft。呼び出し側が POST skip で穏やかに終了する）。
 *   - 全て throw だった場合: 最後のエラーを throw する（fail-loud）。
 */
export async function captureFromTab(tabId: number, deps: CaptureFromTabDeps): Promise<CapturedPlaylist[]> {
  const deadline = deps.now() + deps.timeoutMs;
  let lastErr: unknown;
  let emptyReceived = false;
  while (deps.now() < deadline) {
    try {
      const items = await deps.sendCapture(tabId);
      if (items.length > 0) {
        return items;
      }
      // SPA 未描画: content script は応答したが playlist 要素がまだ無い。リトライする。
      emptyReceived = true;
      await deps.sleep(deps.pollMs);
    } catch (err) {
      // content script 未注入（tab ロード中）。間隔を空けて再試行する。
      lastErr = err;
      await deps.sleep(deps.pollMs);
    }
  }
  if (emptyReceived) {
    return [];
  }
  throw lastErr ?? new Error("capturePlaylists timed out");
}
