// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

const entrypointMocks = vi.hoisted(() => ({
  definition: undefined as
    | {
        main: (context: object) => Promise<void>;
        cssInjectionMode: string;
      }
    | undefined,
  mount: vi.fn(),
  render: vi.fn(),
  unmount: vi.fn(),
  shadowOptions: undefined as
    | {
        onMount: (container: HTMLElement) => unknown;
        onRemove: (root: { unmount: () => void } | undefined) => void;
      }
    | undefined,
}));

vi.mock("react-dom/client", () => ({
  createRoot: vi.fn(() => ({
    render: entrypointMocks.render,
    unmount: entrypointMocks.unmount,
  })),
}));

describe("distrokid overlay content entrypoint", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
    entrypointMocks.mount.mockClear();
    entrypointMocks.render.mockClear();
    entrypointMocks.unmount.mockClear();
    entrypointMocks.definition = undefined;
    entrypointMocks.shadowOptions = undefined;
  });

  it("mounts, renders, and unmounts the React root through the Shadow UI lifecycle", async () => {
    vi.stubGlobal(
      "defineContentScript",
      (definition: typeof entrypointMocks.definition) => {
        entrypointMocks.definition = definition;
        return definition;
      }
    );
    vi.stubGlobal(
      "createShadowRootUi",
      vi.fn(async (_context, options) => {
        entrypointMocks.shadowOptions = options;
        return { mount: entrypointMocks.mount };
      })
    );

    await import("../entrypoints/overlay.content");
    expect(entrypointMocks.definition?.cssInjectionMode).toBe("ui");
    await entrypointMocks.definition!.main({ page: "distrokid" });
    expect(createShadowRootUi).toHaveBeenCalledWith(
      { page: "distrokid" },
      expect.objectContaining({
        name: "distrokid-helper-overlay",
        position: "overlay",
      })
    );
    expect(entrypointMocks.mount).toHaveBeenCalledOnce();

    const root = entrypointMocks.shadowOptions!.onMount(
      document.createElement("div")
    );
    expect(entrypointMocks.render).toHaveBeenCalledOnce();
    entrypointMocks.shadowOptions!.onRemove(root as { unmount: () => void });
    expect(entrypointMocks.unmount).toHaveBeenCalledOnce();
  });
});
