import dadsTokens from "@digital-go-jp/design-tokens";
import { defineConfig } from "blume";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { z } from "zod";
import {
  createOperatorDocSource,
  operatorDocMap,
  operatorDocRedirects,
  operatorDocReleaseField,
} from "./operator-doc-source";
import { releaseFrontmatter } from "./release-schema";
import {
  firstReleaseRoute,
  releaseRedirects,
  releaseSidebarGroups,
} from "./release-sidebar";
import { createSkillPageSource, skillSidebarRoutes } from "./skill-page-source";

const lightAccent = dadsTokens.Color.Key["800"].$value;
const darkAccent = dadsTokens.Color.Key["400"].$value;
const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const releaseNotesRoot = join(repositoryRoot, "docs/release-notes");
const releaseNavigationGroups = releaseSidebarGroups(releaseNotesRoot);
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
      { prefix: "releases", root: "../docs/release-notes", type: "filesystem" },
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
  i18n: {
    defaultLocale: "ja",
    locales: [{ code: "ja", label: "日本語" }],
  },
  navigation: {
    sidebar: [
      {
        label: "はじめる",
        root: "/getting-started",
        items: [
          "/getting-started/tool-setup",
          "/getting-started/oauth-setup",
          "/getting-started/chrome-extension-install-guide",
        ],
      },
      {
        label: "ガイド",
        root: "/guides",
        items: [
          "/guides/workflow-cheatsheet",
          {
            display: "group",
            label: "実験的機能",
            items: [
              "/guides/dashboard",
              "/guides/cloud-execution",
              "/guides/live-chat-reply",
              "/guides/audio-studio",
              "/guides/review-viewers",
            ],
          },
          {
            display: "group",
            label: "こんなこともできる！",
            items: [
              "/guides/live-streaming",
              "/guides/ambient-layers",
              "/guides/scheduled-publish",
              "/guides/localizations",
              "/guides/distrokid",
            ],
          },
        ],
      },
      {
        label: "スキル",
        root: "/skills",
        items: skillSidebarRoutes(repositoryRoot),
      },
      {
        label: "アップデート",
        root: "/releases",
        items: [
          {
            label: "移行ガイド",
            items: [
              "/releases/workspace-migration",
              "/releases/high-cpm-locales",
            ],
          },
          {
            label: "バージョン別アップグレード",
            items: [
              "/releases/upgrades/v5.5.1",
              "/releases/upgrades/v5.5.0",
              "/releases/upgrades/v5.4.0",
            ],
          },
          ...releaseNavigationGroups,
        ],
      },
    ],
    tabs: [
      {
        href: "/getting-started/tool-setup",
        label: "はじめる",
        path: "/getting-started",
      },
      {
        href: "/guides/workflow-cheatsheet",
        label: "ガイド",
        path: "/guides",
      },
      {
        href: "/skills",
        label: "スキル",
        path: "/skills",
      },
      {
        href: firstReleaseRoute(releaseNavigationGroups),
        label: "アップデート",
        path: "/releases",
      },
    ],
  },
  redirects: [
    ...releaseRedirects(releaseNotesRoot),
    ...operatorDocRedirects(operatorDocMap),
  ],
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
