// プレイリスト設定（Python `utils/config/playlists.py` + loader `_build_playlists` の移植）。

import { isRecord } from "./internal.ts";

/**
 * `playlists` セクション（optional）。
 *
 * `items` は `{ key: { playlist_id, auto_add, title, ... } }` の dict-of-dict。
 * 入力 JSON は string 形式 (`{"main": "PL..."}`) と dict 形式の両方を許容し、
 * loader で必ず dict 形式へ正規化する。string は
 * `{ playlist_id: <値>, auto_add: true, title: null }` へ展開（#275）。
 * 内部エントリは snake_case キーを verbatim 保持する。
 */
export interface Playlists {
  readonly items: Readonly<Record<string, Record<string, unknown>>>;
}

export const parsePlaylists = (merged: Record<string, unknown>): Playlists => {
  const raw = merged.playlists;
  if (raw === undefined || raw === null) {
    return { items: {} };
  }
  if (!isRecord(raw)) {
    throw new Error(
      "config: playlists セクションは object でなければなりません"
    );
  }
  const items: Record<string, Record<string, unknown>> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value === "string") {
      items[key] = { auto_add: true, playlist_id: value, title: null };
    } else if (isRecord(value)) {
      items[key] = { ...value };
    } else {
      // list / number / null など想定外型は Fail Fast で弾く（#419）。
      throw new Error(
        `config: playlists.${key} は string または object でなければなりません`
      );
    }
  }
  return { items };
};
