import {
  existsSync,
  lstatSync,
  readFileSync,
  realpathSync,
  statSync,
} from "node:fs";
import {
  dirname,
  extname,
  isAbsolute,
  relative,
  resolve,
  sep,
} from "node:path";

const OUTPUT_DIRS = ["branding", "collections"] as const;
const REFERENCE_DIRS = ["assets", "collections", "references"] as const;
const OUTPUT_EXTENSIONS = new Set([".jpg", ".jpeg", ".png"]);
const REFERENCE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".webp"]);
const MAX_REFERENCE_BYTES = 10 * 1024 * 1024;

const assertRelativePath = (label: string, value: string): void => {
  if (isAbsolute(value)) {
    throw new Error(`validation: ${label} は相対パスで指定してください`);
  }
  const parts = value.split(/[\\/]+/u);
  if (parts.includes("..") || parts.includes("")) {
    throw new Error(`validation: ${label} に不正なパス区切りが含まれています`);
  }
};

const assertAllowedDir = (
  label: string,
  value: string,
  allowedDirs: readonly string[]
): void => {
  const [head] = value.split(/[\\/]+/u);
  if (head === undefined || !allowedDirs.some((dir) => dir === head)) {
    throw new Error(
      `validation: ${label} は ${allowedDirs.join(" / ")} 配下を指定してください`
    );
  }
};

const assertAllowedExtension = (
  label: string,
  value: string,
  allowedExtensions: ReadonlySet<string>
): void => {
  const extension = extname(value).toLowerCase();
  if (!allowedExtensions.has(extension)) {
    throw new Error(
      `validation: ${label} の拡張子は ${[...allowedExtensions].join(" / ")} のいずれかにしてください`
    );
  }
};

const assertUnderRoot = (
  label: string,
  rootRealPath: string,
  targetRealPath: string
): void => {
  const rel = relative(rootRealPath, targetRealPath);
  if (rel === "" || (!rel.startsWith("..") && !isAbsolute(rel))) {
    return;
  }
  throw new Error(
    `validation: ${label} は channel root 配下を指定してください`
  );
};

const nearestExistingPath = (path: string): string => {
  let current = path;
  while (!existsSync(current)) {
    const parent = dirname(current);
    if (parent === current) {
      return current;
    }
    current = parent;
  }
  return current;
};

const isSymlink = (path: string): boolean => {
  try {
    return lstatSync(path).isSymbolicLink();
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      return false;
    }
    throw error;
  }
};

const assertExistingAncestorUnderRoot = (
  label: string,
  rootRealPath: string,
  targetPath: string
): void => {
  const existing = nearestExistingPath(targetPath);
  assertUnderRoot(label, rootRealPath, realpathSync(existing));
};

const assertNoSymlinkInExistingPath = (
  label: string,
  rootRealPath: string,
  targetPath: string
): void => {
  const rel = relative(rootRealPath, targetPath);
  const parts = rel.split(sep).filter(Boolean);
  let current = rootRealPath;
  for (const part of parts.slice(0, -1)) {
    current = resolve(current, part);
    if (isSymlink(current)) {
      throw new Error(
        `validation: ${label} に symlink 経由のパスは指定できません`
      );
    }
  }
};

const detectImageMagic = (bytes: Uint8Array): boolean => {
  const isPng =
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47;
  const isJpeg = bytes[0] === 0xff && bytes[1] === 0xd8;
  const isWebp =
    bytes[0] === 0x52 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x46 &&
    bytes[8] === 0x57 &&
    bytes[9] === 0x45 &&
    bytes[10] === 0x42 &&
    bytes[11] === 0x50;
  return isPng || isJpeg || isWebp;
};

const assertImageFile = (label: string, path: string): void => {
  const bytes = readFileSync(path).subarray(0, 12);
  if (!detectImageMagic(bytes)) {
    throw new Error(`validation: ${label} は画像ファイルを指定してください`);
  }
};

export const resolveOutputPath = (
  channelDir: string,
  outputPath: string
): string => {
  assertRelativePath("output_path", outputPath);
  assertAllowedDir("output_path", outputPath, OUTPUT_DIRS);
  assertAllowedExtension("output_path", outputPath, OUTPUT_EXTENSIONS);

  const rootRealPath = realpathSync(channelDir);
  const absolute = resolve(rootRealPath, outputPath);
  assertUnderRoot("output_path", rootRealPath, absolute);
  assertExistingAncestorUnderRoot(
    "output_path",
    rootRealPath,
    dirname(absolute)
  );
  assertNoSymlinkInExistingPath("output_path", rootRealPath, absolute);
  if (isSymlink(absolute)) {
    throw new Error("validation: output_path に symlink は指定できません");
  }
  return absolute;
};

export const resolveReferencePaths = (
  channelDir: string,
  references: readonly string[] | undefined
): string[] | undefined => {
  if (references === undefined) {
    return undefined;
  }
  const rootRealPath = realpathSync(channelDir);
  return references.map((reference) => {
    assertRelativePath("references", reference);
    assertAllowedDir("references", reference, REFERENCE_DIRS);
    assertAllowedExtension("references", reference, REFERENCE_EXTENSIONS);
    const absolute = resolve(rootRealPath, reference);
    if (!existsSync(absolute)) {
      throw new Error(`validation: references が存在しません: ${reference}`);
    }
    const real = realpathSync(absolute);
    assertUnderRoot("references", rootRealPath, real);
    const stat = statSync(real);
    if (!stat.isFile()) {
      throw new Error(`validation: references はファイルを指定してください`);
    }
    if (stat.size > MAX_REFERENCE_BYTES) {
      throw new Error("validation: references のファイルサイズが大きすぎます");
    }
    assertImageFile("references", real);
    return real;
  });
};
