// @vitest-environment jsdom

import { act, createElement, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ItemState } from "../../shared/constants";
import { buildInitialPatternSelection, PatternList, reconcilePatternSelection } from "../components/PatternList";
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

  it("各 entry の checkbox に selection を反映し、done entry は打ち消し線のまま手動で再チェックできる", () => {
    const onToggleEntry = vi.fn();

    act(() => {
      root.render(
        createElement(PatternList, {
          entries: makePromptEntries(3),
          itemStates: ["idle", "done", "failed"],
          selectedEntries: [true, false, true],
          onToggleEntry,
        }),
      );
    });

    const checkboxes = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
    expect(checkboxes.map((checkbox) => checkbox.checked)).toEqual([true, false, true]);
    expect(checkboxes[1].closest("li")?.className).toContain("line-through");

    act(() => {
      checkboxes[1].click();
    });

    expect(onToggleEntry).toHaveBeenCalledWith(1, true);
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

    act(() => {
      checkboxes[1]!.click();
    });

    checkboxes = Array.from(container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
    expect(checkboxes.map((checkbox) => checkbox.checked)).toEqual([true, true, true]);
    expect(checkboxes[1]!.closest("li")?.className).toContain("line-through");
  });
});
