// コレクションディレクトリ構造のパス解決（Python `utils/collection_paths.py` の移植）。
//
// ディレクトリ構造:
//   NNN-collection-name/
//   ├── 01-master/           # マスター音声・動画 + 番号付き shorts/
//   ├── 02-Individual-music/ # 個別音声ファイル
//   ├── 03-Individual-movie/ # 個別動画ファイル
//   ├── 10-assets/           # 静止画・ループ動画素材
//   ├── 20-documentation/    # 作業文書・プロンプト
//   └── workflow-state.json  # 進捗トラッキング

import { existsSync, readdirSync, statSync } from "node:fs";
import { basename, extname, join, resolve } from "node:path";

const SHORT_THUMBNAIL_EXTENSIONS = ["jpg", "png"] as const;
const SHORT_LOOP_INPUT_NAMES = ["short.png", "short.jpg"] as const;

// サムネイル候補ファイルの優先順。アップロード経路と統一し、呼び出し経路によらず
// 同一コレクションで同じ画像が選ばれることを保証する。
const THUMBNAIL_CANDIDATES = [
  "thumbnail.jpg",
  "thumbnail.png",
  "main.jpg",
  "main.png",
] as const;

const isDir = (path: string): boolean =>
  existsSync(path) && statSync(path).isDirectory();

// 指定ディレクトリ直下の、拡張子が一致するファイルを sorted（Python `sorted(glob)` 相当）。
// JS の既定文字列比較は UTF-16 code unit 順で、ASCII ファイル名では Python sorted() と一致する。
const sortedByExt = (dir: string, ext: string): string[] => {
  if (!existsSync(dir)) {
    return [];
  }
  return readdirSync(dir)
    .filter((name) => extname(name).toLowerCase() === ext)
    .toSorted()
    .map((name) => join(dir, name));
};

const pad2 = (value: number): string => String(value).padStart(2, "0");

// 番号付き Shorts 動画を探す glob パターン（文字列）と、それに対応する実ファイル名 RegExp。
const shortVideoGlob = (shortNum: number): string =>
  `short-${pad2(shortNum)}-*.mp4`;
const shortVideoNameRe = (shortNum: number): RegExp =>
  new RegExp(`^short-${pad2(shortNum)}-.*\\.mp4$`, "u");

// Python `str.split(sep, maxsplit)` 相当（JS の limit 引数は残りを捨てるため自前実装）。
const splitMax = (value: string, sep: string, maxsplit: number): string[] => {
  const parts: string[] = [];
  let rest = value;
  for (let i = 0; i < maxsplit; i += 1) {
    const idx = rest.indexOf(sep);
    if (idx === -1) {
      break;
    }
    parts.push(rest.slice(0, idx));
    rest = rest.slice(idx + sep.length);
  }
  parts.push(rest);
  return parts;
};

const isAllDigits = (value: string): boolean =>
  value.length > 0 && /^\d+$/u.test(value);

/** 標準コレクションディレクトリ構造のパスリゾルバ。 */
export class CollectionPaths {
  readonly root: string;

  constructor(collectionDir: string) {
    this.root = resolve(collectionDir);
  }

  get masterDir(): string {
    return join(this.root, "01-master");
  }

  get musicDir(): string {
    return join(this.root, "02-Individual-music");
  }

  get movieDir(): string {
    return join(this.root, "03-Individual-movie");
  }

  get assetsDir(): string {
    return join(this.root, "10-assets");
  }

  get docsDir(): string {
    return join(this.root, "20-documentation");
  }

  get workflowStatePath(): string {
    return join(this.root, "workflow-state.json");
  }

  get trackingPath(): string {
    return join(this.docsDir, "upload_tracking.json");
  }

  get descriptionsMdPath(): string {
    return join(this.docsDir, "descriptions.md");
  }

  get thumbnailPromptsPath(): string {
    return join(this.docsDir, "thumbnail-prompts.md");
  }

  /** 番号付き Shorts 動画を格納する実ディレクトリ。 */
  get shortsDir(): string {
    return join(this.masterDir, "shorts");
  }

  /** Shorts ループ動画の出力実ファイルパス。 */
  get shortLoop(): string {
    return join(this.assetsDir, "short-loop.mp4");
  }

  /** コレクション名（ディレクトリ名から日付・チャンネルプレフィックスを除去）。 */
  get collectionName(): string {
    const name = basename(this.root);
    // "20260310-clm-some-name" → "some-name"
    const parts = splitMax(name, "-", 2);
    if (parts.length >= 3 && isAllDigits(parts[0] ?? "")) {
      return parts[2] ?? name;
    }
    return name;
  }

