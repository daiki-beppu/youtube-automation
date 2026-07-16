import { useEffect, useRef, useState } from "react";

import { DOWNLOAD_FORMAT_DEFAULT, formatServerSourceLabel, RUN_MODES, type RunModeId } from "../../shared/constants";
import {
  buildInitialPatternSelection,
  reconcilePatternSelection,
  selectedEntryCount as countSelectedEntries,
} from "../lib/pattern-selection";
import { buildSelectedEntriesRunOverrides } from "../lib/run-overrides";
import { downloadFormatItem, readDownloadFormat, type DownloadFormat } from "../lib/storage";
import { PatternList } from "./PatternList";
import { ReloadRequiredNotice } from "./ReloadRequiredNotice";
import { Button, ButtonSlot } from "./ui/button";
import { useSunoRunner } from "./useSunoRunner";

// RUN_MODES のキー集合から導出する（手書き複製だと mode 追加時に UI へ出ないまま型チェックが通る）。
// Record の string キーは挿入順で列挙されるため、表示順は RUN_MODES の定義順 = serial, queue。
const RUN_MODE_ORDER = Object.keys(RUN_MODES) as RunModeId[];
const DOWNLOAD_FORMAT_OPTIONS: DownloadFormat[] = ["mp3", "m4a", "wav"];

export function App() {
  const [downloadFormat, setDownloadFormat] = useState<DownloadFormat>(DOWNLOAD_FORMAT_DEFAULT);
  const [reloadRequired, setReloadRequired] = useState(false);
  const [selectedEntries, setSelectedEntries] = useState<boolean[]>([]);
  const {
    reloadRequired: runnerReloadRequired,
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
  } = useSunoRunner();
  const previousEntriesRef = useRef(entries);
  const previousItemStatesRef = useRef(itemStates);

  const visibleResumeBanner = resumeBanner && resumeBanner.failedIndex < resumeBanner.total ? resumeBanner : null;

  useEffect(() => {
    let mounted = true;
    void readDownloadFormat()
      .then((value) => {
        if (mounted) {
          setDownloadFormat(value);
        }
      })
      .catch((error: unknown) => {
        console.warn(
          "[suno-helper] ダウンロード形式の読込に失敗しました（拡張更新後はタブを再読み込みしてください）:",
          error,
        );
        if (mounted) {
          setReloadRequired(true);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  const updateDownloadFormat = (value: DownloadFormat): void => {
    setDownloadFormat(value);
    void downloadFormatItem.setValue(value).catch((error: unknown) => {
      console.warn(
        "[suno-helper] ダウンロード形式の保存に失敗しました（拡張更新後はタブを再読み込みしてください）:",
        error,
      );
      setReloadRequired(true);
    });
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
  if (reloadRequired || runnerReloadRequired) {
    return <ReloadRequiredNotice />;
  }

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
              {formatServerSourceLabel(source, "suno-helper")}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-sm">
        コレクション
        <ButtonSlot variant="outline" size="sm" className="w-full justify-between font-normal">
          <select
            value={selectedCollectionId}
            onChange={(e) => selectCollection(e.target.value)}
            data-suno-control="collection-select"
          >
            {collections.length === 0 && (
              <option value="" disabled>
                コレクションなし
              </option>
            )}
            {collections.map((c) => (
              <option key={c.id} value={c.id} disabled={c.status === "needs_prompts"}>
                {c.status === "downloaded"
                  ? `${c.name}（完了 ${c.downloaded_count}/${c.expected_file_count ?? (c.pattern_count ?? 0) * 2}）`
                  : c.status === "ready"
                    ? `${c.name} (${c.pattern_count})`
                    : `${c.name}（prompts なし）`}
              </option>
            ))}
          </select>
        </ButtonSlot>
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
            <Button type="button" onClick={acceptResume} data-suno-control="resume" size="sm">
              再開
            </Button>
            <Button
              type="button"
              onClick={dismissResume}
              data-suno-control="dismiss-resume"
              variant="outline"
              size="sm"
            >
              閉じる
            </Button>
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
          <Button type="button" onClick={rerunFailed} variant="destructive" size="sm" className="self-start">
            失敗分のみ再実行
          </Button>
        </div>
      )}

      <fieldset className="flex flex-col gap-2 rounded border border-gray-200 px-2 py-2 text-sm">
        <legend className="px-1 text-xs text-gray-600">投入方式</legend>
        {RUN_MODE_ORDER.map((id) => {
          const mode = RUN_MODES[id];
          return (
            <ButtonSlot
              key={id}
              variant={runModeId === id ? "default" : "outline"}
              size="sm"
              className="h-auto w-full justify-start whitespace-normal p-2"
            >
              <label className="flex items-start gap-2">
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
            </ButtonSlot>
          );
        })}
      </fieldset>

      <label className="flex items-start gap-2 rounded border border-gray-200 px-2 py-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={regenerateDurationOutliers}
          disabled={entries.length === 0 || isRunning}
          onChange={(event) => setRegenerateDurationOutliers(event.target.checked)}
        />
        <span className="flex flex-col">
          <span className="font-medium">異常値の曲を再生成する</span>
          {!regenerateDurationOutliers && (
            <span className="text-xs text-amber-700">
              OFF の場合、duration guard NG も Playlist / Download 候補に残ります。完了後に手動確認してください。
            </span>
          )}
        </span>
      </label>

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
        <Button
          type="button"
          onClick={runSelectedEntries}
          disabled={!canRunSelectedEntries}
          data-suno-control="run"
          size="sm"
          className="flex-1"
        >
          {runButtonLabel}
        </Button>
        <Button
          type="button"
          onClick={() => void stop()}
          disabled={!isRunning}
          data-suno-control="stop"
          variant="destructive"
          size="sm"
        >
          停止
        </Button>
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
              <Button
                type="button"
                onClick={() => void retryPlaylist()}
                data-suno-control="retry-playlist"
                variant="outline"
                size="sm"
                className="flex-1"
              >
                Playlist から再開
              </Button>
            )}
            <Button
              type="button"
              onClick={() => void retryDownload()}
              disabled={!selectedCollectionId}
              data-suno-control="retry-download"
              variant="outline"
              size="sm"
              className="flex-1"
            >
              Download から再開
            </Button>
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
