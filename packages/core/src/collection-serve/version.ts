import { readFile } from "node:fs/promises";
import { join } from "node:path";

const PYPROJECT_PATH = join(
  import.meta.dir,
  "..",
  "..",
  "..",
  "..",
  "pyproject.toml"
);

export const readPackageVersion = async (): Promise<string> => {
  const pyproject = await readFile(PYPROJECT_PATH, "utf-8");
  const match = /^version = "([^"]+)"$/mu.exec(pyproject);
  if (match?.[1] === undefined) {
    throw new Error("validation: pyproject.toml version is required");
  }
  return match[1];
};
