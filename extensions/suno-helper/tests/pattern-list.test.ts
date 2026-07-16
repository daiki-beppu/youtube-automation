// @vitest-environment jsdom

import { act, createElement, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ItemState } from "../../shared/constants";
import { PatternList } from "../components/PatternList";
import { buildInitialPatternSelection, reconcilePatternSelection } from "../lib/pattern-selection";
import { makePromptEntries } from "./_helpers";

describe("PatternList selection helpers", () => {
  it("初期 selection は done entry だけ OFF にする", () => {
    const entries = makePromptEntries(3);

    expect(buildInitialPatternSelection(entries, ["idle", "done", "failed"])).toEqual([true, false, true]);
  });

  it("同じ entries では手動 selection を保持し、done に遷移した entry だけ OFF にする", () => {
    const entries = makePromptEntries(3);
    const previousItemStates: ItemState[] = ["idle", "done", "failed"];
    const itemStates: ItemState[] = ["done", "done", "failed"];

    expect(
      reconcilePatternSelection({
        selection: [true, true, false],
        previousEntries: entries,
        previousItemStates,
        entries,
        itemStates,
      }),
    ).toEqual([false, true, false]);
  });

  it("entries が差し替わった場合は itemStates から初期 selection を作り直す", () => {
    const previousEntries = makePromptEntries(3);
    const entries = makePromptEntries(2);

    expect(
      reconcilePatternSelection({
        selection: [false, false, false],
        previousEntries,
        previousItemStates: ["done", "done", "done"],
        entries,
        itemStates: ["idle", "done"],
      }),
    ).toEqual([true, false]);
  });
});

describe("PatternList checkbox UI", () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it("各 entry の selection を shadcn variant と semantic token に反映する", () => {
    const onToggleEntry = vi.fn();

    act(() => {
      root.render(
        createElement(PatternList, {
          entries: makePromptEntries(5),
          itemStates: ["idle", "active", "submitted", "done", "failed"],
          selectedEntries: [true, false, true, false, true],
          onToggleEntry,
        }),
      );
    });

    const checkboxes = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
    expect(checkboxes.map((checkbox) => checkbox.checked)).toEqual([true, false, true, false, true]);
    expect(checkboxes.map((checkbox) => checkbox.getAttribute("aria-label"))).toEqual([
      "entry 1: pattern-1",
      "entry 2: pattern-2",
      "entry 3: pattern-3",
      "entry 4: pattern-4",
      "entry 5: pattern-5",
    ]);

    const list = container.querySelector<HTMLUListElement>("[data-suno-entry-list]");
    expect(list?.tagName).toBe("UL");
    expect(list?.dataset.sunoEntryList).toBe("true");
    expect(list?.className).toContain("border-border");
    const rows = Array.from(container.querySelectorAll<HTMLLIElement>("[data-suno-entry-index]"));
    expect(rows.map((row) => row.tagName)).toEqual(["LI", "LI", "LI", "LI", "LI"]);
    expect(
      rows.map((row) => ({
        index: row.dataset.sunoEntryIndex,
        selected: row.dataset.sunoEntrySelected,
        state: row.dataset.sunoEntryState,
      })),
    ).toEqual([
      { index: "0", selected: "true", state: "idle" },
      { index: "1", selected: "false", state: "active" },
      { index: "2", selected: "true", state: "submitted" },
      { index: "3", selected: "false", state: "done" },
      { index: "4", selected: "true", state: "failed" },
    ]);
    expect(rows.map((row) => row.querySelector("label")?.dataset.variant)).toEqual([
      "default",
      "outline",
      "default",
      "outline",
      "default",
    ]);
    expect(rows.map((row) => row.querySelector("label")?.dataset.size)).toEqual(["sm", "sm", "sm", "sm", "sm"]);
    expect(checkboxes.every((checkbox) => checkbox.className.includes("accent-primary"))).toBe(true);
    const names = rows.map((row) => row.querySelector("span")!);
    expect(names[0].className).toContain("text-foreground");
    expect(names[1].className).toContain("bg-primary/10");
    expect(names[1].className).toContain("text-primary");
    expect(names[2].className).toContain("bg-secondary");
    expect(names[2].className).toContain("text-secondary-foreground");
    expect(names[3].className).toContain("text-muted-foreground");
    expect(names[3].className).toContain("line-through");
    expect(names[4].className).toContain("bg-destructive/10");
    expect(names[4].className).toContain("text-destructive");
  });

  it("controlled state 更新後に done entry の手動再チェックを DOM に反映する", () => {
    const entries = makePromptEntries(3);
    const itemStates: ItemState[] = ["idle", "done", "failed"];

    function StatefulPatternList() {
      const [selectedEntries, setSelectedEntries] = useState(() => buildInitialPatternSelection(entries, itemStates));
      return createElement(PatternList, {
        entries,
        itemStates,
        selectedEntries,
        onToggleEntry: (index: number, checked: boolean) => {
          setSelectedEntries((selection) => selection.map((selected, i) => (i === index ? checked : selected)));
        },
      });
    }

    act(() => {
      root.render(createElement(StatefulPatternList));
    });

    let checkboxes = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
    expect(checkboxes.map((checkbox) => checkbox.checked)).toEqual([true, false, true]);
    expect(checkboxes.map((checkbox) => checkbox.disabled)).toEqual([false, false, false]);

    act(() => {
      checkboxes[0]!.click();
      checkboxes[1]!.click();
    });

    checkboxes = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
    expect(checkboxes.map((checkbox) => checkbox.checked)).toEqual([false, true, true]);
    const rows = Array.from(container.querySelectorAll<HTMLLIElement>("[data-suno-entry-index]"));
    expect(rows.map((row) => row.dataset.sunoEntrySelected)).toEqual(["false", "true", "true"]);
    expect(rows.map((row) => row.querySelector("label")?.dataset.variant)).toEqual(["outline", "default", "default"]);
    expect(rows[1].querySelector("span")?.className).toContain("line-through");
  });
});
