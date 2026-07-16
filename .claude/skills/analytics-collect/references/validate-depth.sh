#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: validate-depth.sh <analytics-json> <standard|full>" >&2
  exit 2
fi

analytics_json=$1
requested_depth=$2

if [ ! -f "$analytics_json" ]; then
  echo "analytics JSON not found: $analytics_json" >&2
  exit 1
fi

case "$requested_depth" in
  standard)
    jq -e '.collection_depth == "standard"' "$analytics_json" >/dev/null
    ;;
  full)
    jq -e '
      (.collection_depth == "full")
      and (.retention | type == "array" and length > 0)
      and (.retention | all(.[]; type == "object" and (has("error") | not)))
      and (.retention | any(.[];
        (.video_id | type == "string" and length > 0)
        and (.average_retention | type == "number")
        and (.midpoint_retention | type == "number")
        and (.data_points | type == "number" and . > 0)
        and (.retention_curve | type == "array" and length > 0)
        and (.retention_curve | all(.[];
          type == "object"
          and (.elapsed_ratio | type == "number")
          and (.watch_ratio | type == "number")
        ))
      ))
      and (.audience | type == "object" and has("by_country"))
      and (.audience.by_country | type == "object" and (has("error") | not))
    ' "$analytics_json" >/dev/null
    ;;
  *)
    echo "unsupported depth: $requested_depth" >&2
    exit 2
    ;;
esac
