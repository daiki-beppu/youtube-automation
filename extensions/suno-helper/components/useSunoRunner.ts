// popup の状態管理フック。旧 popup.js の挙動 (取得 / 連続実行 / 停止 / 進捗・エラー表示) を保持する。
import { useCallback, useEffect, useState } from "react";
import { browser } from "wxt/browser";

import {
  type CollectionSummary,
  fetchCollectionPrompts,
  fetchCollections,
  fetchPrompts,
  pickInitialCollectionId,
  type PromptEntry,
} from "../../shared/api";
import { type ItemState, PHASE } from "../../shared/constants";
import { onMessage, sendMessage } from "../lib/messaging";
import { isTerminalPhase, nextItemStates } from "../lib/snapshot";
import { serverUrlItem } from "../lib/storage";
import { buildRestoreState, formatRunError, formatStopError, phaseToStatus } from "./runner-errors";

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
  canRun: boolean;
  isRunning: boolean;
  fetchData: () => Promise<void>;
  run: () => Promise<void>;
  stop: () => Promise<void>;
}

async function activeTabId(): Promise<number> {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  if (typeof tab?.id !== "number") {
    throw new Error("アクティブなタブが見つかりません。");
  }
  return tab.id;
}

export function useSunoRunner(): RunnerState {
  const [url, setUrl] = useState("");
  const [collections, setCollections] = useState<CollectionSummary[]>([]);
  const [selectedCollectionId, setSelectedCollectionId] = useState("");
  const [entries, setEntries] = useState<PromptEntry[]>([]);
  const [itemStates, setItemStates] = useState<ItemState[]>([]);
  const [status, setStatus] = useState("");
  const [isError, setIsError] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

  const report = useCallback((text: string, error = false) => {
    setStatus(text);
    setIsError(error);
  }, []);

  const loadCollections = useCallback(async (baseUrl: string) => {
    try {
      const list = await fetchCollections(baseUrl);
      setCollections(list);
      setSelectedCollectionId(pickInitialCollectionId(list) ?? "");
    } catch {
      // 単一ファイル mode サーバーは `/collections` が 404。ドロップダウンを出さず単一 mode へ fallback。
      setCollections([]);
      setSelectedCollectionId("");
    }
  }, []);

  useEffect(() => {
    void serverUrlItem.getValue().then((stored) => {
      setUrl(stored);
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

  // popup 再 open 時、content が保持する snapshot から進捗を即時復元する (#852)。
  // Suno タブでない / content 未注入は queryProgress が失敗 → 復元せず従来表示へ silent fallback。
  useEffect(() => {
    void (async () => {
      try {
        const tabId = await activeTabId();
        const snapshot = await sendMessage("queryProgress", undefined, tabId);
        const restored = buildRestoreState(snapshot);
        if (!restored) {
          return;
        }
        setEntries(restored.entries);
        setItemStates(restored.itemStates);
        setIsRunning(restored.isRunning);
        report(restored.status, restored.isError);
      } catch {
        // Suno タブでない / content 未注入では queryProgress が到達しない。復元を諦め従来表示を維持する。
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
    try {
      // collection を選択している場合は dir mode の個別配信、未選択なら単一ファイル mode へ fallback。
      const data = selectedCollectionId
        ? await fetchCollectionPrompts(trimmed, selectedCollectionId)
        : await fetchPrompts(trimmed);
      setEntries(data);
      setItemStates(data.map(() => "idle"));
      report(`${data.length} パターンを取得しました。`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setEntries([]);
      setItemStates([]);
      report(`取得失敗: ${message}\nyt-collection-serve が起動しているか確認してください。`, true);
    }
  }, [url, selectedCollectionId, report]);

  const run = useCallback(async () => {
    if (entries.length === 0) {
      return;
    }
    try {
      const tabId = await activeTabId();
      await sendMessage("run", entries, tabId);
      setIsRunning(true);
      report("連続実行を開始しました。");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      report(formatRunError(message), true);
    }
  }, [entries, report]);

  const stop = useCallback(async () => {
    try {
      const tabId = await activeTabId();
      await sendMessage("stop", undefined, tabId);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      report(formatStopError(message), true);
    }
  }, [report]);

  return {
    url,
    setUrl,
    collections,
    selectedCollectionId,
    selectCollection: setSelectedCollectionId,
    entries,
    itemStates,
    status,
    isError,
    canRun: entries.length > 0 && !isRunning,
    isRunning,
    fetchData,
    run,
    stop,
  };
}
