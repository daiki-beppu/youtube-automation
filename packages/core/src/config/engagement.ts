// engagement バケット — 視聴者接点（comments / pinnedComment / playlists / localizations）。
//
// localizations は sidecar 由来の値として ChannelConfigSchema の assemble で engagement に合成する。

import { z } from "zod";

import { Comments } from "./comments.ts";
import { parseWithIssues } from "./internal.ts";
import { PinnedComment } from "./pinned-comment.ts";
import { Playlists } from "./playlists.ts";

/** engagement バケット: merged から視聴者接点セクションを取り出して束ねる。 */
export const Engagement = z.unknown().transform((merged, ctx) => ({
  comments: parseWithIssues(Comments, merged, ctx),
  pinnedComment: parseWithIssues(PinnedComment, merged, ctx),
  playlists: parseWithIssues(Playlists, merged, ctx),
}));
