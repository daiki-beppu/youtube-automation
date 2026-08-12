import { describe, expect, it } from "vitest"
import ts from "typescript"

import overviewGolden from "@/lib/__fixtures__/overview.golden.json"
import {
  DASHBOARD_SCHEMA_VERSION,
  type ChannelOverview,
  type OverviewResponse,
  type Summary,
} from "@/lib/dashboard-types"

type SameKeys<Left, Right> = [
  Exclude<keyof Left, keyof Right>,
  Exclude<keyof Right, keyof Left>,
] extends [never, never]
  ? true
  : false

type GoldenChannel = (typeof overviewGolden.channels)[number]

const overviewFixture: OverviewResponse = overviewGolden
const overviewKeysMatch: SameKeys<typeof overviewGolden, OverviewResponse> =
  true
const channelKeysMatch: SameKeys<GoldenChannel, ChannelOverview> = true
const periodKeysMatch: SameKeys<
  GoldenChannel["period"],
  ChannelOverview["period"]
> = true
const summaryKeysMatch: SameKeys<
  NonNullable<GoldenChannel["summary"]>,
  Summary
> = true
const errorKeysMatch: SameKeys<
  NonNullable<GoldenChannel["error"]>,
  NonNullable<ChannelOverview["error"]>
> = true
const refreshErrorKeysMatch: SameKeys<
  NonNullable<GoldenChannel["refresh_error"]>,
  NonNullable<ChannelOverview["refresh_error"]>
> = true

const apiResponseTypeNames = [
  "Video",
  "ChannelDetail",
  "OverviewResponse",
  "PublicationActivityState",
] as const
const appResponseTypeNames = [
  "ChannelDetail",
  "OverviewResponse",
  "PublicationActivityState",
] as const
const sources = import.meta.glob<string>("/src/**/*.{ts,tsx}", {
  eager: true,
  import: "default",
  query: "?raw",
})
const dashboardTypesPath = "/src/lib/dashboard-types.ts"
const appPath = "/src/App.tsx"

function sourceAt(path: string): string {
  const source = sources[path]
  if (source === undefined) {
    throw new Error(`Dashboard source not found: ${path}`)
  }
  return source
}

function parseSource(path: string, source: string): ts.SourceFile {
  return ts.createSourceFile(
    path,
    source,
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  )
}

describe("dashboard API response type ownership", () => {
  it("exports each response type exactly once from dashboard-types.ts", () => {
    const declarations = Object.entries(sources).flatMap(([path, source]) =>
      parseSource(path, source).statements.flatMap((statement) => {
        if (
          (!ts.isTypeAliasDeclaration(statement) &&
            !ts.isInterfaceDeclaration(statement)) ||
          !apiResponseTypeNames.includes(
            statement.name.text as (typeof apiResponseTypeNames)[number]
          )
        ) {
          return []
        }
        return [{ path, statement }]
      })
    )

    for (const name of apiResponseTypeNames) {
      const matches = declarations.filter(
        ({ statement }) => statement.name.text === name
      )
      expect(matches).toHaveLength(1)
      expect(matches[0]?.path).toBe(dashboardTypesPath)
      expect(
        matches[0]?.statement.modifiers?.some(
          (modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword
        )
      ).toBe(true)
    }
  })

  it("imports App response types as type-only dependencies", () => {
    const importedTypeNames = parseSource(
      appPath,
      sourceAt(appPath)
    ).statements.flatMap((statement) => {
      if (
        !ts.isImportDeclaration(statement) ||
        statement.moduleSpecifier.getText() !== '"@/lib/dashboard-types"'
      ) {
        return []
      }
      const clause = statement.importClause
      if (!clause?.isTypeOnly || !clause.namedBindings) {
        return []
      }
      return ts.isNamedImports(clause.namedBindings)
        ? clause.namedBindings.elements.map((element) => element.name.text)
        : []
    })

    expect(importedTypeNames).toEqual(
      expect.arrayContaining([...appResponseTypeNames])
    )
  })
})

describe("Python dashboard overview schema contract", () => {
  it("accepts the generated Python response as the exact TypeScript response shape", () => {
    expect(overviewFixture.schema_version).toBe(DASHBOARD_SCHEMA_VERSION)
    expect([
      overviewKeysMatch,
      channelKeysMatch,
      periodKeysMatch,
      summaryKeysMatch,
      errorKeysMatch,
      refreshErrorKeysMatch,
    ]).toEqual([true, true, true, true, true, true])
  })
})
