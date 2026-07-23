// Manifest V3 service worker。
// 拡張ライフサイクルのログ、action クリック中継、および overlay ⇄ runner の content↔content 中継を担う。
// overlay (content script) は `browser.tabs.*` を呼べないため、overlay の no-tabId メッセージを受けて
// 送信元と同一タブの runner content へ tabs.sendMessage で転送する（#892, 詳細は lib/overlay-relay.ts）。
import {
  consumeUnattendedRequest,
  fetchCollectionPromptResponse,
  fetchCollectionPrompts,
  fetchCollections,
  fetchServerInfo,
  postDownloaded,
  resolveCompatibilityWarning,
} from "../../shared/api";
import { discoverServerSources } from "../../shared/server-discovery";
import { describeRelayFailure } from "../components/runner-errors";
import { installSunoContentScriptRecovery } from "../lib/content-script-recovery";
import { installDownloadWatcher } from "../lib/download-watcher";
import { onMessage, sendMessage } from "../lib/messaging";
import { showSunoNotification } from "../lib/notification";
import { relayTabId, requireRelayTab } from "../lib/overlay-relay";
import { migrateServerSourcesStorage } from "../lib/storage";
import { sendTrustedCmdP } from "../lib/trusted-shortcut";
import {
  acquireUnattendedLease,
  releaseUnattendedLease,
  renewUnattendedLease,
  type UnattendedLease,
} from "../lib/unattended-lease";

