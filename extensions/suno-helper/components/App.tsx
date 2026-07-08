import { useEffect, useRef, useState } from "react";

import { DOWNLOAD_FORMAT_DEFAULT, RUN_MODES, type RunModeId } from "../../shared/constants";
import {
  buildInitialPatternSelection,
  reconcilePatternSelection,
  selectedEntryCount as countSelectedEntries,
} from "../lib/pattern-selection";
import { buildSelectedEntriesRunOverrides } from "../lib/run-overrides";
import { downloadFormatItem, readDownloadFormat, type DownloadFormat } from "../lib/storage";
import { PatternList } from "./PatternList";
import { useSunoRunner } from "./useSunoRunner";

// RUN_MODES のキー集合から導出する（手書き複製だと mode 追加時に UI へ出ないまま型チェックが通る）。
// Record の string キーは挿入順で列挙されるため、表示順は RUN_MODES の定義順 = serial, queue。
const RUN_MODE_ORDER = Object.keys(RUN_MODES) as RunModeId[];
const DOWNLOAD_FORMAT_OPTIONS: DownloadFormat[] = ["mp3", "m4a", "wav"];

export function App() {
  const [downloadFormat, setDownloadFormat] = useState<DownloadFormat>(DOWNLOAD_FORMAT_DEFAULT);
  const [selectedEntries, setSelectedEntries] = useState<boolean[]>([]);
  const {
    url,
    setUrl,
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
    canRun,
    isRunning,
    playlistName,
    runModeId,
    setRunMode,
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
  } = useSunoRunner();
  const previousEntriesRef = useRef(entries);
  const previousItemStatesRef = useRef(itemStates);

  const visibleResumeBanner = resumeBanner && resumeBanner.failedIndex < resumeBanner.total ? resumeBanner : null;

  useEffect(() => {
    let mounted = true;
    void readDownloadFormat().then((value) => {
      if (mounted) {
        setDownloadFormat(value);
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  const updateDownloadFormat = (value: DownloadFormat): void => {
    setDownloadFormat(value);
    void downloadFormatItem.setValue(value);
  };

  useEffect(() => {
    const previousEntries = previousEntriesRef.current;
    const previousItemStates = previousItemStatesRef.current;
    setSelectedEntries((selection) =>
      reconcilePatternSelection({
        selection,
        previousEntries,
        previousItemStates,
        entries,
        itemStates,
      }),
    );
    previousEntriesRef.current = entries;
    previousItemStatesRef.current = itemStates;
  }, [entries, itemStates]);

  const toggleEntrySelection = (index: number, checked: boolean): void => {
    setSelectedEntries((selection) =>
      reconcilePatternSelection({
        selection,
        previousEntries: previousEntriesRef.current,
        previousItemStates: previousItemStatesRef.current,
        entries,
        itemStates,
      }).map((selected, i) => (i === index ? checked : selected)),
    );
  };

  const resolvedSelectedEntries =
    selectedEntries.length === entries.length ? selectedEntries : buildInitialPatternSelection(entries, itemStates);
  const selectedEntryCount = countSelectedEntries({
    selectedEntries: resolvedSelectedEntries,
    itemStates,
    entryCount: entries.length,
  });
  const canRunSelectedEntries = canRun && selectedEntryCount > 0;
  const runButtonLabel =
    entries.length > 0 && selectedEntryCount === 0
      ? "実行対象を選択"
      : entries.length > 0 && selectedEntryCount < entries.length
        ? `選択した${selectedEntryCount}件を連続実行`
        : "全パターンを連続実行";

  const runSelectedEntries = (): void => {
    if (selectedEntryCount === 0) {
      return;
    }
    void run(
      buildSelectedEntriesRunOverrides({
        selectedEntries: resolvedSelectedEntries,
        itemStates,
        entryCount: entries.length,
      }),
    );
  };
  return (
    <div
      className="flex flex-col gap-3 p-3 text-gray-900"
      data-suno-helper="control-panel"
      data-suno-phase={phase}
      data-suno-running={isRunning ? "true" : "false"}
      data-suno-error={isError ? "true" : "false"}
      data-suno-collection-id={selectedCollectionId}
      data-suno-entry-count={entries.length}
      data-suno-selected-entry-count={selectedEntryCount}
    >
      <h1 className="text-base font-semibold">Suno Helper</h1>

      <label className="flex flex-col gap-1 text-sm">
        ローカル配信元
        <select
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          data-suno-control="server-url"
          className="rounded border border-gray-300 px-2 py-1"
        >
          {serverSources.map((source) => (
            <option key={source.url} value={source.url}>
              {source.label} - {source.url}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-sm">
        コレクション
        <select
          value={selectedCollectionId}
          onChange={(e) => selectCollection(e.target.value)}
          data-suno-control="collection-select"
          className="rounded border border-gray-300 px-2 py-1"
        >
          {collections.length === 0 && (
            <option value="" disabled>
              コレクションなし
            </option>
          )}
          {collections.map((c) => (
            <option key={c.id} value={c.id} disabled={c.status === "needs_prompts"}>
              {c.status !== "needs_prompts" ? `${c.name} (${c.pattern_count})` : `${c.name}（prompts なし）`}
            </option>
          ))}
        </select>
      </label>

      {playlistName && (
        <p className="text-xs text-gray-600">
          Playlist: <span className="font-medium">{playlistName}</span>
        </p>
      )}

      {visibleResumeBanner && (
        <div className="flex flex-col gap-2 rounded border border-amber-300 bg-amber-50 px-2 py-2 text-xs text-amber-900">
          <p>
            前回の実行が中断されました。entry{" "}
            <span className="font-semibold">{visibleResumeBanner.failedIndex + 1}</span> から再開しますか？
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={acceptResume}
              data-suno-control="resume"
              className="rounded bg-amber-600 px-2 py-1 text-white hover:bg-amber-500"
            >
              再開
            </button>
            <button
              type="button"
              onClick={dismissResume}
              data-suno-control="dismiss-resume"
              className="rounded border border-amber-400 px-2 py-1 hover:bg-amber-100"
            >
              閉じる
            </button>
          </div>
        </div>
      )}

      {compatibilityWarning && (
        <div className="rounded border border-amber-300 bg-amber-50 px-2 py-2 text-xs text-amber-900">
          {compatibilityWarning}
        </div>
      )}

      {/* 失敗スキップされた entry の再実行導線 (#948)。実行中は隠す。 */}
      {failedEntries.length > 0 && !isRunning && (
        <div className="flex flex-col gap-2 rounded border border-red-300 bg-red-50 px-2 py-2 text-xs text-red-900">
          <p>
            失敗してスキップされた entry:{" "}
            <span className="font-semibold">{failedEntries.map((i) => i + 1).join(", ")}</span>
          </p>
          <button
            type="button"
            onClick={rerunFailed}
            className="self-start rounded bg-red-600 px-2 py-1 text-white hover:bg-red-500"
          >
            失敗分のみ再実行
          </button>
        </div>
      )}

      <fieldset className="flex flex-col gap-2 rounded border border-gray-200 px-2 py-2 text-sm">
        <legend className="px-1 text-xs text-gray-600">投入方式</legend>
        {RUN_MODE_ORDER.map((id) => {
          const mode = RUN_MODES[id];
          return (
            <label key={id} className="flex items-start gap-2">
              <input
                type="radio"
                name="run-mode"
                className="mt-1"
                checked={runModeId === id}
                // 実行中の切替は当該 run に効かないのに保存だけ即時反映され、次回 resume の
                // モードを無言で変えてしまうため run 中は無効化する (#1586 review)。
                disabled={isRunning}
                onChange={() => setRunMode(id)}
              />
              <span className="flex flex-col">
                <span className="font-medium">{mode.label}</span>
                <span className="text-xs text-gray-500">{mode.riskNote}</span>
              </span>
            </label>
          );
        })}
      </fieldset>

      <label className="flex flex-col gap-1 text-sm">
        DL 形式
        <select
          value={downloadFormat}
          onChange={(e) => updateDownloadFormat(e.target.value as DownloadFormat)}
          className="rounded border border-gray-300 px-2 py-1"
        >
          {DOWNLOAD_FORMAT_OPTIONS.map((format) => (
            <option key={format} value={format}>
              {format.toUpperCase()}
            </option>
          ))}
        </select>
      </label>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void fetchData()}
          data-suno-control="fetch-data"
          className="flex-1 rounded bg-gray-800 px-2 py-1 text-sm text-white hover:bg-gray-700"
        >
          データ取得
        </button>
        <button
          type="button"
          onClick={runSelectedEntries}
          disabled={!canRunSelectedEntries}
          data-suno-control="run"
          className="flex-1 rounded bg-blue-600 px-2 py-1 text-sm text-white hover:bg-blue-500 disabled:opacity-40"
        >
          {runButtonLabel}
        </button>
        <button
          type="button"
          onClick={() => void stop()}
          disabled={!isRunning}
          data-suno-control="stop"
          className="rounded bg-red-600 px-2 py-1 text-sm text-white hover:bg-red-500 disabled:opacity-40"
        >
          停止
        </button>
      </div>

      {!isRunning && selectedCollectionId && (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={() => void adoptSelectedClips()}
            data-suno-control="adopt-selected-clips"
            className="rounded border border-gray-400 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
          >
            選択中の曲を採用
          </button>
          <div className="flex gap-2">
            {playlistName && (
              <button
                type="button"
                onClick={() => void retryPlaylist()}
                data-suno-control="retry-playlist"
                className="flex-1 rounded border border-amber-500 px-2 py-1 text-xs text-amber-700 hover:bg-amber-50"
              >
                Playlist から再開
              </button>
            )}
            <button
              type="button"
              onClick={() => void retryDownload()}
              disabled={!selectedCollectionId}
              data-suno-control="retry-download"
              className="flex-1 rounded border border-green-500 px-2 py-1 text-xs text-green-700 hover:bg-green-50 disabled:opacity-40"
            >
              Download から再開
            </button>
          </div>
        </div>
      )}

      <PatternList
        entries={entries}
        itemStates={itemStates}
        selectedEntries={resolvedSelectedEntries}
        onToggleEntry={toggleEntrySelection}
      />

      {status && (
        <p
          role="status"
          aria-live="polite"
          data-suno-status={isError ? "error" : "ok"}
          className={`whitespace-pre-wrap text-xs ${isError ? "text-red-600" : "text-gray-600"}`}
        >
          {status}
        </p>
      )}
    </div>
  );
}
