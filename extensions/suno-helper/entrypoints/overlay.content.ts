// Suno UI 上に draggable overlay (#892) をマウントする UI 専用 content script。
// runner 本体 (entrypoints/content.ts) とは責務分離し、本 script は Shadow DOM 上へ
// React tree (<Overlay />) をマウントするだけに専念する。messaging 経由で runner と話すため
// マウント先は問わない。Shadow DOM 隔離で Suno 側 CSS と Tailwind が競合しない (要件8)。
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";

import { SUNO_MATCHES } from "../../shared/constants";
import { Overlay } from "../components/Overlay";

import "../components/overlay.css";

export default defineContentScript({
  matches: [...SUNO_MATCHES],
  // 生成した CSS を Shadow DOM 内へ注入する（webpage 側へは漏らさない）。
  cssInjectionMode: "ui",
  async main(ctx) {
    const ui = await createShadowRootUi<Root>(ctx, {
      name: "suno-helper-overlay",
      position: "overlay",
      alignment: "top-left",
      zIndex: 2147483647,
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
