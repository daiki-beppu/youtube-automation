// Shorts 用メタデータの pure 組み立て（metadata_generator.py の module-level
// helper `_format_short_duration_phrase` / `build_short_description` /
// `build_short_localizations` の移植）。
//
// description / localizations は複数経路から呼ばれるため単一の事実源にする。

import type { Audio } from "../config/audio.ts";
import type { ChannelConfig } from "../config/config.ts";
import {
  DESCRIPTION_CODEPOINT_LIMIT,
  pyFormat,
  truncateCodepoints,
} from "./format.ts";
import { rawLocalizations } from "./loc-data.ts";

// Python 組み込み `round()` 相当の round-half-to-even（banker's rounding）。
// `Math.round` は half-up のため 2.5 → 3 となり Python（2.5 → 2）と乖離する。
// 30 分の奇数倍（例 150 分）で差が出るため、faithful port では Python と揃える。
const roundHalfToEven = (value: number): number => {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff < 0.5) {
    return floor;
  }
  if (diff > 0.5) {
    return floor + 1;
  }
  return floor % 2 === 0 ? floor : floor + 1;
};

/**
 * `audio.target_duration_min` から「2 hours」等の表示文字列を組み立てる。
 * null のときは "Full collection" にフォールバック（TypeError 回避）。
 */
export const formatShortDurationPhrase = (audio: Audio): string => {
  const targetMin = audio.targetDurationMin;
  if (targetMin === null) {
    return "Full collection";
  }
  const hours = roundHalfToEven(targetMin / 60);
  return hours === 1 ? "1 hour" : `${hours} hours`;
};

interface ShortDescriptionOptions {
  readonly collectionName: string;
  readonly ccVideoUrl: string;
}

/**
 * Shorts デフォルト description（fallback と default 両方で使う共通組み立て）。
 * `ccVideoUrl` が空なら `♫` 行を含めない。末尾に必ず `#Shorts` を付ける。
 */
export const buildShortDescription = (
  config: ChannelConfig,
  { collectionName, ccVideoUrl }: ShortDescriptionOptions
): string => {
  const durationPhrase = formatShortDurationPhrase(config.audio);
  const parts = [
    `${collectionName} (${durationPhrase}) | ${config.meta.channelName}`,
    "",
  ];
  if (ccVideoUrl) {
    parts.push(`♫ Full → ${ccVideoUrl}`, "");
  }
  parts.push("#Shorts");
  return parts.join("\n");
};

interface ShortLocalizationsOptions {
  readonly collectionName: string;
  readonly theme: string;
  readonly ccVideoUrl: string;
}

interface LocalizedText {
  readonly title: string;
  readonly description: string;
}

/**
 * Shorts 用 localizations を生成する。
 *
 * - `short_title_template` を持たない言語は skip。
 * - `short_description_template` が無い言語は `buildShortDescription` フォールバック。
 * - `theme` を必須にして、初回 upload タイトル破壊事故を構造的に防ぐ。
 */
export const buildShortLocalizations = (
  config: ChannelConfig,
  { collectionName, theme, ccVideoUrl }: ShortLocalizationsOptions
): Record<string, LocalizedText> => {
  if (Object.keys(config.localizations.data).length === 0) {
    return {};
  }
  const loc = rawLocalizations(config);
  const { channelName, tagline: defaultTagline } = config.meta;
  const result: Record<string, LocalizedText> = {};

  for (const lang of loc.supported_languages ?? []) {
    const langData = loc.languages?.[lang] ?? {};
    const titleTpl = langData.short_title_template;
    if (!titleTpl) {
      continue;
    }
    const title = pyFormat(titleTpl, {
      channel_name: channelName,
      collection_name: collectionName,
      theme,
    });

    const descData = langData.description ?? {};
    const tagline = descData.tagline ?? defaultTagline;
    const descTpl = langData.short_description_template;
    const description = descTpl
      ? pyFormat(descTpl, {
          cc_video_url: ccVideoUrl,
          channel_name: channelName,
          collection_name: collectionName,
          tagline,
        })
      : buildShortDescription(config, { ccVideoUrl, collectionName });

    result[lang] = {
      description: truncateCodepoints(description, DESCRIPTION_CODEPOINT_LIMIT),
      title,
    };
  }
  return result;
};
