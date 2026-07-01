// yt-collection-serve の `/suno/prompts.json` クライアントの契約テスト。
// 旧 `popup.js:54-60` の fetch ロジックを保持する:
//   - fetch 先は `${baseUrl}${PROMPTS_ROUTE}` (= `${baseUrl}/suno/prompts.json`)
//   - HTTP 非 2xx で throw
//   - 配列でない / 空配列の JSON で throw (fail-loud、silent 続行しない)
//   - 成功時は PromptEntry[] を返す
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_DURATION_FILTER,
  type CollectionSummary,
  type DurationFilter,
  type PromptEntry,
  checkServerCompatibility,
  collectionHasPrompts,
  durationFilterOrDefault,
  fetchCollectionPromptResponse,
  fetchCollections,
  fetchCollectionPrompts,
  fetchPromptResponse,
  fetchPrompts,
  fetchServerVersion,
  formatCompatibilityWarning,
  pickInitialCollectionId,
  postDownloaded,
  resolvePromptCollectionId,
  resolveCompatibilityWarning,
  visiblePromptCollections,
} from "../../shared/api";

const BASE_URL = "http://localhost:7873";
const PROMPTS_URL = `${BASE_URL}/suno/prompts.json`;
const COLLECTIONS_URL = `${BASE_URL}/collections`;
const VERSION_URL = `${BASE_URL}/version`;

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

describe("shared/api PromptEntry: More Options 3 フィールドの optional 契約 (#900)", () => {
  // 契約 (draft が実装する shared/api.ts PromptEntry):
  //   style_influence?: number;  // 0-100 整数 (Suno Style Influence slider)
  //   weirdness?: number;        // 0-100 整数 (Suno Weirdness slider)
  //   exclude_styles?: string;   // free text (Suno Exclude styles input)
  // いずれも optional・後方互換。命名は wire 形 snake_case で TS/Python/サーバー契約を統一する。

  it("Given 3 フィールド付き entry When fetch する Then 各値を保持して返す", async () => {
    const entries = [
      { name: "p1", style: "lofi", lyrics: "", style_influence: 85, weirdness: 30, exclude_styles: "hyperpop, edm" },
    ];
    mockFetch(() => ({ ok: true, status: 200, json: async () => entries }));

    const result = await fetchPrompts(BASE_URL);

    expect(result[0].style_influence).toBe(85);
    expect(result[0].weirdness).toBe(30);
    expect(result[0].exclude_styles).toBe("hyperpop, edm");
  });

  it("Given 3 フィールド無し entry When fetch する Then 各 field は undefined（optional なので throw しない）", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "" }];
    mockFetch(() => ({ ok: true, status: 200, json: async () => entries }));

    const result = await fetchPrompts(BASE_URL);

    expect(result[0].style_influence).toBeUndefined();
    expect(result[0].weirdness).toBeUndefined();
    expect(result[0].exclude_styles).toBeUndefined();
  });

  it("Given フィールド有/無 混在配列 When fetch する Then 双方が PromptEntry[] として通る（後方互換）", async () => {
    // 型注釈 PromptEntry が advanced フィールドを optional で持つことのコンパイル時担保も兼ねる。
    const withAdvanced: PromptEntry = {
      name: "p1",
      style: "lofi",
      lyrics: "",
      style_influence: 85,
      weirdness: 30,
      exclude_styles: "hyperpop, edm",
    };
    const without: PromptEntry = { name: "p2", style: "ambient", lyrics: "" };
    mockFetch(() => ({ ok: true, status: 200, json: async () => [withAdvanced, without] }));

    const result = await fetchPrompts(BASE_URL);

    expect(result).toEqual([withAdvanced, without]);
    expect(result[0].style_influence).toBe(85);
    expect(result[1].style_influence).toBeUndefined();
  });

  it("Given weirdness=0 / style_influence=0 entry When fetch する Then 0 を保持する（falsy だが有効値）", async () => {
    const entries = [{ name: "p1", style: "lofi", lyrics: "", style_influence: 0, weirdness: 0 }];
    mockFetch(() => ({ ok: true, status: 200, json: async () => entries }));

    const result = await fetchPrompts(BASE_URL);

    expect(result[0].style_influence).toBe(0);
    expect(result[0].weirdness).toBe(0);
  });
});

