// overlay / popup 共用の状態管理フック。旧 popup.js の挙動 (取得 / 連続実行 / 停止 / 進捗・エラー表示) を保持する。
// run / stop / queryProgress / progress は tabId を指定せず background 宛に送る（#892）。overlay は
// content script で `browser.tabs.*` を呼べないため、background が送信元と同一タブの runner content へ中継する
// （中継ロジックは entrypoints/background.ts + lib/overlay-relay.ts）。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { browser } from "wxt/browser";

import {
  type CollectionSummary,
  type DurationFilter,
  extractPlaylistName,
  type PromptEntry,
  type PromptResponse,
  resolvePromptCollectionId,
  visiblePromptCollections,
} from "../../shared/api";
import {
  CLIPS_PER_REQUEST,
  DEFAULT_REGENERATE_DURATION_OUTLIERS,
  type ItemState,
  type LocalServerSource,
  type RunModeId,
} from "../../shared/constants";
import { onMessage, sendMessage } from "../lib/messaging";
import { DEFAULT_RUN_MODE_ID, readRunModeId, writeRunModeId } from "../lib/preset-state";
import {
  readResumeState,
  resolvePlaylistExpectedClipCountForResume,
  type ResumeBanner,
  type ResumeState,
  shouldShowResumeBanner,
  writeResumeState,
} from "../lib/resume-state";
import {
  buildFailedEntriesRunOverrides,
  buildRunPayload,
  buildResumeRunOverrides,
  type RunOverrides,
} from "../lib/run-overrides";
import { isTerminalPhase, nextItemStates } from "../lib/snapshot";
import { readServerSources, rememberServerSource, serverUrlItem } from "../lib/storage";
import { shouldReportLiveProgressStatus } from "./live-progress-status";
import {
  buildRestoreState,
  formatRunError,
  formatStopError,
  isExtensionReloadRequiredError,
  phaseToStatus,
} from "./runner-errors";

interface RunnerState {
  reloadRequired: boolean;
  url: string;
  setUrl: (url: string) => void;
  serverSources: LocalServerSource[];
  collections: CollectionSummary[];
  selectedCollectionId: string;
  selectCollection: (id: string) => void;
  entries: PromptEntry[];
  itemStates: ItemState[];
  status: string;
  phase: string;
  isError: boolean;
  compatibilityWarning: string;
  canRun: boolean;
  isRunning: boolean;
  // collection 選択時の playlist 名 (#854)。display only。
  playlistName: string | undefined;
  runModeId: RunModeId;
  setRunMode: (id: RunModeId) => void;
  regenerateDurationOutliers: boolean;
  setRegenerateDurationOutliers: (enabled: boolean) => void;
  // 再開バナー (#872)。chrome.storage / content snapshot いずれか有効なソース、無ければ null。
  resumeBanner: ResumeBanner | null;
  acceptResume: () => void;
  dismissResume: () => void;
  // リトライ上限まで失敗しスキップされた entry の 0-based index 一覧 (#948)。表示と再実行導線に使う。
  failedEntries: number[];
  // 失敗分のみ再実行 (#948)。run({indices: failedEntries}) を 1-click で投げる。
  rerunFailed: () => void;
  // playlist / download 単独再実行 (#1251)。失敗フォールバック用。
  retryPlaylist: () => Promise<void>;
  retryDownload: () => Promise<void>;
  adoptSelectedClips: () => Promise<void>;
  // overrides.range があればそれを使う (#892 要件6)。
  // overrides.indices はチェック選択や失敗分再実行の部分実行対象。指定時は range より優先される。
  run: (overrides?: RunOverrides) => Promise<void>;
  stop: () => Promise<void>;
}

function normalizePromptResponseMessage(response: PromptResponse | PromptEntry[]): PromptResponse {
  if (Array.isArray(response)) {
    return { entries: response };
  }
  return response;
}

async function fetchCollectionPromptResponse(baseUrl: string, collectionId: string): Promise<PromptResponse> {
  const response = (await sendMessage("fetchCollectionPromptResponse", {
    baseUrl,
    collectionId,
  })) as PromptResponse | PromptEntry[];
  return normalizePromptResponseMessage(response);
}

function maxDefined(...values: Array<number | null | undefined>): number | undefined {
  const candidates = values.filter((value): value is number => typeof value === "number" && value > 0);
  return candidates.length > 0 ? Math.max(...candidates) : undefined;
}

