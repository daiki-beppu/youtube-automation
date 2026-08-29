// PROTOTYPE — wayfinder #4731「スキル詳細ページのサンプル試作」の使い捨てコード。
// 質問:「1 スキル 1 ページの詳細ドキュメント」の標準セクション構成はどれか。
// /music を題材に、構造の異なる 3 バリアント（A 読み物先行 / B リファレンス先行 / C タスク逆引き）を
// /skills-prototype/* に生成する。骨格は SKILL.md から実際に抽出し（🤖）、解説は手書き定数（✍️）を
// 合成して、ハイブリッド方式の実現可能性ごと見せる。本実装には昇格させず、決定後に破棄する。
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { ContentSource, SourceEntry } from "blume/sources/types";
import { extractMarkdownTitle } from "./markdown-title.ts";
import { operatorDocReleaseField } from "./operator-doc-source.ts";

const TARGET_SKILL = "music";

// ---- SKILL.md からの自動抽出（🤖） ----

interface ExtractedSkill {
  description: string;
  triggers: string[];
  modeTable: string;
  workflow: string;
  artifactsWrite: string[];
  artifactsRead: string[];
  apiCalls: string;
  completion: string;
}

const section = (markdown: string, heading: string): string => {
  const lines = markdown.split("\n");
  const start = lines.findIndex((line) => line === `## ${heading}`);
  if (start === -1) return "";
  const end = lines.findIndex(
    (line, index) => index > start && line.startsWith("## ")
  );
  return lines
    .slice(start + 1, end === -1 ? undefined : end)
    .join("\n")
    .trim();
};

