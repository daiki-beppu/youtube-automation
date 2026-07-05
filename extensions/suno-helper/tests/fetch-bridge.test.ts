// MAIN world fetch bridge の純関数 (#948) の回帰テスト。
//
// URL 判定・Authorization 抽出・レスポンス解析が対象。解析は fail-soft（形崩れで null、
// throw しない）が契約 — 観測の失敗で生成フローを止めないため。
import { describe, expect, it } from "vitest";

import { FEED_V3_METHOD, FEED_V3_PATH, GENERATE_ENDPOINT_PATH, SUNO_API_ORIGIN } from "../../shared/constants";
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

const GENERATE_URL = `${SUNO_API_ORIGIN}${GENERATE_ENDPOINT_PATH}`;
const FEED_URL = `${SUNO_API_ORIGIN}/api/feed/v2?ids=aaa,bbb`;
const FEED_V3_URL = `${SUNO_API_ORIGIN}${FEED_V3_PATH}`;

describe("URL 判定: 観測対象 endpoint の識別", () => {
  it("Given generate endpoint の URL When 判定する Then isGenerateRequest が true", () => {
    expect(isGenerateRequest(GENERATE_URL)).toBe(true);
    expect(isFeedRequest(GENERATE_URL, "GET")).toBe(false);
  });

  it("Given feed/v3 POST の URL When 判定する Then isFeedRequest が true", () => {
    expect(isFeedRequest(FEED_V3_URL, FEED_V3_METHOD)).toBe(true);
    expect(isGenerateRequest(FEED_URL)).toBe(false);
  });

  it("Given feed/v2 GET / feed/v3 GET の URL When 判定する Then isFeedRequest が false", () => {
    expect(isFeedRequest(FEED_URL, "GET")).toBe(false);
    expect(isFeedRequest(FEED_V3_URL, "GET")).toBe(false);
  });

  it("Given 別オリジンの同パス URL When 判定する Then すべて false（オリジン縛り）", () => {
    const phishing = `https://evil.example.com${GENERATE_ENDPOINT_PATH}`;
    expect(isSunoApiUrl(phishing)).toBe(false);
    expect(isGenerateRequest(phishing)).toBe(false);
    expect(isFeedRequest(`https://evil.example.com/api/feed/v3`, FEED_V3_METHOD)).toBe(false);
  });

  it("Given Suno origin に似た別 origin When 判定する Then すべて false", () => {
    const phishing = `https://studio-api-prod.suno.com.evil.example${GENERATE_ENDPOINT_PATH}`;
    expect(isSunoApiUrl(phishing)).toBe(false);
    expect(isGenerateRequest(phishing)).toBe(false);
    expect(isFeedRequest(`https://studio-api-prod.suno.com.evil.example${FEED_V3_PATH}`, FEED_V3_METHOD)).toBe(false);
  });

  it("Given feed/v3 に似た path や query 内一致 When 判定する Then isFeedRequest は false", () => {
    expect(isFeedRequest(`${SUNO_API_ORIGIN}/api/feed/v30`, FEED_V3_METHOD)).toBe(false);
    expect(isFeedRequest(`${SUNO_API_ORIGIN}/api/feed/v3extra`, FEED_V3_METHOD)).toBe(false);
    expect(
      isFeedRequest(`${SUNO_API_ORIGIN}/api/not-feed?next=${encodeURIComponent(FEED_V3_PATH)}`, FEED_V3_METHOD),
    ).toBe(false);
  });

  it("Given generate endpoint に似た path や query 内一致 When 判定する Then isGenerateRequest は false", () => {
    expect(isGenerateRequest(`${SUNO_API_ORIGIN}${GENERATE_ENDPOINT_PATH}extra`)).toBe(false);
    expect(
      isGenerateRequest(`${SUNO_API_ORIGIN}/api/not-generate?next=${encodeURIComponent(GENERATE_ENDPOINT_PATH)}`),
    ).toBe(false);
  });
});

describe("resolveRequestUrl: fetch 第 1 引数からの URL 解決", () => {
  it("Given string / URL / Request When 解決する Then いずれも URL 文字列を返す", () => {
    expect(resolveRequestUrl(GENERATE_URL)).toBe(GENERATE_URL);
    expect(resolveRequestUrl(new URL(GENERATE_URL))).toBe(GENERATE_URL);
    expect(resolveRequestUrl(new Request(GENERATE_URL))).toBe(GENERATE_URL);
  });
});

describe("resolveRequestMethod: fetch の実効 method 解決", () => {
  it("Given init.method When 解決する Then 大文字化して返す", () => {
    expect(resolveRequestMethod(FEED_V3_URL, { method: "post" })).toBe("POST");
  });

  it("Given Request.method When init.method 不在 Then Request 側の method を返す", () => {
    expect(resolveRequestMethod(new Request(FEED_V3_URL, { method: "POST" }))).toBe("POST");
  });

  it("Given method 不在 When 解決する Then GET を返す", () => {
    expect(resolveRequestMethod(FEED_V3_URL)).toBe("GET");
  });
});

