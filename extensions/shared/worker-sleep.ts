// 非表示タブでも throttle されない Worker ベースの sleep (#5221)。
// バックグラウンド tab ではページの setTimeout が 1s+（最悪 1 分/回）に clamp され、
// Studio export や clip 走査の poll ループが実質停止する。Worker 内の setTimeout は
// ページの throttling 対象外のため通常速度で進行する。
// Worker が生成できない環境（CSP で blob: が拒否される、Worker 未対応等）では
// 初回の handshake 失敗以降、永続的にページ側 setTimeout へフォールバックする。

const WORKER_SOURCE = `self.onmessage = (e) => {
  const { id, ms } = e.data;
  setTimeout(() => self.postMessage(id), ms);
};`;

/** handshake で Worker 応答を待つ上限 (ms)。超えたら Worker は使えないとみなす。 */
const WORKER_HANDSHAKE_TIMEOUT_MS = 5000;

let workerReady: Promise<Worker | null> | null = null;
const pendingResolvers = new Map<number, () => void>();
let nextTimerId = 1;

function spawnWorker(): Promise<Worker | null> {
  try {
    const url = URL.createObjectURL(
      new Blob([WORKER_SOURCE], { type: "text/javascript" })
    );
    const worker = new Worker(url);
    URL.revokeObjectURL(url);
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        worker.terminate();
        resolve(null);
      }, WORKER_HANDSHAKE_TIMEOUT_MS);
      worker.addEventListener("error", () => {
        clearTimeout(timer);
        resolve(null);
      });
      worker.addEventListener("message", function onHandshake(event) {
        if (event.data !== 0) {
          return;
        }
        worker.removeEventListener("message", onHandshake);
        clearTimeout(timer);
        // handshake 以降は timer id → resolver の配送に切り替える
        worker.addEventListener("message", (ev) => {
          const resolver = pendingResolvers.get(ev.data);
          pendingResolvers.delete(ev.data);
          resolver?.();
        });
        resolve(worker);
      });
      worker.postMessage({ id: 0, ms: 0 }, []);
    });
  } catch {
    return Promise.resolve(null);
  }
}

/**
 * `ms` 後に resolve する。Worker が利用可能なら Worker 内 setTimeout を使い、
 * 非表示タブの throttling を回避する。利用不可ならページ側 setTimeout に落ちる。
 */
export async function sleep(ms: number): Promise<void> {
  workerReady ??= spawnWorker();
  const worker = await workerReady;
  if (!worker) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
  return new Promise((resolve) => {
    const id = nextTimerId++;
    pendingResolvers.set(id, resolve);
    worker.postMessage({ id, ms }, []);
  });
}
