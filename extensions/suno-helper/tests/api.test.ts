// yt-collection-serve の `/suno/prompts.json` クライアントの契約テスト。
// 旧 `popup.js:54-60` の fetch ロジックを保持する:
//   - fetch 先は `${baseUrl}${PROMPTS_ROUTE}` (= `${baseUrl}/suno/prompts.json`)
//   - HTTP 非 2xx で throw
//   - 配列でない / 空配列の JSON で throw (fail-loud、silent 続行しない)
//   - 成功時は PromptEntry[] を返す
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type CollectionSummary,
  type PromptEntry,
  fetchCollections,
  fetchCollectionPrompts,
  fetchPrompts,
  pickInitialCollectionId,
} from "../../shared/api";

const BASE_URL = "http://localhost:7873";
const PROMPTS_URL = `${BASE_URL}/suno/prompts.json`;
const COLLECTIONS_URL = `${BASE_URL}/collections`;

function mockFetch(impl: () => Partial<Response>) {
  const fn = vi.fn(async () => impl() as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("shared/api fetchPrompts: 配信元 URL の組み立て", () => {
  it("Given baseUrl When fetch する Then `/suno/prompts.json` サブパスへ要求する", async () => {
    const fetchFn = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => [{ name: "p1", style: "lofi", lyrics: "" }],
    }));

    await fetchPrompts(BASE_URL);

    expect(fetchFn).toHaveBeenCalledWith(PROMPTS_URL);
  });
});

describe("shared/api fetchPrompts: 正常系", () => {
  it("Given 配列 JSON When fetch する Then PromptEntry[] を返す", async () => {
    const entries = [
      { name: "夜更けのカフェ", style: "lofi, jazzy", lyrics: "la la la" },
      { name: "instrumental", style: "ambient", lyrics: "" },
    ];
    mockFetch(() => ({ ok: true, status: 200, json: async () => entries }));

    const result = await fetchPrompts(BASE_URL);

    expect(result).toEqual(entries);
    expect(result[0]).toMatchObject({
      name: expect.any(String),
      style: expect.any(String),
      lyrics: expect.any(String),
    });
  });
});

describe("shared/api PromptEntry.title: optional 契約 (#844, 後方互換)", () => {
  it("Given title 付き entry When fetch する Then title を保持して返す", async () => {
    const entries = [{ name: "夜更けのカフェ", title: "Midnight Cafe", style: "lofi, jazzy", lyrics: "la la la" }];
    mockFetch(() => ({ ok: true, status: 200, json: async () => entries }));

    const result = await fetchPrompts(BASE_URL);

    expect(result[0].title).toBe("Midnight Cafe");
  });

  it("Given title 無し entry When fetch する Then title は undefined（optional なので throw しない）", async () => {
    const entries = [{ name: "夜更けのカフェ", style: "lofi, jazzy", lyrics: "la la la" }];
    mockFetch(() => ({ ok: true, status: 200, json: async () => entries }));

    const result = await fetchPrompts(BASE_URL);

    expect(result[0].title).toBeUndefined();
  });

  it("Given title あり/なし混在の配列 When fetch する Then 双方が PromptEntry[] として通る", async () => {
    // 後方互換: 既存の title 無し entry と新 title 付き entry が同一配列に共存できる。
    const withTitle: PromptEntry = { name: "p1", title: "Custom One", style: "ambient", lyrics: "" };
    const withoutTitle: PromptEntry = { name: "p2", style: "cinematic", lyrics: "" };
    mockFetch(() => ({ ok: true, status: 200, json: async () => [withTitle, withoutTitle] }));

    const result = await fetchPrompts(BASE_URL);

    expect(result).toEqual([withTitle, withoutTitle]);
    expect(result[0].title).toBe("Custom One");
    expect(result[1].title).toBeUndefined();
  });
});

describe("shared/api fetchPrompts: 異常系 (fail-loud)", () => {
  it("Given HTTP 500 When fetch する Then ステータスを含めて throw する", async () => {
    mockFetch(() => ({ ok: false, status: 500, json: async () => ({}) }));

    await expect(fetchPrompts(BASE_URL)).rejects.toThrow(/500/);
  });

  it("Given 配列でない JSON (オブジェクト) When fetch する Then throw する", async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => ({ name: "x" }) }));

    await expect(fetchPrompts(BASE_URL)).rejects.toThrow();
  });

  it("Given 空配列 When fetch する Then throw する", async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => [] }));

    await expect(fetchPrompts(BASE_URL)).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// fetchCollections (#816 dir mode): `/collections` 列挙クライアント
//   - fetch 先は `${baseUrl}/collections`
//   - HTTP 非 2xx で throw
//   - 配列を返す（空配列も許容 = 単一 mode / collection 0 件の fallback 判断は呼び出し側）
// ---------------------------------------------------------------------------

const SAMPLE_COLLECTIONS: CollectionSummary[] = [
  { id: "20260601-clm-aaa-collection", name: "aaa-collection", has_prompts: true, pattern_count: 12 },
  { id: "20260602-clm-bbb-collection", name: "bbb-collection", has_prompts: false, pattern_count: null },
];

