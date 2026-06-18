// `config/localizations.json` の raw 構造への型付きアクセサ。
//
// Python 版は `config.engagement.localizations.data`（dict そのもの）を `.get(...)` で読んでいた。
// TS でも parse 済みの `Localizations.data`（raw JSON）を直接読むため、metadata 生成が
// 参照するキー群だけを構造として宣言する。

import type { ChannelConfig } from "../../config/config.ts";

/** 言語別 `description` ブロック（全キー optional）。 */
interface RawLangDescription {
  readonly tagline?: string;
  readonly opening_poem?: string;
  readonly cta_subscribe?: string;
  readonly hashtags?: string;
}

/** 言語別エントリ（`languages[<lang>]`）。 */
interface RawLangData {
  readonly short_title_template?: string;
  readonly short_description_template?: string;
  readonly title_template?: string;
  readonly activities?: string;
  readonly description?: RawLangDescription;
}

/** `localizations.json` の参照キー群。 */
export interface RawLocalizations {
  readonly supported_languages?: readonly string[];
  readonly languages?: Readonly<Record<string, RawLangData>>;
}

export const rawLocalizations = (config: ChannelConfig): RawLocalizations =>
  config.engagement.localizations.data as RawLocalizations;
