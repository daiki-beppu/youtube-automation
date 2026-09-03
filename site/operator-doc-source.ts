import { existsSync, realpathSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { isAbsolute, posix, resolve, sep } from "node:path";
import type { ContentSource, SourceEntry } from "blume/sources/types";
import { extractMarkdownTitle } from "./markdown-title.ts";

const GITHUB_BLOB_BASE =
  "https://github.com/daiki-beppu/youtube-automation/blob/main/";

export interface OperatorDocMapping {
  /** タブ導入前に公開していた flat route。転送不要な新規 doc では省く。 */
  readonly legacyRoute?: string;
  readonly source: string;
  readonly route: string;
}

export interface OperatorDocRedirect {
  readonly from: string;
  readonly status: 301;
  readonly to: string;
}

export const operatorDocMap = [
  {
    legacyRoute: "/onboarding",
    source: "ONBOARDING.md",
    route: "/getting-started/onboarding",
  },
  {
    legacyRoute: "/tool-setup",
    source: "docs/tool-setup.md",
    route: "/getting-started/tool-setup",
  },
  {
    legacyRoute: "/oauth-setup",
    source: "docs/oauth-setup.md",
    route: "/getting-started/oauth-setup",
  },
  { source: "docs/oauth-scopes.md", route: "/getting-started/oauth-scopes" },
  { legacyRoute: "/features", source: "docs/features.md", route: "/skills/features" },
  {
    legacyRoute: "/workflow-cheatsheet",
    source: "docs/workflow-cheatsheet.md",
    route: "/guides/workflow-cheatsheet",
  },
  {
    legacyRoute: "/chrome-extension-install-guide",
    source: "docs/chrome-extension-install-guide.md",
    route: "/getting-started/chrome-extension-install-guide",
  },
  {
    legacyRoute: "/dashboard",
    source: "docs/dashboard.md",
    route: "/guides/dashboard",
  },
  {
    legacyRoute: "/channel-workspace-migration",
    source: "docs/channel-workspace-migration.md",
    route: "/releases/workspace-migration",
  },
  {
    legacyRoute: "/cloud-execution",
    source: "docs/cloud-execution.md",
    route: "/guides/cloud-execution",
  },
  {
    legacyRoute: "/live-streaming",
    source: "docs/live-streaming.md",
    route: "/guides/live-streaming",
  },
  {
    legacyRoute: "/live-chat-reply",
    source: "docs/live-chat-reply.md",
    route: "/guides/live-chat-reply",
  },
  {
    legacyRoute: "/ambient-layers",
    source: "docs/ambient-layers.md",
    route: "/guides/ambient-layers",
  },
  {
    legacyRoute: "/scheduled-publish",
    source: "docs/scheduled-publish.md",
    route: "/guides/scheduled-publish",
  },
  {
    legacyRoute: "/localizations",
    source: "docs/localizations.md",
    route: "/guides/localizations",
  },
  {
    legacyRoute: "/distrokid",
    source: "docs/distrokid.md",
    route: "/guides/distrokid",
  },
  {
    legacyRoute: "/audio-studio",
    source: "docs/audio-studio.md",
    route: "/guides/audio-studio",
  },
  {
    legacyRoute: "/review-viewers",
    source: "docs/review-viewers.md",
    route: "/guides/review-viewers",
  },
  {
    source: "docs/migration/high-cpm-locales.md",
    route: "/releases/high-cpm-locales",
  },
  { source: "docs/upgrades/v5.4.0.md", route: "/releases/upgrades/v5.4.0" },
  { source: "docs/upgrades/v5.5.0.md", route: "/releases/upgrades/v5.5.0" },
  { source: "docs/upgrades/v5.5.1.md", route: "/releases/upgrades/v5.5.1" },
] as const satisfies readonly OperatorDocMapping[];

/** Internal marker allowing staged operator entries through release-only fields. */
export const operatorDocReleaseField = Symbol("operator-doc-release-field");

const onboardingDiscoveryMetadata = {
  ai: { exclude: true },
  noindex: true,
  search: { exclude: true },
} as const;

const normalizedRepositoryPath = (path: string): string => {
  const normalized = posix.normalize(path.replaceAll("\\", "/"));
  if (
    path.length === 0 ||
    isAbsolute(path) ||
    normalized === ".." ||
    normalized.startsWith("../")
  ) {
    throw new Error(`Operator document path escapes repository: ${path}`);
  }
  return normalized.replace(/^\.\//u, "");
};

const normalizedRoute = (route: string): string => {
  const normalized = posix.normalize(`/${route}`);
  if (route.length === 0 || normalized === "/" || normalized.includes("..")) {
    throw new Error(`Invalid operator document route: ${route}`);
  }
  return normalized;
};

const validateMap = (
  map: readonly OperatorDocMapping[]
): readonly OperatorDocMapping[] => {
  const sources = new Set<string>();
  const routes = new Set<string>();
  const legacyRoutes = new Set<string>();
  const validated = map.map((entry) => {
    const source = normalizedRepositoryPath(entry.source);
    const route = normalizedRoute(entry.route);
    if (sources.has(source)) {
      throw new Error(`Duplicate source in operator document map: ${source}`);
    }
    if (routes.has(route)) {
      throw new Error(`Duplicate route in operator document map: ${route}`);
    }
    sources.add(source);
    routes.add(route);
    if (entry.legacyRoute === undefined) {
      return { route, source };
    }
    const legacyRoute = normalizedRoute(entry.legacyRoute);
    if (legacyRoutes.has(legacyRoute)) {
      throw new Error(
        `Duplicate legacy route in operator document map: ${legacyRoute}`
      );
    }
    legacyRoutes.add(legacyRoute);
    return { legacyRoute, route, source };
  });
  for (const legacyRoute of legacyRoutes) {
    if (routes.has(legacyRoute)) {
      // 生成ページを redirect が覆い隠すため、route と legacy route は排他にする。
      throw new Error(
        `Legacy route collides with a generated route: ${legacyRoute}`
      );
    }
  }
  return validated;
};

/**
 * 既存の外部リンクを保つため、タブ導入前の flat route を新 route へ転送する。
 * 明示 map から導くので出力順は宣言順で安定する。
 */
export const operatorDocRedirects = (
  map: readonly OperatorDocMapping[]
): OperatorDocRedirect[] =>
  validateMap(map).flatMap((entry) =>
    entry.legacyRoute === undefined
      ? []
      : [{ from: entry.legacyRoute, status: 301 as const, to: entry.route }]
  );

const upgradeGuideRoutePrefix = "/releases/upgrades/";
const upgradeGuideVersion = /^v(\d+)\.(\d+)\.(\d+)$/u;

const upgradeGuideOrder = (route: string): number[] => {
  const version = upgradeGuideVersion.exec(route.slice(upgradeGuideRoutePrefix.length));
  if (version === null) {
    throw new Error(`Unsupported upgrade guide route: ${route}`);
  }
  return version.slice(1).map(Number);
};

/**
 * 「アップデート」タブの「バージョン別アップグレード」節。
 * version ごとに navigation を手で足す運用は追加漏れで drift するため（#4802）、
 * 公開 map から導いて新しい version から並べる。
 */
export const upgradeGuideRoutes = (map: readonly OperatorDocMapping[]): string[] =>
  validateMap(map)
    .map((entry) => entry.route)
    .filter((route) => route.startsWith(upgradeGuideRoutePrefix))
    // 比較関数は要素が 1 件だと呼ばれないため、order は先に全件求めて fail closed にする。
    .map((route) => ({ order: upgradeGuideOrder(route), route }))
    .toSorted((left, right) => {
      const difference = left.order.findIndex(
        (value, index) => value !== right.order[index]
      );
      return difference === -1 ? 0 : right.order[difference] - left.order[difference];
    })
    .map((entry) => entry.route);

const targetParts = (target: string): { fragment: string; path: string } => {
  const fragmentIndex = target.indexOf("#");
  return fragmentIndex === -1
    ? { fragment: "", path: target }
    : {
        fragment: target.slice(fragmentIndex),
        path: target.slice(0, fragmentIndex),
      };
};

const isAbsoluteUrl = (target: string): boolean =>
  target.startsWith("//") || /^[a-z][a-z\d+.-]*:/iu.test(target);

const resolveLinkTarget = (
  target: string,
  source: string,
  routeBySource: ReadonlyMap<string, string>
): string => {
  if (target.startsWith("#") || isAbsoluteUrl(target)) {
    return target;
  }
  const wrapped = target.startsWith("<") && target.endsWith(">");
  const unwrapped = wrapped ? target.slice(1, -1) : target;
  const { fragment, path } = targetParts(unwrapped);
  if (!/\.mdx?$/iu.test(path)) {
    return target;
  }

  const sourceDirectory = posix.dirname(normalizedRepositoryPath(source));
  const repositoryPath = normalizedRepositoryPath(
    path.startsWith("/")
      ? path.slice(1)
      : posix.join(sourceDirectory === "." ? "" : sourceDirectory, path)
  );
  const resolved = `${routeBySource.get(repositoryPath) ?? `${GITHUB_BLOB_BASE}${repositoryPath}`}${fragment}`;
  return wrapped ? `<${resolved}>` : resolved;
};

export const rewriteMarkdownLinks = (
  markdown: string,
  source: string,
  map: readonly OperatorDocMapping[]
): string => {
  const validatedMap = validateMap(map);
  const routeBySource = new Map(
    validatedMap.map((entry) => [entry.source, entry.route])
  );
  return markdown.replace(
    /(!?\[[^\]\n]*\]\()(<[^>\n]+>|[^\s)]+)([^)\n]*\))/gu,
    (_match, opening: string, target: string, closing: string) =>
      `${opening}${resolveLinkTarget(target, source, routeBySource)}${closing}`
  );
};

