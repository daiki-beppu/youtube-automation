// `lib/inject-runner.ts` の popup 側オーケストレーション契約テスト（#871）。
//
// per-track 逐次注入の送信順序と、停止 race 修正の本体（fetch 中に停止された場合に send
// しない境界）を、transport / fetch を fake にした InjectChannel で検証する。停止後に
// injectTrack / injectCover を送ると content の null セッションへ届き STOPPED を ERROR で
// 上書きするため、「停止後は send しない」が回帰検出の要点。

import { describe, it, expect } from "vitest";
import { runInjection, type InjectChannel } from "../lib/inject-runner";
import type { SerializedAsset } from "../lib/asset-transfer";
import type { ReleasePayload } from "../lib/types";

function makePayload(trackCount: number, withCover: boolean): ReleasePayload {
  return {
    profile: {
      language: "ja",
      main_genre: "Electronic",
      sub_genre: null,
      songwriter: null,
      ai_disclosure: {
        enabled: true,
        lyrics: false,
        composition: true,
        partial_audio_type: null,
      },
    },
    release: {
      album_title: "Vol.1",
      tracks: Array.from({ length: trackCount }, (_, i) => ({
        title: `Track ${i + 1}`,
        filename: `track-0${i + 1}.mp3`,
        asset_path: `/distrokid/assets/track-0${i + 1}.mp3`,
      })),
      cover: withCover
        ? { filename: "main.png", asset_path: "/distrokid/assets/main.png" }
        : null,
      release_date: "2026-07-01",
    },
  };
}

interface ChannelCall {
  kind: "start" | "track" | "cover" | "finish";
  trackIndex?: number;
  filename?: string;
}

// fake InjectChannel。送信を記録し、stopped フラグと「fetch 中に発火する hook」を
// テスト側から制御できるようにする（fetch 中の停止 race を再現するため）。
function makeChannel(options?: {
  onFetch?: (assetPath: string) => void;
}): {
  channel: InjectChannel;
  calls: ChannelCall[];
  fetched: string[];
  stop: () => void;
} {
  const calls: ChannelCall[] = [];
  const fetched: string[] = [];
  let stopped = false;
  const channel: InjectChannel = {
    fetchAsset: async (assetPath, filename): Promise<SerializedAsset> => {
      fetched.push(assetPath);
      options?.onFetch?.(assetPath);
      return { filename, mimeType: "audio/mpeg", base64: btoa("audio") };
    },
    start: async (payload) => {
      calls.push({ kind: "start", trackIndex: payload.release.tracks.length });
    },
    track: async (trackIndex, asset) => {
      calls.push({ kind: "track", trackIndex, filename: asset.filename });
    },
    cover: async (asset) => {
      calls.push({ kind: "cover", filename: asset.filename });
    },
    finish: async () => {
      calls.push({ kind: "finish" });
    },
    setMessage: () => {},
    isStopped: () => stopped,
  };
  return {
    channel,
    calls,
    fetched,
    stop: () => {
      stopped = true;
    },
  };
}

describe("runInjection", () => {
  it("start → track*N → cover → finish の順で送信する", async () => {
    // Given: 2 track + cover あり
    const { channel, calls } = makeChannel();

    // When
    await runInjection(makePayload(2, true), channel);

    // Then: 順序どおりに全メッセージが送られる
    expect(calls).toEqual([
      { kind: "start", trackIndex: 2 },
      { kind: "track", trackIndex: 0, filename: "track-01.mp3" },
      { kind: "track", trackIndex: 1, filename: "track-02.mp3" },
      { kind: "cover", filename: "main.png" },
      { kind: "finish" },
    ]);
  });

  it("cover が null なら cover を送らず finish に進む", async () => {
    // Given: cover なし
    const { channel, calls } = makeChannel();

    // When
    await runInjection(makePayload(1, false), channel);

    // Then: cover 呼び出しは存在しない
    expect(calls.some((c) => c.kind === "cover")).toBe(false);
    expect(calls.at(-1)).toEqual({ kind: "finish" });
  });

  it("track fetch 中に停止されたら、その track を送らず finish もしない（停止 race）", async () => {
    // Given: track-01 の fetch 中に停止が発火する
    const made = makeChannel({
      onFetch: (assetPath) => {
        if (assetPath.endsWith("track-01.mp3")) {
          made.stop();
        }
      },
    });

    // When
    await runInjection(makePayload(2, true), made.channel);

    // Then: start は済むが、停止後の track / cover / finish は一切送らない
    expect(made.calls).toEqual([{ kind: "start", trackIndex: 2 }]);
    expect(made.fetched).toEqual(["/distrokid/assets/track-01.mp3"]);
    expect(made.calls.some((c) => c.kind === "track")).toBe(false);
    expect(made.calls.some((c) => c.kind === "finish")).toBe(false);
  });

  it("cover fetch 中に停止されたら cover を送らず finish もしない（停止 race）", async () => {
    // Given: cover の fetch 中に停止が発火する
    const made = makeChannel({
      onFetch: (assetPath) => {
        if (assetPath.endsWith("main.png")) {
          made.stop();
        }
      },
    });

    // When
    await runInjection(makePayload(1, true), made.channel);

    // Then: track は完了するが cover / finish は送らない
    expect(made.calls.some((c) => c.kind === "cover")).toBe(false);
    expect(made.calls.some((c) => c.kind === "finish")).toBe(false);
    expect(made.calls.filter((c) => c.kind === "track")).toHaveLength(1);
  });

  it("ループ境界で停止済みなら track を fetch すらしない", async () => {
    // Given: start 直後（最初の track 処理前）に既に停止済み
    const made = makeChannel();
    made.stop();

    // When
    await runInjection(makePayload(3, true), made.channel);

    // Then: start のみで fetch も track 送信もしない
    expect(made.calls).toEqual([{ kind: "start", trackIndex: 3 }]);
    expect(made.fetched).toEqual([]);
  });
});
