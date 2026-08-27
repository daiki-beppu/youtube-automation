// 64 MiB 超 asset を注入経路へ通す end-to-end 契約テスト（#4645）。
//
// 音源バイト列は 64MiB 上限のある境界を 3 回跨ぐ（background -> overlay の asset 応答、
// overlay -> background の injectTrack、background -> content の同一タブ relay）。
// 本テストは local-fetch（chunk 切り出し）-> background-fetch（Blob URL 組み立て）->
// inject-runner（Blob URL の relay）-> asset-transfer（File 復元）を実物のまま繋ぎ、
//
//   1. 送信される全メッセージの JSON 直列化サイズが上限未満であること
//   2. 往復後のバイト列が元 asset と完全一致すること
//   3. 生成した Blob URL が漏れなく revoke されること（復元より後に）
//
// を大きい素材で固定する。asset 本体を injectTrack へ巻き戻す退行（51.2 MiB の FLAC で
// 配信が全停止した元インシデント）や ASSET_CHUNK_SIZE の過大化はここで落ちる。

import { afterEach, describe, expect, it, vi } from "vitest";

import { blobUrlToFile } from "../lib/asset-transfer";
import { backgroundFetchAsset } from "../lib/background-fetch";
import { runInjection, type InjectChannel } from "../lib/inject-runner";
import { ASSET_CHUNK_SIZE } from "../lib/local-fetch";
import type { ReleasePayload } from "../lib/types";

// chrome の messaging 上限（"Message exceeded maximum allowed size of 64MiB."）。
const MESSAGE_LIMIT = 64 * 1024 * 1024;
// 上限を 1 byte 超える素材。base64 一括経路なら 1 メッセージが必ず上限を超える。
const HUGE_ASSET_SIZE = MESSAGE_LIMIT + 1;
// base64 は 3 byte -> 4 文字。1 chunk 応答の理論上限に metadata 分の余白を足す。
const CHUNK_MESSAGE_LIMIT = Math.ceil(ASSET_CHUNK_SIZE / 3) * 4 + 1024;
// Blob URL 参照だけを運ぶ注入メッセージの上限（asset 本体が混ざれば即座に超える）。
const REFERENCE_MESSAGE_LIMIT = 1024;
// track は chunk 分割され、cover（256 byte）は 1 chunk で収まる。
const TRACK_CHUNKS = Math.ceil(HUGE_ASSET_SIZE / ASSET_CHUNK_SIZE);
const EXPECTED_CHUNK_RESPONSES = TRACK_CHUNKS + 1;

const SERVER_URL = "http://localhost:7873";
const TRACK_PATH = "/distrokid/assets/track-01.flac";
const COVER_PATH = "/distrokid/assets/main.png";

interface WireMessage {
  type: string;
  bytes: number;
}

interface ChunkRequest {
  url: string;
  offset: number;
}

interface ServedAsset {
  bytes: Uint8Array;
  contentType: string;
}

interface AssetMessage {
  trackIndex?: number;
  asset: { filename: string; blobUrl: string };
}

interface BrowserBoundary {
  createdUrls: string[];
  revokedUrls: string[];
  liveUrls: Map<string, Blob>;
}

// overlay が跨ぐ全境界のメッセージを JSON 直列化サイズで記録する。
// vi.mock の factory は module import 時に走るため vi.hoisted に置く。
const wire = vi.hoisted(() => {
  const messages: WireMessage[] = [];
  return {
    messages,
    record(type: string, payload: unknown): void {
      const json = JSON.stringify(payload);
      messages.push({ type, bytes: new TextEncoder().encode(json).length });
    },
  };
});

// background service worker 境界。overlay の sendMessage を実 handler へ直結し、
// 往復する chunk メッセージの実サイズを測る。
vi.mock("../lib/messaging", () => ({
  sendMessage: async (type: string, request: ChunkRequest) => {
    const { fetchLocalAssetChunk } = await import("../lib/local-fetch");
    wire.record(type, request);
    const chunk = await fetchLocalAssetChunk(request);
    wire.record(`${type}:response`, chunk);
    return chunk;
  },
}));

// Chrome が提供する 2 つの境界（Blob URL の台帳と loopback fetch）を差し替える。
// URL は subclass で差し替え、`new URL()` の解釈（loopback 判定）は実物のまま保つ。
function installBrowserBoundary(
  assets: Map<string, ServedAsset>
): BrowserBoundary {
  const liveUrls = new Map<string, Blob>();
  const createdUrls: string[] = [];
  const revokedUrls: string[] = [];

  class StubURL extends URL {
    static override createObjectURL(object: Blob): string {
      const url = `blob:${SERVER_URL}/${createdUrls.length + 1}`;
      liveUrls.set(url, object);
      createdUrls.push(url);
      return url;
    }

    static override revokeObjectURL(url: string): void {
      liveUrls.delete(url);
      revokedUrls.push(url);
    }
  }
  vi.stubGlobal("URL", StubURL);

  vi.stubGlobal("fetch", async (input: string | URL | Request) => {
    const href = resolveHref(input);
    if (href.startsWith("blob:")) {
      const blob = liveUrls.get(href);
      // revoke 済み / 未登録なら content 側の復元失敗として顕在化させる。
      if (!blob) {
        throw new TypeError(`blob URL is not live: ${href}`);
      }
      return new Response(blob, { headers: { "Content-Type": blob.type } });
    }
    const asset = assets.get(new URL(href).pathname);
    if (!asset) {
      return new Response("not found", { status: 404 });
    }
    return new Response(asset.bytes, {
      status: 200,
      headers: { "Content-Type": asset.contentType },
    });
  });

  return { createdUrls, revokedUrls, liveUrls };
}

