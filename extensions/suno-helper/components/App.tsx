import {
  Alert,
  Button,
  ButtonSlot,
  Checkbox,
  RadioGroup,
  RadioGroupItem,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@youtube-automation/ui";
import { useEffect, useRef, useState } from "react";

import {
  DOWNLOAD_FORMAT_DEFAULT,
  formatServerSourceLabel,
  PHASE,
  RUN_MODES,
  type RunModeId,
} from "../../shared/constants";
import {
  buildInitialPatternSelection,
  reconcilePatternSelection,
  selectedEntryCount as countSelectedEntries,
} from "../lib/pattern-selection";
import { buildSelectedEntriesRunOverrides } from "../lib/run-overrides";
import {
  downloadFormatItem,
  readDownloadFormat,
  type DownloadFormat,
} from "../lib/storage";
import { CompletionSoundControls } from "./CompletionSoundControls";
import { PatternList } from "./PatternList";
import { ReloadRequiredNotice } from "./ReloadRequiredNotice";
import { useSunoRunner } from "./useSunoRunner";

// RUN_MODES のキー集合から導出する（手書き複製だと mode 追加時に UI へ出ないまま型チェックが通る）。
// Record の string キーは挿入順で列挙されるため、表示順は RUN_MODES の定義順 = serial, queue。
const RUN_MODE_ORDER = Object.keys(RUN_MODES) as RunModeId[];
const DOWNLOAD_FORMAT_OPTIONS: DownloadFormat[] = ["mp3", "m4a", "wav"];

export function App() {
  const [downloadFormat, setDownloadFormat] = useState<DownloadFormat>(
    DOWNLOAD_FORMAT_DEFAULT
  );
  const [reloadRequired, setReloadRequired] = useState(false);
  const [selectedEntries, setSelectedEntries] = useState<boolean[]>([]);
  const {
    reloadRequired: runnerReloadRequired,
    url,
    setUrl,
    serverSources,
    refreshServerSources,
    collections,
    selectedCollectionId,
    selectCollection,
    collectionQueue,
    runCollectionQueue,
    resumeCollectionQueue,
    entries,
    itemStates,
    status,
    phase,
    isError,
    compatibilityWarning,
    canRun,
    isRunning,
    completionSoundSettings,
    completionSoundSettingsLoaded,
    setCompletionSoundEnabled,
    setCompletionSoundPreset,
    previewCompletionSound,
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
  const queueInProgress = collectionQueue?.status === "running";
  const controlsLocked = isRunning || queueInProgress;
  const [selectedCollectionIds, setSelectedCollectionIds] = useState<string[]>(
    []
  );
  const previousEntriesRef = useRef(entries);
  const previousItemStatesRef = useRef(itemStates);
  const [refreshingServerSources, setRefreshingServerSources] = useState(false);
  const [serverSourcePickerOpen, setServerSourcePickerOpen] = useState(false);
  const isRunningRef = useRef(isRunning);
  useEffect(() => {
    isRunningRef.current = isRunning;
  }, [isRunning]);

  const openServerSourcePicker = (): void => {
    if (refreshingServerSources || controlsLocked) {
      return;
    }
    setServerSourcePickerOpen(false);
    setRefreshingServerSources(true);
    void refreshServerSources().finally(() => {
      setRefreshingServerSources(false);
      if (!isRunningRef.current) {
        setServerSourcePickerOpen(true);
      }
    });
  };

  const selectedServerSource =
    serverSources.find((source) => source.url === url) ?? serverSources[0];

  const visibleResumeBanner =
    resumeBanner && resumeBanner.failedIndex < resumeBanner.total
      ? resumeBanner
      : null;

  useEffect(() => {
    let mounted = true;
    void readDownloadFormat()
      .then((value) => {
        if (mounted) {
          setDownloadFormat(
            DOWNLOAD_FORMAT_OPTIONS.includes(value)
              ? value
              : DOWNLOAD_FORMAT_DEFAULT
          );
        }
      })
      .catch((error: unknown) => {
        console.warn(
          "[suno-helper] ダウンロード形式の読込に失敗しました（拡張更新後はタブを再読み込みしてください）:",
          error
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
        error
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
      })
    );
    previousEntriesRef.current = entries;
    previousItemStatesRef.current = itemStates;
  }, [entries, itemStates]);

  useEffect(() => {
    setSelectedCollectionIds((selectedIds) => {
      const visibleIds = new Set(
        collections.map((collection) => collection.id)
      );
      const retained = selectedIds.filter((id) => visibleIds.has(id));
      if (retained.length > 0) {
        return retained;
      }
      return selectedCollectionId ? [selectedCollectionId] : [];
    });
  }, [collections, selectedCollectionId]);

  const toggleCollectionSelection = (id: string, checked: boolean): void => {
    setSelectedCollectionIds((selectedIds) => {
      const selected = new Set(selectedIds);
      if (checked) {
        selected.add(id);
      } else {
        selected.delete(id);
      }
      const ordered = collections
        .map((collection) => collection.id)
        .filter((collectionId) => selected.has(collectionId));
      if (checked || id === selectedCollectionId) {
        const nextFocusedId = checked ? id : ordered[0];
        if (nextFocusedId) {
          selectCollection(nextFocusedId);
        }
      }
      return ordered;
    });
  };

  const toggleEntrySelection = (index: number, checked: boolean): void => {
    setSelectedEntries((selection) =>
      reconcilePatternSelection({
        selection,
        previousEntries: previousEntriesRef.current,
        previousItemStates: previousItemStatesRef.current,
        entries,
        itemStates,
      }).map((selected, i) => (i === index ? checked : selected))
    );
  };

  const resolvedSelectedEntries =
    selectedEntries.length === entries.length
      ? selectedEntries
      : buildInitialPatternSelection(entries, itemStates);
  const selectedEntryCount = countSelectedEntries({
    selectedEntries: resolvedSelectedEntries,
    itemStates,
    entryCount: entries.length,
  });
  const multipleCollectionsSelected = selectedCollectionIds.length > 1;
  const canRunSelectedEntries =
    canRun &&
    !queueInProgress &&
    selectedCollectionIds.length > 0 &&
    (multipleCollectionsSelected || selectedEntryCount > 0);
  const runButtonLabel = multipleCollectionsSelected
    ? `選択した${selectedCollectionIds.length}コレクションを連続実行`
    : entries.length > 0 && selectedEntryCount === 0
      ? "実行対象を選択"
      : entries.length > 0 && selectedEntryCount < entries.length
        ? `選択した${selectedEntryCount}件を連続実行`
        : "全パターンを連続実行";

  const runSelectedEntries = (): void => {
    if (selectedCollectionIds.length === 0) {
      return;
    }
    setServerSourcePickerOpen(false);
    if (multipleCollectionsSelected) {
      void runCollectionQueue(selectedCollectionIds);
      return;
    }
    if (selectedEntryCount === 0) {
      return;
    }
    void run(
      buildSelectedEntriesRunOverrides({
        selectedEntries: resolvedSelectedEntries,
        itemStates,
        entryCount: entries.length,
      })
    );
  };
  const serverSourcePickerVisible =
    serverSourcePickerOpen && !controlsLocked && !refreshingServerSources;
  if (reloadRequired || runnerReloadRequired) {
    return <ReloadRequiredNotice />;
  }

  return (
    <div
      className="flex flex-col gap-3 bg-background p-3 text-foreground"
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
        <Button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={serverSourcePickerVisible}
          disabled={controlsLocked || refreshingServerSources}
          onClick={openServerSourcePicker}
          data-suno-control="server-source-trigger"
          variant="outline"
          size="sm"
          className="justify-start text-left"
        >
          {refreshingServerSources
            ? "稼働中の配信元を更新中…"
            : selectedServerSource
              ? formatServerSourceLabel(selectedServerSource, "suno-helper")
              : "配信元を選択"}
        </Button>
        <select
          value={url}
          disabled={controlsLocked || refreshingServerSources}
          onChange={(e) => setUrl(e.target.value)}
          data-suno-control="server-url"
          aria-hidden="true"
          tabIndex={-1}
          className="sr-only"
        >
          {serverSources.map((source) => (
            <option key={source.url} value={source.url}>
              {formatServerSourceLabel(source, "suno-helper")}
            </option>
          ))}
        </select>
        {serverSourcePickerVisible && (
          <div
            role="listbox"
            aria-label="ローカル配信元"
            className="rounded border border-border bg-popover p-1 text-popover-foreground"
          >
            {serverSources.map((source) => (
              <Button
                key={source.url}
                type="button"
                role="option"
                aria-selected={source.url === url}
                disabled={controlsLocked || refreshingServerSources}
                variant="ghost"
                size="sm"
                className="w-full justify-start text-left"
                onClick={() => {
                  if (isRunningRef.current || refreshingServerSources) {
                    return;
                  }
                  setUrl(source.url);
                  setServerSourcePickerOpen(false);
                }}
              >
                {formatServerSourceLabel(source, "suno-helper")}
              </Button>
            ))}
          </div>
        )}
      </label>

      <fieldset className="flex flex-col gap-1 rounded border border-border px-2 py-2 text-sm">
        <legend className="px-1 text-xs text-muted-foreground">
          コレクション
        </legend>
        {collections.length === 0 && (
          <p className="text-xs text-muted-foreground">コレクションなし</p>
        )}
        {collections.map((collection) => {
          const checked = selectedCollectionIds.includes(collection.id);
          return (
            <ButtonSlot
              key={collection.id}
              variant={checked ? "secondary" : "outline"}
              size="sm"
              className="h-auto w-full justify-start whitespace-normal p-2"
            >
              <label className="flex items-start gap-2">
                <Checkbox
                  className="mt-1"
                  checked={checked}
                  disabled={
                    controlsLocked || collection.status === "needs_prompts"
                  }
                  data-suno-control="collection-checkbox"
                  aria-label={`${collection.name} を選択`}
                  onCheckedChange={(nextChecked) =>
                    toggleCollectionSelection(
                      collection.id,
                      nextChecked === true
                    )
                  }
                />
                <span className="flex flex-col text-left">
                  <span className="font-medium">{collection.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {collection.status === "downloaded"
                      ? `完了 ${collection.downloaded_count}/${collection.expected_file_count ?? (collection.pattern_count ?? 0) * 2}`
                      : collection.status === "ready"
                        ? `${collection.pattern_count} patterns`
                        : "prompts なし"}
                  </span>
                </span>
              </label>
            </ButtonSlot>
          );
        })}
      </fieldset>
      <ButtonSlot
        variant="outline"
        size="sm"
        className="sr-only"
        aria-hidden="true"
      >
        <select
          value={selectedCollectionId}
          onChange={(event) => selectCollection(event.target.value)}
          data-suno-control="collection-select"
          tabIndex={-1}
        >
          {collections.map((collection) => (
            <option key={collection.id} value={collection.id}>
              {collection.status === "downloaded"
                ? `${collection.name}（完了 ${collection.downloaded_count}/${collection.expected_file_count ?? (collection.pattern_count ?? 0) * 2}）`
                : collection.status === "ready"
                  ? `${collection.name} (${collection.pattern_count})`
                  : `${collection.name}（prompts なし）`}
            </option>
          ))}
        </select>
      </ButtonSlot>

      {collectionQueue && (
        <Alert
          variant={
            collectionQueue.items.some((item) => item.status === "failed")
              ? "destructive"
              : collectionQueue.status === "completed"
                ? "success"
                : collectionQueue.status === "paused"
                  ? "warning"
                  : "info"
          }
          className="flex flex-col gap-2 rounded px-2 py-2 text-xs"
          data-suno-control="collection-queue-summary"
        >
          <p className="font-medium">
            Collection queue: {collectionQueue.status}
          </p>
          <ul className="list-disc pl-4">
            {collectionQueue.items.map((item) => (
              <li key={item.collectionId}>
                {item.collectionId}: {item.status}
                {item.message ? ` — ${item.message}` : ""}
              </li>
            ))}
          </ul>
          {collectionQueue.status === "paused" && (
            <Button
              type="button"
              size="sm"
              variant="warning"
              className="self-start"
              onClick={() => void resumeCollectionQueue()}
            >
              Queue を再開
            </Button>
          )}
          {collectionQueue.status === "completed" &&
            collectionQueue.items.some((item) => item.status === "failed") && (
              <Button
                type="button"
                size="sm"
                variant="destructive"
                className="self-start"
                onClick={() =>
                  void runCollectionQueue(
                    collectionQueue.items
                      .filter((item) => item.status === "failed")
                      .map((item) => item.collectionId)
                  )
                }
              >
                失敗したコレクションだけ再実行
              </Button>
            )}
        </Alert>
      )}

      {playlistName && (
        <p className="text-xs text-muted-foreground">
          Playlist: <span className="font-medium">{playlistName}</span>
        </p>
      )}

      {visibleResumeBanner && (
        <Alert
          variant="warning"
          className="flex flex-col gap-2 rounded px-2 py-2 text-xs"
        >
          <p>
            前回の実行が中断されました。entry{" "}
            <span className="font-semibold">
              {visibleResumeBanner.failedIndex + 1}
            </span>{" "}
            から再開しますか？
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              onClick={acceptResume}
              data-suno-control="resume"
              variant="warning"
              size="sm"
            >
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
        </Alert>
      )}

      {compatibilityWarning && (
        <Alert variant="warning" className="rounded px-2 py-2 text-xs">
          {compatibilityWarning}
        </Alert>
      )}

      {/* 失敗スキップされた entry の再実行導線 (#948)。実行中は隠す。 */}
      {failedEntries.length > 0 && !controlsLocked && (
        <Alert
          variant="destructive"
          appearance="filled"
          className="flex flex-col gap-2 rounded px-2 py-2 text-xs"
        >
          <p>
            失敗してスキップされた entry:{" "}
            <span className="font-semibold">
              {failedEntries.map((i) => i + 1).join(", ")}
            </span>
          </p>
          <Button
            type="button"
            onClick={rerunFailed}
            variant="destructive"
            size="sm"
            className="self-start"
          >
            失敗分のみ再実行
          </Button>
        </Alert>
      )}

      <fieldset className="flex flex-col gap-2 rounded border border-border px-2 py-2 text-sm">
        <legend className="px-1 text-xs text-muted-foreground">投入方式</legend>
        <RadioGroup
          name="run-mode"
          value={runModeId}
          disabled={controlsLocked}
          onValueChange={(value) => setRunMode(value as RunModeId)}
        >
          {RUN_MODE_ORDER.map((id) => {
            const mode = RUN_MODES[id];
            return (
              <ButtonSlot
                key={id}
                variant={runModeId === id ? "info" : "outline"}
                size="sm"
                className="h-auto w-full justify-start whitespace-normal p-2"
              >
                <label className="flex items-start gap-2">
                  <RadioGroupItem
                    value={id}
                    className="mt-1"
                    aria-label={mode.label}
                    data-suno-control="run-mode"
                  />
                  <span className="flex flex-col">
                    <span className="font-medium">{mode.label}</span>
                    <span className="text-xs text-muted-foreground">
                      {mode.riskNote}
                    </span>
                  </span>
                </label>
              </ButtonSlot>
            );
          })}
        </RadioGroup>
      </fieldset>

      <label className="flex items-start gap-2 rounded border border-border px-2 py-2 text-sm">
        <Checkbox
          className="mt-1"
          checked={regenerateDurationOutliers}
          disabled={entries.length === 0 || controlsLocked}
          data-suno-control="regenerate-duration-outliers"
          aria-label="異常値の曲を再生成する"
          onCheckedChange={(checked) =>
            setRegenerateDurationOutliers(checked === true)
          }
        />
        <span className="flex flex-col">
          <span className="font-medium">異常値の曲を再生成する</span>
          {!regenerateDurationOutliers && (
            <span className="text-xs text-warning-foreground">
              OFF の場合、duration guard NG も Playlist / Download
              候補に残ります。完了後に手動確認してください。
            </span>
          )}
        </span>
      </label>

      <CompletionSoundControls
        settings={completionSoundSettings}
        disabled={!completionSoundSettingsLoaded}
        onEnabledChange={setCompletionSoundEnabled}
        onPresetChange={setCompletionSoundPreset}
        onPreview={previewCompletionSound}
      />

      <div className="flex flex-col gap-1 text-sm">
        <span id="download-format-label">DL 形式</span>
        <Select
          value={downloadFormat}
          disabled={controlsLocked}
          onValueChange={(value) =>
            updateDownloadFormat(value as DownloadFormat)
          }
        >
          <SelectTrigger
            className="w-full"
            aria-labelledby="download-format-label"
            data-suno-control="download-format"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DOWNLOAD_FORMAT_OPTIONS.map((format) => (
              <SelectItem key={format} value={format}>
                {format.toUpperCase()}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex gap-2">
        <Button
          type="button"
          onClick={runSelectedEntries}
          disabled={!canRunSelectedEntries}
          data-suno-control="run"
          variant="info"
          size="sm"
          className="flex-1"
        >
          {runButtonLabel}
        </Button>
        <Button
          type="button"
          onClick={() => void stop()}
          disabled={!controlsLocked}
          data-suno-control="stop"
          variant="destructive"
          size="sm"
        >
          停止
        </Button>
      </div>

      {!controlsLocked && selectedCollectionId && (
        <div className="flex flex-col gap-2">
          <Button
            type="button"
            onClick={() => void adoptSelectedClips()}
            data-suno-control="adopt-selected-clips"
            variant="outline"
            size="sm"
          >
            選択中の曲を採用
          </Button>
          <div className="flex gap-2">
            {playlistName && (
              <Button
                type="button"
                onClick={() => void retryPlaylist()}
                data-suno-control="retry-playlist"
                variant="warning"
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
              variant="success"
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
        <Alert
          variant={
            isError
              ? "destructive"
              : phase === PHASE.ADDING_TO_PLAYLIST
                ? "warning"
                : phase === PHASE.DOWNLOADING || phase === PHASE.FINISHED
                  ? "success"
                  : "info"
          }
          appearance={isError ? "filled" : "subtle"}
          role="status"
          aria-live="polite"
          data-suno-status={isError ? "error" : "ok"}
          className="whitespace-pre-wrap rounded px-2 py-2 text-xs"
        >
          {status}
        </Alert>
      )}
    </div>
  );
}
