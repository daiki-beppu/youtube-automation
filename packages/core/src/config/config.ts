// ChannelConfig 合成スキーマ（責務別セクションを 4 バケットへ束ねる）。
//
// 各バケット schema は merged（`config/channel/*.json` をマージした object）を受け取り、
// 担当セクションを名前空間付きの camelCase 出力へ transform する。
// バケット構成（Issue #827）:
//   identity     → { meta }
//   publishing   → { audio, content, shorts, workflow, youtube }
//   engagement   → { comments, pinnedComment, playlists }（localizations は loader 注入）
//   integrations → { analytics, distrokid }
//
// content.tags.channelName は identity.meta 由来のセクション横断値のため、合成ルートで注入する。
// cross-section 検証（title.theme_scenes ⊆ tags.themes）は superRefine で行う。
// localizations は別ファイル（`config/localizations.json`）由来のため loader が engagement へ合成する。

import { z } from "zod";

import { Engagement } from "./engagement.ts";
import { Identity } from "./identity.ts";
import { Integrations } from "./integrations.ts";
import type { Localizations } from "./localizations.ts";
import { Publishing } from "./publishing.ts";

const assemble = (merged: unknown) => {
  const identity = Identity.parse(merged);
  const publishing = Publishing.parse(merged);
  // tags.channelName は content 単体では決まらないため meta（identity）から注入する。
  const content = {
    ...publishing.content,
    tags: {
      ...publishing.content.tags,
      channelName: identity.meta.channelName,
    },
  };
  return {
    engagement: Engagement.parse(merged),
    identity,
    integrations: Integrations.parse(merged),
    publishing: { ...publishing, content },
  };
};

/** merged config を 4 バケット ChannelConfig（localizations を除く）へ組み立てる schema。 */
export const ChannelConfigSchema = z
  .unknown()
  .transform(assemble)
  .superRefine((config, ctx) => {
    // title.theme_scenes のキー ⊆ tags.themes のキー
    const themeKeys = new Set(
      Object.keys(config.publishing.content.tags.themes)
    );
    const unknownScenes = Object.keys(config.publishing.content.title.themeScenes)
      .filter((key) => !themeKeys.has(key))
      .toSorted();
    if (unknownScenes.length > 0) {
      ctx.addIssue({
        code: "custom",
        message: `title.theme_scenes に tags.themes で定義されていないテーマキーがあります: ${JSON.stringify(unknownScenes)}`,
      });
    }
  });

type Assembled = z.infer<typeof ChannelConfigSchema>;

/**
 * チャンネル設定の合成ルート（4 バケット名前空間でアクセスする）。
 * localizations は loader が engagement バケットへ注入するため、合成スキーマの infer に
 * 後付けする（schema 単体では表現できない cross-file 値のため intersection で合成する）。
 */
export type ChannelConfig = Omit<Assembled, "engagement"> & {
  readonly engagement: Assembled["engagement"] & {
    readonly localizations: Localizations;
  };
};
