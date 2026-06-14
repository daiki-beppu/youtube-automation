// プレイリスト設定（merged の `playlists`・optional）。
//
// `items` は `{ key: { playlist_id, auto_add, title, ... } }` の dict-of-dict。
// 入力 JSON は string 形式 (`{"main": "PL..."}`) と dict 形式の両方を許容し、
// string は `{ playlist_id: <値>, auto_add: true, title: null }` へ展開（#275）。
// 内部エントリは snake_case キーを verbatim 保持する。

import { z } from "zod";

/** `playlists` セクション（optional）。 */
export const Playlists = z
  .object({
    playlists: z
      .record(
        z.string(),
        z.union([z.string(), z.record(z.string(), z.unknown())])
      )
      .prefault({}),
  })
  .transform((o) => {
    const items: Record<string, Record<string, unknown>> = {};
    for (const [key, value] of Object.entries(o.playlists)) {
      items[key] =
        typeof value === "string"
          ? { auto_add: true, playlist_id: value, title: null }
          : { ...value };
    }
    return { items };
  });

export type Playlists = z.infer<typeof Playlists>;
