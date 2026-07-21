// @vitest-environment jsdom

import { act, createElement, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ItemState } from "../../shared/constants";
import { PatternList } from "../components/PatternList";
import {
  buildInitialPatternSelection,
  reconcilePatternSelection,
} from "../lib/pattern-selection";
import { makePromptEntries } from "./_helpers";

describe("PatternList selection helpers", () => {
  it("初期 selection は done entry だけ OFF にする", () => {
    const entries = makePromptEntries(3);

    expect(
      buildInitialPatternSelection(entries, ["idle", "done", "failed"])
    ).toEqual([true, false, true]);
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
      })
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
      })
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

  it("楽曲件数を表示し、初期状態を閉じて独立に開閉する", () => {
    act(() => {
      root.render(
        createElement(PatternList, {
          entries: makePromptEntries(2),
          itemStates: ["idle", "idle"],
          selectedEntries: [true, true],
          onToggleEntry: vi.fn(),
        })
      );
    });

    const trigger = container.querySelector<HTMLButtonElement>(
      '[data-suno-control="entries-collapsible-trigger"]'
    )!;
    const content = container.querySelector<HTMLElement>(
      '[data-slot="collapsible-content"]'
    )!;
    expect(trigger.textContent).toContain("楽曲 (2)");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(content.hidden).toBe(true);

    act(() => {
      trigger.click();
    });

    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(content.hidden).toBe(false);
  });

  it("0件でも閉じた見出しを表示する", () => {
    act(() => {
      root.render(
        createElement(PatternList, {
          entries: [],
          itemStates: [],
          selectedEntries: [],
          onToggleEntry: vi.fn(),
        })
      );
    });

    const trigger = container.querySelector<HTMLButtonElement>(
      '[data-suno-control="entries-collapsible-trigger"]'
    )!;
    expect(trigger.textContent).toContain("楽曲 (0)");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("5 状態それぞれの選択・非選択で semantic token と選択 marker を競合なく描画する", () => {
    const states: ItemState[] = [
      "idle",
      "idle",
      "active",
      "active",
      "submitted",
      "submitted",
      "done",
      "done",
      "failed",
      "failed",
    ];
    const stateTokens: Record<ItemState, string[]> = {
      idle: ["border-border", "bg-background", "text-foreground"],
      active: [
        "border-info-border",
        "bg-info-background",
        "text-info-foreground",
      ],
      submitted: [
        "border-warning-border",
        "bg-warning-background",
        "text-warning-foreground",
      ],
      done: [
        "border-success-border",
        "bg-success-background",
        "text-success-foreground",
      ],
      failed: [
        "border-destructive-border",
        "bg-destructive-background",
        "text-destructive-foreground",
      ],
    };

    act(() => {
      root.render(
        createElement(PatternList, {
          entries: makePromptEntries(states.length),
          itemStates: states,
          selectedEntries: states.map((_, index) => index % 2 === 1),
          onToggleEntry: vi.fn(),
        })
      );
    });

    const rows = Array.from(
      container.querySelectorAll<HTMLLIElement>("[data-suno-entry-index]")
    );
    rows.forEach((row, index) => {
      const control = row.querySelector<HTMLElement>(
        '[data-slot="field-label"]'
      )!;
      const selected = index % 2 === 1;
      expect(row.dataset.sunoEntryState).toBe(states[index]);
      expect(row.dataset.sunoEntrySelected).toBe(String(selected));
      for (const token of stateTokens[states[index]!]!) {
        expect(control.className).toContain(token);
      }
      expect(control.className).toContain(selected ? "ring-2" : "shadow-none");
      expect(control.className).not.toContain("text-primary-foreground");
    });
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
        })
      );
    });

    const checkboxes = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-slot="checkbox"]')
    );
    expect(
      checkboxes.map((checkbox) => checkbox.hasAttribute("data-checked"))
    ).toEqual([true, false, true, false, true]);
    expect(
      checkboxes.map((checkbox) => checkbox.getAttribute("aria-label"))
    ).toEqual([
      "entry 1: pattern-1",
      "entry 2: pattern-2",
      "entry 3: pattern-3",
      "entry 4: pattern-4",
      "entry 5: pattern-5",
    ]);

    const list = container.querySelector<HTMLUListElement>(
      "[data-suno-entry-list]"
    );
    expect(list?.tagName).toBe("UL");
    expect(list?.dataset.sunoEntryList).toBe("true");
    const scrollArea = list?.closest<HTMLElement>('[data-slot="scroll-area"]');
    expect(scrollArea?.dataset.sunoEntryScrollArea).toBe("true");
    expect(scrollArea?.className).toContain("border-border");
    const rows = Array.from(
      container.querySelectorAll<HTMLLIElement>("[data-suno-entry-index]")
    );
    expect(rows.map((row) => row.tagName)).toEqual([
      "LI",
      "LI",
      "LI",
      "LI",
      "LI",
    ]);
    expect(
      rows.map((row) => ({
        index: row.dataset.sunoEntryIndex,
        selected: row.dataset.sunoEntrySelected,
        state: row.dataset.sunoEntryState,
      }))
    ).toEqual([
      { index: "0", selected: "true", state: "idle" },
      { index: "1", selected: "false", state: "active" },
      { index: "2", selected: "true", state: "submitted" },
      { index: "3", selected: "false", state: "done" },
      { index: "4", selected: "true", state: "failed" },
    ]);
    expect(
      rows.map((row) => row.querySelector("label")?.dataset.variant)
    ).toEqual(["outline", "outline", "outline", "outline", "outline"]);
    expect(rows.map((row) => row.querySelector("label")?.dataset.size)).toEqual(
      ["sm", "sm", "sm", "sm", "sm"]
    );
    expect(
      checkboxes.every((checkbox) => checkbox.dataset.slot === "checkbox")
    ).toBe(true);
    const controls = rows.map((row) =>
      row.querySelector<HTMLElement>('[data-slot="field-label"]')!
    );
    const stateTokens = [
      ["border-border", "bg-background", "text-foreground"],
      ["border-info-border", "bg-info-background", "text-info-foreground"],
      [
        "border-warning-border",
        "bg-warning-background",
        "text-warning-foreground",
      ],
      [
        "border-success-border",
        "bg-success-background",
        "text-success-foreground",
      ],
      [
        "border-destructive-border",
        "bg-destructive-background",
        "text-destructive-foreground",
      ],
    ];
    controls.forEach((control, index) => {
      for (const token of stateTokens[index]!) {
        expect(control.className).toContain(token);
      }
      expect(control.className).toContain(
        [true, false, true, false, true][index] ? "ring-2" : "shadow-none"
      );
      expect(control.className).toContain("p-2");
      expect(control.className).not.toContain("p-0");
    });
    expect(
      checkboxes.every((checkbox) => checkbox.classList.contains("mt-0.5"))
    ).toBe(true);
    expect(
      controls.every((control) => control.classList.contains("items-start"))
    ).toBe(true);
    expect(
      rows.every((row) => {
        const text = row.querySelector('[data-suno-slot="entry-name"]');
        return (
          text?.classList.contains("min-w-0") &&
          text.classList.contains("flex-1") &&
          !text.classList.contains("px-2") &&
          !text.classList.contains("py-1")
        );
      })
    ).toBe(true);
    expect(rows[3].className).toContain("line-through");
  });

  it("controlled state 更新後に done entry の手動再チェックを DOM に反映する", () => {
    const entries = makePromptEntries(3);
    const itemStates: ItemState[] = ["idle", "done", "failed"];

    function StatefulPatternList() {
      const [selectedEntries, setSelectedEntries] = useState(() =>
        buildInitialPatternSelection(entries, itemStates)
      );
      return createElement(PatternList, {
        entries,
        itemStates,
        selectedEntries,
        onToggleEntry: (index: number, checked: boolean) => {
          setSelectedEntries((selection) =>
            selection.map((selected, i) => (i === index ? checked : selected))
          );
        },
      });
    }

    act(() => {
      root.render(createElement(StatefulPatternList));
    });

    let checkboxes = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-slot="checkbox"]')
    );
    expect(
      checkboxes.map((checkbox) => checkbox.hasAttribute("data-checked"))
    ).toEqual([true, false, true]);
    expect(
      checkboxes.map((checkbox) => checkbox.hasAttribute("data-disabled"))
    ).toEqual([false, false, false]);

    act(() => {
      checkboxes[0]!.click();
      checkboxes[1]!.click();
    });

    checkboxes = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-slot="checkbox"]')
    );
    expect(
      checkboxes.map((checkbox) => checkbox.hasAttribute("data-checked"))
    ).toEqual([false, true, true]);
    const rows = Array.from(
      container.querySelectorAll<HTMLLIElement>("[data-suno-entry-index]")
    );
    expect(rows.map((row) => row.dataset.sunoEntrySelected)).toEqual([
      "false",
      "true",
      "true",
    ]);
    expect(
      rows.map((row) => row.querySelector("label")?.dataset.variant)
    ).toEqual(["outline", "outline", "outline"]);
    expect(rows[1].className).toContain("line-through");
  });

  it("Space キーで checkbox を1回だけ切り替える", () => {
    const onToggleEntry = vi.fn();
    act(() => {
      root.render(
        createElement(PatternList, {
          entries: makePromptEntries(1),
          itemStates: ["idle"],
          selectedEntries: [true],
          onToggleEntry,
        })
      );
    });

    const checkbox = container.querySelector<HTMLElement>(
      '[data-slot="checkbox"]'
    )!;
    act(() => {
      checkbox.focus();
      checkbox.dispatchEvent(
        new KeyboardEvent("keydown", { bubbles: true, key: " " })
      );
      checkbox.dispatchEvent(
        new KeyboardEvent("keyup", { bubbles: true, key: " " })
      );
    });

    expect(onToggleEntry).toHaveBeenCalledOnce();
    expect(onToggleEntry).toHaveBeenCalledWith(0, false);
  });
});
