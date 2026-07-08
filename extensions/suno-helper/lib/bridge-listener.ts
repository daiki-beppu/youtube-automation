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
  FEED_V3_POLL_RESPONSE_TIMEOUT_MS,
  FEED_STALE_MS,
  type ObservedClip,
  SLIDER_SET_RESPONSE_TIMEOUT_MS,
} from "../../shared/constants";
import type { ClipTracker } from "./clip-tracker";

interface BridgeMessage {
  source?: string;
  type?: string;
  clips?: unknown;
  requestId?: number;
  ok?: unknown;
  actual?: unknown;
}

function isObservedClipArray(value: unknown): value is ObservedClip[] {
  return (
    Array.isArray(value) &&
    value.every((item) => {
      if (typeof item !== "object" || item === null) {
        return false;
      }
      const clip = item as { duration?: unknown; id?: unknown; status?: unknown };
      return (
        typeof clip.id === "string" &&
        typeof clip.status === "string" &&
        (clip.duration === undefined ||
          (typeof clip.duration === "number" && Number.isFinite(clip.duration) && clip.duration >= 0))
      );
    })
  );
}

/**
 * bridge からの観測イベントを tracker へ配線する。返り値の関数で解除できる。
 * FEED_V3_POLL_RESPONSE は requestFeedPoll 側の一時 listener が個別に拾うが、tracker にも観測として合流させる。
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
    } else if (data.type === BRIDGE_MSG.FEED_CLIPS) {
      tracker.applyFeedStatuses(data.clips);
    } else if (data.type === BRIDGE_MSG.FEED_V3_POLL_RESPONSE) {
      // active poll（ID 指定照会）の応答は終端 status の未知 clip も登録する（requestId の突合は poller 側）。
      // reload 後 resume の保存済み clip は照会時点で complete 済みのことが多く、passive 合流と同じ
      // 「未知+終端は捨てる」規則だと getPendingIdsByIds が永遠に pending 扱いして完了待ちが stall する（#1586）。
      tracker.applyRequestedStatuses(data.clips);
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
  timeoutMs: number = FEED_V3_POLL_RESPONSE_TIMEOUT_MS,
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
        data.type !== BRIDGE_MSG.FEED_V3_POLL_RESPONSE ||
        data.requestId !== requestId
      ) {
        return;
      }
      cleanup(isObservedClipArray(data.clips) ? data.clips : null);
    };
    const timer = setTimeout(() => cleanup(null), timeoutMs);
    window.addEventListener("message", handler);
    window.postMessage(
      { source: BRIDGE_SOURCE, type: BRIDGE_MSG.FEED_V3_POLL_REQUEST, requestId, ids },
      window.location.origin,
    );
  });
}

/**
 * bridge へ slider 注入を要求し、応答を待つ（#973）。MAIN world 側が React props の
 * onKeyDown を isTrusted: true の疑似イベントで直接呼び、aria-valuenow 読み戻しまで検証する。
 * bridge 不在・plain DOM（e2e mock）・timeout は false（fail-soft。呼び出し側が
 * 合成 dispatchEvent 経路へ縮退する）。
 */
export function requestSliderSet(
  ariaLabel: string,
  target: number,
  timeoutMs: number = SLIDER_SET_RESPONSE_TIMEOUT_MS,
): Promise<boolean> {
  return new Promise((resolve) => {
    const requestId = nextRequestId++;
    const cleanup = (result: boolean): void => {
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
        data.type !== BRIDGE_MSG.SLIDER_SET_RESPONSE ||
        data.requestId !== requestId
      ) {
        return;
      }
      cleanup(data.ok === true);
    };
    const timer = setTimeout(() => cleanup(false), timeoutMs);
    window.addEventListener("message", handler);
    window.postMessage(
      { source: BRIDGE_SOURCE, type: BRIDGE_MSG.SLIDER_SET_REQUEST, requestId, ariaLabel, target },
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
