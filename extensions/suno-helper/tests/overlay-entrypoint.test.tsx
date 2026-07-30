// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const reactRootMocks = vi.hoisted(() => ({
  createRoot: vi.fn(),
  render: vi.fn(),
  unmount: vi.fn(),
}));

vi.mock("react-dom/client", () => ({
  createRoot: reactRootMocks.createRoot,
}));

vi.mock("../components/Overlay", () => ({
  Overlay: () => null,
}));

interface ShadowUiOptions {
  onMount: (container: HTMLElement) => { unmount: () => void };
  onRemove: (root: { unmount: () => void } | undefined) => void;
}

// REQ-2920-01: overlay lifecycle unmounts and cleans up failed mounts.
describe("overlay content entrypoint", () => {
  let options: ShadowUiOptions;
  const mount = vi.fn();
  const remove = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    reactRootMocks.createRoot.mockReturnValue({
      render: reactRootMocks.render,
      unmount: reactRootMocks.unmount,
    });
    mount.mockImplementation(() => undefined);
    remove.mockImplementation(() => undefined);
    vi.stubGlobal(
      "defineContentScript",
      (definition: { main: (context: unknown) => Promise<void> }) => definition
    );
    vi.stubGlobal(
      "createShadowRootUi",
      vi.fn(async (_context: unknown, receivedOptions: ShadowUiOptions) => {
        options = receivedOptions;
        return { mount, remove };
      })
    );
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("onRemove は mount 済み React root を一回 unmount する", async () => {
    const entrypoint = (await import("../entrypoints/overlay.content")).default;

    await entrypoint.main({} as never);
    const root = options.onMount(document.createElement("div"));
    options.onRemove(root);

    expect(mount).toHaveBeenCalledOnce();
    expect(reactRootMocks.render).toHaveBeenCalledOnce();
    expect(reactRootMocks.unmount).toHaveBeenCalledOnce();
  });

  it("mount 失敗時は UI を cleanup して元の失敗を reject する", async () => {
    const error = new Error("shadow mount failed");
    mount.mockImplementationOnce(() => {
      throw error;
    });
    const entrypoint = (await import("../entrypoints/overlay.content")).default;

    await expect(entrypoint.main({} as never)).rejects.toBe(error);

    expect(remove).toHaveBeenCalledOnce();
  });
});
