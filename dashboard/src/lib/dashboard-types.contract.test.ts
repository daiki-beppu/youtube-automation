import { describe, expect, it } from "vitest"
import ts from "typescript"

import overviewGolden from "@/lib/__fixtures__/overview.golden.json"
import pipelineGolden from "@/lib/__fixtures__/pipeline.golden.json"
import trendsGolden from "@/lib/__fixtures__/trends.golden.json"
import {
  DASHBOARD_SCHEMA_VERSION,
  type OverviewResponse,
  type TrendsResponse,
} from "@/lib/dashboard-types"

type KeysOfUnion<Value> = Value extends Value ? keyof Value : never
type PresentValue<Value> = Exclude<Value, null | undefined>
type NullishValue<Value> = Extract<Value, null | undefined>
type NormalizeObjectUnion<Value> = [PresentValue<Value>] extends [never]
  ? NullishValue<Value>
  : [PresentValue<Value>] extends [object]
    ? MergeObjectUnion<PresentValue<Value>> | NullishValue<Value>
    : Value
type FieldOfUnion<Value, Key extends PropertyKey> =
  Value extends Record<Key, infer Field> ? Field : never
type MergeObjectUnion<Value> = {
  [Key in KeysOfUnion<Value>]: NormalizeObjectUnion<FieldOfUnion<Value, Key>>
}
type BidirectionallyExact<Left, Right> = [Left] extends [Right]
  ? [Right] extends [Left]
    ? true
    : false
  : false

type GoldenChannel = (typeof overviewGolden.channels)[number]
type GoldenChannelShape = MergeObjectUnion<GoldenChannel>
type GoldenOverviewShape = Omit<typeof overviewGolden, "channels"> & {
  channels: GoldenChannelShape[]
}
type GoldenTrendChannel = (typeof trendsGolden.channels)[number]
type GoldenTrendPoint = (typeof trendsGolden.channels)[0]["points"][number]
type GoldenTrendChannelShape = Omit<
  MergeObjectUnion<GoldenTrendChannel>,
  "points"
> & {
  points: MergeObjectUnion<GoldenTrendPoint>[]
}
type GoldenTrendsShape = Omit<typeof trendsGolden, "channels"> & {
  channels: GoldenTrendChannelShape[]
}

const overviewFixture: OverviewResponse = overviewGolden
const overviewTypesMatch: BidirectionallyExact<
  GoldenOverviewShape,
  OverviewResponse
> = true
const trendsFixture: TrendsResponse = trendsGolden
const trendsTypesMatch: BidirectionallyExact<
  GoldenTrendsShape,
  TrendsResponse
> = true

const apiResponseTypeNames = [
  "Video",
  "ChannelDetail",
  "OverviewResponse",
  "PublicationActivityState",
  "PipelineResponse",
  "TrendPoint",
  "TrendsResponse",
] as const
const appResponseTypeNames = [
  "ChannelDetail",
  "OverviewResponse",
  "PublicationActivityState",
  "PipelineResponse",
  "TrendsResponse",
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
    expect(overviewTypesMatch).toBe(true)
  })

  it("accepts the generated Python pipeline response shape", () => {
    expect(pipelineShapeDiagnostics(pipelineGolden)).toEqual([])
  })

  it.each([
    [
      "missing nested field",
      (collection) =>
        Object.fromEntries(
          Object.entries(collection).filter(([key]) => key !== "collection_id")
        ),
    ],
    [
      "wrong nested type",
      (collection) => ({ ...collection, collection_id: 42 }),
    ],
    ["unknown phase", (collection) => ({ ...collection, phase: "unknown" })],
    ["extra nested field", (collection) => ({ ...collection, extra: true })],
  ] satisfies Array<
    [
      string,
      (
        collection: (typeof pipelineGolden.channels)[number]["collections"][number]
      ) => unknown,
    ]
  >)("rejects a pipeline golden with %s", (_name, mutate) => {
    const channel = pipelineGolden.channels[0]
    const malformed = {
      channels: [{ ...channel, collections: [mutate(channel.collections[0])] }],
    }
    expect(pipelineShapeDiagnostics(malformed).length).toBeGreaterThan(0)
  })

  it("accepts the generated Python trends response as the exact TypeScript shape", () => {
    expect(trendsFixture.channels[0]?.points[1]?.impressions).toBe(2400)
    expect(trendsTypesMatch).toBe(true)
  })
})

// Check the JSON as a fresh literal against the actual response type. A JSON
// import widens enum strings; an `as` cast would hide missing/incorrect fields.
function pipelineShapeDiagnostics(payload: unknown): string[] {
  const filename = ts.sys.resolvePath("pipeline-golden-check.ts")
  const declarations = parseSource(
    dashboardTypesPath,
    sourceAt(dashboardTypesPath)
  )
    .statements.filter(
      (statement) =>
        ts.isTypeAliasDeclaration(statement) &&
        ["PipelineCollection", "PipelineResponse"].includes(statement.name.text)
    )
    .map((statement) => statement.getText())
    .join("\n")
  const source = `${declarations}
    const response = ${JSON.stringify(payload)} satisfies PipelineResponse;`
  const options: ts.CompilerOptions = {
    strict: true,
    noEmit: true,
    skipLibCheck: true,
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    types: [],
  }
  const host = ts.createCompilerHost(options)
  const getSourceFile = host.getSourceFile.bind(host)
  host.getSourceFile = (
    path,
    languageVersion,
    onError,
    shouldCreateNewSourceFile
  ) =>
    path === filename
      ? ts.createSourceFile(path, source, languageVersion, true)
      : getSourceFile(path, languageVersion, onError, shouldCreateNewSourceFile)
  const program = ts.createProgram([filename], options, host)
  return ts
    .getPreEmitDiagnostics(program)
    .map((diagnostic) =>
      ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")
    )
}