describe("shared/api PromptResponse.duration_filter: collection 単位 duration guard 契約 (#1259)", () => {
  it("Given envelope JSON When fetchPromptResponse する Then entries と duration_filter を返す", async () => {
    const entries: PromptEntry[] = [{ name: "p1", style: "lofi", lyrics: "" }];
    const durationFilter: DurationFilter = { min_sec: 75, max_sec: 240 };
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ entries, duration_filter: durationFilter }),
    }));

    const result = await fetchPromptResponse(BASE_URL);

    expect(result.entries).toEqual(entries);
    expect(result.duration_filter).toEqual(durationFilter);
  });

  it("Given duration_filter 省略 When fetchPromptResponse する Then 既定値を補う", async () => {
    const entries: PromptEntry[] = [{ name: "p1", style: "lofi", lyrics: "" }];
    mockFetch(() => ({ ok: true, status: 200, json: async () => ({ entries }) }));

    const result = await fetchPromptResponse(BASE_URL);

    expect(result.duration_filter).toEqual(DEFAULT_DURATION_FILTER);
  });

  it("Given legacy 配列 JSON When fetchPromptResponse する Then entries に正規化して既定値を補う", async () => {
    const entries: PromptEntry[] = [{ name: "p1", style: "lofi", lyrics: "" }];
    mockFetch(() => ({ ok: true, status: 200, json: async () => entries }));

    const result = await fetchPromptResponse(BASE_URL);

    expect(result).toEqual({ entries, duration_filter: DEFAULT_DURATION_FILTER });
  });

  it("Given invalid duration_filter When fetchPromptResponse する Then fail-loud で throw する", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({
        entries: [{ name: "p1", style: "lofi", lyrics: "" }],
        duration_filter: { min_sec: 300, max_sec: 60 },
      }),
    }));

    await expect(fetchPromptResponse(BASE_URL)).rejects.toThrow(/min_sec/);
  });

  it("Given explicit/undefined filter When durationFilterOrDefault Then explicit または既定値を返す", () => {
    const explicit: DurationFilter = { min_sec: 90, max_sec: 180 };

    expect(durationFilterOrDefault(explicit)).toEqual(explicit);
    expect(durationFilterOrDefault()).toEqual(DEFAULT_DURATION_FILTER);
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
  {
    id: "20260601-clm-aaa-collection",
    name: "aaa-collection",
    status: "ready",
    pattern_count: 12,
    downloaded_count: 0,
  },
  {
    id: "20260602-clm-bbb-collection",
    name: "bbb-collection",
    status: "needs_prompts",
    pattern_count: null,
    downloaded_count: 0,
  },
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
      status: expect.any(String),
    });
  });

  it("Given 空配列 When fetch する Then throw せず [] を返す (fallback 判断は呼び出し側)", async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => [] }));

    await expect(fetchCollections(BASE_URL)).resolves.toEqual([]);
  });

  it("Given expected_file_count が null または非負整数 When fetch する Then 値を保持する", async () => {
    const rows = [
      { ...SAMPLE_COLLECTIONS[0], expected_file_count: null },
      { ...SAMPLE_COLLECTIONS[1], expected_file_count: 4 },
    ];
    mockFetch(() => ({ ok: true, status: 200, json: async () => rows }));

    await expect(fetchCollections(BASE_URL)).resolves.toEqual(rows);
  });

  it("Given suno_playlist_url がある When fetch する Then 値を保持する", async () => {
    const rows = [{ ...SAMPLE_COLLECTIONS[0], suno_playlist_url: "https://suno.com/playlist/saved" }];
    mockFetch(() => ({ ok: true, status: 200, json: async () => rows }));

    await expect(fetchCollections(BASE_URL)).resolves.toEqual(rows);
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

  it("Given invalid status When fetch する Then fail-loud に throw する", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => [{ ...SAMPLE_COLLECTIONS[0], status: "mapped" }],
    }));

    await expect(fetchCollections(BASE_URL)).rejects.toThrow(/status/);
  });

  it("Given downloaded_count 欠落 When fetch する Then fail-loud に throw する", async () => {
    const withoutDownloadedCount: Record<string, unknown> = { ...SAMPLE_COLLECTIONS[0] };
    delete withoutDownloadedCount.downloaded_count;
    mockFetch(() => ({ ok: true, status: 200, json: async () => [withoutDownloadedCount] }));

    await expect(fetchCollections(BASE_URL)).rejects.toThrow(/downloaded_count/);
  });

  it("Given pattern_count 型不正 When fetch する Then fail-loud に throw する", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => [{ ...SAMPLE_COLLECTIONS[0], pattern_count: "12" }],
    }));

    await expect(fetchCollections(BASE_URL)).rejects.toThrow(/pattern_count/);
  });

  it.each([["4"], [false], [-1]])(
    "Given expected_file_count=%s When fetch する Then fail-loud に throw する",
    async (expectedFileCount) => {
      mockFetch(() => ({
        ok: true,
        status: 200,
        json: async () => [{ ...SAMPLE_COLLECTIONS[0], expected_file_count: expectedFileCount }],
      }));

      await expect(fetchCollections(BASE_URL)).rejects.toThrow(/expected_file_count/);
    },
  );

  it("Given suno_playlist_url 型不正 When fetch する Then fail-loud に throw する", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => [{ ...SAMPLE_COLLECTIONS[0], suno_playlist_url: ["https://suno.com/playlist/saved"] }],
    }));

    await expect(fetchCollections(BASE_URL)).rejects.toThrow(/suno_playlist_url/);
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

  it("Given スペース入り id When fetch する Then id を path segment encode して要求する", async () => {
    const fetchFn = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => [{ name: "p1", style: "lofi", lyrics: "" }],
    }));

    await fetchCollectionPrompts(BASE_URL, "20260526-rainy jazz-collection");

    expect(fetchFn).toHaveBeenCalledWith(`${BASE_URL}/collections/20260526-rainy%20jazz-collection/suno/prompts.json`);
  });
});

