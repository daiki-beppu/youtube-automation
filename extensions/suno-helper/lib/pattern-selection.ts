import type { PromptEntry } from "../../shared/api";
import type { ItemState } from "../../shared/constants";

export interface PatternSelectionInput {
  selectedEntries: boolean[];
  itemStates: ItemState[];
  entryCount: number;
}

export interface ReconcilePatternSelectionInput {
  selection: boolean[];
  previousEntries: PromptEntry[];
  previousItemStates: ItemState[];
  entries: PromptEntry[];
  itemStates: ItemState[];
}

export function isEntrySelected(selectedEntries: boolean[], itemStates: ItemState[], index: number): boolean {
  return selectedEntries[index] ?? (itemStates[index] ?? "idle") !== "done";
}

export function selectedEntryIndices({ selectedEntries, itemStates, entryCount }: PatternSelectionInput): number[] {
  return Array.from({ length: entryCount }, (_, index) => index).filter((index) =>
    isEntrySelected(selectedEntries, itemStates, index),
  );
}

export function selectedEntryCount(input: PatternSelectionInput): number {
  return selectedEntryIndices(input).length;
}

export function buildInitialPatternSelection(entries: PromptEntry[], itemStates: ItemState[]): boolean[] {
  return entries.map((_, index) => (itemStates[index] ?? "idle") !== "done");
}

export function reconcilePatternSelection({
  selection,
  previousEntries,
  previousItemStates,
  entries,
  itemStates,
}: ReconcilePatternSelectionInput): boolean[] {
  if (previousEntries !== entries || selection.length !== entries.length) {
    return buildInitialPatternSelection(entries, itemStates);
  }

  return entries.map((_, index) => {
    const previousState = previousItemStates[index] ?? "idle";
    const nextState = itemStates[index] ?? "idle";
    if (previousState !== "done" && nextState === "done") {
      return false;
    }
    return isEntrySelected(selection, itemStates, index);
  });
}
