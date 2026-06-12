// ISOLATED content script 側の bridge 受信配線 (#948)。
//
// MAIN world bridge（entrypoints/suno-bridge.content.ts）からの window.postMessage を検証して
// clip-tracker へ流し込み、passive 観測が途絶えたときの active feed poll を駆動する。
//
// メッセージ検証: `event.source === window`（同一 window 以外を拒否）+ `source === BRIDGE_SOURCE`。
// ページ本体や他拡張からの message は type が一致しても source マーカーで弾く。
import {
  BRIDGE_MSG,
  BRIDGE_SOURCE,
  FEED_POLL_INTERVAL_MS,
  FEED_POLL_RESPONSE_TIMEOUT_MS,
  FEED_STALE_MS,
  type ObservedClip,
} from "../../shared/constants";
import type { ClipTracker } from "./clip-tracker";

interface BridgeMessage {
  source?: string;
  type?: string;
  clips?: unknown;
  requestId?: number;
}

function isObservedClipArray(value: unknown): value is ObservedClip[] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as { id?: unknown }).id === "string" &&
        typeof (item as { status?: unknown }).status === "string",
    )
  );
}

/**
 * bridge からの観測イベントを tracker へ配線する。返り値の関数で解除できる。
 * FEED_POLL_RESPONSE は requestFeedPoll 側の一時 listener が個別に拾うため、ここでは扱わない。
 */
export function attachBridgeListener(tracker: ClipTracker): () => void {
  const handler = (event: MessageEvent): void => {
    if (event.source !== window) {
      return;
    }
    const data = event.data as BridgeMessage | null;
    if (!data || data.source !== BRIDGE_SOURCE || !isObservedClipArray(data.clips)) {
      return;
    }
    if (data.type === BRIDGE_MSG.GENERATE_CLIPS) {
      tracker.registerSubmitted(data.clips);
    } else if (data.type === BRIDGE_MSG.FEED_CLIPS || data.type === BRIDGE_MSG.FEED_POLL_RESPONSE) {
      // active poll の応答も観測の一種として tracker に合流させる（requestId の突合は poller 側）。
      tracker.applyFeedStatuses(data.clips);
    }
  };
  window.addEventListener("message", handler);
  return () => window.removeEventListener("message", handler);
}

let nextRequestId = 1;

/**
 * bridge へ active feed poll を要求し、対応する応答を待つ。
 * bridge 不在・token 未捕捉・timeout は null（fail-soft。tracker への反映は
 * attachBridgeListener が応答 message を受けた時点で済んでいる）。
 */
export function requestFeedPoll(
  ids: string[],
  timeoutMs: number = FEED_POLL_RESPONSE_TIMEOUT_MS,
): Promise<ObservedClip[] | null> {
  return new Promise((resolve) => {
    const requestId = nextRequestId++;
    const cleanup = (result: ObservedClip[] | null): void => {
      window.removeEventListener("message", handler);
      clearTimeout(timer);
      resolve(result);
    };
    const handler = (event: MessageEvent): void => {
      if (event.source !== window) {
        return;
      }
      const data = event.data as BridgeMessage | null;
      if (
        !data ||
        data.source !== BRIDGE_SOURCE ||
        data.type !== BRIDGE_MSG.FEED_POLL_RESPONSE ||
        data.requestId !== requestId
      ) {
        return;
      }
      cleanup(isObservedClipArray(data.clips) ? data.clips : null);
    };
    const timer = setTimeout(() => cleanup(null), timeoutMs);
    window.addEventListener("message", handler);
    window.postMessage(
      { source: BRIDGE_SOURCE, type: BRIDGE_MSG.FEED_POLL_REQUEST, requestId, ids },
      window.location.origin,
    );
  });
}

export interface FeedPoller {
  start(): void;
  stop(): void;
}

/**
 * passive 観測が FEED_STALE_MS 途絶え、かつ未終端 clip が残っているときだけ
 * active feed poll を発行する poller。run 中のみ start し、終端で stop する。
 * Suno の clip status 更新は WebSocket 経由のため feed の passive 観測は期待できず、
 * 実運用では本 poller が status 更新の主経路になる（間隔はページ自身のポーリング頻度相当に抑制）。
 */
export function createFeedPoller(
  tracker: ClipTracker,
  options: {
    intervalMs?: number;
    staleMs?: number;
    now?: () => number;
    /** poll 実体の DI（テスト用）。省略時は requestFeedPoll。 */
    poll?: (ids: string[]) => Promise<unknown>;
  } = {},
): FeedPoller {
  const intervalMs = options.intervalMs ?? FEED_POLL_INTERVAL_MS;
  const staleMs = options.staleMs ?? FEED_STALE_MS;
  const now = options.now ?? Date.now;
  const poll = options.poll ?? requestFeedPoll;
  let timer: ReturnType<typeof setInterval> | null = null;
  let polling = false;

  async function tick(): Promise<void> {
    if (polling) {
      return; // 応答待ちの間に次 tick が重ならないようにする
    }
    const ids = tracker.getPendingIds();
    if (ids.length === 0 || now() - tracker.lastFeedAt() < staleMs) {
      return;
    }
    polling = true;
    try {
      await poll(ids);
    } finally {
      polling = false;
    }
  }

  return {
    start() {
      if (timer === null) {
        timer = setInterval(() => void tick(), intervalMs);
      }
    },
    stop() {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    },
  };
}
