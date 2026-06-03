// popup の状態管理フック。旧 popup.js の挙動 (取得 / 連続実行 / 停止 / 進捗・エラー表示) を保持する。
import { useCallback, useEffect, useState } from "react";
import { browser } from "wxt/browser";

import { fetchPrompts, type PromptEntry } from "../../shared/api";
import { PHASE } from "../../shared/constants";
import { onMessage, sendMessage } from "../lib/messaging";
import { serverUrlItem } from "../lib/storage";

export type ItemState = "idle" | "active" | "done";

interface RunnerState {
  url: string;
  setUrl: (url: string) => void;
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
  const [entries, setEntries] = useState<PromptEntry[]>([]);
  const [itemStates, setItemStates] = useState<ItemState[]>([]);
  const [status, setStatus] = useState("");
  const [isError, setIsError] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

  const report = useCallback((text: string, error = false) => {
    setStatus(text);
    setIsError(error);
  }, []);

  useEffect(() => {
    void serverUrlItem.getValue().then(setUrl);
  }, []);

  useEffect(() => {
    const unwatch = onMessage("progress", ({ data }) => {
      const { phase, index, total, message } = data;
      switch (phase) {
        case PHASE.INJECTING:
          setItemStates((prev) =>
            prev.map((_, i) => (i === index ? "active" : prev[i] === "active" ? "idle" : prev[i])),
          );
          report(`[${(index ?? 0) + 1}/${total}] 注入中: ${entries[index ?? 0]?.name ?? ""}`);
          break;
        case PHASE.GENERATING:
          report(`[${(index ?? 0) + 1}/${total}] 生成待ち…`);
          break;
        case PHASE.DONE:
          setItemStates((prev) => prev.map((s, i) => (i === index ? "done" : s)));
          break;
        case PHASE.FINISHED:
          report(`完了: ${total} パターンを実行しました。`);
          setIsRunning(false);
          break;
        case PHASE.STOPPED:
          report("停止しました。手動で続行できます。", true);
          setIsRunning(false);
          break;
        case PHASE.ERROR:
          report(`中断: ${message ?? ""}`, true);
          setIsRunning(false);
          break;
      }
    });
    return () => unwatch();
  }, [entries, report]);

  const fetchData = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      report("サーバー URL を入力してください。", true);
      return;
    }
    await serverUrlItem.setValue(trimmed);
    report("取得中…");
    try {
      const data = await fetchPrompts(trimmed);
      setEntries(data);
      setItemStates(data.map(() => "idle"));
      report(`${data.length} パターンを取得しました。`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setEntries([]);
      setItemStates([]);
      report(`取得失敗: ${message}\nyt-collection-serve が起動しているか確認してください。`, true);
    }
  }, [url, report]);

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
      report(`開始失敗: ${message}\nSuno の Custom Mode 画面を開いた状態で実行してください。`, true);
    }
  }, [entries, report]);

  const stop = useCallback(async () => {
    try {
      const tabId = await activeTabId();
      await sendMessage("stop", undefined, tabId);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      report(`停止リクエスト失敗: ${message}`, true);
    }
  }, [report]);

  return {
    url,
    setUrl,
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