export const rewriteFeatureSkillLinks = (markdown: string): string =>
  markdown.replace(
    /^(\|\s*)\/([a-z0-9]+(?:-[a-z0-9]+)*)(\s*\|)/gmu,
    "$1[/$2](/skills/$2)$3"
  );

const assertReadableSource = (repositoryRoot: string, source: string): string => {
  const path = resolve(repositoryRoot, source);
  if (!existsSync(path)) {
    throw new Error(`Operator document source not found: ${source}`);
  }
  const realRepositoryRoot = realpathSync(repositoryRoot);
  const realSource = realpathSync(path);
  if (
    realSource !== realRepositoryRoot &&
    !realSource.startsWith(`${realRepositoryRoot}${sep}`)
  ) {
    throw new Error(`Operator document source escapes repository: ${source}`);
  }
  return realSource;
};

export const createOperatorDocSource = (options: {
  readonly map: readonly OperatorDocMapping[];
  readonly repositoryRoot: string;
}): ContentSource => {
  const map = validateMap(options.map);
  const repositoryRoot = resolve(options.repositoryRoot);

  const validate = (): void => {
    for (const entry of map) {
      assertReadableSource(repositoryRoot, entry.source);
    }
  };

  const readEntry = async (mapping: OperatorDocMapping): Promise<SourceEntry> => {
    const path = assertReadableSource(repositoryRoot, mapping.source);
    const original = await readFile(path, "utf8");
    const rewritten = rewriteMarkdownLinks(original, mapping.source, map);
    const rendered =
      mapping.source === "docs/features.md"
        ? rewriteFeatureSkillLinks(rewritten)
        : rewritten;
    const { text, title } = extractMarkdownTitle(rendered);
    const discoveryMetadata =
      mapping.source === "ONBOARDING.md" ? onboardingDiscoveryMetadata : {};
    const rawDiscoveryMetadata =
      mapping.source === "ONBOARDING.md"
        ? "ai:\n  exclude: true\nnoindex: true\nsearch:\n  exclude: true\nseo:\n  noindex: true\n"
        : "";
    return {
      body: { format: "md", text },
      data: {
        kind: operatorDocReleaseField,
        released_at: operatorDocReleaseField,
        summary: operatorDocReleaseField,
        title,
        type: "doc",
        version: operatorDocReleaseField,
        ...discoveryMetadata,
      },
      editUrl: `${GITHUB_BLOB_BASE}${mapping.source}`,
      raw: `---\ntitle: ${JSON.stringify(title)}\ntype: doc\n${rawDiscoveryMetadata}---\n\n${text}`,
      ref: mapping.source,
      slug: mapping.route,
    };
  };

  return {
    load: async () => {
      validate();
      return {
        diagnostics: [],
        entries: await Promise.all(map.map(readEntry)),
      };
    },
    name: "operator-docs",
    read: async (ref) => {
      const mapping = map.find((entry) => entry.source === ref);
      if (!mapping) {
        throw new Error(`Unknown operator document source: ${ref}`);
      }
      return (await readEntry(mapping)).body.text;
    },
    staged: true,
    validate,
  };
};
