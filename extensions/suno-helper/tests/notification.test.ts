import { describe, expect, it, vi } from "vitest";

import { showSunoNotification } from "../lib/notification";

describe("showSunoNotification", () => {
  it("同梱 icon と silent basic template で通知する", async () => {
    const create = vi.fn(async () => "notification-id");
    const getUrl = vi.fn((path: string) => `chrome-extension://id${path}`);

    await showSunoNotification(
      { kind: "success", message: "3件の処理が完了しました。" },
      { create, getUrl }
    );

    expect(getUrl).toHaveBeenCalledWith("/icon/48.png");
    expect(create).toHaveBeenCalledWith({
      type: "basic",
      iconUrl: "chrome-extension://id/icon/48.png",
      title: "Suno Helper",
      message: "3件の処理が完了しました。",
      silent: true,
    });
  });

  it("通知 API の失敗を呼び出し元へ返して警告可能にする", async () => {
    const error = new Error("notifications unavailable");
    await expect(
      showSunoNotification(
        { kind: "error", message: "中断: failed" },
        {
          create: vi.fn(async () => Promise.reject(error)),
          getUrl: vi.fn(() => "icon.png"),
        }
      )
    ).rejects.toBe(error);
  });
});