function resolveHref(input: string | URL | Request): string {
  if (typeof input === "string") {
    return input;
  }
  return input instanceof Request ? input.url : input.href;
}

function messagesAtLeast(messages: WireMessage[], limit: number) {
  return messages.filter((message) => message.bytes >= limit);
}

function isChunkResponse(message: WireMessage): boolean {
  return message.type === "fetchLocalAssetChunk:response";
}

function isAssetReference(message: WireMessage): boolean {
  return message.type === "injectTrack" || message.type === "injectCover";
}

// 0..255 全域を巡回させ、chunk 境界での byte 取りこぼし・ずれを検出可能にする。
function makeSource(size: number): Uint8Array {
  const bytes = new Uint8Array(size);
  for (let index = 0; index < size; index += 1) {
    bytes[index] = index % 256;
  }
  return bytes;
}

// 不一致の先頭 index を返す（一致なら -1）。64 MiB の差分表示を避け index で比べる。
function firstMismatch(actual: Uint8Array, expected: Uint8Array): number {
  if (actual.length !== expected.length) {
    return Math.min(actual.length, expected.length);
  }
  for (let index = 0; index < expected.length; index += 1) {
    if (actual[index] !== expected[index]) {
      return index;
    }
  }
  return -1;
}

function makePayload(): ReleasePayload {
  return {
    profile: {
      artist: "Test Artist",
      language: "ja",
      main_genre: "Electronic",
      sub_genre: null,
      songwriter: null,
      ai_disclosure: {
        enabled: true,
        lyrics: false,
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
      album_title: "Vol.79",
      tracks: [
        {
          title: "Track 1",
          filename: "track-01.flac",
          asset_path: TRACK_PATH,
        },
      ],
      cover: { filename: "main.png", asset_path: COVER_PATH },
      release_date: "2026-07-01",
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  wire.messages.length = 0;
});

describe("64MiB 超 asset の注入 end-to-end", () => {
  it("上限未満のメッセージだけで byte 列を往復させ revoke する", async () => {
    // Given: 上限を超える音源と小さいジャケットを配る loopback サーバー
    const track = makeSource(HUGE_ASSET_SIZE);
    const cover = makeSource(256);
    const assets = new Map<string, ServedAsset>([
      [TRACK_PATH, { bytes: track, contentType: "audio/flac" }],
      [COVER_PATH, { bytes: cover, contentType: "image/png" }],
    ]);
    const boundary = installBrowserBoundary(assets);
    const restored: { filename: string; bytes: Uint8Array }[] = [];
    // content 側の File 復元まで実物を通す。
    const receive = async (type: string, request: AssetMessage) => {
      wire.record(type, request);
      const { blobUrl, filename } = request.asset;
      const file = await blobUrlToFile(blobUrl, filename);
      const bytes = new Uint8Array(await file.arrayBuffer());
      restored.push({ filename: file.name, bytes });
    };
    // overlay の実 channel 配線（components/useDistrokidRunner.ts）と同型にする。
    const channel: InjectChannel = {
      fetchAsset: (assetPath, filename) =>
        backgroundFetchAsset(`${SERVER_URL}${assetPath}`, filename),
      start: async (payload) => {
        wire.record("injectStart", { payload });
      },
      track: (trackIndex, asset) =>
        receive("injectTrack", { trackIndex, asset }),
      cover: (asset) => receive("injectCover", { asset }),
      finish: async () => {
        wire.record("injectFinish", null);
      },
      setMessage: () => {},
      isStopped: () => false,
    };

    // When
    await runInjection(makePayload(), channel);

    // Then: asset は chunk 分割で運ばれ、どのメッセージも上限に届かない
    const chunkResponses = wire.messages.filter(isChunkResponse);
    expect(chunkResponses).toHaveLength(EXPECTED_CHUNK_RESPONSES);
    expect(messagesAtLeast(wire.messages, MESSAGE_LIMIT)).toEqual([]);
    expect(messagesAtLeast(wire.messages, CHUNK_MESSAGE_LIMIT)).toEqual([]);

    // Then: 注入メッセージは Blob URL 参照だけを運ぶ
    const references = wire.messages.filter(isAssetReference);
    expect(references).toHaveLength(2);
    expect(messagesAtLeast(references, REFERENCE_MESSAGE_LIMIT)).toEqual([]);

    // Then: content 側へ復元された byte 列が元 asset と一致する
    expect(restored.map((entry) => entry.filename)).toEqual([
      "track-01.flac",
      "main.png",
    ]);
    expect(firstMismatch(restored[0].bytes, track)).toBe(-1);
    expect(firstMismatch(restored[1].bytes, cover)).toBe(-1);

    // Then: 生成した Blob URL は復元後に漏れなく revoke される
    expect(boundary.createdUrls).toHaveLength(2);
    expect(boundary.revokedUrls).toEqual(boundary.createdUrls);
    expect(boundary.liveUrls.size).toBe(0);
  }, 180_000);
});