describe("shared/api fetchCollectionPrompts: 正常系", () => {
  it("Given 配列 JSON When fetch する Then PromptEntry[] を返す", async () => {
    const entries = [{ name: "夜更けのカフェ", style: "lofi, jazzy", lyrics: "la la la" }];
    mockFetch(() => ({ ok: true, status: 200, json: async () => entries }));

    const result = await fetchCollectionPrompts(BASE_URL, "20260601-clm-aaa-collection");

    expect(result).toEqual(entries);
  });

  it("Given envelope JSON When fetchCollectionPromptResponse する Then duration_filter を保持する", async () => {
    const entries: PromptEntry[] = [{ name: "夜更けのカフェ", style: "lofi, jazzy", lyrics: "la la la" }];
    const durationFilter: DurationFilter = { min_sec: 90, max_sec: 260 };
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ entries, duration_filter: durationFilter }),
    }));

    const result = await fetchCollectionPromptResponse(BASE_URL, "20260601-clm-aaa-collection");

    expect(result).toEqual({ entries, duration_filter: durationFilter });
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
//   - 初期値は最初の ready entry の id (#1216)
//   - 全て needs_prompts/downloaded / 空配列 のときは null（選択不可）
// React テスト基盤を増やさず、選択ルールを純関数として担保する。
// ---------------------------------------------------------------------------

