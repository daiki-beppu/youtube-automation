import type { PromptEntry } from "../../shared/api";
import type { ItemState } from "./useSunoRunner";

interface PatternListProps {
  entries: PromptEntry[];
  itemStates: ItemState[];
}

const STATE_CLASS: Record<ItemState, string> = {
  idle: "text-gray-700",
  active: "bg-blue-100 font-medium text-blue-800",
  done: "text-green-700 line-through",
};

export function PatternList({ entries, itemStates }: PatternListProps) {
  if (entries.length === 0) {
    return null;
  }
  return (
    <ul className="max-h-48 overflow-y-auto rounded border border-gray-200">
      {entries.map((entry, index) => (
        <li key={`${entry.name}-${index}`} className={`px-2 py-1 text-sm ${STATE_CLASS[itemStates[index] ?? "idle"]}`}>
          {entry.name}
        </li>
      ))}
    </ul>
  );
}
