#!/bin/sh
set -eu

usage() {
  echo "usage: run-sandwich.sh --repository-url URL --ref REF --workspace DIR -- <yt-hybrid-runner args>" >&2
  exit 2
}

repository_url=
repository_ref=
workspace=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repository-url) [ "$#" -ge 2 ] || usage; repository_url=$2; shift 2 ;;
    --ref) [ "$#" -ge 2 ] || usage; repository_ref=$2; shift 2 ;;
    --workspace) [ "$#" -ge 2 ] || usage; workspace=$2; shift 2 ;;
    --) shift; break ;;
    *) usage ;;
  esac
done

[ -n "$repository_url" ] && [ -n "$repository_ref" ] && [ -n "$workspace" ] || usage
[ ! -e "$workspace" ] && [ ! -L "$workspace" ] || { echo "workspace already exists: $workspace" >&2; exit 1; }
mkdir -p "$workspace"
checkout=$workspace/channel
git clone --quiet --branch "$repository_ref" --single-branch "$repository_url" "$checkout"
cd "$checkout"

# Cloud and local use the same uv-direct path. Provider-specific workflow syntax belongs outside this script.
uv run --frozen yt-hybrid-runner --channel-dir . "$@"
uv run --frozen yt-human-tasks --channel-dir .