export function useSunoRunner(): RunnerState {
  const [reloadRequired, setReloadRequired] = useState(false);
  const [url, setUrlState] = useState("");
  const [serverSources, setServerSources] = useState<LocalServerSource[]>([]);
  const [allCollections, setAllCollections] = useState<CollectionSummary[]>([]);
  const [selectedCollectionIdState, setSelectedCollectionId] = useState("");
  const [entries, setEntries] = useState<PromptEntry[]>([]);
  const [durationFilter, setDurationFilter] = useState<DurationFilter | undefined>(undefined);
  const [itemStates, setItemStates] = useState<ItemState[]>([]);
  const [status, setStatus] = useState("");
  const [phase, setPhase] = useState("idle");
  const [isError, setIsError] = useState(false);
  const [compatibilityWarning, setCompatibilityWarning] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  // popup 再 open 時に content snapshot から復元する playlist 名 (#854)。
  // 選択由来 (derivedPlaylistName) が無い実行中復元ケースで display only に使う。
  const [restoredPlaylistName, setRestoredPlaylistName] = useState<string | undefined>(undefined);
  const [restoredCollectionId, setRestoredCollectionId] = useState<string | undefined>(undefined);
  // content snapshot 由来の失敗 index (#872 要件3)。chrome.storage の resume state が失われても、
  // 現在タブの live snapshot が ERROR phase で保持する failedIndex を再開バナーの冗長ソースにする。
  const [restoredFailedIndex, setRestoredFailedIndex] = useState<number | undefined>(undefined);
  // content snapshot 由来のスキップ済み失敗 index 一覧 (#948)。chrome.storage と二重化する。
  const [restoredFailedIndices, setRestoredFailedIndices] = useState<number[] | undefined>(undefined);
  const [restoredRemainingIndices, setRestoredRemainingIndices] = useState<number[] | undefined>(undefined);
  const [restoredSubmittedClipIds, setRestoredSubmittedClipIds] = useState<string[] | undefined>(undefined);
  const [restoredSubmittedClipIdsAreDurationFiltered, setRestoredSubmittedClipIdsAreDurationFiltered] = useState(false);
  const [restoredPlaylistExpectedClipCount, setRestoredPlaylistExpectedClipCount] = useState<number | undefined>(
    undefined,
  );
  // 投入方式 (#1586)。マウント時に storage から復元し、選択時に永続化する。
  const [runModeId, setRunModeId] = useState<RunModeId>(DEFAULT_RUN_MODE_ID);
  const [regenerateDurationOutliers, setRegenerateDurationOutliers] = useState(DEFAULT_REGENERATE_DURATION_OUTLIERS);
  const [restoredRegenerateDurationOutliers, setRestoredRegenerateDurationOutliers] = useState<boolean | undefined>(
    undefined,
  );
  const [restoredDurationOutlierWarnings, setRestoredDurationOutlierWarnings] = useState<
    Record<number, string> | undefined
  >(undefined);
  // chrome.storage から読んだ前回の ERROR 停止 state (#872)。表示可否は selectedCollectionId と時刻で判定する。
  const [persistedResume, setPersistedResume] = useState<ResumeState | null>(null);
  // resume state を読んだ popup 起動時刻 (#872)。stale 判定の基準 now をここで一度だけ確定し、
  // render 中の Date.now()（非純粋）を避ける。
  const [resumeCheckedAt, setResumeCheckedAt] = useState<number | null>(null);
  // 一度承認/却下したバナーは再表示しない（同一 popup セッション内）。
  const [resumeDismissed, setResumeDismissed] = useState(false);
  const durationOutlierWarningsRef = useRef<string[]>([]);
  const fetchRequestIdRef = useRef(0);
  const serverSourcePersistenceRef = useRef<Promise<void>>(Promise.resolve());
  const serverSourcesRevisionRef = useRef(0);
  const restoredProgressRef = useRef(false);
  const initialFetchStartedRef = useRef(false);

  const resumableCollectionId = useMemo(() => {
    if (
      resumeCheckedAt !== null &&
      persistedResume &&
      shouldShowResumeBanner(persistedResume, persistedResume.collectionId, resumeCheckedAt)
    ) {
      return persistedResume.collectionId;
    }
    return undefined;
  }, [persistedResume, resumeCheckedAt]);

  const resolveVisibleCollections = useCallback(
    (source: CollectionSummary[], currentSelectedId: string) => {
      const visibleCollections = visiblePromptCollections(source);
      const preferredSelectedId = currentSelectedId || resumableCollectionId || "";
      const nextSelectedId = resolvePromptCollectionId(visibleCollections, preferredSelectedId, true);
      return { visibleCollections, nextSelectedId };
    },
    [resumableCollectionId],
  );

  const { visibleCollections: collections, nextSelectedId } = useMemo(
    () => resolveVisibleCollections(allCollections, selectedCollectionIdState),
    [allCollections, resolveVisibleCollections, selectedCollectionIdState],
  );
  const selectedCollectionId = restoredCollectionId ?? nextSelectedId ?? "";

  // collection 選択から導出する playlist 名 (#854)。
  const selectedCollection = useMemo(
    () => collections.find((c) => c.id === selectedCollectionId),
    [collections, selectedCollectionId],
  );

  const derivedPlaylistName = useMemo(() => {
    const selected = selectedCollection;
    if (!selected) {
      return undefined;
    }
    if (selected.channel && selected.theme) {
      return `${selected.channel} | ${selected.theme}`;
    }
    const theme = (selected.theme ?? selected.name).replace(/-collection$/, "");
    return extractPlaylistName(selected.id, theme);
  }, [selectedCollection]);
  const playlistName = derivedPlaylistName ?? restoredPlaylistName;

  // 再開バナーのソース (#872)。chrome.storage と content snapshot を二重化し、いずれかが
  // 生きていれば再開導線を出す（要件3 の二重化を実消費する）。一度承認/却下したら resumeDismissed で隠す。
  const resumeBanner = useMemo<ResumeBanner | null>(() => {
    if (resumeDismissed) {
      return null;
    }
    // 1) 永続化 (chrome.storage) 由来 (要件4)。選択中 collection 一致 + 24h 以内のときのみ。
    //    基準 now は読み込み時刻 (resumeCheckedAt) を使う（render 中の Date.now() を避ける）。
    if (
      resumeCheckedAt !== null &&
      persistedResume &&
      shouldShowResumeBanner(persistedResume, selectedCollectionId, resumeCheckedAt)
    ) {
      return {
        failedIndex: persistedResume.failedIndex,
        total: persistedResume.total,
        remainingIndices: persistedResume.remainingIndices,
      };
    }
    // 2) content snapshot 由来 (要件3 二重化)。chrome.storage 書込が失われても、現在タブの
    //    実行セッションが ERROR phase で保持する failedIndex から同じ再開導線を出す。
    //    snapshot の collectionId が現在選択と一致するときだけ消費する。
    if (restoredCollectionId === selectedCollectionId && restoredFailedIndex !== undefined && entries.length > 0) {
      return { failedIndex: restoredFailedIndex, total: entries.length, remainingIndices: restoredRemainingIndices };
    }
    return null;
  }, [
    persistedResume,
    selectedCollectionId,
    resumeDismissed,
    resumeCheckedAt,
    restoredCollectionId,
    restoredFailedIndex,
    restoredRemainingIndices,
    entries.length,
  ]);

  // 失敗スキップされた entry の一覧 (#948)。resumeBanner と同じ二重ソース
  // （chrome.storage 優先、無ければ content snapshot）から解決する。
  const failedEntries = useMemo<number[]>(() => {
    if (
      resumeCheckedAt !== null &&
      persistedResume?.failedIndices?.length &&
      shouldShowResumeBanner(persistedResume, selectedCollectionId, resumeCheckedAt)
    ) {
      return persistedResume.failedIndices;
    }
    return restoredCollectionId === selectedCollectionId ? (restoredFailedIndices ?? []) : [];
  }, [persistedResume, selectedCollectionId, resumeCheckedAt, restoredCollectionId, restoredFailedIndices]);

  const submittedClipIdsForResume = useMemo<string[]>(() => {
    if (
      resumeCheckedAt !== null &&
      persistedResume &&
      shouldShowResumeBanner(persistedResume, selectedCollectionId, resumeCheckedAt)
    ) {
      return persistedResume.submittedClipIds ?? [];
    }
    return restoredCollectionId === selectedCollectionId ? (restoredSubmittedClipIds ?? []) : [];
  }, [persistedResume, selectedCollectionId, resumeCheckedAt, restoredCollectionId, restoredSubmittedClipIds]);

  const submittedClipIdsAreDurationFilteredForResume = useMemo<boolean>(() => {
    if (
      resumeCheckedAt !== null &&
      persistedResume &&
      shouldShowResumeBanner(persistedResume, selectedCollectionId, resumeCheckedAt)
    ) {
      return persistedResume.submittedClipIdsAreDurationFiltered === true;
    }
    return restoredCollectionId === selectedCollectionId ? restoredSubmittedClipIdsAreDurationFiltered : false;
  }, [
    persistedResume,
    selectedCollectionId,
    resumeCheckedAt,
    restoredCollectionId,
    restoredSubmittedClipIdsAreDurationFiltered,
  ]);

  const durationFilterForResume = useMemo<DurationFilter | undefined>(() => {
    if (
      resumeCheckedAt !== null &&
      persistedResume &&
      shouldShowResumeBanner(persistedResume, selectedCollectionId, resumeCheckedAt)
    ) {
      return persistedResume.durationFilter ?? durationFilter;
    }
    return durationFilter;
  }, [persistedResume, selectedCollectionId, resumeCheckedAt, durationFilter]);

  // 中断した run の投入方式 (#1586)。再開は popup の現在選択ではなく元 run のモードで行う。
  // 旧 state / snapshot 由来バナーには無いため undefined（run 側で現在選択へフォールバック）。
  const runModeForResume = useMemo<RunModeId | undefined>(() => {
    if (
      resumeCheckedAt !== null &&
      persistedResume &&
      shouldShowResumeBanner(persistedResume, selectedCollectionId, resumeCheckedAt)
    ) {
      return persistedResume.runMode;
    }
    return undefined;
  }, [persistedResume, selectedCollectionId, resumeCheckedAt]);

  const regenerateDurationOutliersForResume = useMemo<boolean | undefined>(() => {
    if (
      resumeCheckedAt !== null &&
      persistedResume &&
      shouldShowResumeBanner(persistedResume, selectedCollectionId, resumeCheckedAt)
    ) {
      return persistedResume.regenerateDurationOutliers;
    }
    if (restoredCollectionId === selectedCollectionId) {
      return restoredRegenerateDurationOutliers;
    }
    return undefined;
  }, [
    persistedResume,
    selectedCollectionId,
    resumeCheckedAt,
    restoredCollectionId,
    restoredRegenerateDurationOutliers,
  ]);
  const durationOutlierWarningsForResume = useMemo<Record<number, string> | undefined>(() => {
    if (
      resumeCheckedAt !== null &&
      persistedResume &&
      shouldShowResumeBanner(persistedResume, selectedCollectionId, resumeCheckedAt)
    ) {
      return persistedResume.durationOutlierWarnings;
    }
    if (restoredCollectionId === selectedCollectionId) {
      return restoredDurationOutlierWarnings;
    }
    return undefined;
  }, [persistedResume, selectedCollectionId, resumeCheckedAt, restoredCollectionId, restoredDurationOutlierWarnings]);

  const playlistExpectedClipCountForResume = useMemo<number | undefined>(() => {
    if (
      resumeCheckedAt !== null &&
      persistedResume &&
      shouldShowResumeBanner(persistedResume, selectedCollectionId, resumeCheckedAt)
    ) {
      return resolvePlaylistExpectedClipCountForResume(
        persistedResume.playlistExpectedClipCount,
        persistedResume.total,
      );
    }
    if (restoredCollectionId === selectedCollectionId && restoredFailedIndex !== undefined && entries.length > 0) {
      return resolvePlaylistExpectedClipCountForResume(restoredPlaylistExpectedClipCount, entries.length);
    }
    return undefined;
  }, [
    persistedResume,
    selectedCollectionId,
    resumeCheckedAt,
    restoredCollectionId,
    restoredFailedIndex,
    restoredPlaylistExpectedClipCount,
    entries.length,
  ]);

  const expectedClipCountForManualAdoption = useMemo<number | undefined>(() => {
    return maxDefined(
      playlistExpectedClipCountForResume,
      selectedCollection?.expected_file_count,
      entries.length > 0 ? entries.length * CLIPS_PER_REQUEST : undefined,
      selectedCollection?.pattern_count ? selectedCollection.pattern_count * CLIPS_PER_REQUEST : undefined,
    );
  }, [playlistExpectedClipCountForResume, entries.length, selectedCollection]);

  const report = useCallback((text: string, error = false) => {
    setStatus(text);
    setIsError(error);
  }, []);

  const reportStorageFailure = useCallback((error: unknown) => {
    console.warn("[suno-helper] storage 操作に失敗しました（拡張更新後はタブを再読み込みしてください）:", error);
    setReloadRequired(true);
  }, []);

  // popup 起動時に前回の ERROR 停止 state を読む (#872 要件4)。表示可否は resumeBanner 側で判定する。
  // 基準 now は読み込み完了時に確定する（render 中の Date.now() を避けるため effect 内で取得）。
  useEffect(() => {
    void readResumeState()
      .then((state) => {
        const checkedAt = Date.now();
        setPersistedResume(state);
        setResumeCheckedAt(checkedAt);
        if (
          state &&
          typeof state.regenerateDurationOutliers === "boolean" &&
          shouldShowResumeBanner(state, state.collectionId, checkedAt)
        ) {
          setRegenerateDurationOutliers(state.regenerateDurationOutliers);
        }
      })
      .catch((err: unknown) => {
        reportStorageFailure(err);
      });
  }, [reportStorageFailure]);

  useEffect(() => {
    void readRunModeId().then(setRunModeId).catch(reportStorageFailure);
  }, [reportStorageFailure]);

  const setRunMode = useCallback(
    (id: RunModeId) => {
      setRunModeId(id);
      void writeRunModeId(id).catch(reportStorageFailure);
    },
    [reportStorageFailure],
  );

  const dismissResume = useCallback(() => {
    setResumeDismissed(true);
  }, []);

  const clearLoadedRunState = useCallback(() => {
    setDurationFilter(undefined);
    setPhase("idle");
    setRestoredCollectionId(undefined);
    setRestoredPlaylistName(undefined);
    setRestoredFailedIndex(undefined);
    setRestoredFailedIndices(undefined);
    setRestoredRemainingIndices(undefined);
    setRestoredSubmittedClipIds(undefined);
    setRestoredSubmittedClipIdsAreDurationFiltered(false);
    setRestoredPlaylistExpectedClipCount(undefined);
    setRestoredDurationOutlierWarnings(undefined);
  }, []);

  useEffect(() => {
    const unwatch = onMessage("progress", ({ data }) => {
      setItemStates((prev) => nextItemStates(prev, data));
      setPhase(data.phase);
      if (data.durationOutlierWarning) {
        durationOutlierWarningsRef.current.push(data.durationOutlierWarning);
      }
      if (shouldReportLiveProgressStatus(data)) {
        const { text, error } = phaseToStatus(data, entries);
        const terminalWarning =
          data.phase === "finished" && durationOutlierWarningsRef.current.length > 0
            ? ` / 異常値警告: ${durationOutlierWarningsRef.current.join("; ")}`
            : "";
        report(`${text}${terminalWarning}`, Boolean(error));
      }
      if (isTerminalPhase(data.phase)) {
        setIsRunning(false);
      }
    });
    return () => unwatch();
  }, [entries, report]);

  // overlay mount / popup 再 open 時、runner content が保持する snapshot から進捗を即時復元する (#852)。
  // queryProgress は background 経由で同一タブの runner content へ中継される (#892)。runner 未注入なら
  // 中継が失敗 → 復元せず従来表示へ silent fallback。
  useEffect(() => {
    void (async () => {
      try {
        const snapshot = await sendMessage("queryProgress", undefined);
        if (!snapshot) {
          return;
        }
        const restored = buildRestoreState(snapshot);
        if (!restored) {
          return;
        }
        restoredProgressRef.current = true;
        setEntries(restored.entries);
        setItemStates(restored.itemStates);
        setIsRunning(restored.isRunning);
        setRestoredCollectionId(restored.collectionId);
        setSelectedCollectionId(restored.collectionId);
        setRestoredPlaylistName(restored.playlistName);
        setDurationFilter(restored.durationFilter);
        // ERROR 停止の snapshot なら failedIndex を再開バナーの冗長ソースへ流す (#872 要件3)。
        setRestoredFailedIndex(restored.failedIndex);
        setRestoredFailedIndices(restored.failedIndices);
        setRestoredRemainingIndices(restored.remainingIndices);
        setRestoredSubmittedClipIds(restored.submittedClipIds);
        setRestoredSubmittedClipIdsAreDurationFiltered(restored.submittedClipIdsAreDurationFiltered === true);
        setRestoredPlaylistExpectedClipCount(restored.playlistExpectedClipCount);
        setRestoredRegenerateDurationOutliers(restored.regenerateDurationOutliers);
        setRestoredDurationOutlierWarnings(restored.durationOutlierWarnings);
        setRegenerateDurationOutliers(restored.regenerateDurationOutliers);
        durationOutlierWarningsRef.current = Object.values(restored.durationOutlierWarnings);
        setPhase(snapshot.progress.phase);
        report(restored.status, restored.isError);
      } catch {
        // runner content 未注入（中継先不在）では queryProgress が到達しない。復元を諦め従来表示を維持する。
      }
    })();
  }, [report]);

  const fetchData = useCallback(
    async (targetUrl: string, preferredCollectionId: string) => {
      const requestId = ++fetchRequestIdRef.current;
      const isLatestRequest = (): boolean => requestId === fetchRequestIdRef.current;
      const isRestoreFetch = (): boolean => restoredProgressRef.current || resumableCollectionId !== undefined;
      const trimmed = targetUrl.trim();
      if (!trimmed) {
        if (isLatestRequest()) {
          report("ローカル配信元を選択してください。", true);
        }
        return;
      }
      let baseUrl = trimmed;
      let serverLabel: string | undefined;
      try {
        const info = await sendMessage("fetchServerInfo", { baseUrl: trimmed });
        if (!isLatestRequest()) {
          return;
        }
        baseUrl = info.base_url;
        serverLabel = info.label;
      } catch {
        // 古い server は fetchServerInfo を提供しないため、入力 URL のまま継続する。
        if (!isLatestRequest()) {
          return;
        }
      }
      const persistServerSource = serverSourcePersistenceRef.current.then(async () => {
        if (!isLatestRequest()) {
          return;
        }
        await serverUrlItem.setValue(trimmed);
        if (!isLatestRequest()) {
          return;
        }
        const rememberedSources = await rememberServerSource(trimmed, serverLabel);
        if (!isLatestRequest()) {
          return;
        }
        serverSourcesRevisionRef.current += 1;
        setServerSources(rememberedSources);
      });
      serverSourcePersistenceRef.current = persistServerSource.catch(() => undefined);
      try {
        await persistServerSource;
        if (!isLatestRequest()) {
          return;
        }
      } catch (error) {
        if (isLatestRequest()) {
          reportStorageFailure(error);
        }
        return;
      }
      if (!restoredProgressRef.current) {
        setPhase("loading");
        report("取得中…");
      }
      try {
        const extensionVersion = browser.runtime.getManifest().version;
        const warning = await sendMessage("fetchCompatibilityWarning", { baseUrl, extensionVersion });
        if (!isLatestRequest()) {
          return;
        }
        setCompatibilityWarning(typeof warning === "string" ? warning : "");
      } catch (error) {
        if (!isLatestRequest()) {
          return;
        }
        const message = error instanceof Error ? error.message : String(error);
        if (isExtensionReloadRequiredError(message)) {
          setReloadRequired(true);
          return;
        }
        setPhase("error");
        report(`互換性確認失敗: ${message}`, true);
        return;
      }
      try {
        const fetched = await sendMessage("fetchCollections", { baseUrl });
        if (!isLatestRequest()) {
          return;
        }
        const { nextSelectedId: collectionId } = resolveVisibleCollections(fetched, preferredCollectionId);
        if (collectionId === null) {
          throw new Error("prompts を取得できる collection がありません。");
        }
        if (isRestoreFetch()) {
          setAllCollections(fetched);
          setSelectedCollectionId(collectionId);
        }
        const data = await fetchCollectionPromptResponse(baseUrl, collectionId);
        if (!isLatestRequest()) {
          return;
        }
        setAllCollections(fetched);
        if (restoredProgressRef.current) {
          return;
        }
        setSelectedCollectionId(collectionId);
        setEntries(data.entries);
        setDurationFilter(data.duration_filter);
        setItemStates(data.entries.map(() => "idle"));
        setPhase("idle");
        report(`${data.entries.length} パターンを取得しました。`);
      } catch (err) {
        if (!isLatestRequest() || restoredProgressRef.current) {
          return;
        }
        const message = err instanceof Error ? err.message : String(err);
        setPhase("error");
        report(`取得失敗: ${message}\nyt-collection-serve が起動しているか確認してください。`, true);
      }
    },
    [report, reportStorageFailure, resolveVisibleCollections, resumableCollectionId],
  );

  const updateUrl = useCallback(
    (nextUrl: string) => {
      initialFetchStartedRef.current = true;
      setUrlState(nextUrl);
      restoredProgressRef.current = false;
      clearLoadedRunState();
      void fetchData(nextUrl, selectedCollectionId);
    },
    [clearLoadedRunState, fetchData, selectedCollectionId],
  );

  const selectCollection = useCallback(
    (id: string) => {
      restoredProgressRef.current = false;
      clearLoadedRunState();
      void fetchData(url, id);
    },
    [clearLoadedRunState, fetchData, url],
  );

  useEffect(() => {
    if (resumeCheckedAt === null || initialFetchStartedRef.current) {
      return;
    }
    initialFetchStartedRef.current = true;
    void serverUrlItem
      .getValue()
      .then((stored) => {
        setUrlState(stored);
        if (stored.trim()) {
          void fetchData(stored, resumableCollectionId ?? "");
        }
      })
      .catch((err: unknown) => {
        reportStorageFailure(err);
      });
  }, [fetchData, reportStorageFailure, resumableCollectionId, resumeCheckedAt]);

  useEffect(() => {
    const revisionAtStart = serverSourcesRevisionRef.current;
    void readServerSources()
      .then((sources) => {
        if (revisionAtStart === serverSourcesRevisionRef.current) {
          setServerSources(sources);
        }
      })
      .catch((err: unknown) => {
        reportStorageFailure(err);
      });
  }, [reportStorageFailure]);

  const run = useCallback(
    async (overrides?: RunOverrides) => {
      // 二重実行ガード (#892 要件7)。実行中の再入（「再開」連打等）を no-op で弾く。
      if (isRunning) {
        return;
      }
      if (entries.length === 0) {
        return;
      }
      if (!selectedCollectionId) {
        report("コレクションを選択してください。", true);
        return;
      }
      if (!playlistName) {
        report("playlist 名を解決できません。コレクションを選択し直してください。", true);
        return;
      }
      const range = overrides?.range;
      durationOutlierWarningsRef.current = Object.values(overrides?.durationOutlierWarnings ?? {});
      // 二重実行ガード成立後、送信前に実行中フラグを立てる (#892 要件7: setIsRunning を sendMessage の前へ)。
      setIsRunning(true);
      setPhase("starting");
      try {
        // collection mode の payload だけを送る。collectionId は resume 紐付けと download 記録に必須。
        // tabId は指定せず background 宛に送り、同一タブの runner content へ中継させる (#892)。
        await sendMessage(
          "run",
          buildRunPayload({
            entries,
            playlistName,
            durationFilter,
            range,
            collectionId: selectedCollectionId,
            runMode: runModeId,
            regenerateDurationOutliers,
            durationOutlierWarnings: overrides?.durationOutlierWarnings,
            overrides,
          }),
        );
        report("連続実行を開始しました。");
      } catch (err) {
        // 送信失敗時はフラグを戻して再実行可能にする（実行は始まっていない）。
        setIsRunning(false);
        setPhase("error");
        const message = err instanceof Error ? err.message : String(err);
        report(formatRunError(message), true);
      }
    },
    [
      isRunning,
      entries,
      durationFilter,
      playlistName,
      selectedCollectionId,
      runModeId,
      regenerateDurationOutliers,
      report,
    ],
  );

  // playlist 追加のみ再実行。entries 不要のため retryPlaylist 専用メッセージを送る。
  const retryPlaylist = useCallback(async () => {
    if (isRunning) {
      return;
    }
    if (!selectedCollectionId) {
      report("コレクションを選択してから、playlist 追加を再開してください。", true);
      return;
    }
    if (!playlistName) {
      report(
        "playlist 名を解決できないため、playlist 追加を再開できません。コレクションを選択し直してください。",
        true,
      );
      return;
    }
    const expectedClipCount = playlistExpectedClipCountForResume ?? submittedClipIdsForResume.length;
    const shouldDownload =
      resumeBanner !== null && resumeBanner.failedIndex >= resumeBanner.total && !resumeBanner.remainingIndices?.length;
    if (submittedClipIdsForResume.length === 0 || expectedClipCount <= 0) {
      report("playlist 再開に必要な clip ID がありません。ページを再読み込みしてから再試行してください。", true);
      return;
    }
    setIsRunning(true);
    setPhase("adding-to-playlist");
    durationOutlierWarningsRef.current = Object.values(durationOutlierWarningsForResume ?? {});
    try {
      await sendMessage("retryPlaylist", {
        playlistName,
        submittedClipIds: submittedClipIdsForResume,
        expectedClipCount,
        collectionId: selectedCollectionId,
        durationFilter: durationFilterForResume,
        regenerateDurationOutliers: regenerateDurationOutliersForResume ?? regenerateDurationOutliers,
        durationOutlierWarnings: durationOutlierWarningsForResume,
        submittedClipIdsAreDurationFiltered: submittedClipIdsAreDurationFilteredForResume,
        shouldDownload,
      });
      setResumeDismissed(true);
      report("playlist 追加とダウンロードを再実行しています…");
    } catch (err) {
      setIsRunning(false);
      setPhase("error");
      setResumeDismissed(false);
      const message = err instanceof Error ? err.message : String(err);
      report(formatRunError(message), true);
    }
  }, [
    isRunning,
    playlistName,
    durationFilterForResume,
    regenerateDurationOutliersForResume,
    regenerateDurationOutliers,
    durationOutlierWarningsForResume,
    submittedClipIdsForResume,
    submittedClipIdsAreDurationFilteredForResume,
    playlistExpectedClipCountForResume,
    resumeBanner,
    selectedCollectionId,
    report,
  ]);

  // バナー承認 = 1-click 自動再開 (#892 要件6)。failedIndex === total（全 entry 投入済み）のときは
  // entries 不要の retryPlaylist を使い、ページリロード後でも確実に playlist 追加を再実行する。
  // それ以外（途中中断）は従来通り run で entry 生成から再開する。
  const acceptResume = useCallback(() => {
    if (!resumeBanner) {
      return;
    }
    if (resumeBanner.failedIndex >= resumeBanner.total && !resumeBanner.remainingIndices?.length) {
      void retryPlaylist();
      return;
    }
    if (entries.length === 0) {
      report("再開に必要なパターンが未取得です。ページを再読み込みしてから再試行してください。", true);
      return;
    }
    setResumeDismissed(true);
    void run({
      ...buildResumeRunOverrides(resumeBanner, {
        submittedClipIds: submittedClipIdsForResume,
        submittedClipIdsAreDurationFiltered: submittedClipIdsAreDurationFilteredForResume,
        playlistExpectedClipCount: playlistExpectedClipCountForResume,
      }),
      runMode: runModeForResume,
      regenerateDurationOutliers: regenerateDurationOutliersForResume,
      durationOutlierWarnings: durationOutlierWarningsForResume,
    });
  }, [
    resumeBanner,
    retryPlaylist,
    entries.length,
    report,
    run,
    submittedClipIdsForResume,
    submittedClipIdsAreDurationFilteredForResume,
    playlistExpectedClipCountForResume,
    runModeForResume,
    regenerateDurationOutliersForResume,
    durationOutlierWarningsForResume,
  ]);

  // ダウンロードのみ再実行 (#1251)。clip を再選択 → Download all を実行する。
  const retryDownload = useCallback(async () => {
    if (isRunning) {
      return;
    }
    if (!selectedCollectionId) {
      report("コレクションを選択してから、ダウンロードを再開してください。", true);
      return;
    }
    if (submittedClipIdsForResume.length === 0) {
      report("ダウンロード再開に必要な clip ID がありません。ページを再読み込みしてから再試行してください。", true);
      return;
    }
    setIsRunning(true);
    setPhase("downloading");
    try {
      const payload = {
        collectionId: selectedCollectionId,
        submittedClipIds: submittedClipIdsForResume,
        expectedClipCount: expectedClipCountForManualAdoption,
      };
      await sendMessage("retryDownload", payload);
      report("ダウンロードを再実行しています…");
    } catch (err) {
      setIsRunning(false);
      setPhase("error");
      const message = err instanceof Error ? err.message : String(err);
      report(formatRunError(message), true);
    }
  }, [isRunning, selectedCollectionId, submittedClipIdsForResume, expectedClipCountForManualAdoption, report]);

  const adoptSelectedClips = useCallback(async () => {
    if (isRunning) {
      return;
    }
    if (!selectedCollectionId) {
      report("コレクションを選択してから、選択中の曲を採用してください。", true);
      return;
    }
    if (expectedClipCountForManualAdoption === undefined || expectedClipCountForManualAdoption <= 0) {
      report("期待 clip 数を解決できません。ページを再読み込みしてから再試行してください。", true);
      return;
    }
    setIsRunning(true);
    setPhase("adopting");
    try {
      const result = await sendMessage("adoptSelectedClips", {
        expectedClipCount: expectedClipCountForManualAdoption,
      });
      const totalEntries =
        persistedResume?.collectionId === selectedCollectionId
          ? persistedResume.total
          : entries.length || selectedCollection?.pattern_count || Math.ceil(result.clipIds.length / CLIPS_PER_REQUEST);
      const failedIndex =
        persistedResume?.collectionId === selectedCollectionId ? persistedResume.failedIndex : totalEntries;
      const nextResume: ResumeState = {
        collectionId: selectedCollectionId,
        failedIndex,
        total: totalEntries,
        timestamp: Date.now(),
        failedIndices:
          persistedResume?.collectionId === selectedCollectionId
            ? persistedResume.failedIndices
            : restoredFailedIndices,
        remainingIndices:
          persistedResume?.collectionId === selectedCollectionId
            ? persistedResume.remainingIndices
            : restoredRemainingIndices,
        submittedClipIds: result.clipIds,
        durationFilter,
        submittedClipIdsAreDurationFiltered: false,
        playlistExpectedClipCount: result.clipIds.length,
        regenerateDurationOutliers:
          persistedResume?.collectionId === selectedCollectionId
            ? (persistedResume.regenerateDurationOutliers ?? regenerateDurationOutliers)
            : regenerateDurationOutliers,
        durationOutlierWarnings:
          persistedResume?.collectionId === selectedCollectionId
            ? persistedResume.durationOutlierWarnings
            : restoredDurationOutlierWarnings,
      };
      await writeResumeState(nextResume);
      setPersistedResume(nextResume);
      setResumeCheckedAt(Date.now());
      setRestoredSubmittedClipIds(result.clipIds);
      setRestoredSubmittedClipIdsAreDurationFiltered(false);
      setRestoredPlaylistExpectedClipCount(result.clipIds.length);
      setResumeDismissed(false);
      setPhase("idle");
      report(`選択中の曲 ${result.clipIds.length} 件を採用しました。Playlist / Download から再開できます。`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setPhase("error");
      report(formatRunError(message), true);
    } finally {
      setIsRunning(false);
    }
  }, [
    isRunning,
    selectedCollectionId,
    expectedClipCountForManualAdoption,
    persistedResume,
    entries.length,
    selectedCollection,
    restoredFailedIndices,
    restoredRemainingIndices,
    restoredDurationOutlierWarnings,
    durationFilter,
    regenerateDurationOutliers,
    report,
  ]);

  // 失敗分のみ再実行 (#948)。failedEntries を indices として run へ渡す。
  // 完走すると content 側が playlist 追加まで実行し resume state を消す。
  const rerunFailed = useCallback(() => {
    if (failedEntries.length === 0) {
      return;
    }
    setResumeDismissed(true);
    setRestoredFailedIndices(undefined);
    void run({
      ...buildFailedEntriesRunOverrides(failedEntries, {
        submittedClipIds: submittedClipIdsForResume,
        submittedClipIdsAreDurationFiltered: submittedClipIdsAreDurationFilteredForResume,
        playlistExpectedClipCount: playlistExpectedClipCountForResume,
      }),
      runMode: runModeForResume,
      regenerateDurationOutliers: regenerateDurationOutliersForResume,
      durationOutlierWarnings: durationOutlierWarningsForResume,
    });
  }, [
    failedEntries,
    run,
    submittedClipIdsForResume,
    submittedClipIdsAreDurationFilteredForResume,
    playlistExpectedClipCountForResume,
    runModeForResume,
    regenerateDurationOutliersForResume,
    durationOutlierWarningsForResume,
  ]);

  const stop = useCallback(async () => {
    try {
      // tabId は指定せず background 宛に送り、同一タブの runner content へ中継させる (#892)。
      await sendMessage("stop", undefined);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      report(formatStopError(message), true);
    }
  }, [report]);

  return {
    reloadRequired,
    url,
    setUrl: updateUrl,
    serverSources,
    collections,
    selectedCollectionId,
    selectCollection,
    entries,
    itemStates,
    status,
    phase,
    isError,
    compatibilityWarning,
    canRun: entries.length > 0 && !isRunning,
    isRunning,
    playlistName,
    runModeId,
    setRunMode,
    regenerateDurationOutliers,
    setRegenerateDurationOutliers,
    resumeBanner,
    acceptResume,
    dismissResume,
    failedEntries,
    rerunFailed,
    retryPlaylist,
    retryDownload,
    adoptSelectedClips,
    run,
    stop,
  };
}
