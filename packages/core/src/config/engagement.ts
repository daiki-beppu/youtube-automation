// engagement バケット — 視聴者接点（comments / pinnedComment / playlists / localizations）。
//
// localizations は `config/channel/` の外（`config/localizations.json`）由来のため、ここでは
// 束ねず loader が読み込んで engagement バケットへ注入する（Issue #827）。

import { z } from "zod";

import { Comments } from "./comments.ts";
import { PinnedComment } from "./pinned-comment.ts";
import { Playlists } from "./playlists.ts";

/** engagement バケット: merged から視聴者接点セクションを取り出して束ねる。 */
export const Engagement = z.unknown().transform((merged) => ({
  comments: Comments.parse(merged),
  pinnedComment: PinnedComment.parse(merged),
  playlists: Playlists.parse(merged),
}));