describe("shared/api visiblePromptCollections: popup 表示対象", () => {
  it("Given ready/needs_prompts/downloaded When 表示対象へ絞る Then downloaded だけ除外する", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "ready", pattern_count: 1, downloaded_count: 0 },
      { id: "c2", name: "c2", status: "needs_prompts", pattern_count: null, downloaded_count: 0 },
      { id: "c3", name: "c3", status: "downloaded", pattern_count: 2, downloaded_count: 4 },
    ];

    expect(visiblePromptCollections(collections).map((c) => c.id)).toEqual(["c1", "c2"]);
  });

  it("Given downloaded が resume 対象 When 表示対象へ絞る Then その collection だけ例外的に残す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "ready", pattern_count: 1, downloaded_count: 0 },
      { id: "c2", name: "c2", status: "downloaded", pattern_count: 2, downloaded_count: 4 },
      { id: "c3", name: "c3", status: "downloaded", pattern_count: 2, downloaded_count: 4 },
    ];

    expect(visiblePromptCollections(collections, ["c2"]).map((c) => c.id)).toEqual(["c1", "c2"]);
  });
});

describe("shared/api collectionHasPrompts: status ベースの prompts 判定", () => {
  it.each([
    ["ready", true],
    ["downloaded", true],
    ["needs_prompts", false],
  ] as const)("Given status=%s When 判定 Then %s を返す", (status, expected) => {
    expect(
      collectionHasPrompts({
        id: "c1",
        name: "c1",
        status,
        pattern_count: status === "needs_prompts" ? null : 1,
        downloaded_count: 0,
      }),
    ).toBe(expected);
  });
});

describe("shared/api pickInitialCollectionId: 初期選択ルール", () => {
  it("Given ready/downloaded When 初期値を選ぶ Then ready の id を返す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "ready", pattern_count: 1, downloaded_count: 0 },
      { id: "c2", name: "c2", status: "downloaded", pattern_count: 2, downloaded_count: 2 },
    ];

    expect(pickInitialCollectionId(collections)).toBe("c1");
  });

  it("Given 先頭が needs_prompts When 初期値を選ぶ Then 最初の ready id を返す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "needs_prompts", pattern_count: null, downloaded_count: 0 },
      { id: "c2", name: "c2", status: "ready", pattern_count: 2, downloaded_count: 0 },
    ];

    expect(pickInitialCollectionId(collections)).toBe("c2");
  });

  it("Given 全て needs_prompts/downloaded When 初期値を選ぶ Then null を返す (実行可能な選択肢なし)", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "needs_prompts", pattern_count: null, downloaded_count: 0 },
      { id: "c2", name: "c2", status: "downloaded", pattern_count: 2, downloaded_count: 4 },
    ];

    expect(pickInitialCollectionId(collections)).toBeNull();
  });

  it("Given 空配列 When 初期値を選ぶ Then null を返す", () => {
    expect(pickInitialCollectionId([])).toBeNull();
  });
});

