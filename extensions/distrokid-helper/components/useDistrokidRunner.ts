// popup の実行制御フック（#1361）。App.tsx から fetch / collection 選択 / injection / stop /
// released record の状態と制御フローを分離し、suno-helper の useSunoRunner と同じ
// helper extension shell 構成に揃える（ADR-0016）。UI は popup のまま維持し、
// 「注入後にユーザーが目視確認して手動で続行する」安全境界は変えない。
import { useCallback, useEffect, useRef, useState } from "react";
import { browser } from "wxt/browser";

import {
  fetchAsset,
  fetchCollectionRelease,
  fetchRelease,
  ReleaseUnavailableError,
} from "@/lib/api";
import { runInjection } from "@/lib/inject-runner";
import { onMessage, sendMessage, PHASES } from "@/lib/messaging";
import type { Phase } from "@/lib/messaging";
import { migrateServerSourcesStorage, serverUrlItem } from "@/lib/storage";
import type { ReleasePayload } from "@/lib/types";

import {
  excludeReleasedDiscs,
  fetchDistrokidCollections,
  fetchServerInfo,
  resolveCompatibilityWarning,
  type DistrokidCollectionSummary,
  type DistrokidReleaseRecord,
} from "../../shared/api";
import type { LocalServerSource } from "../../shared/constants";
import { discoverServerSources } from "../../shared/server-discovery";

// 無効チャンネル（distrokid.enabled=false / 未配置）時のガイダンス（要件 #16）。
const UNAVAILABLE_GUIDANCE =
  "このチャンネルでは distrokid 連携が無効です。config/channel/distrokid.json を enabled:true にして yt-collection-serve を再起動してください。";

// popup 表示 component へ渡す runner state と実行制御。
export interface DistrokidRunnerState {
  serverUrl: string;
  setServerUrl: (url: string) => void;
  serverSources: LocalServerSource[];
  refreshServerSources: () => Promise<void>;
  payload: ReleasePayload | null;
  busy: boolean;
  isInjecting: boolean;
  phase: Phase | null;
  message: string;
  compatibilityWarning: string;
  // dir mode 用コレクション一覧（#934）。空配列 = 単一 mode か 0 件。
  collections: DistrokidCollectionSummary[];
  // 全 disc が配信済みで filter 後 0 件になった場合のフラグ（#934）。
  allReleased: boolean;
  // 選択中 disc の index（collections 配列の index）。-1 = 未選択（単一 mode）。
  selectedIndex: number;
  selectCollection: (index: number) => void;
  inject: () => Promise<void>;
  stop: () => Promise<void>;
}

type DiscIdentity = Pick<DistrokidCollectionSummary, "collection_id" | "disc">;

interface CollectionLoadResult {
  list: DistrokidCollectionSummary[];
  isDirMode: boolean;
}

async function activeTabId(): Promise<number> {
  const [tab] = await browser.tabs.query({
    active: true,
    currentWindow: true,
  });
  if (tab?.id === undefined) {
    throw new Error("アクティブなタブが見つかりません");
  }
  return tab.id;
}

