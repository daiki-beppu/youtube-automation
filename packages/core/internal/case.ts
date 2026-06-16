// snake_case → camelCase の deep 変換ヘルパー（zod retrofit #825 の共用基盤）。
//
// config セクションは JSON on disk と一致する snake_case で zod schema を declare し、
// `.transform(snakeToCamel)` でパイプして core が consume する camelCase 出力 shape へ
// 変換する。型レベルでも `Camelize<T>` で key を変換するため、`z.infer<typeof Schema>` が
// camelCase の型を導出できる（手書き interface 不要）。
//
// 注意: passthrough map（任意の言語コード / テーマキーを保持する Record）を含むセクションは
// この helper を丸ごと適用すると map の key まで camel 化してしまうため、そこでは適用しない。

/** 単一 key を snake_case → camelCase へ変換する型。 */
type CamelizeKey<S extends string> = S extends `${infer Head}_${infer Tail}`
  ? `${Head}${Capitalize<CamelizeKey<Tail>>}`
  : S;

/** object / array を再帰的に camelCase 化する型。 */
export type Camelize<T> = T extends readonly (infer Element)[]
  ? Camelize<Element>[]
  : T extends object
    ? {
        [K in keyof T as K extends string ? CamelizeKey<K> : K]: Camelize<T[K]>;
      }
    : T;

const segmentToCamel = (key: string): string =>
  key.replaceAll(/_+([a-z0-9])/gu, (_match, char: string) =>
    char.toUpperCase()
  );

/**
 * object の全 key を（ネストした object・配列内 object も含め）camelCase へ変換する。
 *
 * - object: 各 key を camel 化し、値を再帰変換した新しい object を返す
 * - array: 各要素を再帰変換した新しい配列を返す
 * - それ以外（string / number / boolean / null / undefined）: そのまま返す
 *
 * 純関数: 入力は変更しない。
 */
export const snakeToCamel = <T>(value: T): Camelize<T> => {
  if (Array.isArray(value)) {
    return value.map((item: unknown) => snakeToCamel(item)) as Camelize<T>;
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      out[segmentToCamel(key)] = snakeToCamel(item);
    }
    return out as Camelize<T>;
  }
  return value as Camelize<T>;
};