describe("shared/api resolvePromptCollectionId: prompts 取得対象 collection の解決", () => {
  it("Given 選択中 id が最新一覧に存在し prompts あり When 解決 Then 選択中 id を返す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "ready", pattern_count: 1, downloaded_count: 0 },
      { id: "c2", name: "c2", status: "ready", pattern_count: 2, downloaded_count: 0 },
    ];

    expect(resolvePromptCollectionId(collections, "c2")).toBe("c2");
  });

  it("Given 選択中 id が最新一覧に無い When 解決 Then 初期選択 id を返す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "ready", pattern_count: 1, downloaded_count: 0 },
      { id: "c2", name: "c2", status: "ready", pattern_count: 2, downloaded_count: 0 },
    ];

    expect(resolvePromptCollectionId(collections, "old-url-c9")).toBe("c1");
  });

  it("Given 選択中 id が needs_prompts When 解決 Then 最初の ready id を返す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "needs_prompts", pattern_count: null, downloaded_count: 0 },
      { id: "c2", name: "c2", status: "ready", pattern_count: 2, downloaded_count: 0 },
    ];

    expect(resolvePromptCollectionId(collections, "c1")).toBe("c2");
  });

  it("Given 選択中 id が downloaded When 解決 Then 最初の ready id を返す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "downloaded", pattern_count: 1, downloaded_count: 2 },
      { id: "c2", name: "c2", status: "ready", pattern_count: 2, downloaded_count: 0 },
    ];

    expect(resolvePromptCollectionId(collections, "c1")).toBe("c2");
  });

  it("Given 選択中 id が downloaded かつ resume 対象 When 解決 Then 選択中 id を返す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "downloaded", pattern_count: 1, downloaded_count: 2 },
      { id: "c2", name: "c2", status: "ready", pattern_count: 2, downloaded_count: 0 },
    ];

    expect(resolvePromptCollectionId(collections, "c1", true)).toBe("c1");
  });

  it("Given prompts あり collection が無い When 解決 Then null を返す", () => {
    const collections: CollectionSummary[] = [
      { id: "c1", name: "c1", status: "needs_prompts", pattern_count: null, downloaded_count: 0 },
    ];

    expect(resolvePromptCollectionId(collections, "c1")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// /version compatibility (#1023): popup 初回 fetch 前に server / extension 互換を確認する。
//   - fetch 先は `${baseUrl}/version`（末尾 slash は正規化）
//   - 200 は `{version, min_extension_version}` の semver envelope
//   - 404 は旧サーバーとして skip（データ取得を妨げない）
//   - min_extension_version > extensionVersion は incompatible
// ---------------------------------------------------------------------------

describe("shared/api fetchServerVersion: 配信元 URL とレスポンス契約", () => {
  it("Given baseUrl When fetch する Then `/version` サブパスへ要求する", async () => {
    const fetchFn = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ version: "5.5.7", min_extension_version: "0.1.0" }),
    }));

    await fetchServerVersion(BASE_URL);

    expect(fetchFn).toHaveBeenCalledWith(VERSION_URL);
  });

  it("Given baseUrl 末尾 slash When fetch する Then 二重 slash を作らない", async () => {
    const fetchFn = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ version: "5.5.7", min_extension_version: "0.1.0" }),
    }));

    await fetchServerVersion(`${BASE_URL}/`);

    expect(fetchFn).toHaveBeenCalledWith(VERSION_URL);
  });

  it("Given semver envelope When fetch する Then ServerVersionInfo を返す", async () => {
    const payload = { version: "5.5.7", min_extension_version: "0.1.0" };
    mockFetch(() => ({ ok: true, status: 200, json: async () => payload }));

    await expect(fetchServerVersion(BASE_URL)).resolves.toEqual(payload);
  });

  it("Given response envelope の流用で min_extension_version が無い When fetch する Then throw する", async () => {
    mockFetch(() => ({ ok: true, status: 200, json: async () => ({ data: { version: "5.5.7" } }) }));

    await expect(fetchServerVersion(BASE_URL)).rejects.toThrow(/min_extension_version/);
  });
});

describe("shared/api checkServerCompatibility: semver 判定", () => {
  it("Given 拡張 version が最低要求と同じ When check Then compatible を返す", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ version: "5.5.7", min_extension_version: "0.1.0" }),
    }));

    await expect(checkServerCompatibility(BASE_URL, "0.1.0")).resolves.toEqual({
      status: "compatible",
      serverVersion: "5.5.7",
      minExtensionVersion: "0.1.0",
      extensionVersion: "0.1.0",
    });
  });

  it("Given 拡張 version が最低要求より新しい When check Then compatible を返す", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ version: "5.5.7", min_extension_version: "0.1.0" }),
    }));

    await expect(checkServerCompatibility(BASE_URL, "0.1.1")).resolves.toMatchObject({ status: "compatible" });
  });

  it("Given 拡張 version が最低要求より古い When check Then incompatible を返す", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ version: "5.5.7", min_extension_version: "0.2.0" }),
    }));

    await expect(checkServerCompatibility(BASE_URL, "0.1.9")).resolves.toEqual({
      status: "incompatible",
      serverVersion: "5.5.7",
      minExtensionVersion: "0.2.0",
      extensionVersion: "0.1.9",
    });
  });

  it("Given major が上がった拡張 version When check Then compatible を返す", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ version: "5.5.7", min_extension_version: "0.9.9" }),
    }));

    await expect(checkServerCompatibility(BASE_URL, "1.0.0")).resolves.toMatchObject({ status: "compatible" });
  });

  it("Given 旧サーバーが 404 を返す When check Then skipped を返してデータ取得を妨げない", async () => {
    mockFetch(() => ({ ok: false, status: 404, json: async () => ({}) }));

    await expect(checkServerCompatibility(BASE_URL, "0.1.0")).resolves.toEqual({
      status: "skipped",
      reason: "version-endpoint-unavailable",
    });
  });

  it("Given /version が 500 を返す When check Then error result を返して 404 skip と区別する", async () => {
    mockFetch(() => ({ ok: false, status: 500, json: async () => ({}) }));

    await expect(checkServerCompatibility(BASE_URL, "0.1.0")).resolves.toEqual({
      status: "error",
      message: "HTTP 500",
    });
  });
});