const parseArtifactBullet = (body: string, label: string): string[] => {
  const line = body
    .split("\n")
    .find((candidate) => candidate.startsWith(`- \`${label}\`:`));
  if (!line) return [];
  return [...line.matchAll(/`([^`]+)`/gu)]
    .map((match) => match[1])
    .filter((value) => value !== label);
};

const extractSkill = (markdown: string): ExtractedSkill => {
  const frontmatter = markdown.match(/^---\n([\s\S]*?)\n---/u)?.[1] ?? "";
  const rawDescription =
    frontmatter.match(/^description:\s*"((?:[^"\\]|\\.)*)"\s*$/mu)?.[1] ?? "";
  // 散文中の --flag は smartypants で – に潰されるため code span に包む
  const description = rawDescription
    .replace(/\\"/gu, '"')
    .replace(/(--[a-z][a-z-]*)/gu, "`$1`");
  const triggers = [...description.matchAll(/「([^」]+)」/gu)].map(
    (match) => match[1]
  );
  const modeBody = section(markdown, "モード判定");
  const modeTable = modeBody
    .split("\n")
    .filter((line) => line.startsWith("|"))
    .join("\n");
  const artifactBody = section(markdown, "成果物");
  return {
    apiCalls: section(markdown, "想定 API call 数"),
    artifactsRead: parseArtifactBullet(artifactBody, "読み込む"),
    artifactsWrite: parseArtifactBullet(artifactBody, "書き込む"),
    completion: section(markdown, "完了条件"),
    description,
    modeTable,
    triggers,
    workflow: section(markdown, "前後工程"),
  };
};

// ---- 手書き解説（✍️）: 本実装ではスキルごとの手書きファイルになる部分 ----

const HANDWRITTEN = {
  overview:
    "音楽制作の 4 工程 — プロンプト生成 → 歌詞 → 音源生成 → マスター化 — を、collection の進み具合を見ながら自動で進めるスキルです。チャンネルの `music_engine`（Suno / Lyria / MiniMax）を読み取り、その engine に必要な段だけを実行します。すでに終わっている段は自動で skip されるので、途中で失敗しても同じ呼び出しで安全に再開できます。",
  scenarios: [
    "**新しい collection の音楽をまとめて作りたい** — フラグなしの `/music` で、状態判定つきの一括実行に任せる",
    "**Suno に貼るプロンプトだけ作り直したい** — `/music --prompt` で一段だけやり直す",
    "**ボーカル曲の歌詞を先に固めたい** — `/music --lyric`（instrumental の collection では不要と判定されて止まります）",
    "**音源だけ再生成したい・マスターだけ作り直したい** — `/music --generate` / `/music --master`",
  ],
  examples: [
    {
      command: "/music",
      note: "状態判定つき一括実行。prompt → lyric → generate → master を必要な段だけ進める",
    },
    {
      command: "/music --prompt",
      note: "Suno UI 投入用の Style / プロンプトだけ生成する",
    },
    {
      command: "/music --lyric",
      note: "Suno / MiniMax ボーカル曲の歌詞だけ生成する",
    },
    {
      command: "/music --generate",
      note: "music_engine に応じた音源生成だけ実行する",
    },
    {
      command: "/music --master",
      note: "Suno 音源の一括 DL とマスター化だけ実行する",
    },
  ],
  modeSummaries: [
    ["`--prompt`", "Suno UI 投入用の Style / プロンプトを生成", "`suno-prompts.json` / `suno-prompts.html` ほか"],
    ["`--lyric`", "Suno / MiniMax ボーカル曲の歌詞を生成", "`suno-lyrics.md` / `suno-lyrics.json`"],
    ["`--generate`", "music_engine に応じた音源生成", "`02-Individual-music/*`（Lyria / MiniMax は `master.mp3` まで）"],
    ["`--master`", "Suno 音源の一括 DL とマスター化", "`01-master/master.mp3`"],
  ],
  troubleshooting: [
    "**blocked と言われて止まる** — 前提の `creative-constraints.json` や persona が未整備です。先に `/channel-strategy --constraints` を実行してください",
    "**`--lyric` が「歌詞不要」と言って止まる** — instrumental の collection と Lyria では歌詞は使いません。そのまま `--generate` に進んで問題ありません",
    "**`--master` が何もしない** — Lyria / MiniMax は `--generate` が `master.mp3` まで直接作るため、マスター化は完了済みとして skip されます",
    "**どの collection が対象か聞かれる** — 対象 collection を 1 件に確定できないときは候補を提示して止まります。collection を指定して再実行してください",
  ],
} as const;

// ---- 共通部品 ----

const VARIANTS = [
  { key: "a", label: "A 読み物先行" },
  { key: "b", label: "B リファレンス先行" },
  { key: "c", label: "C タスク逆引き" },
] as const;

const switcher = (current: string): string => {
  const links = VARIANTS.map((variant) =>
    variant.key === current
      ? `**${variant.label}（表示中）**`
      : `[${variant.label}](/skills-prototype/music-${variant.key})`
  );
  return `> 🧪 **試作バリアント切替**: ${links.join(" ・ ")} ｜ [この試作について](/skills-prototype)\n>\n> 見出しの 🤖 = SKILL.md から自動生成、✍️ = 手書き解説`;
};

const bulletList = (items: readonly string[]): string =>
  items.map((item) => `- ${item}`).join("\n");

const codeList = (items: readonly string[]): string =>
  items.map((item) => `- \`${item}\``).join("\n");

const exampleBlock = (): string =>
  [
    "```",
    ...HANDWRITTEN.examples.map(
      (example) => `${example.command.padEnd(18)}# ${example.note}`
    ),
    "```",
  ].join("\n");

const modeSummaryTable = (): string =>
  [
    "| mode | すること | 主な成果物 |",
    "|---|---|---|",
    ...HANDWRITTEN.modeSummaries.map((row) => `| ${row.join(" | ")} |`),
  ].join("\n");

// ---- バリアント A: 読み物先行（ガイド型） ----
// 手書き解説を上に、機械的リファレンスは末尾へまとめる。

const renderVariantA = (skill: ExtractedSkill): string => `# /music

${switcher("a")}

${skill.description} 🤖

## 何ができるか ✍️

${HANDWRITTEN.overview}

${modeSummaryTable()}

## 使いどころ ✍️

${bulletList(HANDWRITTEN.scenarios)}

## 実行例 ✍️

${exampleBlock()}

## つまずいたら ✍️

${bulletList(HANDWRITTEN.troubleshooting)}

## リファレンス 🤖

### 発動フレーズ

${skill.triggers.map((trigger) => `「${trigger}」`).join(" ")}

### 前後工程

${skill.workflow}

### 成果物

**書き込む**

${codeList(skill.artifactsWrite)}

**読み込む**

${codeList(skill.artifactsRead)}

### 想定 API call 数

${skill.apiCalls}
`;

// ---- バリアント B: リファレンス先行（マニュアル型） ----
// 冒頭に一目サマリ、その下をモード軸で束ねる。

const renderVariantB = (skill: ExtractedSkill): string => `# /music

${switcher("b")}

${skill.description} 🤖

## 一目でわかる /music 🤖

| 項目 | 内容 |
|---|---|
| 前工程 | \`/channel-strategy --constraints\` |
| 後工程 | \`/video --generate\` |
| mode | \`--prompt\` / \`--lyric\` / \`--generate\` / \`--master\`（フラグなしで一括） |
| 発動フレーズ | ${skill.triggers.map((trigger) => `「${trigger}」`).join("")} |

## モード別ガイド ✍️

### フラグなし — 状態判定つき一括実行

${HANDWRITTEN.overview}

### \`--prompt\` — Suno プロンプト生成

Suno UI に貼り付ける Style / プロンプト一式を生成します。成果物は \`suno-prompts.json\` / \`suno-prompts.html\`（ブラウザで開いてコピーできる形式）。

### \`--lyric\` — 歌詞生成

Suno / MiniMax のボーカル曲向けに歌詞を生成します。instrumental collection と Lyria では不要と判定され、実行されません。

### \`--generate\` — 音源生成

チャンネルの \`music_engine\` に応じて音源を生成します。Lyria / MiniMax はこの段で \`master.mp3\` まで直接生成されます。

### \`--master\` — マスター化

Suno 音源を一括ダウンロードし、\`01-master/master.mp3\` に仕上げます。Lyria / MiniMax では skip されます。

## 実行例 ✍️

${exampleBlock()}

## 成果物 🤖

**書き込む**

${codeList(skill.artifactsWrite)}

**読み込む**

${codeList(skill.artifactsRead)}

## 想定 API call 数と承認 🤖

${skill.apiCalls}

## 完了条件 🤖

${skill.completion}

## つまずいたら ✍️

${bulletList(HANDWRITTEN.troubleshooting)}
`;

// ---- バリアント C: タスク逆引き（Q&A 型） ----
// 「〜したいとき」見出しでタスク別に束ね、機械的リファレンスは末尾に圧縮。

const renderVariantC = (skill: ExtractedSkill): string => `# /music

${switcher("c")}

${skill.description} 🤖

やりたいことから直接該当の節へ進んでください。

## 音楽をまとめて作りたい ✍️

\`\`\`
/music
\`\`\`

${HANDWRITTEN.overview}

## Suno に貼るプロンプトだけ欲しい ✍️

\`\`\`
/music --prompt
\`\`\`

Suno UI 投入用の Style / プロンプト一式を生成します。\`suno-prompts.html\` をブラウザで開くと、そのままコピーして Suno に貼り付けられます。

## 歌詞を作りたい ✍️

\`\`\`
/music --lyric
\`\`\`

Suno / MiniMax のボーカル曲向けに歌詞を生成します。instrumental collection と Lyria では不要と判定されて止まります — その場合はそのまま音源生成へ進んでください。

## 音源を生成したい ✍️

\`\`\`
/music --generate
\`\`\`

チャンネルの \`music_engine\`（Suno / Lyria / MiniMax）に応じた音源生成を実行します。Lyria / MiniMax はこの一段で \`master.mp3\` まで直接生成されます。

## マスターを作り直したい ✍️

\`\`\`
/music --master
\`\`\`

Suno 音源の一括ダウンロードとマスター化を実行します。Lyria / MiniMax では完了済みとして skip されます。

## 途中で止まった・うまくいかない ✍️

${bulletList(HANDWRITTEN.troubleshooting)}

## 詳細リファレンス 🤖

### 発動フレーズ

${skill.triggers.map((trigger) => `「${trigger}」`).join(" ")}

### 前後工程

${skill.workflow}

### 成果物（書き込む）

${codeList(skill.artifactsWrite)}

### 想定 API call 数

${skill.apiCalls}
`;

// ---- 試作の説明ページ ----

const renderIndex = (): string => `# 🧪 スキル詳細ページ試作

wayfinder [ドキュメントサイト超絶拡充 マップ #4729](https://github.com/daiki-beppu/youtube-automation/issues/4729) のチケット [#4731](https://github.com/daiki-beppu/youtube-automation/issues/4731) の試作です。**「1 スキル 1 ページの詳細ドキュメント」の標準セクション構成**を決めるため、/music を題材に構造の異なる 3 案を用意しました。

| 案 | 構成の考え方 |
|---|---|
| [A 読み物先行](/skills-prototype/music-a) | ガイド型。手書き解説（何ができる → 使いどころ → 実行例）を上に置き、機械的リファレンスは末尾にまとめる |
| [B リファレンス先行](/skills-prototype/music-b) | マニュアル型。冒頭の一目サマリ表 → モード別ガイド → 成果物・API・完了条件と、mode 軸で束ねる |
| [C タスク逆引き](/skills-prototype/music-c) | Q&A 型。「〜したいとき」見出しでタスク別に束ね、リファレンスは末尾に圧縮 |

各ページの見出しには **🤖（SKILL.md から自動生成できた部分）** と **✍️（手書きが必要な部分）** の印を付けています。ハイブリッド生成の境界線への意見もください。

## 見てほしい観点

- どの構成が「下流チャンネル運用者・新規導入者」にとって読みやすいか
- 要らない節・足りない節はどれか（完了条件は要る？ トラブルシューティングは要る？）
- 「A の導入 + B のモード表」のような組み合わせ指摘も歓迎
- 🤖/✍️ の境界は妥当か（手書き分量はスキル数 19 個分書ける量に収まっているか）
`;

// ---- source 実体 ----

const entry = (
  ref: string,
  slug: string,
  markdown: string,
  navTitle?: string
): SourceEntry => {
  const { text, title: extracted } = extractMarkdownTitle(markdown);
  const title = navTitle ?? extracted;
  return {
    body: { format: "md", text },
    data: {
      kind: operatorDocReleaseField,
      released_at: operatorDocReleaseField,
      summary: operatorDocReleaseField,
      title,
      type: "doc",
      version: operatorDocReleaseField,
    },
    raw: `---\ntitle: ${JSON.stringify(title)}\ntype: doc\n---\n\n${text}`,
    ref,
    slug,
  };
};

const loadEntries = async (repositoryRoot: string): Promise<SourceEntry[]> => {
  const skillPath = resolve(
    repositoryRoot,
    ".claude/skills",
    TARGET_SKILL,
    "SKILL.md"
  );
  const skill = extractSkill(await readFile(skillPath, "utf8"));
  return [
    entry("prototype-index.md", "/skills-prototype", renderIndex()),
    entry(
      "prototype-music-a.md",
      "/skills-prototype/music-a",
      renderVariantA(skill)
    ),
    entry(
      "prototype-music-b.md",
      "/skills-prototype/music-b",
      renderVariantB(skill)
    ),
    entry(
      "prototype-music-c.md",
      "/skills-prototype/music-c",
      renderVariantC(skill)
    ),
  ];
};

export const createSkillDetailPrototypeSource = (options: {
  readonly repositoryRoot: string;
}): ContentSource => {
  const repositoryRoot = resolve(options.repositoryRoot);
  return {
    load: async () => ({
      diagnostics: [],
      entries: await loadEntries(repositoryRoot),
    }),
    name: "skill-detail-prototype",
    read: async (ref) => {
      const found = (await loadEntries(repositoryRoot)).find(
        (candidate) => candidate.ref === ref
      );
      if (!found) throw new Error(`Unknown prototype page: ${ref}`);
      return found.body.text;
    },
    staged: true,
    validate: () => undefined,
  };
};
