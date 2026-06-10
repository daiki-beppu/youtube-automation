// Complete Collection のタイトル・説明文・多言語ローカライゼーション生成
// （metadata_generator.py の `_generate_title` / `generate_complete_collection_metadata`
// の説明文組み立て / `generate_localizations` / `validate_scene_phrases` の pure 部分）。
//
// section_headers / usage_lines / duration / tracks など workflow-state / skill_config
// 由来の値は引数で受け取り、ここでは fs I/O・subprocess を持たない純関数に保つ。

import type { ChannelConfig } from "../config/config.ts";
import { hashtagLine, renderOpening, titleCase } from "../config/content.ts";
import {
  codepointLength,
  DESCRIPTION_CODEPOINT_LIMIT,
  formatTitleTemplate,
  pyFormat,
  truncateCodepoints,
} from "./format.ts";
import { rawLocalizations } from "./loc-data.ts";

const TITLE_CODEPOINT_LIMIT = 100;

// generate_localizations が全言語共通で埋める usage 行（Python 版と同一文面）。
const LOCALIZED_USAGE_LINES = [
  "• Original AI composition",
  "• Free for personal & non-commercial use",
  "• For commercial use, check the platform's AI content policy",
  "• Redistribution prohibited",
].join("\n");

/** 多言語タイトルの codepoint 超過違反（100 codepoint 上限）。 */
export interface SceneTitleViolation {
  readonly lang: string;
  readonly length: number;
  readonly title: string;
  readonly template: string;
}

const metadataString = (
  metadata: Readonly<Record<string, unknown>>,
  key: string,
  fallback: string
): string => (metadata[key] as string | undefined) ?? fallback;

/**
 * scene_phrases を localizations の全言語で試算し、100 codepoint 超過を一括検出する。
 *
 * @throws {Error} `validation:` prefix — scene_phrases が一部言語で欠落、または
 *   `title_template` が無い言語があるとき。
 */
export const validateScenePhrases = (
  scenePhrases: Readonly<Record<string, string>>,
  config: ChannelConfig,
  sceneEmoji: string
): SceneTitleViolation[] => {
  const loc = rawLocalizations(config);
  const supported = loc.supported_languages ?? [];

  const missing = supported.filter((lang) => !scenePhrases[lang]);
  if (missing.length > 0) {
    throw new Error(
      `validation: scene_phrases に翻訳が不足しています。不足言語: ${JSON.stringify(missing)}\n` +
        "→ コレクションの workflow-state.json に scene_phrases: {en, ja, ...} を populate してください。"
    );
  }

  const bestForLine = metadataString(
    config.content.descriptions.metadata,
    "best_for",
    "Study, Focus, Late Night"
  );

  const violations: SceneTitleViolation[] = [];
  for (const lang of supported) {
    const langData = loc.languages?.[lang] ?? {};
    const titleTpl = langData.title_template;
    if (!titleTpl) {
      throw new Error(
        `validation: localizations.json: language '${lang}' に title_template が無い`
      );
    }
    const activities = langData.activities ?? bestForLine;
    // missing チェック通過済みのため scenePhrases[lang] は必ず存在する。
    const scene = scenePhrases[lang] as string;
    const title = formatTitleTemplate(
      titleTpl,
      { activities, scene_emoji: sceneEmoji, scene_phrase: scene },
      `localizations.json: language '${lang}' の title_template`
    );
    const length = codepointLength(title);
    if (length > TITLE_CODEPOINT_LIMIT) {
      violations.push({ lang, length, template: titleTpl, title });
    }
  }
  return violations;
};

/** 違反リストを人間可読な複数行テキストへ整形する（CLI / エラーメッセージ共通）。 */
export const formatSceneTitleViolations = (
  violations: readonly SceneTitleViolation[]
): string =>
  violations
    .map(
      (v) =>
        `  - [${v.lang}] ${v.length} codepoints (+${
          v.length - TITLE_CODEPOINT_LIMIT
        }): ${v.title}`
    )
    .join("\n");

interface CompleteCollectionTitleOptions {
  readonly theme: string;
  readonly activity: string;
  readonly activities: string;
  readonly scenePhrase: string;
  readonly sceneEmoji: string;
  readonly durationDisplay: string;
  readonly durationShort: string;
}

/**
 * content.json の title.template から Complete Collection タイトルを生成する（100 codepoint 制限）。
 *
 * @throws {Error} `validation:` prefix — タイトルが 100 codepoint を超過したとき（silent slice 禁止）。
 */
export const generateCompleteCollectionTitle = (
  config: ChannelConfig,
  options: CompleteCollectionTitleOptions
): string => {
  const title = formatTitleTemplate(
    config.content.title.template,
    {
      activities: options.activities,
      activity: options.activity,
      duration_display: options.durationDisplay,
      duration_short: options.durationShort,
      scene_emoji: options.sceneEmoji,
      scene_phrase: options.scenePhrase,
      style: titleCase(config.content.genre.style),
      theme: options.theme,
    },
    "content.json: title.template"
  );
  const length = codepointLength(title);
  if (length > TITLE_CODEPOINT_LIMIT) {
    throw new Error(
      `validation: 生成したタイトルが ${length} codepoint と ${TITLE_CODEPOINT_LIMIT} を超過: \n  ${title}\n` +
        "→ config/channel/content.json の title.theme_scenes の scene を短く書き直してください"
    );
  }
  return title;
};