describe("shared/api formatCompatibilityWarning: popup 表示文", () => {
  it("Given incompatible result When format Then popup 用の更新警告文を返す", () => {
    const result = formatCompatibilityWarning({
      status: "incompatible",
      serverVersion: "5.5.7",
      minExtensionVersion: "0.2.0",
      extensionVersion: "0.1.9",
    });

    expect(result).toBe("拡張を更新してください（拡張 0.1.9 / 必要 0.2.0 / サーバー 5.5.7）。");
  });

  it("Given incompatible 以外の result When format Then バナーを表示しない空文字を返す", () => {
    expect(
      formatCompatibilityWarning({
        status: "compatible",
        serverVersion: "5.5.7",
        minExtensionVersion: "0.1.0",
        extensionVersion: "0.1.0",
      }),
    ).toBe("");
    expect(formatCompatibilityWarning({ status: "skipped", reason: "version-endpoint-unavailable" })).toBe("");
    expect(formatCompatibilityWarning({ status: "error", message: "HTTP 500" })).toBe("");
  });
});

describe("shared/api resolveCompatibilityWarning: popup warning state", () => {
  it("Given incompatible /version When resolve Then popup 用の更新警告文を返す", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ version: "5.5.7", min_extension_version: "0.2.0" }),
    }));

    await expect(resolveCompatibilityWarning(BASE_URL, "0.1.9")).resolves.toBe(
      "拡張を更新してください（拡張 0.1.9 / 必要 0.2.0 / サーバー 5.5.7）。",
    );
  });

  it("Given compatible /version When resolve Then バナーを表示しない空文字を返す", async () => {
    mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ version: "5.5.7", min_extension_version: "0.1.0" }),
    }));

    await expect(resolveCompatibilityWarning(BASE_URL, "0.1.0")).resolves.toBe("");
  });
});

// ---------------------------------------------------------------------------
// postDownloaded (#1215): POST /collections/:id/downloaded
//   - fetch 先は `${baseUrl}/collections/<id>/downloaded`（id は URL エンコード）
//   - HTTP 2xx で resolve
//   - HTTP 非 2xx で throw（fail-loud）
// ---------------------------------------------------------------------------

