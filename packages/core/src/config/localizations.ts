// ローカライゼーション設定（Python `utils/config/localizations.py` + loader の移植）。

import { ConfigError } from "../errors.ts";
import { isRecord } from "./internal.ts";

/**
 * `config/localizations.json`（`config/` 直下、`config/channel/` の外）の内容。
 *
 * - exists=true: `data` に JSON 全量、`supportedLanguages` / `defaultLanguage` も埋める
 * - exists=false: `data={}`、`supportedLanguages=[youtube.api.language]`、`defaultLanguage=""`
 */
export interface Localizations {
  readonly data: Readonly<Record<string, unknown>>;
  readonly exists: boolean;
  readonly supportedLanguages: readonly string[];
  readonly defaultLanguage: string;
}

/** localizations.json が存在しないチャンネルのフォールバック値。 */
export const localizationsAbsent = (
  fallbackLanguage: string
): Localizations => ({
  data: {},
  defaultLanguage: "",
  exists: false,
  supportedLanguages: [fallbackLanguage],
});

export const parseLocalizations = (data: unknown): Localizations => {
  if (!isRecord(data)) {
    throw new ConfigError(
      "localizations.json のトップレベルは object でなければなりません"
    );
  }
  return {
    data,
    defaultLanguage: (data.default_language as string | undefined) ?? "",
    exists: true,
    supportedLanguages: [
      ...((data.supported_languages as string[] | undefined) ?? []),
    ],
  };
};
