#!/usr/bin/env bash
# Changed-path classifier shared by CI and Extensions workflows (#2333).
set -eu

changed_file="${1:?changed paths file is required}"

python=false
packaging=false
windows=false
adr=false
suno=false
distrokid=false
community=false
seen=false

while IFS= read -r path || [ -n "$path" ]; do
  [ -n "$path" ] || continue
  seen=true

  case "$path" in
    extensions/suno-helper/*)
      suno=true
      ;;
    extensions/distrokid-helper/*)
      distrokid=true
      ;;
    extensions/community-helper/*)
      community=true
      ;;
    extensions/shared/* | extensions/shared-ui/* | extensions/package.json | extensions/pnpm-lock.yaml | extensions/pnpm-workspace.yaml | extensions/ultracite.jsonc | .github/workflows/extensions.yml | .github/scripts/classify-ci-paths.sh)
      suno=true
      distrokid=true
      community=true
      ;;
    tests/test_actions_parallel_workflows.py | flake.nix | flake.lock)
      python=true
      suno=true
      distrokid=true
      community=true
      ;;
  esac

  case "$path" in
    extensions/* | .github/workflows/extensions.yml | .github/workflows/release-extensions.yml | CHANGELOG.md | README.md)
      ;;
    *)
      python=true
      ;;
  esac

  case "$path" in
    src/* | .claude/* | pyproject.toml | uv.lock | flake.nix | flake.lock | .github/workflows/ci.yml | tests/test_skills_sync_installed_wheel.py | tests/test_packaging*)
      packaging=true
      ;;
  esac

  case "$path" in
    src/youtube_automation/scripts/cost_tracker* | tests/test_cost_tracker.py | pyproject.toml | uv.lock | flake.nix | flake.lock | .github/workflows/ci.yml)
      windows=true
      ;;
  esac

  case "$path" in
    docs/adr/* | .github/workflows/ci.yml | tests/test_actions_parallel_workflows.py)
      adr=true
      ;;
  esac
done < "$changed_file"

# An empty or unavailable diff must fail safe by running every gate.
if [ "$seen" = false ]; then
  python=true
  packaging=true
  windows=true
  adr=true
  suno=true
  distrokid=true
  community=true
fi

printf 'python=%s\n' "$python"
printf 'packaging=%s\n' "$packaging"
printf 'windows=%s\n' "$windows"
printf 'adr=%s\n' "$adr"
printf 'suno=%s\n' "$suno"
printf 'distrokid=%s\n' "$distrokid"
printf 'community=%s\n' "$community"
