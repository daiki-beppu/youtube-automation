import { EXTENSION_RELOAD_REQUIRED_MESSAGE } from "./runner-errors";

export function ReloadRequiredNotice() {
  return (
    <div className="fixed left-4 top-4 z-[2147483647] flex max-w-xs flex-col gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 shadow-xl dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100">
      <p>{EXTENSION_RELOAD_REQUIRED_MESSAGE}</p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="rounded bg-amber-600 px-2 py-1 text-amber-50 hover:bg-amber-500 dark:bg-amber-500 dark:text-amber-950 dark:hover:bg-amber-400"
      >
        タブを再読み込み
      </button>
    </div>
  );
}
