// コンテンツ責務（genre / tags / descriptions / title）の型 + parser + ヘルパー。
// Python `utils/config/content.py` の dataclass メソッドは co-located 純関数として移植。

/** `genre` セクション。 */
interface Genre {
  readonly primary: string;
  readonly style: string;
  readonly context: string;
}

/** `tags` セクション。`channelName` は loader が合成時に注入する。 */
export interface Tags {
  readonly base: readonly string[];
  readonly themes: Readonly<Record<string, readonly string[]>>;
  readonly channelSpecific: readonly string[];
  readonly channelName: string;
  readonly minCount: number | null;
}

/** `title.theme_scenes` の各エントリ（TTP 形式）。 */
interface ThemeScene {
  readonly scene?: string;
  readonly activities?: string;
}

/** `title` セクション。 */
export interface Title {
  readonly template: string;
  readonly defaultActivity: string;
  readonly themeScenes: Readonly<Record<string, ThemeScene>>;
  readonly themeActivities: Readonly<Record<string, string>>;
  readonly templateCheck: Readonly<Record<string, unknown>>;
}

/** `descriptions` セクション。`genre` は loader が合成時に注入する。 */
export interface Descriptions {
  readonly opening: string;
  readonly subOpening: string;
  readonly perfectFor: readonly string[];
  readonly hashtags: readonly string[];
  readonly metadata: Readonly<Record<string, unknown>>;
  readonly genre: Genre;
}

/** コンテンツ責務の合成。 */
export interface Content {
  readonly genre: Genre;
  readonly tags: Tags;
  readonly descriptions: Descriptions;
  readonly title: Title;
}

const parseGenre = (merged: Record<string, unknown>): Genre => {
  const gn = merged.genre as Record<string, unknown>;
  return {
    context: gn.context as string,
    primary: gn.primary as string,
    style: gn.style as string,
  };
};

const parseTags = (
  merged: Record<string, unknown>,
  channelName: string
): Tags => {
  const tg = merged.tags as Record<string, unknown>;
  const themesRaw = tg.themes as Record<string, string[]>;
  return {
    base: [...(tg.base as string[])],
    channelName,
    channelSpecific: [...((tg.channel_specific as string[] | undefined) ?? [])],
    minCount: (tg.min_count as number | undefined) ?? null,
    themes: Object.fromEntries(
      Object.entries(themesRaw).map(([k, v]) => [k, [...v]])
    ),
  };
};

const parseDescriptions = (
  merged: Record<string, unknown>,
  genre: Genre
): Descriptions => {
  const dp = merged.descriptions as Record<string, unknown>;
  return {
    genre,
    hashtags: [...(dp.hashtags as string[])],
    metadata: { ...(dp.metadata as Record<string, unknown> | undefined) },
    opening: dp.opening as string,
    perfectFor: [...(dp.perfect_for as string[])],
    subOpening: (dp.sub_opening as string | undefined) ?? "",
  };
};

const parseTitle = (merged: Record<string, unknown>): Title => {
  const tl = merged.title as Record<string, unknown>;
  // 旧実装が default_activities（タイポ）も許容していたので踏襲。
  const defaultActivity =
    (tl.default_activity as string | undefined) ??
    (tl.default_activities as string | undefined) ??
    "Study";
  return {
    defaultActivity,
    template: tl.template as string,
    templateCheck: {
      ...(tl.template_check as Record<string, unknown> | undefined),
    },
    themeActivities: {
      ...(tl.theme_activities as Record<string, string> | undefined),
    },
    themeScenes: {
      ...(tl.theme_scenes as Record<string, ThemeScene> | undefined),
    },
  };
};

export const parseContent = (
  merged: Record<string, unknown>,
  channelName: string
): Content => {
  const genre = parseGenre(merged);
  return {
    descriptions: parseDescriptions(merged, genre),
    genre,
    tags: parseTags(merged, channelName),
    title: parseTitle(merged),
  };
};

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
const titleCase = (s: string): string =>
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