export function useDistrokidRunner(): DistrokidRunnerState {
  const [serverUrl, setServerUrl] = useState("");
  const serverUrlRef = useRef(serverUrl);
  const [serverSources, setServerSources] = useState<LocalServerSource[]>([]);
  const [payload, setPayload] = useState<ReleasePayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [isInjecting, setIsInjecting] = useState(false);
  const [phase, setPhase] = useState<Phase | null>(null);
  const [message, setMessage] = useState("");
  const [compatibilityWarning, setCompatibilityWarning] = useState("");

  const [collections, setCollections] = useState<DistrokidCollectionSummary[]>(
    []
  );
  const [allReleased, setAllReleased] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);

  // 停止要求フラグ。injection ループの境界で参照し、押下後は以降の送信を打ち切る。
  const stoppedRef = useRef(false);
  // 注入中は取得操作を受け付けない。busy は fetch と注入で共有されるため、selector と
  // 停止ボタンの制御には使わない。
  const injectionActiveRef = useRef(false);
  // dir mode 判定フラグ（fetchDistrokidCollections 成功時に true）。
  const isDirModeRef = useRef(false);
  // 現在の payload を取得した disc（#934）。配信済み記録はフィルした payload の
  // 取得元に束縛する — fetch 後に select を変えても誤った disc を記録しないため。
  const payloadSourceRef = useRef<DistrokidReleaseRecord | null>(null);
  // 自動取得は選択操作が連続しても最後の要求だけを state へ反映する。
  const fetchRequestIdRef = useRef(0);
  const serverSourcePersistenceRef = useRef<Promise<void>>(Promise.resolve());
  // URL 永続化を直列化し、遅い旧 write の後に必ず最新 write が完了するようにする。
  // 古い discovery 応答が新しい候補一覧を上書きしないための revision。
  const serverSourcesRevisionRef = useRef(0);
  // ユーザー選択後に遅い初期 URL 読込が開始されないようにする。
  const initialFetchStartedRef = useRef(false);
  const initializationRef = useRef<Promise<void> | null>(null);

  // サーバー URL が確定したときに DistroKid collection 一覧を試行する (#934)。
  // 成功（dir mode）: released 除外済み一覧を state にセットし、その一覧を返す。
  // 404（単一 mode）: collections を空のままにして従来動作へ fallback。
  // 通信障害・不正応答: 既存の一覧と選択を保持したまま caller へ失敗を伝える。
  // setState は次レンダーまで反映されないため、同一ハンドラ内で一覧を使う caller は
  // 戻り値を直接参照する（stale closure 回避、#934）。
  const loadCollections = useCallback(
    async (
      baseUrl: string,
      shouldApply: () => boolean = () => true
    ): Promise<CollectionLoadResult | null> => {
      try {
        const fetched = await fetchDistrokidCollections(baseUrl);
        if (!shouldApply()) {
          return null;
        }
        const list = excludeReleasedDiscs(fetched);
        setCollections(list);
        setAllReleased(fetched.length > 0 && list.length === 0);
        // 未配信 disc があれば先頭を初期選択する。
        setSelectedIndex(list.length > 0 ? 0 : -1);
        isDirModeRef.current = true;
        return { list, isDirMode: true };
      } catch (error) {
        if (!shouldApply()) {
          return null;
        }
        if (!(error instanceof Error && error.message === "HTTP 404")) {
          throw error;
        }
        // 単一ファイル mode サーバーは /distrokid/collections が 404。
        // ドロップダウンを出さず従来の単一 mode へ fallback する（後方互換）。
        setCollections([]);
        setAllReleased(false);
        setSelectedIndex(-1);
        isDirModeRef.current = false;
        return { list: [], isDirMode: false };
      }
    },
    []
  );

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

  // 対象 URL と優先 disc をイベント時点の値で受け取り、一覧最新化から release 取得まで行う。
  // 各 await 後に request ID を検査し、古い応答が最新の state を上書きするのを防ぐ。
  const fetchData = useCallback(
    async (targetUrl: string, preferredDisc: DiscIdentity | null) => {
      const requestId = ++fetchRequestIdRef.current;
      const isLatestRequest = (): boolean =>
        requestId === fetchRequestIdRef.current;
      let baseUrl = targetUrl.trim();
      if (!baseUrl) {
        return;
      }

      setBusy(true);
      setPhase(null);
      setMessage("");
      setPayload(null);
      payloadSourceRef.current = null;

      try {
        const info = await fetchServerInfo(baseUrl);
        if (!isLatestRequest()) {
          return;
        }
        baseUrl = info.base_url;
        serverUrlRef.current = baseUrl;
        setServerUrl(baseUrl);
      } catch {
        // /server-info 非対応の旧サーバーは選択 URL のまま継続する。
        if (!isLatestRequest()) {
          return;
        }
      }

      try {
        const persistSelectedUrl = serverSourcePersistenceRef.current.then(
          async () => {
            if (isLatestRequest()) await serverUrlItem.setValue(baseUrl);
          }
        );
        serverSourcePersistenceRef.current = persistSelectedUrl.catch(
          () => undefined
        );
        await persistSelectedUrl;
        if (!isLatestRequest()) {
          return;
        }

        const extensionVersion = browser.runtime.getManifest().version;
        const warning = await resolveCompatibilityWarning(
          baseUrl,
          extensionVersion
        );
        if (!isLatestRequest()) {
          return;
        }
        setCompatibilityWarning(warning);

        const loadedCollections = await loadCollections(
          baseUrl,
          isLatestRequest
        );
        if (loadedCollections === null) {
          return;
        }
        const { list, isDirMode } = loadedCollections;

        let result: ReleasePayload;
        if (isDirMode) {
          if (list.length === 0) {
            // dir mode で未配信 disc が無い場合は単一 mode へ fallback しない
            // （dir mode サーバーに /distrokid/release.json は無く、誤った 404 ガイダンスになるため）。
            setPayload(null);
            setMessage("未配信の disc はありません。");
            return;
          }
          // 識別子で選択を維持し、一覧から消えていれば先頭へフォールバックする。
          const keptIndex = preferredDisc
            ? list.findIndex(
                (item) =>
                  item.collection_id === preferredDisc.collection_id &&
                  item.disc === preferredDisc.disc
              )
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
          result = await fetchCollectionRelease(
            baseUrl,
            selected.collection_id,
            selected.disc
          );
        } else {
          // 単一 mode（後方互換）: 従来の /distrokid/release.json を取得する。
          payloadSourceRef.current = null;
          result = await fetchRelease(baseUrl);
        }
        if (!isLatestRequest()) {
          return;
        }
        setPayload(result);
      } catch (error) {
        if (!isLatestRequest()) {
          return;
        }
        setPayload(null);
        setPhase(PHASES.ERROR);
        setMessage(
          error instanceof ReleaseUnavailableError
            ? UNAVAILABLE_GUIDANCE
            : error instanceof Error
              ? error.message
              : String(error)
        );
      } finally {
        if (isLatestRequest()) {
          setBusy(false);
        }
      }
    },
    [loadCollections]
  );

  const updateServerUrl = useCallback(
    (nextUrl: string) => {
      if (injectionActiveRef.current) {
        return;
      }
      initialFetchStartedRef.current = true;
      serverUrlRef.current = nextUrl;
      setServerUrl(nextUrl);
      void fetchData(nextUrl, null);
    },
    [fetchData]
  );

  const selectCollection = useCallback(
    (index: number) => {
      if (injectionActiveRef.current) {
        return;
      }
      const selected = collections[index];
      if (!selected) {
        return;
      }
      setSelectedIndex(index);
      void fetchData(serverUrl, {
        collection_id: selected.collection_id,
        disc: selected.disc,
      });
    },
    [collections, fetchData, serverUrl]
  );

  const refreshServerSources = useCallback(async () => {
    if (injectionActiveRef.current) return;
    await initializationRef.current;
    if (injectionActiveRef.current) return;
    const revision = ++serverSourcesRevisionRef.current;
    try {
      const sources = await discoverServerSources();
      if (
        injectionActiveRef.current ||
        revision !== serverSourcesRevisionRef.current
      )
        return;
      setServerSources(sources);
      const currentServerUrl = serverUrlRef.current;
      if (
        currentServerUrl &&
        sources.length > 0 &&
        !sources.some((source) => source.url === currentServerUrl)
      ) {
        updateServerUrl(sources[0].url);
      }
    } catch (error) {
      if (
        injectionActiveRef.current ||
        revision !== serverSourcesRevisionRef.current
      )
        return;
      setPhase(PHASES.ERROR);
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }, [updateServerUrl]);

  useEffect(() => {
    const revision = ++serverSourcesRevisionRef.current;
    const initialization = migrateServerSourcesStorage()
      .then(() =>
        Promise.all([serverUrlItem.getValue(), discoverServerSources()])
      )
      .then(([stored, sources]) => {
        if (
          initialFetchStartedRef.current ||
          revision !== serverSourcesRevisionRef.current
        )
          return;
        initialFetchStartedRef.current = true;
        setServerSources(sources);
        if (!stored.trim()) return;
        const nextUrl = sources.some((source) => source.url === stored)
          ? stored
          : sources[0]?.url;
        if (!nextUrl) return;
        serverUrlRef.current = nextUrl;
        setServerUrl(nextUrl);
        void fetchData(nextUrl, null);
      })
      .catch((error: unknown) => {
        setPhase(PHASES.ERROR);
        setMessage(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        initializationRef.current = null;
      });
    initializationRef.current = initialization;
  }, [fetchData]);

  const inject = useCallback(async () => {
    if (payload === null || injectionActiveRef.current) {
      return;
    }
    // 注入と配信済み記録は、開始時に表示されていた payload と取得元へ束縛する。
    // await 中に UI 外から state 更新が試みられても、別 disc/URL を記録しない。
    const injectionPayload = payload;
    const injectionBaseUrl = serverUrl.trim();
    const injectionSource = payloadSourceRef.current;
    const injectionIsDirMode = isDirModeRef.current;
    stoppedRef.current = false;
    injectionActiveRef.current = true;
    setIsInjecting(true);
    setBusy(true);
    setPhase(PHASES.INJECTING);
    setMessage("注入を開始します");
    try {
      // asset は popup（chrome-extension:// origin）で fetch する。content からの fetch は
      // ページ origin で CORS 評価され遮断されるため（asset-transfer.ts 参照）。逐次実行・
      // 停止境界の制御フローは runInjection に抽出し、ここでは transport を束ねて渡す（#871）。
      const tabId = await activeTabId();
      await runInjection(injectionPayload, {
        fetchAsset: (assetPath, filename) =>
          fetchAsset(injectionBaseUrl, assetPath, filename),
        start: (p) => sendMessage("injectStart", { payload: p }, tabId),
        track: (trackIndex, asset) =>
          sendMessage("injectTrack", { trackIndex, asset }, tabId),
        cover: (asset) => sendMessage("injectCover", { asset }, tabId),
        finish: () => sendMessage("injectFinish", undefined, tabId),
        setMessage,
        isStopped: () => stoppedRef.current,
      });

      // フィル完了後、dir mode で payload を取得した disc のみ配信済み記録を POST する (#934)。
      // 現在の select 値ではなく payload 取得元（payloadSourceRef）に束縛する —
      // fetch 後に select を変えてもフィルされたのは取得済み payload の disc のため。
      // POST は popup から直接 fetch せず background に委譲する — serve token 必須の
      // 書き込み境界は extension origin の background で越える（#1360、ADR-0016）。
      // POST 失敗はフィル成功を覆さない（warning を添えるだけ）。
      if (injectionIsDirMode && injectionSource !== null) {
        try {
          await sendMessage("recordRelease", {
            baseUrl: injectionBaseUrl,
            record: injectionSource,
          });
          // 配信済み記録成功後、一覧を再取得して select から消す (#934)。
          await loadCollections(injectionBaseUrl);
        } catch (recordError) {
          // 配信記録失敗はフィル結果に影響しない補助機能のため warn 表示のみ (#934)。
          setMessage(
            `注入完了（配信済み記録に失敗しました: ${recordError instanceof Error ? recordError.message : String(recordError)}）`
          );
        }
      }
    } catch (error) {
      setPhase(PHASES.ERROR);
      setMessage(error instanceof Error ? error.message : String(error));
      setBusy(false);
    } finally {
      injectionActiveRef.current = false;
      setIsInjecting(false);
    }
  }, [payload, serverUrl, loadCollections]);

  const stop = useCallback(async () => {
    // ループ送信を打ち切り、content にも停止を通知する（content が STOPPED を report し busy 解除）。
    stoppedRef.current = true;
    try {
      await sendMessage("stop", undefined, await activeTabId());
    } catch (error) {
      setPhase(PHASES.ERROR);
      setMessage(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  }, []);

  return {
    serverUrl,
    setServerUrl: updateServerUrl,
    serverSources,
    refreshServerSources,
    payload,
    busy,
    isInjecting,
    phase,
    message,
    compatibilityWarning,
    collections,
    allReleased,
    selectedIndex,
    selectCollection,
    inject,
    stop,
  };
}
