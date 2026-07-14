#!/usr/bin/env bash
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
if [[ ${PWD} != "${repo_root}" ]]; then
  echo "ERROR: repository root で実行してください: ${repo_root}" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  extension_names=(suno-helper distrokid-helper)
else
  extension_names=("$@")
fi

for name in "${extension_names[@]}"; do
  case "${name}" in
    suno-helper | distrokid-helper) ;;
    *)
      echo "ERROR: unsupported extension: ${name}" >&2
      exit 1
      ;;
  esac
done

node_version=$(nix develop .#extensions --command node --version)
if [[ ${node_version} != v24.* ]]; then
  echo "ERROR: expected Node 24, got ${node_version}" >&2
  exit 1
fi

pnpm_version=$(nix develop .#extensions --command pnpm --version)
if [[ ${pnpm_version} != 11.12.0 ]]; then
  echo "ERROR: expected pnpm 11.12.0, got ${pnpm_version}" >&2
  exit 1
fi

lockfiles=()
for name in "${extension_names[@]}"; do
  extension_dir="extensions/${name}"
  nix develop .#extensions --command pnpm -C "${extension_dir}" install --frozen-lockfile
  nix develop .#extensions --command pnpm -C "${extension_dir}" build
  nix develop .#extensions --command pnpm -C "${extension_dir}" zip

  version=$(nix develop .#extensions --command node -p "require('./${extension_dir}/package.json').version")
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
