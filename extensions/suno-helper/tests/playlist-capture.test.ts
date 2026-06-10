// Suno playlist capture のクライアント契約テスト (#893)。
//   - constants.ts: PLAYLISTS_CAPTURE_ROUTE が `/suno/playlists` (サーバー契約と対の SSOT)
//   - shared/api.ts: postCapturedPlaylists(baseUrl, items) の POST 組み立て / fail-loud
//   - shared/api.ts: CollectionSummary.mapped は optional（後方互換）
//   - shared/api.ts: excludeMappedCollections は mapped===true を除外する純関数（追加要件 B）
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type CapturedPlaylist,
  type CollectionSummary,
  excludeMappedCollections,
  fetchCollections,
  postCapturedPlaylists,
} from "../../shared/api";
import { PLAYLISTS_CAPTURE_ROUTE } from "../../shared/constants";

const BASE_URL = "http://localhost:7873";
const CAPTURE_URL = `${BASE_URL}/suno/playlists`;

function mockFetch(impl: () => Partial<Response>) {
  const fn = vi.fn(async () => impl() as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// PLAYLISTS_CAPTURE_ROUTE: サーバー (SUNO_PLAYLISTS_ROUTE) と対の契約文字列
// ---------------------------------------------------------------------------

describe("constants PLAYLISTS_CAPTURE_ROUTE: SSOT 契約", () => {
  it("Given 定数 When 値を読む Then `/suno/playlists` である（サーバー SUNO_PLAYLISTS_ROUTE と一致）", () => {
    expect(PLAYLISTS_CAPTURE_ROUTE).toBe("/suno/playlists");
  });
});

// ---------------------------------------------------------------------------
// postCapturedPlaylists: 捕捉した playlist を POST するクライアント
// ---------------------------------------------------------------------------

const SAMPLE_ITEMS: CapturedPlaylist[] = [
  { title: "df365 | Deep Focus", url: "https://suno.com/playlist/u1" },
  { title: "df365 | Night Drive", url: "https://suno.com/playlist/u2" },
];

describe("shared/api postCapturedPlaylists: POST 組み立て", () => {
  it("Given baseUrl と items When POST する Then `/suno/playlists` へ method POST + JSON body で要求する", async () => {
    const fetchFn = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ written: 2, path: "/root/config/suno-playlists.json" }),
    }));

    await postCapturedPlaylists(BASE_URL, SAMPLE_ITEMS);

    expect(fetchFn).toHaveBeenCalledTimes(1);
    // mockFetch の fn は 0 引数型で .mock.calls[0] が [] と推論されるため unknown 経由で読む。
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(CAPTURE_URL);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(SAMPLE_ITEMS);
  });

  it("Given items を body の root shape のまま渡す When POST する Then body は配列のまま（envelope 包みしない）", async () => {
    const fetchFn = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ written: 2, path: "/p" }),
    }));

    await postCapturedPlaylists(BASE_URL, SAMPLE_ITEMS);

    const [, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(Array.isArray(JSON.parse(init.body as string))).toBe(true);
  });
});

describe("shared/api postCapturedPlaylists: 正常系", () => {
  it("Given 200 + {written, path} When POST する Then parse した {written, path} を返す", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ written: 2, path: "/root/config/suno-playlists.json" }),
    }));

    const result = await postCapturedPlaylists(BASE_URL, SAMPLE_ITEMS);

    expect(result).toEqual({ written: 2, path: "/root/config/suno-playlists.json" });
  });
});

describe("shared/api postCapturedPlaylists: 異常系 (fail-loud)", () => {
  it("Given 403 (Origin 不許可) When POST する Then ステータスを含めて throw する", async () => {
    mockFetch(() => ({ ok: false, status: 403, json: async () => ({}) }));

    await expect(postCapturedPlaylists(BASE_URL, SAMPLE_ITEMS)).rejects.toThrow(/403/);
  });

  it("Given 404 (capture 無効サーバー) When POST する Then throw する", async () => {
    mockFetch(() => ({ ok: false, status: 404, json: async () => ({}) }));

    await expect(postCapturedPlaylists(BASE_URL, SAMPLE_ITEMS)).rejects.toThrow(/404/);
  });
});

// ---------------------------------------------------------------------------
// CollectionSummary.mapped: optional フィールド（後方互換）
// ---------------------------------------------------------------------------

describe("shared/api CollectionSummary.mapped: optional 契約（追加要件 B）", () => {
  it("Given mapped 付き collection When fetchCollections する Then mapped を保持して返す", async () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", has_prompts: true, pattern_count: 1, mapped: true },
      { id: "c2", name: "c2", has_prompts: true, pattern_count: 2, mapped: false },
    ];
    mockFetch(() => ({ ok: true, status: 200, json: async () => collections }));

    const result = await fetchCollections(BASE_URL);

    expect(result[0].mapped).toBe(true);
    expect(result[1].mapped).toBe(false);
  });

  it("Given mapped 無し collection（prefix 未設定の旧サーバー）When fetchCollections する Then mapped は undefined（throw しない）", async () => {
    const collections = [{ id: "c1", name: "c1", has_prompts: true, pattern_count: 1 }];
    mockFetch(() => ({ ok: true, status: 200, json: async () => collections }));

    const result = await fetchCollections(BASE_URL);

    expect(result[0].mapped).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// excludeMappedCollections: mapped===true を除外する純関数（追加要件 B）
// ---------------------------------------------------------------------------

describe("shared/api excludeMappedCollections: 未マッピングのみ残す", () => {
  it("Given mapped と未 mapped 混在 When フィルタする Then mapped===true を除外する", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", has_prompts: true, pattern_count: 1, mapped: true },
      { id: "c2", name: "c2", has_prompts: true, pattern_count: 2, mapped: false },
      { id: "c3", name: "c3", has_prompts: true, pattern_count: 3, mapped: true },
    ];

    const result = excludeMappedCollections(collections);

    expect(result.map((c) => c.id)).toEqual(["c2"]);
  });

  it("Given 全件 mapped===true When フィルタする Then 空配列を返す（ドロップダウンに出ない）", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", has_prompts: true, pattern_count: 1, mapped: true },
      { id: "c2", name: "c2", has_prompts: true, pattern_count: 2, mapped: true },
    ];

    expect(excludeMappedCollections(collections)).toEqual([]);
  });

  it("Given mapped 未設定（prefix 未指定の旧運用）When フィルタする Then 全件残す（後方互換）", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", has_prompts: true, pattern_count: 1 },
      { id: "c2", name: "c2", has_prompts: false, pattern_count: null },
    ];

    expect(excludeMappedCollections(collections)).toEqual(collections);
  });

  it("Given 空配列 When フィルタする Then 空配列を返す", () => {
    expect(excludeMappedCollections([])).toEqual([]);
  });
});
