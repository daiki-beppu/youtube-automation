// 連続実行完了時の自動 playlist capture の glue ロジック (#893 追加要件 A)。
// background.ts / content.ts はともに wxt の defineBackground / defineContentScript globals を伴い
// node 環境の vitest から import できない。orchestration 本体（background 側）と fail-soft trigger
// （content 側）をここへ切り出し、副作用（tab 開閉 / scrape 送信 / POST / storage 読取）を引数注入に
// して tester surface とする（overlay-relay.ts と同じ「lib に純ロジック・entrypoint で配線」方針）。
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
 * bg `/me` tab の content script が応答するまでリトライしつつ playlist を scrape する (#893)。
 * tab 生成直後は content script 未注入で sendCapture が reject されるため、deadline まで poll する。
 * deadline 超過時は最後のエラーを throw する（fail-loud。呼び出し側 autoCapturePlaylists が握る）。
 */
export async function captureFromTab(tabId: number, deps: CaptureFromTabDeps): Promise<CapturedPlaylist[]> {
  const deadline = deps.now() + deps.timeoutMs;
  let lastErr: unknown;
  while (deps.now() < deadline) {
    try {
      return await deps.sendCapture(tabId);
    } catch (err) {
      // content script 未注入（tab ロード中）。間隔を空けて再試行する。
      lastErr = err;
      await deps.sleep(deps.pollMs);
    }
  }
  throw lastErr ?? new Error("capturePlaylists timed out");
}

/** autoCapturePlaylists の副作用注入点。 */
export interface AutoCaptureDeps {
  /** サーバー URL（overlay の入力値）を読み取る。空なら capture を諦める。 */
  getServerUrl: () => Promise<string>;
  /** 非アクティブな bg `/me` tab を開く。 */
  createMeTab: () => Promise<{ id?: number }>;
  removeTab: (tabId: number) => Promise<void>;
  /** 開いた tab から playlist を scrape する（リトライ込み）。 */
  capture: (tabId: number) => Promise<CapturedPlaylist[]>;
  post: (baseUrl: string, items: CapturedPlaylist[]) => Promise<unknown>;
}

/**
 * 連続実行完了時の自動 capture（追加要件 A）。bg `/me` tab を開いて playlist を scrape し、
 * POST /suno/playlists へ送って tab を閉じる。
 *   - サーバー URL 未設定: 送信先が無いため capture せず return（fail soft、明示要件 A）。
 *   - tab.id が取れない: 中継先が無いため return。
 *   - capture が空: POST しない（不要書き込みを避ける）。
 *   - tab は capture / POST の成否に関わらず finally で必ず閉じる。
 * scrape / POST の失敗は throw されるが、呼び出し側（background の onMessage）が warning に留める。
 */
export async function autoCapturePlaylists(deps: AutoCaptureDeps): Promise<void> {
  const baseUrl = (await deps.getServerUrl()).trim();
  if (!baseUrl) {
    return;
  }
  const tab = await deps.createMeTab();
  if (typeof tab.id !== "number") {
    return;
  }
  const tabId = tab.id;
  try {
    const items = await deps.capture(tabId);
    if (items.length > 0) {
      await deps.post(baseUrl, items);
    }
  } finally {
    await deps.removeTab(tabId);
  }
}

/**
 * 連続実行の playlist 化完了時に、content (runner) から background へ自動 capture を fail-soft で trigger する (#893)。
 * 送信失敗（background 不在等）は onError へ流して握り、呼び出し側の PHASE.FINISHED 進行を妨げない
 * （capture はベストエフォート。送信できなくても連続実行は完了扱いにする）。
 */
export async function triggerPlaylistCaptureFailSoft(
  send: () => Promise<void>,
  onError: (err: unknown) => void,
): Promise<void> {
  try {
    await send();
  } catch (err) {
    onError(err);
  }
}
