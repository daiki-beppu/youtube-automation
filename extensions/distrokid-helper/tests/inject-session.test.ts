// `lib/inject-session.ts` の content 側 state machine 契約テスト（#871）。
//
// per-track 分割注入の順序保証（injectStart 先行）・範囲検査・進捗フェーズ報告を、
// DOM 非依存の fake Injector で検証する。実 DOM へのファイル注入は Playwright e2e が担う。

import { describe, it, expect, beforeEach } from "vitest";
import { InjectSession, type Injector, type Reporter } from "../lib/inject-session";
import { PHASES, type Phase } from "../lib/messaging";
import type { SerializedAsset } from "../lib/asset-transfer";
import type { ReleasePayload } from "../lib/types";

function makePayload(trackCount: number): ReleasePayload {
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
      album_title: "Vol.1",
      tracks: Array.from({ length: trackCount }, (_, i) => ({
        title: `Track ${i + 1}`,
        filename: `track-0${i + 1}.mp3`,
        asset_path: `/distrokid/assets/track-0${i + 1}.mp3`,
      })),
      cover: { filename: "main.png", asset_path: "/distrokid/assets/main.png" },
      release_date: "2026-07-01",
    },
  };
}

function makeAsset(filename: string): SerializedAsset {
  return { filename, mimeType: "audio/mpeg", base64: btoa("audio") };
}

interface InjectorCall {
  kind: "static" | "trackFile" | "cover" | "ai";
  trackIndex?: number;
  fileName?: string;
}

function makeInjector(): { injector: Injector; calls: InjectorCall[] } {
  const calls: InjectorCall[] = [];
  const injector: Injector = {
    injectStaticFields: async () => {
      calls.push({ kind: "static" });
    },
    injectTrackFile: (trackIndex, file) => calls.push({ kind: "trackFile", trackIndex, fileName: file.name }),
    injectCover: (file) => calls.push({ kind: "cover", fileName: file.name }),
    injectAiDisclosure: async () => {
      calls.push({ kind: "ai" });
    },
  };
  return { injector, calls };
}

describe("InjectSession", () => {
  let calls: InjectorCall[];
  let reports: { phase: Phase; message: string }[];
  let session: InjectSession;

  beforeEach(() => {
    const made = makeInjector();
    calls = made.calls;
    reports = [];
    const report: Reporter = (phase, message) => reports.push({ phase, message });
    session = new InjectSession(made.injector, report);
  });

  it("injectStart は静的フィールドを注入し INJECTING を報告する", async () => {
    // Given: 2 track の payload
    const payload = makePayload(2);

    // When: セッションを開始する（track 行生成待ちのため async）
    await session.start(payload);

    // Then: 静的フィールドが注入され INJECTING が報告される
    expect(calls).toEqual([{ kind: "static" }]);
    expect(reports[0].phase).toBe(PHASES.INJECTING);
  });

  it("injectStart 先行なしの track は順序違反として throw する", () => {
    // Given: 開始していないセッション
    // When / Then: track 注入は fail-loud
    expect(() => session.track(0, makeAsset("track-01.mp3"))).toThrow(/injectStart/);
    expect(calls).toEqual([]);
  });

  it("injectStart 先行なしの cover / finish も throw する", async () => {
    // Given: 開始していないセッション
    // When / Then（finish は async のため rejects で検証）
    expect(() => session.cover(makeAsset("main.png"))).toThrow(/injectStart/);
    await expect(session.finish()).rejects.toThrow(/injectStart/);
  });

  it("track は範囲内なら 0-indexed で曲ファイルを注入する", async () => {
    // Given: 2 track のセッション
    await session.start(makePayload(2));

    // When: index 1 の track を注入する
    session.track(1, makeAsset("track-02.mp3"));

    // Then: trackIndex=1 で File 名が渡り、filename 付き進捗が出る
    expect(calls).toContainEqual({
      kind: "trackFile",
      trackIndex: 1,
      fileName: "track-02.mp3",
    });
    expect(reports.at(-1)).toEqual({
      phase: PHASES.INJECTING,
      message: "曲ファイルを注入中: track-02.mp3",
    });
  });

  it("trackIndex が範囲外なら throw する", async () => {
    // Given: 2 track のセッション
    await session.start(makePayload(2));

    // When / Then: 範囲外 index は fail-loud
    expect(() => session.track(2, makeAsset("track-03.mp3"))).toThrow(/範囲外/);
    expect(() => session.track(-1, makeAsset("track-00.mp3"))).toThrow(/範囲外/);
  });

  it("cover はジャケット File を注入する", async () => {
    // Given
    await session.start(makePayload(1));

    // When
    session.cover(makeAsset("main.png"));

    // Then
    expect(calls).toContainEqual({ kind: "cover", fileName: "main.png" });
  });

  it("finish は AI 開示を注入し DONE を報告してセッションを終了する", async () => {
    // Given: 開始済みセッション
    await session.start(makePayload(1));

    // When: 完了する（AI 開示は modal フローのため async）
    await session.finish();

    // Then: AI 開示注入 + DONE 報告
    expect(calls.at(-1)).toEqual({ kind: "ai" });
    expect(reports.at(-1)).toEqual({
      phase: PHASES.DONE,
      message: "注入が完了しました。内容を確認して手動で続行してください",
    });

    // Then: セッションは終了済み（以降の track は順序違反）
    expect(() => session.track(0, makeAsset("track-01.mp3"))).toThrow(/injectStart/);
  });

  it("stop は STOPPED を報告してセッションを破棄する", async () => {
    // Given: 開始済みセッション
    await session.start(makePayload(1));

    // When: 停止する
    session.stop();

    // Then: STOPPED 報告 + 以降の asset 注入は順序違反
    expect(reports.at(-1)).toEqual({ phase: PHASES.STOPPED, message: "停止しました" });
    expect(() => session.track(0, makeAsset("track-01.mp3"))).toThrow(/injectStart/);
  });
});
