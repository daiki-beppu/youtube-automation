// chrome.storage.local 経由のサーバー URL 保存を @wxt-dev/storage の型付き wrapper で
// 書き換える (要件4)。key は shared/constants の STORAGE_KEY を SSOT とする。
import { storage } from "wxt/utils/storage";

import {
  DEFAULT_SERVER_SOURCES,
  DEFAULT_URL,
  DOWNLOAD_FORMAT_DEFAULT,
  DOWNLOAD_FORMAT_KEY,
  type LocalServerSource,
  labelFromServerUrl,
  normalizeServerUrl,
  SERVER_SOURCES_STORAGE_KEY,
  serverSourceIdFromUrl,
  STORAGE_KEY,
} from "../../shared/constants";

/** サーバー URL の型付き storage item。未設定時は DEFAULT_URL を返す。 */
export const serverUrlItem = storage.defineItem<string>(`local:${STORAGE_KEY}`, {
  fallback: DEFAULT_URL,
});

export const serverSourcesItem = storage.defineItem<LocalServerSource[]>(`local:${SERVER_SOURCES_STORAGE_KEY}`, {
  fallback: [...DEFAULT_SERVER_SOURCES],
});

/** Suno ダウンロード形式の union 型 (#1215)。postDownloaded の payload と一致させる。 */
export type DownloadFormat = "mp3" | "m4a" | "wav";

/** Suno ダウンロード形式の型付き storage item (#1215)。未設定時は "mp3" を返す。 */
export const downloadFormatItem = storage.defineItem<DownloadFormat>(`local:${DOWNLOAD_FORMAT_KEY}`, {
  fallback: DOWNLOAD_FORMAT_DEFAULT,
});

const DOWNLOAD_FORMAT_VALUES = ["mp3", "m4a", "wav"] as const;

export function normalizeDownloadFormat(value: unknown): DownloadFormat {
  return DOWNLOAD_FORMAT_VALUES.includes(value as DownloadFormat) ? (value as DownloadFormat) : DOWNLOAD_FORMAT_DEFAULT;
}

export async function readDownloadFormat(): Promise<DownloadFormat> {
  const value: unknown = await downloadFormatItem.getValue();
  const normalized = normalizeDownloadFormat(value);
  if (normalized !== value) {
    await downloadFormatItem.setValue(normalized);
  }
  return normalized;
}

function normalizeSource(source: LocalServerSource): LocalServerSource {
  const url = normalizeServerUrl(source.url);
  return {
    id: source.id || serverSourceIdFromUrl(url),
    label: source.label || labelFromServerUrl(url),
    url,
  };
}

function mergeSources(sources: LocalServerSource[]): LocalServerSource[] {
  const byUrl = new Map<string, LocalServerSource>();
  for (const source of [...DEFAULT_SERVER_SOURCES, ...sources]) {
    const normalized = normalizeSource(source);
    byUrl.set(normalized.url, normalized);
  }
  return [...byUrl.values()];
}

export async function readServerSources(): Promise<LocalServerSource[]> {
  const stored = await serverSourcesItem.getValue();
  const sources = Array.isArray(stored) ? mergeSources(stored) : [...DEFAULT_SERVER_SOURCES];
  await serverSourcesItem.setValue(sources);
  return sources;
}

export async function rememberServerSource(url: string, label?: string): Promise<LocalServerSource[]> {
  const normalizedUrl = normalizeServerUrl(url);
  const current = await readServerSources();
  const source = normalizeSource({
    id: serverSourceIdFromUrl(normalizedUrl),
    label: label || labelFromServerUrl(normalizedUrl),
    url: normalizedUrl,
  });
  const next = mergeSources([...current.filter((item) => item.url !== normalizedUrl), source]);
  await serverSourcesItem.setValue(next);
  return next;
}
