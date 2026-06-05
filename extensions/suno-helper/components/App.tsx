import { DEFAULT_URL } from "../../shared/constants";
import { PatternList } from "./PatternList";
import { useSunoRunner } from "./useSunoRunner";

export function App() {
  const {
    url,
    setUrl,
    collections,
    selectedCollectionId,
    selectCollection,
    entries,
    itemStates,
    status,
    isError,
    canRun,
    isRunning,
    playlistName,
    rangeMode,
    setRangeMode,
    rangeStart,
    setRangeStart,
    rangeEnd,
    setRangeEnd,
    resumeBanner,
    acceptResume,
    dismissResume,
    fetchData,
    run,
    stop,
  } = useSunoRunner();

  return (
    <div className="flex flex-col gap-3 p-3 text-gray-900">
      <h1 className="text-base font-semibold">Suno Helper</h1>

      <label className="flex flex-col gap-1 text-sm">
        サーバー URL
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={DEFAULT_URL}
          className="rounded border border-gray-300 px-2 py-1"
        />
      </label>

      {collections.length > 0 && (
        <label className="flex flex-col gap-1 text-sm">
          コレクション
          <select
            value={selectedCollectionId}
            onChange={(e) => selectCollection(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1"
          >
            {collections.map((c) => (
              <option key={c.id} value={c.id} disabled={!c.has_prompts}>
                {c.has_prompts ? `${c.name} (${c.pattern_count})` : `${c.name}（prompts なし）`}
              </option>
            ))}
          </select>
        </label>
      )}

      {playlistName && (
        <p className="text-xs text-gray-600">
          Playlist: <span className="font-medium">{playlistName}</span>
        </p>
      )}

      {resumeBanner && (
        <div className="flex flex-col gap-2 rounded border border-amber-300 bg-amber-50 px-2 py-2 text-xs text-amber-900">
          <p>
            前回 entry <span className="font-semibold">{resumeBanner.failedIndex + 1}</span> で停止しました。entry{" "}
            {resumeBanner.failedIndex + 1} から再開しますか？
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={acceptResume}
              className="rounded bg-amber-600 px-2 py-1 text-white hover:bg-amber-500"
            >
              再開
            </button>
            <button
              type="button"
              onClick={dismissResume}
              className="rounded border border-amber-400 px-2 py-1 hover:bg-amber-100"
            >
              閉じる
            </button>
          </div>
        </div>
      )}

      <fieldset className="flex flex-col gap-2 rounded border border-gray-200 px-2 py-2 text-sm">
        <legend className="px-1 text-xs text-gray-600">実行範囲</legend>
        <label className="flex items-center gap-2">
          <input type="radio" name="range-mode" checked={rangeMode === "all"} onChange={() => setRangeMode("all")} />
          全パターン
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="range-mode"
            checked={rangeMode === "range"}
            onChange={() => setRangeMode("range")}
          />
          範囲指定
        </label>
        {rangeMode === "range" && (
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={1}
              value={rangeStart}
              onChange={(e) => setRangeStart(e.target.value)}
              placeholder="開始"
              aria-label="開始 entry"
              className="w-20 rounded border border-gray-300 px-2 py-1"
            />
            <span className="text-gray-500">〜</span>
            <input
              type="number"
              min={1}
              value={rangeEnd}
              onChange={(e) => setRangeEnd(e.target.value)}
              placeholder="終了 (省略可)"
              aria-label="終了 entry"
              className="w-28 rounded border border-gray-300 px-2 py-1"
            />
          </div>
        )}
      </fieldset>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void fetchData()}
          className="flex-1 rounded bg-gray-800 px-2 py-1 text-sm text-white hover:bg-gray-700"
        >
          データ取得
        </button>
        <button
          type="button"
          onClick={() => void run()}
          disabled={!canRun}
          className="flex-1 rounded bg-blue-600 px-2 py-1 text-sm text-white hover:bg-blue-500 disabled:opacity-40"
        >
          {rangeMode === "range" ? "範囲を連続実行" : "全パターンを連続実行"}
        </button>
        <button
          type="button"
          onClick={() => void stop()}
          disabled={!isRunning}
          className="rounded bg-red-600 px-2 py-1 text-sm text-white hover:bg-red-500 disabled:opacity-40"
        >
          停止
        </button>
      </div>

      <PatternList entries={entries} itemStates={itemStates} />

      {status && (
        <p className={`whitespace-pre-wrap text-xs ${isError ? "text-red-600" : "text-gray-600"}`}>{status}</p>
      )}
    </div>
  );
}
