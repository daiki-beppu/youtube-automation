import type { PromptEntry } from "../../shared/api";
import type { ItemState } from "../../shared/constants";

interface PatternListProps {
  entries: PromptEntry[];
  itemStates: ItemState[];
  selectedEntries: boolean[];
  onToggleEntry: (index: number, checked: boolean) => void;
}

const STATE_CLASS: Record<ItemState, string> = {
  idle: "text-gray-700",
  active: "bg-blue-100 font-medium text-blue-800",
  done: "text-green-700 line-through",
  // リトライ上限まで失敗しスキップされた entry (#948)。「失敗分のみ再実行」の対象。
  failed: "bg-red-50 font-medium text-red-700",
};

export function buildInitialPatternSelection(entries: PromptEntry[], itemStates: ItemState[]): boolean[] {
  return entries.map((_, index) => (itemStates[index] ?? "idle") !== "done");
}

export function reconcilePatternSelection({
  selection,
  previousEntries,
  previousItemStates,
  entries,
  itemStates,
}: {
  selection: boolean[];
  previousEntries: PromptEntry[];
  previousItemStates: ItemState[];
  entries: PromptEntry[];
  itemStates: ItemState[];
}): boolean[] {
  if (previousEntries !== entries || selection.length !== entries.length) {
    return buildInitialPatternSelection(entries, itemStates);
  }

  return entries.map((_, index) => {
    const previousState = previousItemStates[index] ?? "idle";
    const nextState = itemStates[index] ?? "idle";
    if (previousState !== "done" && nextState === "done") {
      return false;
    }
    return selection[index] ?? nextState !== "done";
  });
}

export function PatternList({ entries, itemStates, selectedEntries, onToggleEntry }: PatternListProps) {
  if (entries.length === 0) {
    return null;
  }
  return (
    <ul className="max-h-48 overflow-y-auto rounded border border-gray-200">
      {entries.map((entry, index) => {
        const itemState = itemStates[index] ?? "idle";
        return (
          <li key={`${entry.name}-${index}`} className={`px-2 py-1 text-sm ${STATE_CLASS[itemState]}`}>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={selectedEntries[index] ?? itemState !== "done"}
                onChange={(event) => onToggleEntry(index, event.currentTarget.checked)}
                aria-label={`entry ${index + 1}: ${entry.name}`}
                className="h-4 w-4 shrink-0"
              />
              <span className="min-w-0 flex-1">{entry.name}</span>
            </label>
          </li>
        );
      })}
    </ul>
  );
}
