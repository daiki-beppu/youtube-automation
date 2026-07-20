import { buttonVariants, Checkbox, FieldLabel } from "@youtube-automation/ui";

import type { PromptEntry } from "../../shared/api";
import type { ItemState } from "../../shared/constants";
import { isEntrySelected } from "../lib/pattern-selection";

interface PatternListProps {
  entries: PromptEntry[];
  itemStates: ItemState[];
  selectedEntries: boolean[];
  onToggleEntry: (index: number, checked: boolean) => void;
}

const STATE_CLASS: Record<ItemState, string> = {
  idle: "border-border bg-background text-foreground",
  active:
    "border-info-border bg-info-background font-medium text-info-foreground",
  submitted:
    "border-warning-border bg-warning-background font-medium text-warning-foreground",
  done: "border-success-border bg-success-background text-success-foreground",
  // リトライ上限まで失敗しスキップされた entry (#948)。「失敗分のみ再実行」の対象。
  failed:
    "border-destructive-border bg-destructive-background font-medium text-destructive-foreground",
};

const SELECTION_CLASS: Record<"selected" | "unselected", string> = {
  selected: "ring-2 ring-current/20",
  unselected: "shadow-none",
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
            <FieldLabel
              data-variant="outline"
              data-size="sm"
              className={buttonVariants({
                variant: "outline",
                size: "sm",
                className: `h-auto w-full justify-start whitespace-normal p-0 font-normal ${STATE_CLASS[itemState]} ${SELECTION_CLASS[selected ? "selected" : "unselected"]}`,
              })}
            >
              <Checkbox
                checked={selected}
                onCheckedChange={(checked) =>
                  onToggleEntry(index, checked === true)
                }
                aria-label={`entry ${index + 1}: ${entry.name}`}
              />
              <span className="min-w-0 flex-1 px-2 py-1 text-left">
                {entry.name}
              </span>
            </FieldLabel>
          </li>
        );
      })}
    </ul>
  );
}