function mockFetchForDownloaded(postResponse: () => Partial<Response>) {
  const fn = vi.fn(async (url: string) => {
    if (typeof url === "string" && url.includes("/auth/token")) {
      return { ok: true, status: 200, json: async () => ({ token: "test-token" }) } as Response;
    }
    return postResponse() as Response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("shared/api postDownloaded: 正常系", () => {
  it("Given 200 応答 When postDownloaded Then resolve する", async () => {
    const fetchFn = mockFetchForDownloaded(() => ({ ok: true, status: 200, json: async () => ({}) }));

    await expect(
      postDownloaded(BASE_URL, "20260601-clm-aaa-collection", {
        file_count: 0,
        format: "mp3",
        suno_playlist_url: "https://suno.com/playlist/test",
      }),
    ).resolves.toBeUndefined();

    expect(fetchFn).toHaveBeenCalledTimes(2);
    expect(fetchFn).toHaveBeenCalledWith(
      `${BASE_URL}/collections/20260601-clm-aaa-collection/downloaded`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("Given download_path 付き payload When postDownloaded Then request body に download_path が含まれる", async () => {
    const fetchFn = mockFetchForDownloaded(() => ({ ok: true, status: 200, json: async () => ({}) }));

    await postDownloaded(BASE_URL, "20260601-clm-aaa-collection", {
      file_count: 0,
      expected_file_count: 5,
      format: "mp3",
      suno_playlist_url: "https://suno.com/playlist/test",
      download_path: "/Users/test/Downloads/test.zip",
    });

    const postCall = fetchFn.mock.calls.find(
      (c) => typeof c[0] === "string" && c[0].includes("/downloaded"),
    ) as unknown as [string, RequestInit];
    const body = JSON.parse(postCall[1].body as string);
    expect(body.download_path).toBe("/Users/test/Downloads/test.zip");
    expect(body.expected_file_count).toBe(5);
    expect(body.suno_playlist_url).toBe("https://suno.com/playlist/test");
  });

  it("Given download_path 付きで playlist URL が無い payload When postDownloaded Then fetch 前に throw する", async () => {
    const fetchFn = mockFetchForDownloaded(() => ({ ok: true, status: 200, json: async () => ({}) }));

    await expect(
      postDownloaded(BASE_URL, "20260601-clm-aaa-collection", {
        file_count: 5,
        expected_file_count: 5,
        format: "mp3",
        download_path: "/Users/test/Downloads/test.zip",
      }),
    ).rejects.toThrow(/suno_playlist_url/);

    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("Given file_count 正数で download_path が無い payload When postDownloaded Then fetch 前に throw する", async () => {
    const fetchFn = mockFetchForDownloaded(() => ({ ok: true, status: 200, json: async () => ({}) }));

    await expect(
      postDownloaded(BASE_URL, "20260601-clm-aaa-collection", {
        file_count: 5,
        format: "mp3",
        suno_playlist_url: "https://suno.com/playlist/test",
      }),
    ).rejects.toThrow(/download_path/);

    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("Given postDownloaded When ヘッダーを確認 Then X-Serve-Token が含まれる", async () => {
    const fetchFn = mockFetchForDownloaded(() => ({ ok: true, status: 200, json: async () => ({}) }));

    await postDownloaded(BASE_URL, "20260601-clm-aaa-collection", {
      file_count: 0,
      format: "mp3",
      suno_playlist_url: "https://suno.com/playlist/test",
    });

    const postCall = fetchFn.mock.calls.find(
      (c) => typeof c[0] === "string" && c[0].includes("/downloaded"),
    ) as unknown as [string, RequestInit];
    const headers = postCall[1].headers as Record<string, string>;
    expect(headers["X-Serve-Token"]).toBe("test-token");
  });

  it("Given baseUrl 末尾 slash When postDownloaded Then token と POST URL を正規化する", async () => {
    const fetchFn = mockFetchForDownloaded(() => ({ ok: true, status: 200, json: async () => ({}) }));

    await postDownloaded(`${BASE_URL}/`, "20260601-clm-aaa-collection", {
      file_count: 0,
      format: "mp3",
      suno_playlist_url: "https://suno.com/playlist/test",
    });

    expect(fetchFn).toHaveBeenCalledWith(`${BASE_URL}/auth/token`);
    expect(fetchFn).toHaveBeenCalledWith(
      `${BASE_URL}/collections/20260601-clm-aaa-collection/downloaded`,
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("shared/api postDownloaded: 異常系 (fail-loud)", () => {
  it("Given /auth/token が非 2xx When postDownloaded Then downloaded POST に進まず throw する", async () => {
    const fetchFn = vi.fn(async (url: string) => {
      if (typeof url === "string" && url.includes("/auth/token")) {
        return { ok: false, status: 403, statusText: "Forbidden", json: async () => ({}) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchFn);

    await expect(
      postDownloaded(BASE_URL, "20260601-clm-aaa-collection", {
        file_count: 0,
        format: "mp3",
        suno_playlist_url: "https://suno.com/playlist/test",
      }),
    ).rejects.toThrow(/GET \/auth\/token failed: 403/);

    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("Given /auth/token が invalid body When postDownloaded Then downloaded POST に進まず throw する", async () => {
    const fetchFn = vi.fn(async (url: string) => {
      if (typeof url === "string" && url.includes("/auth/token")) {
        return { ok: true, status: 200, json: async () => ({ token: "" }) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchFn);

    await expect(
      postDownloaded(BASE_URL, "20260601-clm-aaa-collection", {
        file_count: 0,
        format: "mp3",
        suno_playlist_url: "https://suno.com/playlist/test",
      }),
    ).rejects.toThrow(/invalid response/);

    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("Given HTTP 500 When postDownloaded Then ステータスを含めて throw する", async () => {
    mockFetchForDownloaded(() => ({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => ({}),
    }));

    await expect(
      postDownloaded(BASE_URL, "20260601-clm-aaa-collection", {
        file_count: 0,
        format: "mp3",
        suno_playlist_url: "https://suno.com/playlist/test",
      }),
    ).rejects.toThrow(/POST downloaded failed: 500/);
  });
});

describe("shared/api postDownloaded: 403 retry (#1217 ARCH-1217-002)", () => {
  it("Given 初回 POST が 403 When postDownloaded Then token を再取得してリトライし成功する", async () => {
    let postCallCount = 0;
    const fn = vi.fn(async (url: string) => {
      if (typeof url === "string" && url.includes("/auth/token")) {
        // 2 回目の token fetch は別のトークンを返す
        const callIndex = fn.mock.calls.filter(
          (c) => typeof c[0] === "string" && (c[0] as string).includes("/auth/token"),
        ).length;
        const token = callIndex <= 1 ? "stale-token" : "fresh-token";
        return { ok: true, status: 200, json: async () => ({ token }) } as Response;
      }
      // POST: 1 回目は 403, 2 回目は 200
      postCallCount++;
      if (postCallCount === 1) {
        return { ok: false, status: 403, statusText: "Forbidden", json: async () => ({}) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fn);

    await expect(
      postDownloaded(BASE_URL, "20260601-clm-aaa-collection", {
        file_count: 0,
        format: "mp3",
        suno_playlist_url: "https://suno.com/playlist/test",
      }),
    ).resolves.toBeUndefined();

    // token fetch 2 回 + POST 2 回 = 4 回
    expect(fn).toHaveBeenCalledTimes(4);
    // 2 回目の POST は fresh-token を使用
    const postCalls = fn.mock.calls.filter(
      (c) => typeof c[0] === "string" && (c[0] as string).includes("/downloaded"),
    ) as unknown as Array<[string, RequestInit]>;
    expect(postCalls).toHaveLength(2);
    const retryHeaders = postCalls[1][1].headers as Record<string, string>;
    expect(retryHeaders["X-Serve-Token"]).toBe("fresh-token");
  });
});

describe("shared/api postDownloaded: collectionId の URL エンコード", () => {
  it("Given 特殊文字を含む collectionId When postDownloaded Then URL エンコードされる", async () => {
    const fetchFn = mockFetchForDownloaded(() => ({ ok: true, status: 200, json: async () => ({}) }));

    await postDownloaded(BASE_URL, "coll with spaces/slash", {
      file_count: 0,
      format: "wav",
      suno_playlist_url: "https://suno.com/playlist/test",
    });

    expect(fetchFn).toHaveBeenCalledWith(
      `${BASE_URL}/collections/coll%20with%20spaces%2Fslash/downloaded`,
      expect.anything(),
    );
  });
});
