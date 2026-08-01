import { defineConfig } from "blume";
import { releaseFrontmatter } from "../../../release-schema";

export default defineConfig({
  content: { root: "docs" },
  frontmatter: { extend: releaseFrontmatter },
});
