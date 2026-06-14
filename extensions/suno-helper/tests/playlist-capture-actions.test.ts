// overlay の手動 Playlist Capture（要件8）の Capture / Send orchestration の回帰テスト (#893)。
//
// 要件8「Capture → Send to localhost の 2 ボタンで完結、レスポンスの {written, path} を status に表示」の中核。
// @testing-library/react 未導入のため、PlaylistCaptureTab.tsx はレンダ層に徹し、capture/send の判断ロジックを
// lib/playlist-capture-actions の純関数へ切り出して検証する（resume-state の resumeRunRange と同方針）。
import { describe, expect, it, vi } from "vitest";

import { runCapture, runSend } from "../lib/playlist-capture-actions";
import type { CapturedPlaylist, CapturedPlaylistsResult } from "../../shared/api";

const ITEMS: CapturedPlaylist[] = [
  { title: "df365 | Deep Focus", url: "https://suno.com/playlist/u1" },
  { title: "df365 | Night Drive", url: "https://suno.com/playlist/u2" },
];

describe("runCapture: runner content の scrape 結果を status へ整形する", () => {
  it("Given capture 成功 (2 件) When runCapture Then items を載せ件数 status・非エラーを返す", async () => {
    const outcome = await runCapture(async () => ITEMS);

    expect(outcome.items).toEqual(ITEMS);
    expect(outcome.status).toBe("2 件の playlist を取得しました。");
    expect(outcome.isError).toBe(false);
  });

  it("Given capture 0 件 When runCapture Then items=[] を載せる（成功扱い・truthy 化に依存しない）", async () => {
    const outcome = await runCapture(async () => []);

    expect(outcome.items).toEqual([]);
    expect(outcome.status).toBe("0 件の playlist を取得しました。");
    expect(outcome.isError).toBe(false);
  });

  it("Given capture が throw（/me 以外で実行等）When runCapture Then items 未設定・エラー status を返す", async () => {
    const outcome = await runCapture(async () => Promise.reject(new Error("no content script")));

    expect(outcome.items).toBeUndefined();
    expect(outcome.isError).toBe(true);
    expect(outcome.status).toContain("取得失敗: no content script");
    expect(outcome.status).toContain("/me ページで実行してください。");
  });
});

describe("runSend: 捕捉済み items を POST し {written, path} を status へ整形する", () => {
  it("Given baseUrl・items あり・POST 成功 When runSend Then {written, path} を status に出す", async () => {
    const post = vi.fn<(baseUrl: string, items: CapturedPlaylist[]) => Promise<CapturedPlaylistsResult>>(async () => ({
      written: 2,
      path: "/root/config/suno-playlists.json",
    }));

    const outcome = await runSend("http://localhost:7873", ITEMS, post);

    expect(post).toHaveBeenCalledWith("http://localhost:7873", ITEMS);
    expect(outcome.isError).toBe(false);
    expect(outcome.status).toBe("2 件を書き込みました: /root/config/suno-playlists.json");
  });

  it("Given baseUrl 末尾空白付き When runSend Then trim した URL で POST する", async () => {
    const post = vi.fn<(baseUrl: string, items: CapturedPlaylist[]) => Promise<CapturedPlaylistsResult>>(async () => ({
      written: 2,
      path: "/p",
    }));

    await runSend("  http://localhost:7873  ", ITEMS, post);

    expect(post).toHaveBeenCalledWith("http://localhost:7873", ITEMS);
  });

  it("Given baseUrl 空 When runSend Then POST せず URL 入力を促すエラーを返す", async () => {
    const post = vi.fn();

    const outcome = await runSend("   ", ITEMS, post);

    expect(post).not.toHaveBeenCalled();
    expect(outcome.isError).toBe(true);
    expect(outcome.status).toBe("サーバー URL を入力してください。");
  });

  it("Given items 空 When runSend Then POST せず先に Capture を促すエラーを返す", async () => {
    const post = vi.fn();

    const outcome = await runSend("http://localhost:7873", [], post);

    expect(post).not.toHaveBeenCalled();
    expect(outcome.isError).toBe(true);
    expect(outcome.status).toBe("先に Capture してください。");
  });

  it("Given POST が 403 で throw When runSend Then ステータスを含むエラー status を返す", async () => {
    const post = vi.fn<(baseUrl: string, items: CapturedPlaylist[]) => Promise<CapturedPlaylistsResult>>(async () =>
      Promise.reject(new Error("HTTP 403")),
    );

    const outcome = await runSend("http://localhost:7873", ITEMS, post);

    expect(outcome.isError).toBe(true);
    expect(outcome.status).toContain("送信失敗: HTTP 403");
  });
});
