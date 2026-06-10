// ChannelConfig 合成スキーマ（責務別セクション schema を merged から組み立てる）。
//
// 各セクション schema は merged（`config/channel/*.json` をマージした object）を受け取り、
// 自分の担当キーを取り出して名前空間付きの camelCase 出力へ transform する。
// cross-section 検証（title.theme_scenes ⊆ tags.themes）は superRefine で行う。
// localizations は別ファイル（`config/localizations.json`）由来のため loader が合成する。

import { z } from "zod";

import { Analytics } from "./analytics.ts";
import { Audio } from "./audio.ts";
import { Comments } from "./comments.ts";
import { Content } from "./content.ts";
import { Distrokid } from "./distrokid.ts";
import type { Localizations } from "./localizations.ts";
import { ChannelMeta } from "./meta.ts";
import { PinnedComment } from "./pinned-comment.ts";
import { Playlists } from "./playlists.ts";
import { Shorts } from "./shorts.ts";
import { Workflow } from "./workflow.ts";
import { Youtube } from "./youtube.ts";

const assemble = (merged: unknown) => {
  const meta = ChannelMeta.parse(merged);
  const contentRaw = Content.parse(merged);
  // tags.channelName は content 単体では決まらないため meta から注入する。
  const content = {
    ...contentRaw,
    tags: { ...contentRaw.tags, channelName: meta.channelName },
  };
  return {
    analytics: Analytics.parse(merged),
    audio: Audio.parse(merged),
    comments: Comments.parse(merged),
    content,
    distrokid: Distrokid.parse(merged),
    meta,
    pinnedComment: PinnedComment.parse(merged),
    playlists: Playlists.parse(merged),
    shorts: Shorts.parse(merged),
    workflow: Workflow.parse(merged),
    youtube: Youtube.parse(merged),
  };
};

/** merged config を名前空間付き ChannelConfig（localizations を除く）へ組み立てる schema。 */
export const ChannelConfigSchema = z
  .unknown()
  .transform(assemble)
  .superRefine((config, ctx) => {
    // title.theme_scenes のキー ⊆ tags.themes のキー
    const themeKeys = new Set(Object.keys(config.content.tags.themes));
    const unknownScenes = Object.keys(config.content.title.themeScenes)
      .filter((key) => !themeKeys.has(key))
      .toSorted();
    if (unknownScenes.length > 0) {
      ctx.addIssue({
        code: "custom",
        message: `title.theme_scenes に tags.themes で定義されていないテーマキーがあります: ${JSON.stringify(unknownScenes)}`,
      });
    }
  });

/** チャンネル設定の合成ルート（責務別ネームスペースでアクセスする）。 */
export type ChannelConfig = z.infer<typeof ChannelConfigSchema> & {
  readonly localizations: Localizations;
};