  private get shortVideoPath(): string {
    return join(this.masterDir, "short.mp4");
  }

  private shortThumbnailPath(
    ext: (typeof SHORT_THUMBNAIL_EXTENSIONS)[number]
  ): string {
    return join(this.assetsDir, `short-thumbnail.${ext}`);
  }

  /** 01-master/ からマスター動画（.mp4）を探す。 */
  findMasterVideo(): string | null {
    return sortedByExt(this.masterDir, ".mp4")[0] ?? null;
  }

  /** 01-master/ からマスター音声（.mp3）を探す。 */
  findMasterAudio(): string | null {
    return sortedByExt(this.masterDir, ".mp3")[0] ?? null;
  }

  /** 10-assets/ からサムネイル画像を優先順（thumbnail.jpg > thumbnail.png > main.jpg > main.png）で探す。 */
  findThumbnail(): string | null {
    for (const name of THUMBNAIL_CANDIDATES) {
      const path = join(this.assetsDir, name);
      if (existsSync(path)) {
        return path;
      }
    }
    return null;
  }

  /** 10-assets/ からメイン画像を探す（main.png > main.jpg）。 */
  findMainImage(): string | null {
    for (const name of ["main.png", "main.jpg"]) {
      const path = join(this.assetsDir, name);
      if (existsSync(path)) {
        return path;
      }
    }
    return null;
  }

  /** 10-assets/ からループ動画を探す。 */
  findLoopVideo(): string | null {
    const path = join(this.assetsDir, "loop.mp4");
    return existsSync(path) ? path : null;
  }

  /** 番号付き Shorts 動画を優先し、無ければ単一 Shorts 動画を探す。 */
  findShortVideo(shortNum: number | null): string | null {
    if (shortNum !== null && existsSync(this.shortsDir)) {
      const pattern = shortVideoNameRe(shortNum);
      const [first] = readdirSync(this.shortsDir)
        .filter((name) => pattern.test(name))
        .toSorted();
      if (first !== undefined) {
        return join(this.shortsDir, first);
      }
    }
    const fallback = this.shortVideoPath;
    return existsSync(fallback) ? fallback : null;
  }

  /** Shorts 動画探索時に確認する実パスまたは glob パターン（文字列）を返す。 */
  shortVideoSearchPaths(shortNum: number | null): string[] {
    if (shortNum === null) {
      return [this.shortVideoPath];
    }
    return [
      join(this.shortsDir, shortVideoGlob(shortNum)),
      this.shortVideoPath,
    ];
  }

  /** Shorts サムネイルの実ファイルを jpg、png の順に探す。 */
  findShortThumbnail(): string | null {
    for (const ext of SHORT_THUMBNAIL_EXTENSIONS) {
      const path = this.shortThumbnailPath(ext);
      if (existsSync(path)) {
        return path;
      }
    }
    return null;
  }

  /** Shorts ループ動画入力画像の探索候補実パス（png、jpg の順）。 */
  shortLoopInputImageSearchPaths(): string[] {
    return SHORT_LOOP_INPUT_NAMES.map((name) => join(this.assetsDir, name));
  }

  /** Shorts ループ動画入力画像の実ファイルを png、jpg の順に探す。 */
  findShortLoopInputImage(): string | null {
    for (const path of this.shortLoopInputImageSearchPaths()) {
      if (existsSync(path)) {
        return path;
      }
    }
    return null;
  }

  /** 02-Individual-music/ の音声ファイル一覧（ソート済み）。 */
  individualMusicFiles(): string[] {
    return sortedByExt(this.musicDir, ".mp3");
  }

  /** 03-Individual-movie/ の動画ファイル一覧（ソート済み）。 */
  individualMovieFiles(): string[] {
    return sortedByExt(this.movieDir, ".mp4");
  }
}

/**
 * CLI 引数から collection ディレクトリを解決する（CWD フォールバック）。
 *
 * `arg` 指定時はそのパスを resolve して返す。未指定時は CWD が `01-master/` と
 * `02-Individual-music/` を持つコレクションディレクトリであることを検証して返す。
 *
 * @throws {Error} `validation:` prefix — 判定に失敗したとき（Fail Fast）。
 */
export const resolveCollectionDir = (arg: string | null): string => {
  if (arg) {
    return resolve(arg);
  }

  const cwd = process.cwd();
  const paths = new CollectionPaths(cwd);
  if (isDir(paths.masterDir) && isDir(paths.musicDir)) {
    return cwd;
  }

  throw new Error(
    "validation: コレクションディレクトリを解決できません。引数で指定するか、" +
      "01-master/ と 02-Individual-music/ を持つディレクトリで実行してください。"
  );
};
