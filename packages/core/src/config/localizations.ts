// ローカライゼーション設定（`config/localizations.json`、`config/channel/` の外の別ファイル）。
//
// - exists=true: `data` に JSON 全量（raw passthrough）、`supportedLanguages` /
//   `defaultLanguage` も埋める
// - exists=false: `data={}`、`supportedLanguages=[youtube.api.language]`、`defaultLanguage=""`

import { z } from "zod";

/** localizations.json の内容を parse して計算済みフィールドへ transform する。 */
export const Localizations = z
  .looseObject({
    default_language: z.string().default(""),
    supported_languages: z.array(z.string()).default([]),
  })
  .transform((o) => ({
    data: o as Record<string, unknown>,
    defaultLanguage: o.default_language,
    exists: true,
    supportedLanguages: o.supported_languages,
  }));

export type Localizations = z.infer<typeof Localizations>;

/** localizations.json が存在しないチャンネルのフォールバック値。 */
export const localizationsAbsent = (
  fallbackLanguage: string
): Localizations => ({
  data: {},
  defaultLanguage: "",
  exists: false,
  supportedLanguages: [fallbackLanguage],
});