interface CompleteDescriptionSectionHeaders {
  readonly channelLinkTemplate: string;
  readonly perfectFor: string;
  readonly usageAttribution: string;
}

interface CompleteDescriptionOptions {
  readonly title: string;
  readonly timestampBody: string;
  readonly usageLines: readonly string[];
  readonly sectionHeaders: CompleteDescriptionSectionHeaders;
}

/** Complete Collection の説明文を組み立てる（Python 版の構造順を踏襲）。 */
export const buildCompleteCollectionDescription = (
  config: ChannelConfig,
  options: CompleteDescriptionOptions
): string => {
  const { sectionHeaders, timestampBody, title, usageLines } = options;
  const { descriptions } = config.content;

  const parts: string[] = [`🎵 ${title}`, ""];
  if (timestampBody) {
    parts.push(timestampBody);
  }

  const perfectForLines = descriptions.perfectFor
    .map((item) => `• ${item}`)
    .join("\n");
  const channelLinkHeader = pyFormat(sectionHeaders.channelLinkTemplate, {
    channel_name: config.meta.channelName,
  });

  parts.push(
    "",
    renderOpening(descriptions),
    descriptions.subOpening,
    "",
    sectionHeaders.usageAttribution,
    ...usageLines,
    "",
    `${sectionHeaders.perfectFor}\n${perfectForLines}`,
    "",
    channelLinkHeader,
    config.meta.ctaSubscribe,
    config.meta.tagline,
    "",
    hashtagLine(descriptions)
  );
  return parts.join("\n");
};

interface LocalizationsSectionHeaders {
  readonly channelLinkTemplate: string;
  readonly trackList: string;
  readonly usageAttribution: string;
}

interface GenerateLocalizationsOptions {
  readonly scenePhrases: Readonly<Record<string, string>>;
  readonly timestampBody: string;
  readonly sceneEmoji: string;
  readonly sectionHeaders: LocalizationsSectionHeaders;
}

interface LocalizedText {
  readonly title: string;
  readonly description: string;
}

/**
 * 各言語のローカライズされたタイトル・説明文を生成する（TTP ハイブリッド方式）。
 *
 * 100 codepoint 超過は全言語まとめて検出し、1 件でもあれば throw する。
 *
 * @throws {Error} `validation:` prefix — scene_phrases 欠落・title_template 欠落・codepoint 超過時。
 */
export const generateLocalizations = (
  config: ChannelConfig,
  options: GenerateLocalizationsOptions
): Record<string, LocalizedText> => {
  const { sceneEmoji, scenePhrases, sectionHeaders, timestampBody } = options;
  const loc = rawLocalizations(config);
  const { metadata } = config.content.descriptions;
  const genreLine = metadataString(metadata, "genre", "Jazz");
  const vibeLine = metadataString(metadata, "vibe", "Rainy night, Cozy");
  const bestForLine = metadataString(
    metadata,
    "best_for",
    "Study, Focus, Late Night"
  );

  const violations = validateScenePhrases(scenePhrases, config, sceneEmoji);
  if (violations.length > 0) {
    throw new Error(
      `validation: localizations の ${violations.length} 言語でタイトルが ${TITLE_CODEPOINT_LIMIT} codepoint を超過:\n` +
        `${formatSceneTitleViolations(violations)}\n` +
        "→ workflow-state.json の該当 scene_phrases を短縮してください"
    );
  }

  const result: Record<string, LocalizedText> = {};
  for (const lang of loc.supported_languages ?? []) {
    const langData = loc.languages?.[lang] ?? {};
    const descData = langData.description ?? {};
    // validateScenePhrases 通過済みのため scene と title_template は必ず存在する。
    const scene = scenePhrases[lang] as string;
    const titleTpl = langData.title_template as string;
    const activities = langData.activities ?? bestForLine;
    const title = formatTitleTemplate(
      titleTpl,
      { activities, scene_emoji: sceneEmoji, scene_phrase: scene },
      `localizations.json: language '${lang}' の title_template`
    );

    const openingPoem = descData.opening_poem ?? "";
    const cta = descData.cta_subscribe ?? config.meta.ctaSubscribe;
    const tagline = descData.tagline ?? config.meta.tagline;
    const hashtags =
      descData.hashtags ?? hashtagLine(config.content.descriptions);
    const channelLinkHeader = pyFormat(sectionHeaders.channelLinkTemplate, {
      channel_name: config.meta.channelName,
    });

    const descParts: string[] = [];
    if (openingPoem) {
      descParts.push(openingPoem, "");
    }
    descParts.push(
      `- Genre : ${genreLine}`,
      `- Vibe : ${vibeLine}`,
      `- Best for : ${bestForLine}`,
      "",
      sectionHeaders.trackList,
      timestampBody,
      "",
      sectionHeaders.usageAttribution,
      LOCALIZED_USAGE_LINES,
      "",
      channelLinkHeader,
      cta,
      tagline,
      "",
      hashtags
    );

    result[lang] = {
      description: truncateCodepoints(
        descParts.join("\n"),
        DESCRIPTION_CODEPOINT_LIMIT
      ),
      title,
    };
  }
  return result;
};
