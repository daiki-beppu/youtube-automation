import { EXTENSION_RELOAD_REQUIRED_MESSAGE } from "./runner-errors";

export function ReloadRequiredNotice() {
  return (
    <div className="fixed left-4 top-4 z-[2147483647] flex max-w-xs flex-col gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 shadow-xl">
      <p>{EXTENSION_RELOAD_REQUIRED_MESSAGE}</p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="rounded bg-amber-600 px-2 py-1 text-white hover:bg-amber-500"
      >
        タブを再読み込み
      </button>
    </div>
  );
}
