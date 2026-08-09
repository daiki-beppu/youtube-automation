import dadsTokens from "@digital-go-jp/design-tokens";
import { defineConfig } from "blume";
import { releaseFrontmatter } from "./release-schema";

const lightAccent = dadsTokens.Color.Key["800"].$value;
const darkAccent = dadsTokens.Color.Key["400"].$value;

export default defineConfig({
  title: "youtube-automation ドキュメント",
  description: "youtube-automation の公式ドキュメント",
  content: {
    root: "../docs/release-notes",
  },
  frontmatter: {
    extend: releaseFrontmatter,
  },
  navigation: {
    sidebar: [
      {
        label: "本体",
        items: ["/v5.6.0", "/v5.5.17"],
      },
      {
        label: "Chrome 拡張",
        items: ["/ext-v0.3.0", "/ext-v0.2.5"],
      },
    ],
    tabs: [{ label: "リリースノート", path: "/", href: "/" }],
  },
  theme: {
    accent: {
      light: lightAccent,
      dark: darkAccent,
    },
    mode: "system",
    radius: "lg",
  },
  toc: false,
});
