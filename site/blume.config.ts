import { defineConfig } from "blume";
import { releaseFrontmatter } from "./release-schema";

export default defineConfig({
  title: "youtube-automation リリースノート",
  description: "youtube-automation と Chrome 拡張の更新内容",
  content: {
    root: "../docs/release-notes",
  },
  frontmatter: {
    extend: releaseFrontmatter,
  },
  navigation: {
    tabs: [{ label: "リリースノート", path: "/", href: "/" }],
  },
  theme: {
    accent: "violet",
    mode: "system",
    radius: "lg",
  },
  toc: false,
});
