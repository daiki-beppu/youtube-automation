import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";

import { Overlay } from "@/components/Overlay";
import { MANIFEST_CONTENT_SCRIPT_MATCHES } from "@/lib/manifest";

import "../components/overlay.css";

export default defineContentScript({
  matches: [...MANIFEST_CONTENT_SCRIPT_MATCHES],
  cssInjectionMode: "ui",
  async main(ctx) {
    const ui = await createShadowRootUi<Root>(ctx, {
      name: "distrokid-helper-overlay",
      position: "overlay",
      alignment: "top-left",
      zIndex: 2_147_483_647,
      onMount: (container) => {
        const root = createRoot(container);
        root.render(createElement(Overlay));
        return root;
      },
      onRemove: (root) => root?.unmount(),
    });
    ui.mount();
  },
});
