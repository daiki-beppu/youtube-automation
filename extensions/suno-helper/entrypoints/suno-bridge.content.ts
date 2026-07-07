// MAIN world fetch bridge (#948)。Suno ページ自身の fetch をラップし、
//   - 生成投入（POST /api/generate/v2-web/）のレスポンス → 投入 clip の観測イベント
//   - feed（POST /api/feed/v3）のレスポンス → clip status の観測イベント
// を window.postMessage で ISOLATED content script（lib/bridge-listener.ts）へ転送する。
//
// MAIN world で動かす理由: content script（ISOLATED）からはページの fetch を観測できず、
// studio-api への自前 fetch も CORS / 認証文脈の制約を受ける。MAIN world ならページと
// 同一文脈で観測・照会でき、manifest の権限追加も不要（最小権限契約を維持）。
//
// Authorization（Bearer）はこの MAIN world のローカル変数に閉じ、extension 側へは出さない。
// 失効（401）したら破棄し、ページの次リクエストで自動再捕捉する。
//
// 観測は徹底して fail-soft: 解析失敗・転送失敗で例外を漏らさず、ページの fetch 結果には
// 一切干渉しない（res は clone を読み、原物をそのまま返す）。
import {
  BRIDGE_MSG,
  BRIDGE_SOURCE,
  FEED_V3_METHOD,
  FEED_V3_PATH,
  type ObservedClip,
  SUNO_API_ORIGIN,
  SUNO_MATCHES,
} from "../../shared/constants";
import {
  extractAuthHeader,
  isFeedRequest,
  isGenerateRequest,
  isSunoApiUrl,
  parseClipsFromFeedResponse,
  parseClipsFromGenerateResponse,
  resolveRequestMethod,
  resolveRequestUrl,
} from "../lib/fetch-bridge";
import { findSliderElement, setSliderValueViaReact } from "../lib/slider-bridge";

export default defineContentScript({
  matches: [...SUNO_MATCHES],
  // ページの最初の fetch（認証付き）から token を捕捉できるよう document_start で注入する。
  runAt: "document_start",
  world: "MAIN",
  main() {
    const originalFetch = window.fetch.bind(window);
    let authHeader: string | null = null;

    function post(type: string, payload: Record<string, unknown>): void {
      window.postMessage({ source: BRIDGE_SOURCE, type, ...payload }, window.location.origin);
    }

    function postClips(type: string, clips: ObservedClip[] | null): void {
      if (clips) {
        post(type, { clips });
      }
    }

    /** レスポンス clone を非同期で観測する。fetch の戻りを遅延させない・失敗を漏らさない。 */
    async function observe(url: string, method: string, res: Response): Promise<void> {
      try {
        if (!res.ok) {
          return;
        }
        if (isGenerateRequest(url)) {
          postClips(BRIDGE_MSG.GENERATE_CLIPS, parseClipsFromGenerateResponse(await res.json()));
        } else if (isFeedRequest(url, method)) {
          postClips(BRIDGE_MSG.FEED_CLIPS, parseClipsFromFeedResponse(await res.json()));
        }
      } catch {
        // 観測のみの経路。解析失敗でページにも runner にも影響させない。
      }
    }

    const observedFetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      let url = "";
      let method = "GET";
      try {
        url = resolveRequestUrl(input);
        method = resolveRequestMethod(input, init);
        if (isSunoApiUrl(url)) {
          const auth = extractAuthHeader(input, init);
          if (auth) {
            authHeader = auth;
          }
        }
      } catch {
        // URL 解決の失敗は観測を諦めるだけで、fetch 自体は素通しする。
      }
      const res = await originalFetch(input, init);
      if (url) {
        void observe(url, method, res.clone());
      }
      return res;
    };
    Object.assign(observedFetch, originalFetch);
    window.fetch = observedFetch as typeof fetch;

    /** content script からの active feed poll 要求に応える。token 未捕捉・失敗は clips: null。 */
    async function handleFeedPoll(requestId: number, ids: string[]): Promise<void> {
      const respond = (clips: ObservedClip[] | null): void =>
        post(BRIDGE_MSG.FEED_V3_POLL_RESPONSE, { requestId, clips });
      if (!authHeader || ids.length === 0) {
        respond(null);
        return;
      }
      try {
        const res = await originalFetch(`${SUNO_API_ORIGIN}${FEED_V3_PATH}`, {
          method: FEED_V3_METHOD,
          headers: { authorization: authHeader, "content-type": "application/json" },
          body: JSON.stringify({ ids }),
        });
        if (res.status === 401) {
          // token 失効。破棄してページの次リクエストでの再捕捉に委ねる。
          authHeader = null;
          respond(null);
          return;
        }
        if (!res.ok) {
          respond(null);
          return;
        }
        respond(parseClipsFromFeedResponse(await res.json()));
      } catch {
        respond(null);
      }
    }

    /**
     * content script からの slider 注入要求に応える（#973）。React props の onKeyDown を
     * isTrusted: true の疑似イベントで直接呼び、Suno の bot 検知を通過させる。
     * 失敗（plain DOM / ハンドラ無効）は ok: false で返し、content 側が合成イベント経路へ縮退する。
     */
    async function handleSliderSet(requestId: number, ariaLabel: string, target: number): Promise<void> {
      const respond = (ok: boolean, actual: number | null): void =>
        post(BRIDGE_MSG.SLIDER_SET_RESPONSE, { requestId, ok, actual });
      try {
        const slider = findSliderElement(ariaLabel);
        if (!slider) {
          respond(false, null);
          return;
        }
        const ok = await setSliderValueViaReact(slider, target);
        const actual = Number(slider.getAttribute("aria-valuenow"));
        respond(ok, Number.isFinite(actual) ? actual : null);
      } catch {
        respond(false, null);
      }
    }

    window.addEventListener("message", (event: MessageEvent) => {
      if (event.source !== window) {
        return;
      }
      const data = event.data as {
        source?: string;
        type?: string;
        requestId?: number;
        ids?: string[];
        ariaLabel?: string;
        target?: number;
      } | null;
      if (!data || data.source !== BRIDGE_SOURCE || typeof data.requestId !== "number") {
        return;
      }
      if (data.type === BRIDGE_MSG.FEED_V3_POLL_REQUEST && Array.isArray(data.ids)) {
        void handleFeedPoll(data.requestId, data.ids);
      } else if (
        data.type === BRIDGE_MSG.SLIDER_SET_REQUEST &&
        typeof data.ariaLabel === "string" &&
        typeof data.target === "number"
      ) {
        void handleSliderSet(data.requestId, data.ariaLabel, data.target);
      }
    });
  },
});
