// コンテンツ責務（genre / tags / descriptions / title）の schema + ヘルパー。
// dataclass メソッドは co-located 純関数として保持する。
//
// `tags.themes` / `title.theme_scenes` / `title.theme_activities` / `template_check` /
// `descriptions.metadata` はテーマキー・任意キーを保持する passthrough map のため
// snakeToCamel は適用せず verbatim 保持する。`channelName` は loader が合成時に注入する。

import { z } from "zod";

/** `title.theme_scenes` の各エントリ（TTP 形式）。 */
const ThemeScene = z.object({
  activities: z.string().optional(),
  scene: z.string().optional(),
});

/** コンテンツ責務の合成（merged の `genre` + `tags` + `descriptions` + `title`）。 */
export const Content = z
  .object({
    descriptions: z
      .object({
        hashtags: z.array(z.string()),
        metadata: z.record(z.string(), z.unknown()).default({}),
        opening: z.string(),
        perfect_for: z.array(z.string()),
        sub_opening: z.string().default(""),
      })
      .strict(),
    genre: z
      .object({
        context: z.string(),
        primary: z.string(),
        style: z.string(),
      })
      .strict(),
    tags: z
      .object({
        base: z.array(z.string()),
        channel_specific: z.array(z.string()).default([]),
        min_count: z.number().nullable().default(null),
        themes: z.record(z.string(), z.array(z.string())),
      })
      .strict(),
    title: z
      .object({
        // 旧実装が default_activities（タイポ）も許容していたので踏襲。
        default_activities: z.string().optional(),
        default_activity: z.string().optional(),
        template: z.string(),
        template_check: z.record(z.string(), z.unknown()).default({}),
        theme_activities: z.record(z.string(), z.string()).default({}),
        theme_scenes: z.record(z.string(), ThemeScene).default({}),
      })
      .strict(),
  })
  .transform((o) => {
    const genre = {
      context: o.genre.context,
      primary: o.genre.primary,
      style: o.genre.style,
    };
    return {
      descriptions: {
        genre,
        hashtags: o.descriptions.hashtags,
        metadata: o.descriptions.metadata,
        opening: o.descriptions.opening,
        perfectFor: o.descriptions.perfect_for,
        subOpening: o.descriptions.sub_opening,
      },
      genre,
      tags: {
        base: o.tags.base,
        // loader が meta.channelName を注入する（プレースホルダ）。
        channelName: "",
        channelSpecific: o.tags.channel_specific,
        minCount: o.tags.min_count,
        themes: o.tags.themes,
      },
      title: {
        defaultActivity:
          o.title.default_activity ?? o.title.default_activities ?? "Study",
        template: o.title.template,
        templateCheck: o.title.template_check,
        themeActivities: o.title.theme_activities,
        themeScenes: o.title.theme_scenes,
      },
    };
  });

export type Content = z.infer<typeof Content>;
export type Tags = Content["tags"];
export type Title = Content["title"];
export type Descriptions = Content["descriptions"];

/** チャンネル名（小文字）を含むデフォルトタグリスト。 */
export const tagsDefault = (tags: Tags): string[] => [
  ...tags.base,
  tags.channelName.toLowerCase(),
];

/** コレクション名からタグリストを生成（最大 50 件）。 */
export const tagsForCollection = (
  tags: Tags,
  collectionName: string
): string[] => {
  const result = tagsDefault(tags);
  result.push(...tags.channelSpecific);
  const lowered = collectionName.toLowerCase();
  for (const [theme, themeTagList] of Object.entries(tags.themes)) {
    if (lowered.includes(theme)) {
      result.push(...themeTagList);
      break;
    }
  }
  return result.slice(0, 50);
};

// Python `str.title()` 相当: 連続する英字ランの先頭を大文字・残りを小文字化する。
// 例 "8-bit" → "8-Bit"（数字直後の英字も語頭として扱われる）。
export const titleCase = (s: string): string =>
  s.replaceAll(
    /[A-Za-z]+/gu,
    (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
  );

/** `{style}` / `{primary}` / `{context}` を format 展開した冒頭行を返す。 */
export const renderOpening = (d: Descriptions): string =>
  d.opening
    .replaceAll("{style}", titleCase(d.genre.style))
    .replaceAll("{primary}", d.genre.primary)
    .replaceAll("{context}", d.genre.context);

/** ハッシュタグ行（スペース区切り）。 */
export const hashtagLine = (d: Descriptions): string => d.hashtags.join(" ");

// 長いキーから順に評価するため entries を key 長 降順でソートして返す（longest-match, #80）。
const byLengthDesc = <T>(obj: Readonly<Record<string, T>>): [string, T][] =>
  Object.entries(obj).sort((a, b) => b[0].length - a[0].length);

/**
 * テーマ名からアクティビティキーワードを取得。
 *
 * `theme_scenes` 優先（TTP 形式）、未定義なら `theme_activities`（レガシー形式）。
 * 解決順序: (1) 完全一致 → (2) longest-match substring → (3) `defaultActivity`。
 */
export const activityForTheme = (title: Title, theme: string): string => {
  const lowered = theme.toLowerCase();
  if (Object.keys(title.themeScenes).length > 0) {
    const exact = title.themeScenes[lowered];
    if (exact !== undefined) {
      return exact.activities ?? title.defaultActivity;
    }
    for (const [keyword, scene] of byLengthDesc(title.themeScenes)) {
      if (lowered.includes(keyword)) {
        return scene.activities ?? title.defaultActivity;
      }
    }
    return title.defaultActivity;
  }
  if (Object.keys(title.themeActivities).length > 0) {
    const exact = title.themeActivities[lowered];
    if (exact !== undefined) {
      return exact;
    }
    for (const [keyword, activity] of byLengthDesc(title.themeActivities)) {
      if (lowered.includes(keyword)) {
        return activity;
      }
    }
  }
  return title.defaultActivity;
};

/**
 * テーマ名から英語シーンフレーズを取得（longest-match）。
 * 未定義なら空文字列を返す（呼び出し側が `--en` フォールバックを判定する）。
 */
export const sceneForTheme = (title: Title, theme: string): string => {
  if (Object.keys(title.themeScenes).length === 0) {
    return "";
  }
  const lowered = theme.toLowerCase();
  const exact = title.themeScenes[lowered];
  if (exact !== undefined) {
    return exact.scene ?? "";
  }
  for (const [keyword, scene] of byLengthDesc(title.themeScenes)) {
    if (lowered.includes(keyword)) {
      return scene.scene ?? "";
    }
  }
  return "";
};
