// `lib/api.ts` の API client 契約テスト。
//
// サーバー契約（src/youtube_automation/scripts/distrokid_release.py より裏取り）:
//   - GET <baseUrl>/distrokid/release.json -> { profile, release } envelope
//   - GET <baseUrl><asset_path>            -> binary（asset_path は "/distrokid/assets/" 接頭辞込み）
//   - distrokid.enabled=false / 未配置のチャンネルは /distrokid/* が 404
//
// 設計契約（draft が実装する前提）:
//   - fetchRelease(baseUrl): 200 で ReleasePayload を返す。404 は ReleaseUnavailableError（要件 #16）。
//     その他の非 OK は汎用 Error。baseUrl 末尾スラッシュは正規化して二重スラッシュを作らない。
//   - fetchAsset(baseUrl, assetPath, filename): blob を取得し SerializedAsset
//     （filename / mimeType / base64）を返す。content へは直列化して転送する（CORS 回避）。

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { checkServerCompatibility, resolveCompatibilityWarning } from "../../shared/api";
import { fetchRelease, fetchCollectionRelease, fetchAsset, ReleaseUnavailableError } from "../lib/api";
import { decodeAsset } from "../lib/asset-transfer";
import type { ReleasePayload } from "../lib/types";

const SAMPLE_PAYLOAD: ReleasePayload = {
  profile: {
    artist: "Summer Artist",
    language: "en",
    main_genre: "Electronic",
    sub_genre: "House",
    songwriter: { first: "Jane", last: "Doe", middle: null },
    ai_disclosure: {
      enabled: true,
      lyrics: true,
      music: true,
      recording_scope: "full",
      partial_audio_type: null,
      artist_persona: true,
      apply_to_all: true,
    },
    credits: {
      performer_role: "Audio",
      producer_role: "Producer",
    },
  },
  release: {
    album_title: "Summer Vibes",
    tracks: [
      {
        title: "track-01",
        filename: "track-01.mp3",
        asset_path: "/distrokid/assets/track-01.mp3",
      },
    ],
    cover: { filename: "main.png", asset_path: "/distrokid/assets/main.png" },
    release_date: "2026-07-01",
  },
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function blobResponse(status: number, blob: Blob): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    blob: async () => blob,
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchRelease", () => {
  it("200 のとき release.json を ReleasePayload として返す", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(200, SAMPLE_PAYLOAD));

    // When
    const result = await fetchRelease("http://localhost:7873");

    // Then
    expect(result).toEqual(SAMPLE_PAYLOAD);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:7873/distrokid/release.json", expect.anything());
  });

  it("baseUrl 末尾スラッシュを正規化し二重スラッシュを作らない", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(200, SAMPLE_PAYLOAD));

    // When
    await fetchRelease("http://localhost:7873/");

    // Then
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:7873/distrokid/release.json", expect.anything());
  });

  it("旧 release.json で profile.artist が欠落していても空文字へ正規化する", async () => {
    // Given
    const legacyPayload = {
      ...SAMPLE_PAYLOAD,
      profile: { ...SAMPLE_PAYLOAD.profile, artist: undefined },
    };
    fetchMock.mockResolvedValue(jsonResponse(200, legacyPayload));

    // When
    const result = await fetchRelease("http://localhost:7873");

    // Then
    expect(result.profile.artist).toBe("");
  });

  it("404 のとき ReleaseUnavailableError を throw する（要件 #16: 無効チャンネルのガイダンス）", async () => {
    // Given: enabled=false / 未配置のチャンネルはサーバーが 404 を返す契約
    fetchMock.mockResolvedValue(jsonResponse(404, {}));

    // When / Then
    await expect(fetchRelease("http://localhost:7873")).rejects.toBeInstanceOf(ReleaseUnavailableError);
  });

  it("404 以外の非 OK では汎用 Error を throw する", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(500, {}));

    // When / Then: ReleaseUnavailableError ではなく汎用 Error
    const promise = fetchRelease("http://localhost:7873");
    await expect(promise).rejects.toThrow();
    await expect(promise).rejects.not.toBeInstanceOf(ReleaseUnavailableError);
  });
});

