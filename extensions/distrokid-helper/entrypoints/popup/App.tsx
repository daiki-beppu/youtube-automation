import { useEffect, useState } from "react";
import { browser } from "wxt/browser";
import { fetchAsset, fetchRelease, ReleaseUnavailableError } from "@/lib/api";
import { onMessage, sendMessage, PHASES } from "@/lib/messaging";
import type { Phase } from "@/lib/messaging";
import { serverUrlItem } from "@/lib/storage";
import type { ReleasePayload } from "@/lib/types";
import { ServerUrlField } from "@/components/ServerUrlField";
import { ReleaseReview } from "@/components/ReleaseReview";
import { StatusBanner } from "@/components/StatusBanner";

// 無効チャンネル（distrokid.enabled=false / 未配置）時のガイダンス（要件 #16）。
const UNAVAILABLE_GUIDANCE =
  "このチャンネルでは distrokid 連携が無効です。config/channel/distrokid.json を enabled:true にして yt-collection-serve を再起動してください。";

export function App() {
  const [serverUrl, setServerUrl] = useState("");
  const [payload, setPayload] = useState<ReleasePayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<Phase | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    serverUrlItem.getValue().then(setServerUrl);
  }, []);

  useEffect(() => {
    const unwatch = onMessage("progress", ({ data }) => {
      setPhase(data.phase);
      setMessage(data.message);
      if (data.phase !== PHASES.INJECTING) {
        setBusy(false);
      }
    });
    return () => unwatch();
  }, []);

  const handleFetch = async () => {
    setBusy(true);
    setPhase(null);
    setMessage("");
    await serverUrlItem.setValue(serverUrl);
    try {
      setPayload(await fetchRelease(serverUrl));
    } catch (error) {
      setPayload(null);
      setPhase(PHASES.ERROR);
      setMessage(
        error instanceof ReleaseUnavailableError
          ? UNAVAILABLE_GUIDANCE
          : error instanceof Error
            ? error.message
            : String(error),
      );
    } finally {
      setBusy(false);
    }
  };

  const activeTabId = async (): Promise<number> => {
    const [tab] = await browser.tabs.query({
      active: true,
      currentWindow: true,
    });
    if (tab?.id === undefined) {
      throw new Error("アクティブなタブが見つかりません");
    }
    return tab.id;
  };

  const handleInject = async () => {
    if (payload === null) {
      return;
    }
    setBusy(true);
    setPhase(PHASES.INJECTING);
    setMessage("アセットを取得中");
    try {
      // asset は popup（chrome-extension:// origin）で fetch する。content からの
      // fetch はページ origin で CORS 評価され遮断されるため（asset-transfer.ts 参照）。
      const tabId = await activeTabId();
      const { release } = payload;
      const trackAsset =
        release.tracks.length > 0
          ? await fetchAsset(
              serverUrl,
              release.tracks[0].asset_path,
              release.tracks[0].filename,
            )
          : null;
      const coverAsset =
        release.cover !== null
          ? await fetchAsset(serverUrl, release.cover.asset_path, release.cover.filename)
          : null;
      setMessage("注入を開始します");
      await sendMessage("inject", { payload, trackAsset, coverAsset }, tabId);
    } catch (error) {
      setPhase(PHASES.ERROR);
      setMessage(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  };

  const handleStop = async () => {
    try {
      await sendMessage("stop", undefined, await activeTabId());
    } catch (error) {
      setPhase(PHASES.ERROR);
      setMessage(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  };

  return (
    <main className="flex flex-col gap-3 p-4">
      <h1 className="text-base font-bold text-gray-900">DistroKid Helper</h1>

      <ServerUrlField
        value={serverUrl}
        disabled={busy}
        onChange={setServerUrl}
        onFetch={handleFetch}
      />

      {payload !== null && <ReleaseReview payload={payload} />}

      <div className="flex gap-2">
        <button
          type="button"
          className="flex-1 rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          disabled={payload === null || busy}
          onClick={handleInject}
        >
          フォーム一括入力
        </button>
        <button
          type="button"
          className="rounded border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 disabled:opacity-50"
          disabled={!busy}
          onClick={handleStop}
        >
          停止
        </button>
      </div>

      <StatusBanner phase={phase} message={message} />
    </main>
  );
}
