import dadsTokens from "@digital-go-jp/design-tokens";
import { defineConfig } from "blume";
import { releaseScaleLabels } from "./release-scale";
import { fileURLToPath } from "node:url";
import { z } from "zod";
import {
  createOperatorDocSource,
  operatorDocMap,
  operatorDocReleaseField,
} from "./operator-doc-source";
import { releaseFrontmatter } from "./release-schema";
import { createSkillPageSource } from "./skill-page-source";

const lightAccent = dadsTokens.Color.Key["800"].$value;
const darkAccent = dadsTokens.Color.Key["400"].$value;
const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const operatorDocReleaseFieldSchema = z
  .custom((value) => value === operatorDocReleaseField)
  .transform(() => undefined);
const mixedContentFrontmatter = Object.fromEntries(
  Object.entries(releaseFrontmatter).map(([key, schema]) => [
    key,
    schema.or(operatorDocReleaseFieldSchema),
  ])
);

export default defineConfig({
  title: "youtube-automation ドキュメント",
  description: "youtube-automation の公式ドキュメント",
  content: {
    root: "../docs/release-notes",
    sources: [
      { root: "../docs/release-notes", type: "filesystem" },
      {
        source: createOperatorDocSource({ map: operatorDocMap, repositoryRoot }),
        type: "custom",
      },
      {
        source: createSkillPageSource({ repositoryRoot }),
        type: "custom",
      },
    ],
  },
  frontmatter: {
    extend: mixedContentFrontmatter,
  },
  navigation: {
    sidebar: [
      {
        label: "はじめる",
        items: ["/tool-setup", "/oauth-setup", "/chrome-extension-install-guide"],
      },
      {
        label: "使う",
        items: [
          "/skills",
          "/features",
          "/workflow-cheatsheet",
          "/channel-workspace-migration",
          {
            display: "group",
            label: "実験的機能",
            items: ["/dashboard", "/cloud-execution", "/live-chat-reply"],
          },
          {
            display: "group",
            label: "こんなこともできる！",
            items: [
              "/live-streaming",
              "/ambient-layers",
              "/scheduled-publish",
              "/localizations",
              "/distrokid",
            ],
          },
        ],
      },
      {
        label: `本体｜${releaseScaleLabels.major}`,
        items: ["/v5.6.0"],
      },
      {
        label: `本体｜${releaseScaleLabels.minor}`,
        items: ["/v5.5.17"],
      },
      {
        label: `Chrome 拡張｜${releaseScaleLabels.major}`,
        items: ["/ext-v0.3.0"],
      },
      {
        label: `Chrome 拡張｜${releaseScaleLabels.minor}`,
        items: ["/ext-v0.2.5"],
      },
    ],
    // Operator routes are intentionally flat; root-scoped tabs keep the same
    // three-section sidebar visible instead of treating one route as a prefix.
    tabs: [
      {
        href: "/#getting-started",
        label: "はじめる",
        path: "/",
      },
      {
        href: "/#use",
        label: "使う",
        path: "/",
      },
      {
        href: "/#release-notes",
        label: "リリースノート",
        path: "/",
      },
    ],
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