describe("fetchCollectionRelease", () => {
  it("dir mode の collection-scoped release.json を fetch する", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(200, SAMPLE_PAYLOAD));

    // When
    const result = await fetchCollectionRelease("http://localhost:7873", "20260526-sg-col", "disc1");

    // Then: collection-scoped パスへ要求する。
    expect(result).toEqual(SAMPLE_PAYLOAD);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:7873/collections/20260526-sg-col/distrokid/disc1/release.json",
      expect.anything(),
    );
  });

  it("スペース入り collection id を path segment encode して fetch する", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(200, SAMPLE_PAYLOAD));

    // When
    const result = await fetchCollectionRelease("http://localhost:7873", "20260526-rainy jazz-collection", "disc1");

    // Then
    expect(result).toEqual(SAMPLE_PAYLOAD);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:7873/collections/20260526-rainy%20jazz-collection/distrokid/disc1/release.json",
      expect.anything(),
    );
  });

  it("dir mode でも profile.artist 欠落 payload を空文字へ正規化する", async () => {
    // Given
    const legacyPayload = {
      ...SAMPLE_PAYLOAD,
      profile: { ...SAMPLE_PAYLOAD.profile, artist: undefined },
    };
    fetchMock.mockResolvedValue(jsonResponse(200, legacyPayload));

    // When
    const result = await fetchCollectionRelease("http://localhost:7873", "20260526-sg-col", "disc1");

    // Then
    expect(result.profile.artist).toBe("");
  });

  it("404 のとき ReleaseUnavailableError を throw する", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(404, {}));

    // When / Then
    await expect(fetchCollectionRelease("http://localhost:7873", "col-id", "disc1")).rejects.toBeInstanceOf(
      ReleaseUnavailableError,
    );
  });

  it("404 以外の非 OK では汎用 Error を throw する", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(500, {}));

    // When / Then
    const promise = fetchCollectionRelease("http://localhost:7873", "col-id", "disc1");
    await expect(promise).rejects.toThrow();
    await expect(promise).rejects.not.toBeInstanceOf(ReleaseUnavailableError);
  });
});

describe("fetchAsset", () => {
  it("asset を取得し filename / MIME 型 / base64 を持つ SerializedAsset を返す", async () => {
    // Given: audio/mpeg の blob を返すサーバー
    const blob = new Blob(["abc"], { type: "audio/mpeg" });
    fetchMock.mockResolvedValue(blobResponse(200, blob));

    // When
    const asset = await fetchAsset("http://localhost:7873", "/distrokid/assets/track-01.mp3", "track-01.mp3");

    // Then: 転送用に直列化されている（File ではなく base64）
    expect(asset.filename).toBe("track-01.mp3");
    expect(asset.mimeType).toBe("audio/mpeg");
    expect(asset.base64).toBe(btoa("abc"));

    // Then: content 側 decodeAsset で元バイト列の File に復元できる
    const file = decodeAsset(asset);
    expect(file).toBeInstanceOf(File);
    expect(file.name).toBe("track-01.mp3");
    expect(file.type).toBe("audio/mpeg");
    expect(file.size).toBe(3);
  });

  it("asset_path は接頭辞込みのため baseUrl と連結して fetch する", async () => {
    // Given
    const blob = new Blob(["x"], { type: "image/png" });
    fetchMock.mockResolvedValue(blobResponse(200, blob));

    // When
    await fetchAsset("http://localhost:7873/", "/distrokid/assets/main.png", "main.png");

    // Then: 末尾スラッシュ正規化 + asset_path 連結（二重スラッシュ無し）
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:7873/distrokid/assets/main.png", expect.anything());
  });

  it("非 OK では Error を throw する", async () => {
    // Given
    const blob = new Blob([""], { type: "application/octet-stream" });
    fetchMock.mockResolvedValue(blobResponse(404, blob));

    // When / Then
    await expect(fetchAsset("http://localhost:7873", "/distrokid/assets/missing.mp3", "missing.mp3")).rejects.toThrow();
  });
});

describe("shared compatibility API", () => {
  it("DistroKid helper から shared /version 互換チェックを呼び出せる", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(200, { version: "5.5.7", min_extension_version: "0.1.0" }));

    // When
    const result = await checkServerCompatibility("http://localhost:7873/", "0.1.0");

    // Then
    expect(result).toEqual({
      status: "compatible",
      serverVersion: "5.5.7",
      minExtensionVersion: "0.1.0",
      extensionVersion: "0.1.0",
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:7873/version");
  });

  it("DistroKid helper でも旧サーバーの /version 404 は skip として扱う", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(404, {}));

    // When / Then
    await expect(checkServerCompatibility("http://localhost:7873", "0.1.0")).resolves.toEqual({
      status: "skipped",
      reason: "version-endpoint-unavailable",
    });
  });

  it("DistroKid helper でも incompatible /version は popup 用の更新警告文に変換できる", async () => {
    // Given
    fetchMock.mockResolvedValue(jsonResponse(200, { version: "5.5.7", min_extension_version: "0.2.0" }));

    // When
    const result = await resolveCompatibilityWarning("http://localhost:7873", "0.1.9");

    // Then
    expect(result).toBe("拡張を更新してください（拡張 0.1.9 / 必要 0.2.0 / サーバー 5.5.7）。");
  });
});
