import type { PromptEntry } from "../../shared/api";
import type { ItemState } from "../../shared/constants";
import { isEntrySelected } from "../lib/pattern-selection";
import { ButtonSlot } from "./ui/button";

interface PatternListProps {
  entries: PromptEntry[];
  itemStates: ItemState[];
  selectedEntries: boolean[];
  onToggleEntry: (index: number, checked: boolean) => void;
}

const STATE_CLASS: Record<ItemState, string> = {
  idle: "text-foreground",
  active: "bg-primary/10 font-medium text-primary",
  submitted: "bg-secondary font-medium text-secondary-foreground",
  done: "text-muted-foreground line-through",
  // リトライ上限まで失敗しスキップされた entry (#948)。「失敗分のみ再実行」の対象。
  failed: "bg-destructive/10 font-medium text-destructive",
};

export function PatternList({
  entries,
  itemStates,
  selectedEntries,
  onToggleEntry,
}: PatternListProps) {
  if (entries.length === 0) {
    return null;
  }
  return (
    <ul
      className="max-h-48 overflow-y-auto rounded border border-border"
      data-suno-entry-list="true"
    >
      {entries.map((entry, index) => {
        const itemState = itemStates[index] ?? "idle";
        const selected = isEntrySelected(selectedEntries, itemStates, index);
        return (
          <li
            key={`${entry.name}-${index}`}
            className={`p-1 text-sm ${itemState === "done" ? "line-through" : ""}`}
            data-suno-entry-index={index}
            data-suno-entry-state={itemState}
            data-suno-entry-selected={selected ? "true" : "false"}
          >
            <ButtonSlot
              variant={selected ? "default" : "outline"}
              size="sm"
              className="h-auto w-full justify-start whitespace-normal p-0 font-normal"
            >
              <label className="flex items-center gap-2 px-2 py-1">
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={(event) =>
                    onToggleEntry(index, event.currentTarget.checked)
                  }
                  aria-label={`entry ${index + 1}: ${entry.name}`}
                  className="size-4 shrink-0 accent-primary"
                />
                <span
                  className={`min-w-0 flex-1 text-left ${STATE_CLASS[itemState]}`}
                >
                  {entry.name}
                </span>
              </label>
            </ButtonSlot>
          </li>
        );
      })}
    </ul>
  );
}
