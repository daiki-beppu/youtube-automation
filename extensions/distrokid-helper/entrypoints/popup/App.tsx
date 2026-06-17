import { useCallback, useEffect, useRef, useState } from "react";
import { browser } from "wxt/browser";
import { fetchAsset, fetchCollectionRelease, fetchRelease, ReleaseUnavailableError } from "@/lib/api";
import { onMessage, sendMessage, PHASES } from "@/lib/messaging";
import type { Phase } from "@/lib/messaging";
import { runInjection } from "@/lib/inject-runner";
import { serverUrlItem } from "@/lib/storage";
import type { ReleasePayload } from "@/lib/types";
import { ServerUrlField } from "@/components/ServerUrlField";
import { ReleaseReview } from "@/components/ReleaseReview";
import { StatusBanner } from "@/components/StatusBanner";
import {
  fetchDistrokidCollections,
  excludeReleasedDiscs,
  recordDistrokidRelease,
  resolveCompatibilityWarning,
  type DistrokidCollectionSummary,
  type DistrokidReleaseRecord,
} from "../../../shared/api";

// 無効チャンネル（distrokid.enabled=false / 未配置）時のガイダンス（要件 #16）。
const UNAVAILABLE_GUIDANCE =
  "このチャンネルでは distrokid 連携が無効です。config/channel/distrokid.json を enabled:true にして yt-collection-serve を再起動してください。";

