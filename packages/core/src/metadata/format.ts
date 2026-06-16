// Python `string.Formatter` 系ミニ言語の TS 移植（metadata_generator.py の
// `_referenced_placeholders` / `format_title_template` 周辺）。
//
// `str.format()` 互換を全面実装するのではなく、本リポジトリの title / description
// テンプレートが使う範囲（`{field}` 置換、`{{` `}}` エスケープ、`{a.b}` / `{c[0]}`
// の root 名抽出）に限定して faithfully に再現する。

interface FormatToken {
  readonly literal: string;
  readonly field: string | null;
}

// Python `string.Formatter().parse()` 相当。`{{`/`}}` を literal brace に畳み、
// 置換フィールドは中身（`field!conv:spec`）をそのまま field として持つトークン列を返す。
const parseFormat = (template: string): FormatToken[] => {
  const tokens: FormatToken[] = [];
  let literal = "";
  let i = 0;
  while (i < template.length) {
    const ch = template[i];
    if (ch === "{") {
      if (template[i + 1] === "{") {
        literal += "{";
        i += 2;
        continue;
      }
      const end = template.indexOf("}", i + 1);
      if (end === -1) {
        throw new Error(
          `validation: テンプレートに対応する '}' が無い '{' があります: ${template}`
        );
      }
      tokens.push({ field: template.slice(i + 1, end), literal });
      literal = "";
      i = end + 1;
      continue;
    }
    if (ch === "}") {
      if (template[i + 1] === "}") {
        literal += "}";
        i += 2;
        continue;
      }
      throw new Error(
        `validation: テンプレートに単独の '}' があります: ${template}`
      );
    }
    literal += ch;
    i += 1;
  }
  if (literal) {
    tokens.push({ field: null, literal });
  }
  return tokens;
};

// `field!conv:spec` から root フィールド名を取り出す（`a.b` -> `a`, `c[0]` -> `c`）。
const baseName = (field: string): string => {
  const head = field.split(/[!:]/u)[0] ?? "";
  return (head.split(".")[0] ?? "").split("[")[0] ?? "";
};

/** format テンプレートが参照するフィールド名の集合（`{a.b}` / `{c[0]}` は root に正規化）。 */
export const referencedPlaceholders = (template: string): Set<string> => {
  const referenced = new Set<string>();
  for (const { field } of parseFormat(template)) {
    if (field === null) {
      continue;
    }
    const base = baseName(field);
    if (base) {
      referenced.add(base);
    }
  }
  return referenced;
};

/**
 * Python `str.format(**values)` の限定移植。
 *
 * 参照フィールドの root 名で `values` を引く。`values` に無いキーは Fail Fast。
 * `format_title_template` は事前に未知プレースホルダを弾くため、こちらに到達する
 * 経路では常にキーが揃っている前提。
 */
export const pyFormat = (
  template: string,
  values: Readonly<Record<string, string>>
): string => {
  let out = "";
  for (const { field, literal } of parseFormat(template)) {
    out += literal;
    if (field === null) {
      continue;
    }
    const base = baseName(field);
    if (!(base in values)) {
      throw new Error(
        `validation: テンプレートのプレースホルダ '${base}' に対応する値がありません: ${template}`
      );
    }
    out += values[base];
  }
  return out;
};

/**
 * title テンプレートを整形する。未知プレースホルダは actionable な `validation:` prefix Error にする。
 *
 * `str.format()` を直接呼ぶと提供キー外のプレースホルダ（例: `{adjective}`）で opaque な
 * KeyError を投げて upload 全体が深部でクラッシュする（Python #574）。事前検出して
 * 「使用不可プレースホルダ名 + 許可キー一覧」を含む `validation:` prefix Error に変換する。
 */
export const formatTitleTemplate = (
  template: string,
  values: Readonly<Record<string, string>>,
  context: string
): string => {
  const allowed = new Set(Object.keys(values));
  const unknown = [...referencedPlaceholders(template)]
    .filter((name) => !allowed.has(name))
    .toSorted();
  if (unknown.length > 0) {
    throw new Error(
      `validation: ${context}: 使用できないプレースホルダ ${JSON.stringify(unknown)} が含まれています。\n` +
        `→ 使用可能なキー: ${JSON.stringify([...allowed].toSorted())}\n` +
        `→ テンプレート: ${template}`
    );
  }
  return pyFormat(template, values);
};

/** YouTube 概要欄の codepoint 上限（description 系の単一の事実源）。 */
export const DESCRIPTION_CODEPOINT_LIMIT = 5000;

/** 文字列の codepoint 長（UTF-16 単位ではなく Python `len(str)` 相当）。 */
export const codepointLength = (value: string): number => [...value].length;

/** Python `value[:max]` 相当の codepoint 単位スライス。 */
export const truncateCodepoints = (value: string, max: number): string => {
  const codepoints = [...value];
  return codepoints.length <= max ? value : codepoints.slice(0, max).join("");
};
