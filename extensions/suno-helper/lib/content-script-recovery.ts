interface TabChangeInfo {
  status?: string;
}

interface TabLike {
  id?: number;
  url?: string;
}

interface InstallDetails {
  reason: string;
}

interface ScriptResult {
  result?: unknown;
}

interface ExecuteScriptDetails {
  target: { tabId: number };
  files?: ScriptPublicPath[];
  func?: () => boolean;
  world?: "ISOLATED" | "MAIN";
}

export interface ContentScriptRecoveryDeps {
  addTabUpdatedListener(
    listener: (tabId: number, changeInfo: TabChangeInfo, tab: TabLike) => void
  ): void;
  addInstalledListener(listener: (details: InstallDetails) => void): void;
  queryTabs(): Promise<TabLike[]>;
  reloadTab(tabId: number): Promise<void>;
  executeScript(details: ExecuteScriptDetails): Promise<ScriptResult[]>;
  sleep(ms: number): Promise<void>;
  warn(message: string, error: unknown): void;
}

const SUNO_HOSTS = new Set(["suno.com", "www.suno.com"]);
const ISOLATED_CONTENT_FILES: ScriptPublicPath[] = [
  "/content-scripts/content.js",
  "/content-scripts/overlay.js",
];
const STATIC_INJECTION_GRACE_MS = 1_000;

async function injectSunoContentScripts(
  tabId: number,
  deps: ContentScriptRecoveryDeps
): Promise<void> {
  await Promise.all([
    deps.executeScript({
      target: { tabId },
      files: ["/content-scripts/suno-bridge.js"],
      world: "MAIN",
    }),
    deps.executeScript({
      target: { tabId },
      files: [...ISOLATED_CONTENT_FILES],
      world: "ISOLATED",
    }),
  ]);
}

export function isSunoPageUrl(rawUrl: string | undefined): boolean {
  if (!rawUrl || !URL.canParse(rawUrl)) return false;
  const url = new URL(rawUrl);
  return url.protocol === "https:" && SUNO_HOSTS.has(url.hostname);
}

function hasOverlayHost(): boolean {
  return document.querySelector("suno-helper-overlay") !== null;
}

/**
 * Chrome が unpacked 拡張の静的 content script 登録を取りこぼした場合だけ、同じ bundle を明示注入する。
 * WXT の content-script wrapper は同名 script の新しい起動を検出して古い context を invalidate するため、
 * 静的注入とのレースでも listener / React root が二重に残らない。
 */
export async function recoverSunoContentScripts(
  tabId: number,
  deps: ContentScriptRecoveryDeps
): Promise<boolean> {
  const hasOverlay = async (): Promise<boolean> => {
    const probe = await deps.executeScript({
      target: { tabId },
      func: hasOverlayHost,
    });
    return probe.some(({ result }) => result === true);
  };

  if (await hasOverlay()) return false;

  // tabs.onUpdated(status=complete) と document_idle の静的 content script は前後し得る。
  // 直後の 1 回だけで欠落判定すると静的注入との同時起動で runner が二重化するため、猶予後に再確認する。
  await deps.sleep(STATIC_INJECTION_GRACE_MS);
  if (await hasOverlay()) return false;

  await injectSunoContentScripts(tabId, deps);
  return true;
}

export function installSunoContentScriptRecovery(
  deps: ContentScriptRecoveryDeps
): void {
  deps.addTabUpdatedListener((tabId, changeInfo, tab) => {
    if (changeInfo.status !== "complete" || !isSunoPageUrl(tab.url)) return;
    void recoverSunoContentScripts(tabId, deps).catch((error: unknown) => {
      deps.warn("[suno-helper] content script の自己復旧に失敗しました", error);
    });
  });

  deps.addInstalledListener((details) => {
    if (details.reason !== "update") return;
    void deps
      .queryTabs()
      .then((tabs) =>
        Promise.all(
          tabs
            .filter(
              (tab): tab is TabLike & { id: number } =>
                typeof tab.id === "number" && isSunoPageUrl(tab.url)
            )
            .map((tab) => deps.reloadTab(tab.id))
        )
      )
      .catch((error: unknown) => {
        deps.warn(
          "[suno-helper] 拡張更新後の Suno タブ自動リロードに失敗しました",
          error
        );
      });
  });
}
