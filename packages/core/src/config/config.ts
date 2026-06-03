// ChannelConfig 合成ルート型（Python `utils/config/config.py` の移植）。

import type { Analytics } from "./analytics.ts";
import type { Audio } from "./audio.ts";
import type { Comments } from "./comments.ts";
import type { Content } from "./content.ts";
import type { Distrokid } from "./distrokid.ts";
import type { Localizations } from "./localizations.ts";
import type { ChannelMeta } from "./meta.ts";
import type { PinnedComment } from "./pinned-comment.ts";
import type { Playlists } from "./playlists.ts";
import type { Shorts } from "./shorts.ts";
import type { Workflow } from "./workflow.ts";
import type { YoutubeSection } from "./youtube.ts";

/** チャンネル設定の合成ルート（責務別ネームスペースでアクセスする）。 */
export interface ChannelConfig {
  readonly meta: ChannelMeta;
  readonly content: Content;
  readonly youtube: YoutubeSection;
  readonly analytics: Analytics;
  readonly playlists: Playlists;
  readonly workflow: Workflow;
  readonly shorts: Shorts;
  readonly audio: Audio;
  readonly localizations: Localizations;
  readonly comments: Comments;
  readonly pinnedComment: PinnedComment;
  readonly distrokid: Distrokid;
}
