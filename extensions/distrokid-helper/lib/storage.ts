// サーバー URL の永続化（@wxt-dev/storage）。
//
// 実 read/write は chrome.storage が必要なため拡張ランタイム側でのみ動く。
// 既定値は shared/constants.ts の DEFAULT_URL を SSOT として参照する。

import { storage } from "@wxt-dev/storage";
import {
  DEFAULT_SERVER_SOURCES,
  DEFAULT_URL,
  type LocalServerSource,
  labelFromServerUrl,
  normalizeServerUrl,
  SERVER_SOURCES_STORAGE_KEY,
  serverSourceIdFromUrl,
} from "../../shared/constants";

// サーバー URL の永続化アイテム（local area）。
export const serverUrlItem = storage.defineItem<string>("local:serverUrl", {
  fallback: DEFAULT_URL,
});

export const serverSourcesItem = storage.defineItem<LocalServerSource[]>(`local:${SERVER_SOURCES_STORAGE_KEY}`, {
  fallback: [...DEFAULT_SERVER_SOURCES],
});

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
