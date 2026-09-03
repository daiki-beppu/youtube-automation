import dadsTokens from "@digital-go-jp/design-tokens";
import { defineConfig } from "blume";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { z } from "zod";
import {
  createOperatorDocSource,
  operatorDocMap,
  operatorDocReleaseField,
} from "./operator-doc-source";
import { releaseFrontmatter } from "./release-schema";
import { releaseRedirects, releaseSidebarGroups } from "./release-sidebar";
import { createSkillPageSource } from "./skill-page-source";

const lightAccent = dadsTokens.Color.Key["800"].$value;
const darkAccent = dadsTokens.Color.Key["400"].$value;
const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const releaseNotesRoot = join(repositoryRoot, "docs/release-notes");
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
            items: [
              "/dashboard",
              "/cloud-execution",
              "/live-chat-reply",
              "/audio-studio",
              "/review-viewers",
            ],
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
      ...releaseSidebarGroups(releaseNotesRoot),
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
  redirects: releaseRedirects(releaseNotesRoot),
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
