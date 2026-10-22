#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail

command=${1:-}
[[ $command == build || $command == serve ]] || { echo 'Usage: docs.sh build|serve [docs options]' >&2; exit 1; }
shift
image=${DOCS_IMAGE:-ghcr.io/mrkwatkins/docs-dotnet:latest}
docker pull "$image"
resolved=$(docker image inspect --format '{{index .RepoDigests 0}}' "$image")
[[ -n $resolved ]] || { echo "Cannot resolve image digest: $image" >&2; exit 1; }
printf 'Documentation image: %s\n' "$resolved"
args=(--rm --init --user "$(id -u):$(id -g)" --mount "type=bind,source=$PWD,target=/workspace" --workdir /workspace)
if [[ $command == serve ]]; then
  port=${DOCS_PORT:-5173}
  if [[ ! $port =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
    echo 'DOCS_PORT must be between 1 and 65535.' >&2
    exit 1
  fi
  args+=(-p "127.0.0.1:$port:5173")
fi
docker run "${args[@]}" "$resolved" "$command" "$@"