export function App() {
  const [serverUrl, setServerUrl] = useState("");
  const [payload, setPayload] = useState<ReleasePayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<Phase | null>(null);
  const [message, setMessage] = useState("");
  const [compatibilityWarning, setCompatibilityWarning] = useState("");

  // dir mode 用コレクション一覧（#934）。空配列 = 単一 mode か 0 件。
  const [collections, setCollections] = useState<DistrokidCollectionSummary[]>([]);
  // 全 disc が配信済みで filter 後 0 件になった場合のフラグ（#934）。
  const [allReleased, setAllReleased] = useState(false);
  // 選択中 disc の index（collections 配列の index）。-1 = 未選択（単一 mode）。
  const [selectedIndex, setSelectedIndex] = useState(-1);

  // 停止要求フラグ。injection ループの境界で参照し、押下後は以降の送信を打ち切る。
  const stoppedRef = useRef(false);
  // dir mode 判定フラグ（fetchDistrokidCollections 成功時に true）。
  const isDirModeRef = useRef(false);
  // 現在の payload を取得した disc（#934）。配信済み記録はフィルした payload の
  // 取得元に束縛する — fetch 後に select を変えても誤った disc を記録しないため。
  const payloadSourceRef = useRef<DistrokidReleaseRecord | null>(null);

  // サーバー URL が確定したときに DistroKid collection 一覧を試行する (#934)。
  // 成功（dir mode）: released 除外済み一覧を state にセットし、その一覧を返す。
  // 失敗（404 等 = 単一 mode）: collections を空のままにして従来動作へ fallback。
  // setState は次レンダーまで反映されないため、同一ハンドラ内で一覧を使う caller は
  // 戻り値を直接参照する（stale closure 回避、#934）。
  const loadCollections = useCallback(async (baseUrl: string): Promise<DistrokidCollectionSummary[]> => {
    try {
      const fetched = await fetchDistrokidCollections(baseUrl);
      const list = excludeReleasedDiscs(fetched);
      setCollections(list);
      setAllReleased(fetched.length > 0 && list.length === 0);
      // 未配信 disc があれば先頭を初期選択する。
      setSelectedIndex(list.length > 0 ? 0 : -1);
      isDirModeRef.current = true;
      return list;
    } catch {
      // 単一ファイル mode サーバーは /distrokid/collections が 404。
      // ドロップダウンを出さず従来の単一 mode へ fallback する（後方互換）。
      setCollections([]);
      setAllReleased(false);
      setSelectedIndex(-1);
      isDirModeRef.current = false;
      return [];
    }
  }, []);

  useEffect(() => {
    // 永続化済みサーバー URL を復元し、URL があれば collection 一覧も試行する。
    serverUrlItem.getValue().then((stored) => {
      setServerUrl(stored);
      const trimmed = stored.trim();
      if (trimmed) {
        void loadCollections(trimmed);
      }
    });
  }, [loadCollections]);

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

  // データ取得ボタン。dir mode では選択中 disc の collection-scoped release.json を fetch し、
  // 単一 mode では従来の /distrokid/release.json を fetch する (#934)。
  const handleFetch = async () => {
    setBusy(true);
    setPhase(null);
    setMessage("");
    await serverUrlItem.setValue(serverUrl);
    const trimmedServerUrl = serverUrl.trim();
    const extensionVersion = browser.runtime.getManifest().version;
    setCompatibilityWarning(await resolveCompatibilityWarning(trimmedServerUrl, extensionVersion));

    // URL 変更時に collection 一覧を再取得する（blur 後の最初のデータ取得で最新化）。
    // state の collections/selectedIndex はこのレンダーの closure では古いままなので、
    // 戻り値の最新一覧を直接使う（stale closure 回避、#934）。
    const list = await loadCollections(trimmedServerUrl);

    try {
      let result: ReleasePayload;
      if (isDirModeRef.current) {
        if (list.length === 0) {
          // dir mode で未配信 disc が無い場合は単一 mode へ fallback しない
          // （dir mode サーバーに /distrokid/release.json は無く、誤った 404 ガイダンスになるため）。
          setPayload(null);
          setMessage("未配信の disc はありません。");
          return;
        }
        // 再取得後も同じ disc が残っていれば選択を維持し、消えていれば先頭にする。
        const prev = collections[selectedIndex];
        const keptIndex = prev
          ? list.findIndex((item) => item.collection_id === prev.collection_id && item.disc === prev.disc)
          : -1;
        const effectiveIndex = keptIndex >= 0 ? keptIndex : 0;
        setSelectedIndex(effectiveIndex);
        const selected = list[effectiveIndex];
        // 配信済み記録はこの payload の取得元 disc に束縛する（#934）。
        payloadSourceRef.current = {
          collection_id: selected.collection_id,
          disc: selected.disc,
          album_title: selected.album_title,
        };
        result = await fetchCollectionRelease(serverUrl, selected.collection_id, selected.disc);
      } else {
        // 単一 mode（後方互換）: 従来の /distrokid/release.json を取得する。
        payloadSourceRef.current = null;
        result = await fetchRelease(serverUrl);
      }
      setPayload(result);
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
    stoppedRef.current = false;
    setBusy(true);
    setPhase(PHASES.INJECTING);
    setMessage("注入を開始します");
    try {
      // asset は popup（chrome-extension:// origin）で fetch する。content からの fetch は
      // ページ origin で CORS 評価され遮断されるため（asset-transfer.ts 参照）。逐次実行・
      // 停止境界の制御フローは runInjection に抽出し、ここでは transport を束ねて渡す（#871）。
      const tabId = await activeTabId();
      await runInjection(payload, {
        fetchAsset: (assetPath, filename) => fetchAsset(serverUrl, assetPath, filename),
        start: (p) => sendMessage("injectStart", { payload: p }, tabId),
        track: (trackIndex, asset) => sendMessage("injectTrack", { trackIndex, asset }, tabId),
        cover: (asset) => sendMessage("injectCover", { asset }, tabId),
        finish: () => sendMessage("injectFinish", undefined, tabId),
        setMessage,
        isStopped: () => stoppedRef.current,
      });

      // フィル完了後、dir mode で payload を取得した disc のみ配信済み記録を POST する (#934)。
      // 現在の select 値ではなく payload 取得元（payloadSourceRef）に束縛する —
      // fetch 後に select を変えてもフィルされたのは取得済み payload の disc のため。
      // POST 失敗はフィル成功を覆さない（warning を添えるだけ）。
      const source = payloadSourceRef.current;
      if (isDirModeRef.current && source !== null) {
        try {
          await recordDistrokidRelease(serverUrl, source);
          // 配信済み記録成功後、一覧を再取得して select から消す (#934)。
          await loadCollections(serverUrl.trim());
        } catch (recordError) {
          // 配信記録失敗はフィル結果に影響しない補助機能のため warn 表示のみ (#934)。
          setMessage(
            `注入完了（配信済み記録に失敗しました: ${recordError instanceof Error ? recordError.message : String(recordError)}）`,
          );
        }
      }
    } catch (error) {
      setPhase(PHASES.ERROR);
      setMessage(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  };

  const handleStop = async () => {
    // ループ送信を打ち切り、content にも停止を通知する（content が STOPPED を report し busy 解除）。
    stoppedRef.current = true;
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

      <ServerUrlField value={serverUrl} disabled={busy} onChange={setServerUrl} onFetch={handleFetch} />

      {compatibilityWarning && (
        <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {compatibilityWarning}
        </div>
      )}

      {/* dir mode: 未配信 disc 一覧のドロップダウン (#934)。suno-helper App.tsx 55-69 行の構造を踏襲。 */}
      {collections.length > 0 && (
        <label className="flex flex-col gap-1 text-sm">
          コレクション
          <select
            value={selectedIndex}
            onChange={(e) => setSelectedIndex(Number(e.target.value))}
            className="rounded border border-gray-300 px-2 py-1"
          >
            {collections.map((item, idx) => (
              <option key={`${item.collection_id}/${item.disc}`} value={idx}>
                {`${item.name} / ${item.disc}（${item.album_title}・${item.track_count} 曲）`}
              </option>
            ))}
          </select>
        </label>
      )}

      {/* dir mode で全 disc が配信済みの場合（#934）。suno-helper の allMapped パターンを踏襲。 */}
      {allReleased && <p className="text-xs text-gray-600">未配信の disc はありません。</p>}

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
