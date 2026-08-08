// @vitest-environment jsdom

import {
  SERVER_SOURCE_SELECT_EVENT,
  ServerSourceField,
} from "@youtube-automation/ui";
import { act, createRef } from "react";
import type React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useShadowPortalTriggerRef } from "../../shared-ui/src/use-shadow-portal-trigger-ref";
import { ServerUrlField } from "../components/ServerUrlField";

const SOURCES = [
  { id: "one", label: "One", url: "http://one.localhost:7873" },
  { id: "two", label: "Two", url: "http://two.localhost:7873" },
];

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

async function waitFor(assertion: () => void): Promise<void> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      assertion();
      return;
    } catch (error) {
      if (attempt === 19) throw error;
      await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    }
  }
}

describe("ServerSourceField and Shadow portal ref", () => {
  let host: HTMLDivElement;
  let shadow: ShadowRoot;
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    host = document.createElement("div");
    document.body.append(host);
    shadow = host.attachShadow({ mode: "open" });
    container = document.createElement("div");
    shadow.append(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  async function renderField(
    props: Partial<React.ComponentProps<typeof ServerSourceField>> = {}
  ): Promise<void> {
    await act(async () =>
      root.render(
        <ServerSourceField
          value={SOURCES[0].url}
          sources={SOURCES}
          disabled={false}
          helper="distrokid-helper"
          onValueChange={vi.fn()}
          onRefresh={vi.fn(async () => undefined)}
          id="server-source"
          {...props}
        />
      )
    );
  }

  it("suppresses refresh reentry, recovers disabled state after reject, and portals into ShadowRoot", async () => {
    const pending = deferred<void>();
    const onRefresh = vi.fn(() => pending.promise);
    await renderField({ onRefresh });
    const trigger = shadow.querySelector<HTMLButtonElement>("#server-source")!;

    await act(async () => {
      trigger.click();
      trigger.click();
      await Promise.resolve();
    });
    expect(onRefresh).toHaveBeenCalledOnce();
    expect(trigger.disabled).toBe(true);
    expect(trigger.textContent).toContain("更新中");

    await act(async () => {
      pending.reject(new Error("discovery failed"));
      await pending.promise.catch(() => undefined);
    });
    await waitFor(() => expect(trigger.disabled).toBe(false));
    await waitFor(() =>
      expect(shadow.querySelectorAll('[role="option"]')).toHaveLength(2)
    );
    expect(document.body.querySelector('[role="option"]')).toBeNull();
  });

  it("suppresses equal and duplicate custom commits and honors disabled state", async () => {
    const onValueChange = vi.fn();
    await renderField({ onValueChange });
    const field = shadow.querySelector<HTMLElement>('[data-slot="field"]')!;

    await act(async () => {
      field.dispatchEvent(
        new CustomEvent(SERVER_SOURCE_SELECT_EVENT, {
          bubbles: true,
          detail: SOURCES[0].url,
        })
      );
      field.dispatchEvent(
        new CustomEvent(SERVER_SOURCE_SELECT_EVENT, {
          bubbles: true,
          detail: SOURCES[1].url,
        })
      );
      field.dispatchEvent(
        new CustomEvent(SERVER_SOURCE_SELECT_EVENT, {
          bubbles: true,
          detail: SOURCES[1].url,
        })
      );
    });
    expect(onValueChange).toHaveBeenCalledOnce();
    expect(onValueChange).toHaveBeenCalledWith(SOURCES[1].url);

    await renderField({ onValueChange, disabled: true });
    const disabledField = shadow.querySelector<HTMLElement>(
      '[data-slot="field"]'
    )!;
    await act(async () => {
      disabledField.dispatchEvent(
        new CustomEvent(SERVER_SOURCE_SELECT_EVENT, {
          bubbles: true,
          detail: SOURCES[0].url,
        })
      );
    });
    expect(onValueChange).toHaveBeenCalledOnce();
    expect(
      shadow.querySelector<HTMLButtonElement>("#server-source")!.disabled
    ).toBe(true);
  });

  it("forwards callback/object refs, resolves the portal parent, and clears it on null", async () => {
    const callbackRef = vi.fn();
    const objectRef = createRef<HTMLButtonElement>();
    const setContainer = vi.fn();

    function RefProbe({
      visible,
      forwardedRef,
    }: {
      visible: boolean;
      forwardedRef: React.Ref<HTMLButtonElement>;
    }) {
      const callback = useShadowPortalTriggerRef(forwardedRef, setContainer);
      return visible ? (
        <button ref={callback} type="button">
          Trigger
        </button>
      ) : null;
    }

    await act(async () =>
      root.render(<RefProbe visible forwardedRef={callbackRef} />)
    );
    const button = shadow.querySelector<HTMLButtonElement>("button")!;
    expect(callbackRef).toHaveBeenCalledWith(button);
    expect(setContainer).toHaveBeenCalledWith(container);

    await act(async () =>
      root.render(<RefProbe visible forwardedRef={objectRef} />)
    );
    expect(objectRef.current).toBe(button);

    await act(async () =>
      root.render(<RefProbe visible={false} forwardedRef={objectRef} />)
    );
    expect(callbackRef).toHaveBeenLastCalledWith(null);
    expect(objectRef.current).toBeNull();
    expect(setContainer).toHaveBeenLastCalledWith(null);
  });

  it("renders DistroKid mode and root from structured metadata while preserving legacy labels and URLs", async () => {
    const onChange = vi.fn();
    const sources = [
      {
        id: "single",
        label: "Same Channel (same.localhost:49152)",
        url: "http://same.localhost:49152",
        capabilities: { distrokid: { mode: "single" as const } },
      },
      {
        id: "planning",
        label: "Same Channel (same.localhost:49153)",
        url: "http://same.localhost:49153",
        capabilities: { distrokid: { mode: "dir" as const } },
        collectionsRoot: "planning",
      },
      {
        id: "live",
        label: "Same Channel (same.localhost:49154)",
        url: "http://same.localhost:49154",
        capabilities: { distrokid: { mode: "dir" as const } },
        collectionsRoot: "live",
      },
      {
        id: "legacy",
        label: "Legacy Channel (legacy.localhost:49155)",
        url: "http://legacy.localhost:49155",
      },
    ];
    await act(async () =>
      root.render(
        <ServerUrlField
          value={sources[0].url}
          sources={sources}
          disabled={false}
          onChange={onChange}
          onOpen={vi.fn(async () => undefined)}
        />
      )
    );

    const trigger = shadow.querySelector<HTMLButtonElement>("#server-url")!;
    expect(trigger.textContent).toContain(
      "Same Channel (same.localhost:49152) [single] | distrokid-helper"
    );
    expect(
      trigger
        .closest('[data-slot="field"]')
        ?.getAttribute("data-selected-value")
    ).toBe(sources[0].url);
    await act(async () => trigger.click());
    await waitFor(() =>
      expect(shadow.querySelectorAll('[role="option"]')).toHaveLength(4)
    );
    expect(
      [...shadow.querySelectorAll('[role="option"]')].map((option) =>
        option.textContent?.trim()
      )
    ).toEqual([
      "Same Channel (same.localhost:49152) [single] | distrokid-helper",
      "Same Channel (same.localhost:49153) [dir/planning] | distrokid-helper",
      "Same Channel (same.localhost:49154) [dir/live] | distrokid-helper",
      "Legacy Channel (legacy.localhost:49155) | distrokid-helper",
    ]);

    const field = shadow.querySelector<HTMLElement>('[data-slot="field"]')!;
    await act(async () => {
      field.dispatchEvent(
        new CustomEvent(SERVER_SOURCE_SELECT_EVENT, {
          bubbles: true,
          detail: sources[2].url,
        })
      );
    });
    expect(onChange).toHaveBeenCalledWith(sources[2].url);
  });
});
