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
import { isPlainObject } from "./internal.ts";
import { Localizations, localizationsAbsent } from "./localizations.ts";
import { Publishing } from "./publishing.ts";

const LOCALIZATIONS_KEY = "localizations";

const parseLocalizations = (locRaw: unknown, fallbackLanguage: string) => {
  if (locRaw === undefined) {
    return localizationsAbsent(fallbackLanguage);
  }

  const localizations = Localizations.safeParse(locRaw);
  if (localizations.success) {
    return localizations.data;
  }

  throw new z.ZodError(
    localizations.error.issues.map((issue) => ({
      ...issue,
      path: [LOCALIZATIONS_KEY, ...issue.path],
    }))
  );
};

const assemble = (merged: unknown) => {
  const identity = Identity.parse(merged);
  const publishing = Publishing.parse(merged);
  const engagement = Engagement.parse(merged);
  const locRaw = isPlainObject(merged) ? merged[LOCALIZATIONS_KEY] : undefined;
  const localizations = parseLocalizations(
    locRaw,
    publishing.youtube.api.language
  );

  // tags.channelName は content 単体では決まらないため meta（identity）から注入する。
  const content = {
    ...publishing.content,
    tags: {
      ...publishing.content.tags,
      channelName: identity.meta.channelName,
    },
  };
  return {
    engagement: { ...engagement, localizations },
    identity,
    integrations: Integrations.parse(merged),
    publishing: { ...publishing, content },
  };
};

/** merged config を 4 バケット ChannelConfig へ組み立てる schema。 */
export const ChannelConfigSchema = z
  .unknown()
  .transform(assemble)
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