describe("extractAuthHeader: Authorization の抽出", () => {
  it("Given record 形式の headers When 抽出する Then 値を返す（大文字小文字非依存）", () => {
    expect(extractAuthHeader(GENERATE_URL, { headers: { authorization: "Bearer abc" } })).toBe("Bearer abc");
    expect(extractAuthHeader(GENERATE_URL, { headers: { Authorization: "Bearer abc" } })).toBe("Bearer abc");
  });

  it("Given Headers / 配列形式 When 抽出する Then 値を返す", () => {
    expect(extractAuthHeader(GENERATE_URL, { headers: new Headers({ authorization: "Bearer h" }) })).toBe("Bearer h");
    expect(extractAuthHeader(GENERATE_URL, { headers: [["Authorization", "Bearer a"]] })).toBe("Bearer a");
  });

  it("Given Request オブジェクトに headers When init 不在 Then Request 側から抽出する", () => {
    const req = new Request(GENERATE_URL, { headers: { authorization: "Bearer r" } });
    expect(extractAuthHeader(req)).toBe("Bearer r");
  });

  it("Given Authorization 不在 When 抽出する Then null", () => {
    expect(extractAuthHeader(GENERATE_URL, { headers: { "content-type": "application/json" } })).toBeNull();
    expect(extractAuthHeader(GENERATE_URL)).toBeNull();
  });
});

describe("parseClipsFromGenerateResponse: 生成投入レスポンスの解析 (fail-soft)", () => {
  it("Given 実機形 {id, clips: [{id, status, duration?}]} When 解析する Then ObservedClip[] を返す", () => {
    const json = {
      id: "batch-1",
      clips: [
        { id: "c1", status: "submitted", title: "t1", extra: 1, metadata: { duration: 187.25 } },
        { id: "c2", status: "submitted" },
      ],
    };
    expect(parseClipsFromGenerateResponse(json)).toEqual([
      { id: "c1", status: "submitted", duration: 187.25 },
      { id: "c2", status: "submitted" },
    ]);
  });

  it("Given 形が崩れた JSON When 解析する Then null（throw しない）", () => {
    expect(parseClipsFromGenerateResponse(null)).toBeNull();
    expect(parseClipsFromGenerateResponse("oops")).toBeNull();
    expect(parseClipsFromGenerateResponse({})).toBeNull();
    expect(parseClipsFromGenerateResponse({ clips: "not-array" })).toBeNull();
    expect(parseClipsFromGenerateResponse({ clips: [] })).toBeNull();
    expect(parseClipsFromGenerateResponse({ clips: [{ id: 1, status: 2 }] })).toBeNull();
    expect(
      parseClipsFromGenerateResponse({ clips: [{ id: "c1", status: "submitted", duration: "241.2" }] }),
    ).toBeNull();
  });
});

describe("parseClipsFromFeedResponse: feed レスポンスの解析 (両形対応・fail-soft)", () => {
  it("Given {clips: [...]} 形 When 解析する Then ObservedClip[] を返す", () => {
    expect(parseClipsFromFeedResponse({ clips: [{ id: "c1", status: "streaming", duration: 182.4 }] })).toEqual([
      { id: "c1", status: "streaming", duration: 182.4 },
    ]);
  });

  it("Given feed v3 POST レスポンス形式 When metadata.duration がある Then duration を抽出する", () => {
    expect(
      parseClipsFromFeedResponse({
        clips: [
          { id: "c1", status: "complete", metadata: { duration: 187.25 } },
          { id: "c2", status: "streaming", metadata: {} },
        ],
      }),
    ).toEqual([
      { id: "c1", status: "complete", duration: 187.25 },
      { id: "c2", status: "streaming" },
    ]);
  });

  it("Given metadata.duration が finite number ではない When 解析する Then duration を省いて clip は返す", () => {
    expect(
      parseClipsFromFeedResponse({
        clips: [
          { id: "nan", status: "complete", metadata: { duration: Number.NaN } },
          { id: "inf", status: "complete", metadata: { duration: Infinity } },
          { id: "str", status: "complete", metadata: { duration: "187.25" } },
        ],
      }),
    ).toEqual([
      { id: "nan", status: "complete" },
      { id: "inf", status: "complete" },
      { id: "str", status: "complete" },
    ]);
  });

  it("Given 素の配列形 When 解析する Then ObservedClip[] を返す", () => {
    expect(parseClipsFromFeedResponse([{ id: "c1", status: "complete", duration: 0 }])).toEqual([
      { id: "c1", status: "complete", duration: 0 },
    ]);
  });

  it("Given 形が崩れた JSON When 解析する Then null（throw しない）", () => {
    expect(parseClipsFromFeedResponse(null)).toBeNull();
    expect(parseClipsFromFeedResponse({})).toBeNull();
    expect(parseClipsFromFeedResponse([])).toBeNull();
    expect(parseClipsFromFeedResponse([{ status: "complete" }])).toBeNull();
    expect(parseClipsFromFeedResponse({ clips: [{ id: "c1", status: "streaming", duration: "241.2" }] })).toBeNull();
    expect(parseClipsFromFeedResponse([{ id: "c1", status: "complete", duration: "241.2" }])).toBeNull();
    expect(parseClipsFromFeedResponse([{ id: "c1", status: "complete", duration: -1 }])).toBeNull();
  });
});
