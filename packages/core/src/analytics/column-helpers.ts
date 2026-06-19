import type { youtubeAnalytics_v2 } from "googleapis";

type ColumnHeaders = NonNullable<
  youtubeAnalytics_v2.Schema$QueryResponse["columnHeaders"]
>;

export const resolveColumnIndex = (
  headers: ColumnHeaders,
  name: string,
  context: string
): number => {
  const index = headers.findIndex((header) => header.name === name);
  if (index === -1) {
    throw new Error(`${context}: response is missing the "${name}" column`);
  }
  return index;
};

export const requireHeaders = (
  data: { columnHeaders?: ColumnHeaders | null; rows?: unknown },
  context: string
): ColumnHeaders => {
  if (!data.columnHeaders) {
    throw new Error(`${context}: response has rows but no columnHeaders`);
  }
  return data.columnHeaders;
};

export const readStringCell = (
  row: readonly unknown[],
  index: number,
  columnName: string,
  context: string
): string => {
  const value = row[index];
  if (typeof value !== "string") {
    throw new TypeError(
      `${context}: response has a non-string "${columnName}" value`
    );
  }
  return value;
};

export const readNonEmptyStringCell = (
  row: readonly unknown[],
  index: number,
  columnName: string,
  context: string
): string => {
  const value = row[index];
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(
      `${context}: response has an invalid "${columnName}" value`
    );
  }
  return value;
};

export const readNumberCell = (
  row: readonly unknown[],
  index: number,
  columnName: string,
  context: string
): number => {
  const value = row[index];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(
      `${context}: response has a non-numeric "${columnName}" value`
    );
  }
  return value;
};

export const readCoercedNumberCell = (
  row: readonly unknown[],
  index: number,
  columnName: string,
  context: string
): number => {
  const value = Number(row[index]);
  if (!Number.isFinite(value)) {
    throw new TypeError(
      `${context}: response has a non-numeric "${columnName}" value`
    );
  }
  return value;
};