export default defineBackground(() => {
  const extensionOrigin = browser.runtime.getURL("").replace(/\/+$/, "");
  const leaseStorageKey = "sunoUnattendedLeases";
  let leaseMutation: Promise<unknown> = Promise.resolve();
  const mutateLeases = <T>(
    mutation: (leases: Record<string, UnattendedLease>) => Promise<T> | T
  ): Promise<T> => {
    const next = leaseMutation.then(async () => {
      const stored = await browser.storage.session.get(leaseStorageKey);
      const leases = (stored[leaseStorageKey] ?? {}) as Record<
        string,
        UnattendedLease
      >;
      return mutation(leases);
    });
    leaseMutation = next.catch(() => undefined);
    return next;
  };
  const downloadWatcher = installDownloadWatcher({ sendMessage });

  installSunoContentScriptRecovery({
    addTabUpdatedListener: (listener) =>
      browser.tabs.onUpdated.addListener(listener),
    addInstalledListener: (listener) =>
      browser.runtime.onInstalled.addListener(listener),
    queryTabs: () => browser.tabs.query({}),
    reloadTab: (tabId) => browser.tabs.reload(tabId),
    executeScript: (details) => {
      if (details.files) {
        return chrome.scripting.executeScript({
          target: details.target,
          files: details.files.map((path) => path.replace(/^\//, "")),
          world: details.world,
        });
      }
      if (details.func) {
        return chrome.scripting.executeScript({
          target: details.target,
          func: details.func,
        });
      }
      return Promise.reject(new Error("executeScript requires files or func"));
    },
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    warn: (message, error) => console.warn(message, error),
  });

  browser.runtime.onInstalled.addListener((details) => {
    console.info(`[suno-helper] installed/updated: ${details.reason}`);
    void migrateServerSourcesStorage().catch((error: unknown) => {
      console.error(
        "[suno-helper] legacy server source migration failed:",
        error
      );
    });
  });

  onMessage("extensionVersionHandshake", ({ data, sender }) => {
    requireRelayTab(sender, "extensionVersionHandshake");
    const version = browser.runtime.getManifest().version;
    return { version, matches: data.version === version };
  });

  onMessage("showSunoNotification", async ({ data, sender }) => {
    requireRelayTab(sender, "showSunoNotification");
    await showSunoNotification(data);
  });

  // popup 廃止 (#892): default_popup を持たないため action クリックで onClicked が発火する。
  // クリックされたタブの overlay content script へ表示 toggle を中継する。
  browser.action.onClicked.addListener((tab) => {
    if (typeof tab.id !== "number") {
      // タブ id が取れないケース（特殊ページ等）は overlay も注入されていないため中継しない。
      return;
    }
    // overlay 未注入のタブ（suno.com 以外 / 拡張リロード後の stale タブ）では必ず reject するため
    // catch して消費する。放置すると未処理 rejection としてエラーバッジに記録される（#937）。
    sendMessage("toggleOverlay", undefined, tab.id).catch((err: unknown) => {
      const { level, text } = describeRelayFailure(
        "toggleOverlay",
        err instanceof Error ? err.message : String(err)
      );
      console[level](text);
    });
  });

  // overlay → runner 中継 (#892)。overlay が送る run / stop / queryProgress を送信元と同一タブの
  // runner content へ転送し、runner の応答をそのまま overlay へ返す。tab を持たない送信元は中継不能
  // のため requireRelayTab が fail-loud で throw する（握りつぶさない）。
  onMessage("run", ({ data, sender }) =>
    sendMessage("run", data, requireRelayTab(sender, "run"))
  );
  onMessage("stop", ({ sender }) =>
    sendMessage("stop", undefined, requireRelayTab(sender, "stop"))
  );
  onMessage("retryPlaylist", ({ data, sender }) =>
    sendMessage("retryPlaylist", data, requireRelayTab(sender, "retryPlaylist"))
  );
  onMessage("retryDownload", ({ data, sender }) =>
    sendMessage("retryDownload", data, requireRelayTab(sender, "retryDownload"))
  );
  onMessage("adoptSelectedClips", ({ data, sender }) =>
    sendMessage(
      "adoptSelectedClips",
      data,
      requireRelayTab(sender, "adoptSelectedClips")
    )
  );
  onMessage("queryProgress", ({ sender }) =>
    sendMessage(
      "queryProgress",
      undefined,
      requireRelayTab(sender, "queryProgress")
    )
  );
  onMessage("queryUnattendedState", ({ sender }) =>
    sendMessage(
      "queryUnattendedState",
      undefined,
      requireRelayTab(sender, "queryUnattendedState")
    )
  );
  onMessage("startDownload", async ({ data, sender }) => {
    const tabId = relayTabId(sender);
    if (tabId === null) {
      console.warn("[suno-helper] startDownload: 送信元タブが特定できません");
      return {
        ok: false,
        message: "startDownload: 送信元タブが特定できません",
      } as const;
    }
    return downloadWatcher.start(tabId, data.format);
  });

  onMessage("cancelDownload", async ({ sender }) => {
    await downloadWatcher.cancelForTab(
      requireRelayTab(sender, "cancelDownload")
    );
  });

  // content → background: chrome.debugger で trusted Cmd+P を dispatch する (#1251)。
  // content script は chrome.debugger API にアクセスできないため background に委譲する。
  // attach → rawKeyDown + keyUp → detach を一瞬で行い、デバッグバーの表示時間を最小化する。
  onMessage("sendTrustedCmdP", async ({ data, sender }) => {
    const tabId = relayTabId(sender);
    if (tabId === null) {
      throw new Error("sendTrustedCmdP: 送信元タブが特定できません");
    }
    await sendTrustedCmdP(tabId, data.isMac);
  });

  onMessage("fetchCompatibilityWarning", ({ data, sender }) => {
    requireRelayTab(sender, "fetchCompatibilityWarning");
    return resolveCompatibilityWarning(data.baseUrl, data.extensionVersion);
  });

  onMessage("discoverServerSources", ({ sender }) => {
    requireRelayTab(sender, "discoverServerSources");
    return discoverServerSources();
  });

  onMessage("fetchServerInfo", ({ data, sender }) => {
    requireRelayTab(sender, "fetchServerInfo");
    return fetchServerInfo(data.baseUrl);
  });

  onMessage("fetchCollections", ({ data, sender }) => {
    requireRelayTab(sender, "fetchCollections");
    return fetchCollections(data.baseUrl);
  });

  onMessage("fetchCollectionPrompts", ({ data, sender }) => {
    requireRelayTab(sender, "fetchCollectionPrompts");
    if (
      typeof data.collectionId !== "string" ||
      data.collectionId.length === 0
    ) {
      throw new Error(
        "fetchCollectionPrompts.collectionId must be non-empty string"
      );
    }
    return fetchCollectionPrompts(data.baseUrl, data.collectionId);
  });

  onMessage("fetchCollectionPromptResponse", ({ data, sender }) => {
    requireRelayTab(sender, "fetchCollectionPromptResponse");
    if (
      typeof data.collectionId !== "string" ||
      data.collectionId.length === 0
    ) {
      throw new Error(
        "fetchCollectionPromptResponse.collectionId must be non-empty string"
      );
    }
    return fetchCollectionPromptResponse(data.baseUrl, data.collectionId);
  });

  // runner → background: content script から localhost server へ直接 token 取得しないよう、
  // token fetch と POST /downloaded は background の extension origin から実行する。
  onMessage("postDownloaded", async ({ data, sender }) => {
    requireRelayTab(sender, "postDownloaded");
    return await postDownloaded(data.baseUrl, data.collectionId, data.body, {
      extensionOrigin,
    });
  });

  onMessage("consumeUnattendedRequest", async ({ data, sender }) => {
    requireRelayTab(sender, "consumeUnattendedRequest");
    return await consumeUnattendedRequest(data.baseUrl, data.nonce, {
      extensionOrigin,
    });
  });

  onMessage("acquireUnattendedLease", ({ data, sender }) => {
    const tabId = requireRelayTab(sender, "acquireUnattendedLease");
    return mutateLeases(async (leases) => {
      const result = acquireUnattendedLease(
        leases,
        { ...data, tabId },
        Date.now(),
        crypto.randomUUID()
      );
      if (result.acquired) {
        await browser.storage.session.set({ [leaseStorageKey]: result.leases });
      }
      return { acquired: result.acquired, token: result.lease?.token };
    });
  });

  onMessage("heartbeatUnattendedLease", ({ data, sender }) => {
    requireRelayTab(sender, "heartbeatUnattendedLease");
    return mutateLeases(async (leases) => {
      const next = renewUnattendedLease(
        leases,
        data.collectionId,
        data.token,
        Date.now()
      );
      if (next !== leases)
        await browser.storage.session.set({ [leaseStorageKey]: next });
    });
  });

  onMessage("releaseUnattendedLease", ({ data, sender }) => {
    requireRelayTab(sender, "releaseUnattendedLease");
    return mutateLeases(async (leases) => {
      const next = releaseUnattendedLease(
        leases,
        data.collectionId,
        data.token
      );
      if (next !== leases)
        await browser.storage.session.set({ [leaseStorageKey]: next });
    });
  });

  // runner → overlay 中継 (#892)。runner content が emit する progress 通知を送信元と同一タブへ転送する
  // （content↔content 直送不可のため）。tab を持たない送信元は転送先が無いため no-op。
  onMessage("progress", ({ data, sender }) => {
    const tabId = relayTabId(sender);
    if (tabId === null) {
      return;
    }
    // ページ遷移・タブ閉鎖のレースで overlay 側リスナーが消えていると reject する。progress は
    // 高頻度かつ取りこぼしても次の通知で追いつくため、debug ログのみ残して握りつぶす（#937）。
    sendMessage("progress", data, tabId).catch((err: unknown) => {
      console.debug(
        "[suno-helper] progress 中継先なし（overlay 消滅レース）:",
        err
      );
    });
  });
});