describe("shared/api fetchCollections: 配信元 URL の組み立て", () => {
  it("Given baseUrl When fetch する Then `/collections` サブパスへ要求する", async () => {
    const fetchFn = mockFetch(() => ({ ok: true, status: 200, json: async () => [] }));

    await fetchCollections(BASE_URL);

    expect(fetchFn).toHaveBeenCalledWith(COLLECTIONS_URL);
  });
});

describe("shared/api fetchCollections: 正常系", () => {
  it("Given collection 配列 When fetch する Then CollectionSummary[] を返す", async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => SAMPLE_COLLECTIONS }));

    const result = await fetchCollections(BASE_URL);

    expect(result).toEqual(SAMPLE_COLLECTIONS);
    expect(result[0]).toMatchObject({
      id: expect.any(String),
      name: expect.any(String),
      has_prompts: expect.any(Boolean),
    });
  });

  it("Given 空配列 When fetch する Then throw せず [] を返す (fallback 判断は呼び出し側)", async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => [] }));

    await expect(fetchCollections(BASE_URL)).resolves.toEqual([]);
  });
});

describe("shared/api fetchCollections: 異常系 (fail-loud)", () => {
  it("Given HTTP 404 (単一 mode サーバー) When fetch する Then throw する (popup の fallback トリガー)", async () => {
    mockFetch(() => ({ ok: false, status: 404, json: async () => ({}) }));

    await expect(fetchCollections(BASE_URL)).rejects.toThrow(/404/);
  });

  it("Given 配列でない JSON When fetch する Then throw する", async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => ({ id: "x" }) }));

    await expect(fetchCollections(BASE_URL)).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// fetchCollectionPrompts (#816): `/collections/<id>/suno/prompts.json`
//   - fetch 先は collectionPromptsRoute(id)
//   - HTTP 非 2xx / 空配列 / 非配列で throw（fetchPrompts と同じ fail-loud 契約）
// ---------------------------------------------------------------------------

describe("shared/api fetchCollectionPrompts: 配信元 URL の組み立て", () => {
  it("Given id When fetch する Then `/collections/<id>/suno/prompts.json` へ要求する", async () => {
    const fetchFn = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => [{ name: "p1", style: "lofi", lyrics: "" }],
    }));

    await fetchCollectionPrompts(BASE_URL, "20260601-clm-aaa-collection");

    expect(fetchFn).toHaveBeenCalledWith(`${BASE_URL}/collections/20260601-clm-aaa-collection/suno/prompts.json`);
  });
});

describe("shared/api fetchCollectionPrompts: 正常系", () => {
  it("Given 配列 JSON When fetch する Then PromptEntry[] を返す", async () => {
    const entries = [{ name: "夜更けのカフェ", style: "lofi, jazzy", lyrics: "la la la" }];
    mockFetch(() => ({ ok: true, status: 200, json: async () => entries }));

    const result = await fetchCollectionPrompts(BASE_URL, "20260601-clm-aaa-collection");

    expect(result).toEqual(entries);
  });
});

describe("shared/api fetchCollectionPrompts: 異常系 (fail-loud)", () => {
  it("Given HTTP 404 (未知 id) When fetch する Then throw する", async () => {
    mockFetch(() => ({ ok: false, status: 404, json: async () => ({}) }));

    await expect(fetchCollectionPrompts(BASE_URL, "nope")).rejects.toThrow(/404/);
  });

  it("Given 空配列 When fetch する Then throw する (空 collection は silent 続行しない)", async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => [] }));

    await expect(fetchCollectionPrompts(BASE_URL, "20260601-clm-aaa-collection")).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// pickInitialCollectionId (#816): ドロップダウン初期選択ロジック（純関数）
//   - 初期値は最初の has_prompts===true な entry の id
//   - has_prompts が無い / 空配列 のときは null（選択不可）
// React テスト基盤を増やさず、選択ルールを純関数として担保する。
// ---------------------------------------------------------------------------

describe("shared/api pickInitialCollectionId: 初期選択ルール", () => {
  it("Given 全て has_prompts=true When 初期値を選ぶ Then 先頭の id を返す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", has_prompts: true, pattern_count: 1 },
      { id: "c2", name: "c2", has_prompts: true, pattern_count: 2 },
    ];

    expect(pickInitialCollectionId(collections)).toBe("c1");
  });

  it("Given 先頭が has_prompts=false When 初期値を選ぶ Then 最初の has_prompts=true な id を返す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", has_prompts: false, pattern_count: null },
      { id: "c2", name: "c2", has_prompts: true, pattern_count: 2 },
    ];

    expect(pickInitialCollectionId(collections)).toBe("c2");
  });

  it("Given どれも has_prompts=false When 初期値を選ぶ Then null を返す (実行可能な選択肢なし)", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", has_prompts: false, pattern_count: null },
      { id: "c2", name: "c2", has_prompts: false, pattern_count: null },
    ];

    expect(pickInitialCollectionId(collections)).toBeNull();
  });

  it("Given 空配列 When 初期値を選ぶ Then null を返す", () => {
    expect(pickInitialCollectionId([])).toBeNull();
  });
});
