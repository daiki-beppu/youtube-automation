#!/usr/bin/env bash
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
if [[ ${PWD} != "${repo_root}" ]]; then
  echo "ERROR: repository root で実行してください: ${repo_root}" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  extension_names=(suno-helper distrokid-helper community-helper)
else
  extension_names=("$@")
fi

for name in "${extension_names[@]}"; do
  case "${name}" in
    suno-helper | distrokid-helper | community-helper) ;;
    *)
      echo "ERROR: unsupported extension: ${name}" >&2
      exit 1
      ;;
  esac
done

# Node.js / pnpm は vite-plus（vp）の shim が供給する。shim は実行時の cwd から
# Node を .node-version、pnpm を package.json::packageManager で解決するため、
# pnpm は repository root ではなく各拡張ディレクトリで起動する。
node_version=$(node --version)
if [[ ${node_version} != v24.* ]]; then
  echo "ERROR: expected Node 24, got ${node_version}" >&2
  exit 1
fi

for name in "${extension_names[@]}"; do
  pnpm_version=$(cd "extensions/${name}" && pnpm --version)
  if [[ ${pnpm_version} != 11.15.1 ]]; then
    echo "ERROR: expected pnpm 11.15.1 in extensions/${name}, got ${pnpm_version}" >&2
    exit 1
  fi
done

lockfiles=()
for name in "${extension_names[@]}"; do
  extension_dir="extensions/${name}"
  (cd "${extension_dir}" && pnpm install --frozen-lockfile)
  (cd "${extension_dir}" && pnpm build)
  # 過去 run の zip が残っていると下の「唯一の1件」判定が誤 FAIL する。
  # .output/ は gitignore 済みのビルド成果物で pnpm zip が再生成するため、
  # 判定対象を今回の run が生成した zip だけに揃えてから zip する。
  rm -f "${extension_dir}/.output"/*.zip
  (cd "${extension_dir}" && pnpm zip)

  version=$(node -p "require('./${extension_dir}/package.json').version")
  zip_path="${extension_dir}/.output/${name}-${version}-chrome.zip"
  shopt -s nullglob
  zip_files=("${extension_dir}/.output"/*.zip)
  shopt -u nullglob
  if [[ ${#zip_files[@]} -ne 1 || ${zip_files[0]:-} != "${zip_path}" ]]; then
    echo "ERROR: expected exactly one zip (${zip_path}), found ${#zip_files[@]}" >&2
    exit 1
  fi
  lockfiles+=("${extension_dir}/pnpm-lock.yaml")
done

git diff --exit-code -- "${lockfiles[@]}"
