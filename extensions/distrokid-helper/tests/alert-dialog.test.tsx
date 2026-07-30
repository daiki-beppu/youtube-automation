// @vitest-environment jsdom

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@youtube-automation/ui";
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

describe("AlertDialog Shadow portal", () => {
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

  it("portals inside ShadowRoot, opens/closes via cancel, and passes dialog props", async () => {
    const onOpenChange = vi.fn();
    await act(async () =>
      root.render(
        <AlertDialog onOpenChange={onOpenChange}>
          <AlertDialogTrigger aria-label="open dialog" data-probe="trigger">
            Open
          </AlertDialogTrigger>
          <AlertDialogContent
            size="sm"
            aria-label="confirmation"
            data-probe="content"
          >
            <AlertDialogHeader>
              <AlertDialogTitle>Delete release?</AlertDialogTitle>
              <AlertDialogDescription>
                This cannot be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel aria-label="cancel action">
                Cancel
              </AlertDialogCancel>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )
    );
    const trigger = shadow.querySelector<HTMLButtonElement>(
      '[aria-label="open dialog"]'
    )!;
    expect(trigger.dataset.probe).toBe("trigger");
    await act(async () => trigger.click());
    await waitFor(() =>
      expect(
        shadow.querySelector('[data-slot="alert-dialog-content"]')
      ).not.toBeNull()
    );

    const content = shadow.querySelector<HTMLElement>(
      '[data-slot="alert-dialog-content"]'
    )!;
    expect(content.dataset.size).toBe("sm");
    expect(content.dataset.probe).toBe("content");
    expect(content.getAttribute("aria-label")).toBe("confirmation");
    expect(
      document.body.querySelector("[data-slot='alert-dialog-content']")
    ).toBeNull();
    expect(
      shadow.querySelector('[data-slot="alert-dialog-overlay"]')
    ).not.toBeNull();

    await act(async () =>
      shadow
        .querySelector<HTMLButtonElement>('[aria-label="cancel action"]')!
        .click()
    );
    await waitFor(() =>
      expect(
        shadow.querySelector('[data-slot="alert-dialog-content"]')
      ).toBeNull()
    );
    expect(onOpenChange).toHaveBeenCalledWith(
      false,
      expect.objectContaining({ reason: expect.anything() })
    );
  });

  it("passes action props and lets the action close a controlled dialog", async () => {
    const onAction = vi.fn();
    function ControlledDialog() {
      const [open, setOpen] = useState(false);
      return (
        <AlertDialog open={open} onOpenChange={setOpen}>
          <AlertDialogTrigger>Open action</AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogTitle>Confirm</AlertDialogTitle>
            <AlertDialogAction
              aria-label="confirm action"
              data-probe="action"
              onClick={() => {
                onAction();
                setOpen(false);
              }}
            >
              Confirm
            </AlertDialogAction>
          </AlertDialogContent>
        </AlertDialog>
      );
    }
    await act(async () => root.render(<ControlledDialog />));
    await act(async () =>
      shadow
        .querySelector<HTMLButtonElement>('[data-slot="alert-dialog-trigger"]')!
        .click()
    );
    await waitFor(() =>
      expect(
        shadow.querySelector('[aria-label="confirm action"]')
      ).not.toBeNull()
    );
    const action = shadow.querySelector<HTMLButtonElement>(
      '[aria-label="confirm action"]'
    )!;
    expect(action.dataset.probe).toBe("action");
    await act(async () => action.click());
    expect(onAction).toHaveBeenCalledOnce();
    await waitFor(() =>
      expect(
        shadow.querySelector('[data-slot="alert-dialog-content"]')
      ).toBeNull()
    );
  });
});
