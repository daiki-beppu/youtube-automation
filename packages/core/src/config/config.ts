// ChannelConfig 合成スキーマ（責務別セクションを 4 バケットへ束ねる）。
//
// 各バケット schema は merged（`config/channel/*.json` をマージした object）を受け取り、
// 担当セクションを名前空間付きの camelCase 出力へ transform する。
// バケット構成（Issue #827）:
//   identity     → { meta }
//   publishing   → { audio, content, shorts, workflow, youtube }
//   engagement   → { comments, pinnedComment, playlists, localizations }
//   integrations → { analytics, distrokid }
//
// content.tags.channelName は identity.meta 由来のセクション横断値のため、合成ルートで注入する。
// cross-section / cross-file 検証は superRefine で行う。

import { z } from "zod";

import { Engagement } from "./engagement.ts";
import { Identity } from "./identity.ts";
import { Integrations } from "./integrations.ts";
import { addIssues, isPlainObject } from "./internal.ts";
import { Localizations, localizationsAbsent } from "./localizations.ts";
import { Publishing } from "./publishing.ts";

const LOCALIZATIONS_KEY = "localizations";

const parseLocalizations = (
  locRaw: unknown,
  fallbackLanguage: string,
  ctx: z.RefinementCtx
) => {
  if (locRaw === undefined) {
    return localizationsAbsent(fallbackLanguage);
  }

  const localizations = Localizations.safeParse(locRaw);
  if (localizations.success) {
    return localizations.data;
  }

  addIssues(ctx, localizations.error.issues, [LOCALIZATIONS_KEY]);
  return z.NEVER;
};

const assemble = (merged: unknown, ctx: z.RefinementCtx) => {
  const identity = Identity.safeParse(merged);
  const publishing = Publishing.safeParse(merged);
  const engagement = Engagement.safeParse(merged);
  const integrations = Integrations.safeParse(merged);

  if (!identity.success) {
    addIssues(ctx, identity.error.issues);
  }
  if (!publishing.success) {
    addIssues(ctx, publishing.error.issues);
  }
  if (!engagement.success) {
    addIssues(ctx, engagement.error.issues);
  }
  if (!integrations.success) {
    addIssues(ctx, integrations.error.issues);
  }
  if (
    !identity.success ||
    !publishing.success ||
    !engagement.success ||
    !integrations.success
  ) {
    return z.NEVER;
  }

  const locRaw = isPlainObject(merged) ? merged[LOCALIZATIONS_KEY] : undefined;
  const localizations = parseLocalizations(
    locRaw,
    publishing.data.youtube.api.language,
    ctx
  );

  // tags.channelName は content 単体では決まらないため meta（identity）から注入する。
  const content = {
    ...publishing.data.content,
    tags: {
      ...publishing.data.content.tags,
      channelName: identity.data.meta.channelName,
    },
  };
  return {
    engagement: { ...engagement.data, localizations },
    identity: identity.data,
    integrations: integrations.data,
    publishing: { ...publishing.data, content },
  };
};

/** merged config を 4 バケット ChannelConfig へ組み立てる schema。 */
export const ChannelConfigSchema = z
  .unknown()
  .transform((merged, ctx) => assemble(merged, ctx))
  .superRefine((config, ctx) => {
    // title.theme_scenes のキー ⊆ tags.themes のキー
    const themeKeys = new Set(
      Object.keys(config.publishing.content.tags.themes)
    );
    const unknownScenes = Object.keys(
      config.publishing.content.title.themeScenes
    )
      .filter((key) => !themeKeys.has(key))
      .toSorted();
    if (unknownScenes.length > 0) {
      ctx.addIssue({
        code: "custom",
        message: `title.theme_scenes に tags.themes で定義されていないテーマキーがあります: ${JSON.stringify(unknownScenes)}`,
      });
    }

    if (config.engagement.localizations.exists) {
      const supported = new Set(
        config.engagement.localizations.supportedLanguages
      );
      const unknownLangs =
        config.publishing.youtube.contentModel.languages.filter(
          (lang) => !supported.has(lang)
        );
      if (unknownLangs.length > 0) {
        ctx.addIssue({
          code: "custom",
          message: `content_model.languages に localizations.supported_languages へ未登録の言語があります: ${JSON.stringify(unknownLangs)}`,
        });
      }
    }
  });

/** チャンネル設定の合成ルート（4 バケット名前空間でアクセスする）。 */
export type ChannelConfig = z.infer<typeof ChannelConfigSchema>;
