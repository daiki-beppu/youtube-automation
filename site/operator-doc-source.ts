import { existsSync, realpathSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { isAbsolute, posix, resolve, sep } from "node:path";
import type { ContentSource, SourceEntry } from "blume/sources/types";
import { extractMarkdownTitle } from "./markdown-title.ts";

const GITHUB_BLOB_BASE =
  "https://github.com/daiki-beppu/youtube-automation/blob/main/";

export interface OperatorDocMapping {
  readonly source: string;
  readonly route: string;
}

export const operatorDocMap = [
  { source: "ONBOARDING.md", route: "/onboarding" },
  { source: "docs/tool-setup.md", route: "/tool-setup" },
  { source: "docs/oauth-setup.md", route: "/oauth-setup" },
  { source: "docs/features.md", route: "/features" },
  { source: "docs/workflow-cheatsheet.md", route: "/workflow-cheatsheet" },
  {
    source: "docs/chrome-extension-install-guide.md",
    route: "/chrome-extension-install-guide",
  },
  { source: "docs/dashboard.md", route: "/dashboard" },
  {
    source: "docs/channel-workspace-migration.md",
    route: "/channel-workspace-migration",
  },
  { source: "docs/cloud-execution.md", route: "/cloud-execution" },
  { source: "docs/live-streaming.md", route: "/live-streaming" },
  { source: "docs/live-chat-reply.md", route: "/live-chat-reply" },
  { source: "docs/ambient-layers.md", route: "/ambient-layers" },
  { source: "docs/scheduled-publish.md", route: "/scheduled-publish" },
  { source: "docs/localizations.md", route: "/localizations" },
  { source: "docs/distrokid.md", route: "/distrokid" },
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
  return map.map((entry) => {
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
    return { route, source };
  });
};

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
