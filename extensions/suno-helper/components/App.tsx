import { DEFAULT_URL } from "../../shared/constants";
import { PatternList } from "./PatternList";
import { useSunoRunner } from "./useSunoRunner";

export function App() {
  const { url, setUrl, entries, itemStates, status, isError, canRun, isRunning, fetchData, run, stop } =
    useSunoRunner();

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
          全パターンを連続実行
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
