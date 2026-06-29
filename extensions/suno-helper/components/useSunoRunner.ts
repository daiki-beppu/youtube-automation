// overlay / popup 共用の状態管理フック。旧 popup.js の挙動 (取得 / 連続実行 / 停止 / 進捗・エラー表示) を保持する。
// run / stop / queryProgress / progress は tabId を指定せず background 宛に送る（#892）。overlay は
// content script で `browser.tabs.*` を呼べないため、background が送信元と同一タブの runner content へ中継する
// （中継ロジックは entrypoints/background.ts + lib/overlay-relay.ts）。
import { useCallback, useEffect, useMemo, useState } from "react";
import { browser } from "wxt/browser";

import {
  type CollectionSummary,
  extractPlaylistName,
  type PromptEntry,
  resolvePromptCollectionId,
  visiblePromptCollections,
} from "../../shared/api";
import { CLIPS_PER_REQUEST, type ItemState, PHASE, type SpeedPresetId } from "../../shared/constants";
import { onMessage, sendMessage } from "../lib/messaging";
import { DEFAULT_SPEED_PRESET_ID, readSpeedPresetId, writeSpeedPresetId } from "../lib/preset-state";
import {
  readResumeState,
  resolvePlaylistExpectedClipCountForResume,
  type ResumeBanner,
  type ResumeState,
  resolveRunRange,
  resumeBannerRange,
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
import { serverUrlItem } from "../lib/storage";
import { buildRestoreState, formatRunError, formatStopError, phaseToStatus } from "./runner-errors";

/** 実行範囲モード (#872)。all=全パターン / range=範囲指定。 */
export type RangeMode = "all" | "range";

interface RunnerState {
  url: string;
  setUrl: (url: string) => void;
  collections: CollectionSummary[];
  selectedCollectionId: string;
  selectCollection: (id: string) => void;
  entries: PromptEntry[];
  itemStates: ItemState[];
  status: string;
  isError: boolean;
  compatibilityWarning: string;
  canRun: boolean;
  isRunning: boolean;
  // collection 選択時の playlist 名 (#854)。display only（単一ファイル mode は undefined）。
  playlistName: string | undefined;
  // 実行範囲 UI の状態 (#872)。range モード時のみ start/end を使う。
  rangeMode: RangeMode;
  setRangeMode: (mode: RangeMode) => void;
  rangeStart: string;
  setRangeStart: (value: string) => void;
  rangeEnd: string;
  setRangeEnd: (value: string) => void;
  // 速度プリセット (#875)。実行モード selector の選択値。永続化は setSpeedPreset 内で行う。
  speedPresetId: SpeedPresetId;
  setSpeedPreset: (id: SpeedPresetId) => void;
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
  fetchData: () => Promise<void>;
  // overrides.range があればそれを使う (#892 要件6)。未指定時は range UI の状態から解決する（従来挙動）。
  // overrides.indices は失敗分のみ再実行 (#948)。指定時は range より優先される。
  run: (overrides?: RunOverrides) => Promise<void>;
  stop: () => Promise<void>;
}

type PromptSource = { kind: "collection"; collectionId: string | null } | { kind: "single-file" };

async function fetchCollectionEntries(baseUrl: string, collectionId: string | null): Promise<PromptEntry[]> {
  if (collectionId === null) {
    throw new Error("prompts を取得できる collection がありません。");
  }
  return sendMessage("fetchCollectionPrompts", { baseUrl, collectionId });
}

export function useSunoRunner(): RunnerState {
  const [url, setUrlState] = useState("");
  const [allCollections, setAllCollections] = useState<CollectionSummary[]>([]);
  const [selectedCollectionIdState, setSelectedCollectionId] = useState("");
  const [entries, setEntries] = useState<PromptEntry[]>([]);
  const [itemStates, setItemStates] = useState<ItemState[]>([]);
  const [status, setStatus] = useState("");
  const [isError, setIsError] = useState(false);
  const [compatibilityWarning, setCompatibilityWarning] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  // popup 再 open 時に content snapshot から復元する playlist 名 (#854)。
  // 選択由来 (derivedPlaylistName) が無い実行中復元ケースで display only に使う。
  const [restoredPlaylistName, setRestoredPlaylistName] = useState<string | undefined>(undefined);
  // content snapshot 由来の失敗 index (#872 要件3)。chrome.storage の resume state が失われても、
  // 現在タブの live snapshot が ERROR phase で保持する failedIndex を再開バナーの冗長ソースにする。
  const [restoredFailedIndex, setRestoredFailedIndex] = useState<number | undefined>(undefined);
  // content snapshot 由来のスキップ済み失敗 index 一覧 (#948)。chrome.storage と二重化する。
  const [restoredFailedIndices, setRestoredFailedIndices] = useState<number[] | undefined>(undefined);
  const [restoredSubmittedClipIds, setRestoredSubmittedClipIds] = useState<string[] | undefined>(undefined);
  const [restoredPlaylistExpectedClipCount, setRestoredPlaylistExpectedClipCount] = useState<number | undefined>(
    undefined,
  );
  // 実行範囲 UI の状態 (#872)。rangeStart/rangeEnd は入力欄の生文字列（1-based 表示）。
  const [rangeMode, setRangeMode] = useState<RangeMode>("all");
  const [rangeStart, setRangeStart] = useState("");
  const [rangeEnd, setRangeEnd] = useState("");
  // 速度プリセット (#875)。マウント時に storage から復元し、選択時に永続化する。初期値は既定 (Balanced)。
  const [speedPresetId, setSpeedPresetId] = useState<SpeedPresetId>(DEFAULT_SPEED_PRESET_ID);
  // chrome.storage から読んだ前回の ERROR 停止 state (#872)。表示可否は selectedCollectionId と時刻で判定する。
  const [persistedResume, setPersistedResume] = useState<ResumeState | null>(null);
  // resume state を読んだ popup 起動時刻 (#872)。stale 判定の基準 now をここで一度だけ確定し、
  // render 中の Date.now()（非純粋）を避ける。
  const [resumeCheckedAt, setResumeCheckedAt] = useState<number | null>(null);
  // 一度承認/却下したバナーは再表示しない（同一 popup セッション内）。
  const [resumeDismissed, setResumeDismissed] = useState(false);

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
      const visibleCollections = visiblePromptCollections(source, resumableCollectionId ? [resumableCollectionId] : []);
      const preferredSelectedId = currentSelectedId || resumableCollectionId || "";
      const nextSelectedId = resolvePromptCollectionId(
        visibleCollections,
        preferredSelectedId,
        Boolean(resumableCollectionId),
      );
      return { visibleCollections, nextSelectedId };
    },
    [resumableCollectionId],
  );

  const { visibleCollections: collections, nextSelectedId } = useMemo(
    () => resolveVisibleCollections(allCollections, selectedCollectionIdState),
    [allCollections, resolveVisibleCollections, selectedCollectionIdState],
  );
  const selectedCollectionId = nextSelectedId ?? "";

  // collection 選択から導出する playlist 名 (#854)。未選択（単一ファイル mode）は undefined。
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
      return { failedIndex: persistedResume.failedIndex, total: persistedResume.total };
    }
    // 2) content snapshot 由来 (要件3 二重化)。chrome.storage 書込が失われても、現在タブの
    //    実行セッションが ERROR phase で保持する failedIndex から同じ再開導線を出す。snapshot は
    //    当該タブのセッションそのものなので collection 一致 / stale 判定は不要。
    if (restoredFailedIndex !== undefined && entries.length > 0) {
      return { failedIndex: restoredFailedIndex, total: entries.length };
    }
    return null;
  }, [persistedResume, selectedCollectionId, resumeDismissed, resumeCheckedAt, restoredFailedIndex, entries.length]);

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
    return restoredFailedIndices ?? [];
  }, [persistedResume, selectedCollectionId, resumeCheckedAt, restoredFailedIndices]);

  const submittedClipIdsForResume = useMemo<string[]>(() => {
    if (
      resumeCheckedAt !== null &&
      persistedResume &&
      shouldShowResumeBanner(persistedResume, selectedCollectionId, resumeCheckedAt)
    ) {
      return persistedResume.submittedClipIds ?? [];
    }
    return restoredSubmittedClipIds ?? [];
  }, [persistedResume, selectedCollectionId, resumeCheckedAt, restoredSubmittedClipIds]);

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
    if (restoredFailedIndex !== undefined && entries.length > 0) {
      return resolvePlaylistExpectedClipCountForResume(restoredPlaylistExpectedClipCount, entries.length);
    }
    return undefined;
  }, [
    persistedResume,
    selectedCollectionId,
    resumeCheckedAt,
    restoredFailedIndex,
    restoredPlaylistExpectedClipCount,
    entries.length,
  ]);

  const expectedClipCountForManualAdoption = useMemo<number | undefined>(() => {
    if (playlistExpectedClipCountForResume !== undefined) {
      return playlistExpectedClipCountForResume;
    }
    if (entries.length > 0) {
      return entries.length * CLIPS_PER_REQUEST;
    }
    if (selectedCollection?.expected_file_count) {
      return selectedCollection.expected_file_count;
    }
    if (selectedCollection?.pattern_count) {
      return selectedCollection.pattern_count * CLIPS_PER_REQUEST;
    }
    return undefined;
  }, [playlistExpectedClipCountForResume, entries.length, selectedCollection]);

  const report = useCallback((text: string, error = false) => {
    setStatus(text);
    setIsError(error);
  }, []);

  // popup 起動時に前回の ERROR 停止 state を読む (#872 要件4)。表示可否は resumeBanner 側で判定する。
  // 基準 now は読み込み完了時に確定する（render 中の Date.now() を避けるため effect 内で取得）。
  useEffect(() => {
    void readResumeState().then((state) => {
      setPersistedResume(state);
      setResumeCheckedAt(Date.now());
    });
  }, []);

  // popup 起動時に永続化済みの速度プリセットを復元する (#875 要件2)。
  useEffect(() => {
    void readSpeedPresetId().then(setSpeedPresetId);
  }, []);

  // 速度プリセットの選択を即時永続化する (#875 要件2)。content は run 開始時に storage から読む。
  const setSpeedPreset = useCallback((id: SpeedPresetId) => {
    setSpeedPresetId(id);
    void writeSpeedPresetId(id);
  }, []);

  const dismissResume = useCallback(() => {
    setResumeDismissed(true);
  }, []);

  const clearLoadedRunState = useCallback(() => {
    setEntries([]);
    setItemStates([]);
    setRestoredPlaylistName(undefined);
    setRestoredFailedIndex(undefined);
    setRestoredFailedIndices(undefined);
    setRestoredSubmittedClipIds(undefined);
    setRestoredPlaylistExpectedClipCount(undefined);
  }, []);

  const updateUrl = useCallback(
    (nextUrl: string) => {
      setUrlState(nextUrl);
      clearLoadedRunState();
    },
    [clearLoadedRunState],
  );

  const selectCollection = useCallback(
    (id: string) => {
      setSelectedCollectionId(id);
      clearLoadedRunState();
    },
    [clearLoadedRunState],
  );

  const applySingleFileMode = useCallback(() => {
    setAllCollections([]);
    setSelectedCollectionId("");
  }, []);

  const syncCollections = useCallback(
    async (baseUrl: string, currentSelectedId: string): Promise<PromptSource> => {
      try {
        const fetched = await sendMessage("fetchCollections", { baseUrl });
        setAllCollections(fetched);
        const { nextSelectedId } = resolveVisibleCollections(fetched, currentSelectedId);
        setSelectedCollectionId(nextSelectedId ?? "");
        return { kind: "collection", collectionId: nextSelectedId };
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        if (message === "HTTP 404" || err instanceof TypeError) {
          // 単一ファイル mode サーバーは `/collections` が 404。CORS ヘッダーなしの 404 は
          // ブラウザが TypeError (Failed to fetch) として reject するため両方を捕捉する。
          applySingleFileMode();
          return { kind: "single-file" };
        }
        throw err;
      }
    },
    [applySingleFileMode, resolveVisibleCollections],
  );

  const loadCollections = useCallback(
    async (baseUrl: string) => {
      try {
        await syncCollections(baseUrl, "");
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        report(`コレクション一覧取得失敗: ${message}`, true);
      }
    },
    [report, syncCollections],
  );

  useEffect(() => {
    void serverUrlItem.getValue().then((stored) => {
      setUrlState(stored);
      const trimmed = stored.trim();
      if (trimmed) {
        void loadCollections(trimmed);
      }
    });
  }, [loadCollections]);

  useEffect(() => {
    const unwatch = onMessage("progress", ({ data }) => {
      setItemStates((prev) => nextItemStates(prev, data.phase, data.index));
      // DONE は当該 item を done 化するだけで status 文字列は更新しない（旧 popup.js の live 挙動を維持）。
      // restore 経路は phaseToStatus(DONE) で「完了」を表示するため SSOT 側に DONE case は残す。
      if (data.phase !== PHASE.DONE) {
        const { text, error } = phaseToStatus(data, entries);
        report(text, Boolean(error));
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
        const restored = buildRestoreState(snapshot);
        if (!restored) {
          return;
        }
        setEntries(restored.entries);
        setItemStates(restored.itemStates);
        setIsRunning(restored.isRunning);
        setRestoredPlaylistName(restored.playlistName);
        // ERROR 停止の snapshot なら failedIndex を再開バナーの冗長ソースへ流す (#872 要件3)。
        setRestoredFailedIndex(restored.failedIndex);
        setRestoredFailedIndices(restored.failedIndices);
        setRestoredSubmittedClipIds(restored.submittedClipIds);
        setRestoredPlaylistExpectedClipCount(restored.playlistExpectedClipCount);
        report(restored.status, restored.isError);
      } catch {
        // runner content 未注入（中継先不在）では queryProgress が到達しない。復元を諦め従来表示を維持する。
      }
    })();
  }, [report]);

  const fetchData = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      report("サーバー URL を入力してください。", true);
      return;
    }
    await serverUrlItem.setValue(trimmed);
    report("取得中…");
    const extensionVersion = browser.runtime.getManifest().version;
    const warning = await sendMessage("fetchCompatibilityWarning", { baseUrl: trimmed, extensionVersion });
    setCompatibilityWarning(typeof warning === "string" ? warning : "");
    try {
      const promptSource = await syncCollections(trimmed, selectedCollectionId);
      const data =
        promptSource.kind === "single-file"
          ? await sendMessage("fetchPrompts", { baseUrl: trimmed })
          : await fetchCollectionEntries(trimmed, promptSource.collectionId);
      setEntries(data);
      setItemStates(data.map(() => "idle"));
      report(`${data.length} パターンを取得しました。`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setEntries([]);
      setItemStates([]);
      report(`取得失敗: ${message}\nyt-collection-serve が起動しているか確認してください。`, true);
    }
  }, [url, selectedCollectionId, syncCollections, report]);

  const run = useCallback(
    async (overrides?: RunOverrides) => {
      // 二重実行ガード (#892 要件7)。実行中の再入（「再開」連打等）を no-op で弾く。
      if (isRunning) {
        return;
      }
      if (entries.length === 0) {
        return;
      }
      // overrides.range（1-click 自動再開）があればそれを優先する (#892 要件6)。
      // 無ければ range UI の状態から解決する（従来挙動）。range モードの 1-based 入力は
      // 0-based inclusive へ変換し、不正入力は resolveRunRange が throw → fail-loud で UI に出す。
      let range = overrides?.range;
      if (range === undefined && overrides?.indices === undefined && rangeMode === "range") {
        try {
          const start = Number(rangeStart);
          const end = rangeEnd.trim() === "" ? undefined : Number(rangeEnd);
          range = resolveRunRange(start, end, entries.length);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          report(message, true);
          return;
        }
      }
      // 二重実行ガード成立後、送信前に実行中フラグを立てる (#892 要件7: setIsRunning を sendMessage の前へ)。
      setIsRunning(true);
      try {
        // collection mode は playlistName を伴って送る。単一ファイル mode は undefined で playlist phase を skip (#854)。
        // collectionId は ERROR 停止時の resume 紐付けに使う。単一ファイル mode（空文字）は undefined で送る (#872)。
        // tabId は指定せず background 宛に送り、同一タブの runner content へ中継させる (#892)。
        await sendMessage(
          "run",
          buildRunPayload({
            entries,
            playlistName: derivedPlaylistName,
            range,
            collectionId: selectedCollectionId,
            overrides,
          }),
        );
        report("連続実行を開始しました。");
      } catch (err) {
        // 送信失敗時はフラグを戻して再実行可能にする（実行は始まっていない）。
        setIsRunning(false);
        const message = err instanceof Error ? err.message : String(err);
        report(formatRunError(message), true);
      }
    },
    [isRunning, entries, rangeMode, rangeStart, rangeEnd, derivedPlaylistName, selectedCollectionId, report],
  );

  // playlist 追加のみ再実行。entries 不要のため retryPlaylist 専用メッセージを送る。
  const retryPlaylist = useCallback(async () => {
    if (isRunning) {
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
    const fullCollectionClipCount =
      selectedCollection?.expected_file_count ??
      (selectedCollection?.pattern_count ? selectedCollection.pattern_count * CLIPS_PER_REQUEST : undefined) ??
      (entries.length > 0 ? entries.length * CLIPS_PER_REQUEST : undefined) ??
      playlistExpectedClipCountForResume;
    const shouldDownload = fullCollectionClipCount !== undefined && expectedClipCount >= fullCollectionClipCount;
    if (submittedClipIdsForResume.length === 0 || expectedClipCount <= 0) {
      report(
        "playlist 再開に必要な clip ID がありません。Suno タブを開いたまま「データ取得」後に再試行してください。",
        true,
      );
      return;
    }
    setIsRunning(true);
    try {
      await sendMessage("retryPlaylist", {
        playlistName,
        submittedClipIds: submittedClipIdsForResume,
        expectedClipCount,
        collectionId: selectedCollectionId || undefined,
        shouldDownload,
      });
      setResumeDismissed(true);
      report("playlist 追加とダウンロードを再実行しています…");
    } catch (err) {
      setIsRunning(false);
      setResumeDismissed(false);
      const message = err instanceof Error ? err.message : String(err);
      report(formatRunError(message), true);
    }
  }, [
    isRunning,
    playlistName,
    entries.length,
    submittedClipIdsForResume,
    playlistExpectedClipCountForResume,
    selectedCollectionId,
    selectedCollection,
    report,
  ]);

  // バナー承認 = 1-click 自動再開 (#892 要件6)。failedIndex === total（全 entry 投入済み）のときは
  // entries 不要の retryPlaylist を使い、ページリロード後でも確実に playlist 追加を再実行する。
  // それ以外（途中中断）は従来通り run で entry 生成から再開する。
  const acceptResume = useCallback(() => {
    if (!resumeBanner) {
      return;
    }
    if (resumeBanner.failedIndex >= resumeBanner.total) {
      void retryPlaylist();
      return;
    }
    const prefilled = resumeBannerRange(resumeBanner);
    setRangeMode("range");
    setRangeStart(String(prefilled.start));
    setRangeEnd(String(prefilled.end));
    setResumeDismissed(true);
    void run(
      buildResumeRunOverrides(resumeBanner, {
        submittedClipIds: submittedClipIdsForResume,
        playlistExpectedClipCount: playlistExpectedClipCountForResume,
      }),
    );
  }, [resumeBanner, retryPlaylist, run, submittedClipIdsForResume, playlistExpectedClipCountForResume]);

  // ダウンロードのみ再実行 (#1251)。clip を再選択 → Download all を実行する。
  const retryDownload = useCallback(async () => {
    if (isRunning) {
      return;
    }
    if (!selectedCollectionId || !playlistName) {
      report("コレクションまたは playlist 名を解決できないため、ダウンロードを再開できません。", true);
      return;
    }
    if (submittedClipIdsForResume.length === 0) {
      report(
        "ダウンロード再開に必要な clip ID がありません。Suno タブを開いたまま「データ取得」後に再試行してください。",
        true,
      );
      return;
    }
    setIsRunning(true);
    try {
      await sendMessage("retryDownload", {
        collectionId: selectedCollectionId,
        playlistName,
        submittedClipIds: submittedClipIdsForResume,
        expectedClipCount: expectedClipCountForManualAdoption,
      });
      report("ダウンロードを再実行しています…");
    } catch (err) {
      setIsRunning(false);
      const message = err instanceof Error ? err.message : String(err);
      report(formatRunError(message), true);
    }
  }, [
    isRunning,
    selectedCollectionId,
    playlistName,
    submittedClipIdsForResume,
    expectedClipCountForManualAdoption,
    report,
  ]);

  const adoptSelectedClips = useCallback(async () => {
    if (isRunning) {
      return;
    }
    if (!selectedCollectionId) {
      report("コレクションを選択してから、選択中の曲を採用してください。", true);
      return;
    }
    if (expectedClipCountForManualAdoption === undefined || expectedClipCountForManualAdoption <= 0) {
      report("期待 clip 数を解決できません。データ取得後に再試行してください。", true);
      return;
    }
    setIsRunning(true);
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
        submittedClipIds: result.clipIds,
        playlistExpectedClipCount: expectedClipCountForManualAdoption,
      };
      await writeResumeState(nextResume);
      setPersistedResume(nextResume);
      setResumeCheckedAt(Date.now());
      setRestoredSubmittedClipIds(result.clipIds);
      setRestoredPlaylistExpectedClipCount(expectedClipCountForManualAdoption);
      setResumeDismissed(false);
      report(`選択中の曲 ${result.clipIds.length} 件を採用しました。Playlist / Download から再開できます。`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
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
    void run(
      buildFailedEntriesRunOverrides(failedEntries, {
        submittedClipIds: submittedClipIdsForResume,
        playlistExpectedClipCount: playlistExpectedClipCountForResume,
      }),
    );
  }, [failedEntries, run, submittedClipIdsForResume, playlistExpectedClipCountForResume]);

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
    url,
    setUrl: updateUrl,
    collections,
    selectedCollectionId,
    selectCollection,
    entries,
    itemStates,
    status,
    isError,
    compatibilityWarning,
    canRun: entries.length > 0 && !isRunning,
    isRunning,
    playlistName,
    rangeMode,
    setRangeMode,
    rangeStart,
    setRangeStart,
    rangeEnd,
    setRangeEnd,
    speedPresetId,
    setSpeedPreset,
    resumeBanner,
    acceptResume,
    dismissResume,
    failedEntries,
    rerunFailed,
    retryPlaylist,
    retryDownload,
    adoptSelectedClips,
    fetchData,
    run,
    stop,
  };
}
