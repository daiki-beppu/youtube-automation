import { describe, expect, it, vi } from "vitest";

import {
  installSunoContentScriptRecovery,
  isSunoPageUrl,
  recoverSunoContentScripts,
  type ContentScriptRecoveryDeps,
} from "../lib/content-script-recovery";

function createDeps(results: Array<Array<{ result?: unknown }>> = []) {
  let updatedListener: Parameters<ContentScriptRecoveryDeps["addTabUpdatedListener"]>[0] | undefined;
  const executeScript = vi.fn(async () => results.shift() ?? []);
  const sleep = vi.fn(() => Promise.resolve());
  const warn = vi.fn();
  const deps: ContentScriptRecoveryDeps = {
    addTabUpdatedListener: (listener) => {
      updatedListener = listener;
    },
    executeScript,
    sleep,
    warn,
  };
  return { deps, executeScript, sleep, warn, getUpdatedListener: () => updatedListener };
}

describe("isSunoPageUrl", () => {
  it.each(["https://suno.com/create", "https://www.suno.com/create?x=1"])("Suno URL を許可する: %s", (url) => {
    expect(isSunoPageUrl(url)).toBe(true);
  });

  it.each([undefined, "http://suno.com/create", "https://suno.com.evil.example/create", "not a url"])(
    "Suno 以外を拒否する: %s",
    (url) => {
      expect(isSunoPageUrl(url)).toBe(false);
    },
  );
});

describe("recoverSunoContentScripts", () => {
  it("overlay が存在すれば bundle を再注入しない", async () => {
    const { deps, executeScript } = createDeps([[{ result: true }]]);

    await expect(recoverSunoContentScripts(42, deps)).resolves.toBe(false);

    expect(executeScript).toHaveBeenCalledOnce();
    expect(executeScript).toHaveBeenCalledWith(
      expect.objectContaining({ target: { tabId: 42 }, func: expect.any(Function) }),
    );
  });

  it("overlay が無ければ MAIN bridge と ISOLATED bundles を再注入する", async () => {
    const { deps, executeScript, sleep } = createDeps([[{ result: false }], [{ result: false }], [], []]);

    await expect(recoverSunoContentScripts(42, deps)).resolves.toBe(true);

    expect(sleep).toHaveBeenCalledWith(1_000);
    expect(executeScript).toHaveBeenCalledTimes(4);
    expect(executeScript).toHaveBeenNthCalledWith(3, {
      target: { tabId: 42 },
      files: ["/content-scripts/suno-bridge.js"],
      world: "MAIN",
    });
    expect(executeScript).toHaveBeenNthCalledWith(4, {
      target: { tabId: 42 },
      files: ["/content-scripts/content.js", "/content-scripts/overlay.js"],
      world: "ISOLATED",
    });
  });

  it("初回 probe 後に静的 overlay が現れたら再注入しない", async () => {
    const { deps, executeScript, sleep } = createDeps([[{ result: false }], [{ result: true }]]);

    await expect(recoverSunoContentScripts(42, deps)).resolves.toBe(false);

    expect(sleep).toHaveBeenCalledWith(1_000);
    expect(executeScript).toHaveBeenCalledTimes(2);
    expect(executeScript).not.toHaveBeenCalledWith(expect.objectContaining({ files: expect.any(Array) }));
  });
});

describe("installSunoContentScriptRecovery", () => {
  it("Suno の complete 更新だけを復旧対象にする", async () => {
    const { deps, executeScript, getUpdatedListener } = createDeps([[{ result: true }]]);
    installSunoContentScriptRecovery(deps);
    const listener = getUpdatedListener();
    expect(listener).toBeTypeOf("function");

    listener!(1, { status: "loading" }, { url: "https://suno.com/create" });
    listener!(2, { status: "complete" }, { url: "https://example.com/" });
    listener!(3, { status: "complete" }, { url: "https://suno.com/create" });
    await vi.waitFor(() => expect(executeScript).toHaveBeenCalledOnce());
    expect(executeScript).toHaveBeenCalledWith(expect.objectContaining({ target: { tabId: 3 } }));
  });

  it("復旧失敗を未処理 rejection にせず warn する", async () => {
    const { deps, executeScript, warn, getUpdatedListener } = createDeps();
    executeScript.mockRejectedValueOnce(new Error("blocked"));
    installSunoContentScriptRecovery(deps);

    getUpdatedListener()!(3, { status: "complete" }, { url: "https://suno.com/create" });

    await vi.waitFor(() => expect(warn).toHaveBeenCalledOnce());
    expect(warn).toHaveBeenCalledWith("[suno-helper] content script の自己復旧に失敗しました", expect.any(Error));
  });
});
