#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$root"
port=${DOCS_PORT:-5173}
if [[ ! $port =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
  echo 'DOCS_PORT must be between 1 and 65535.' >&2
  exit 1
fi

docker build -f images/docs-base/Dockerfile -t docs-base:local .
docker build -f images/docs-dotnet/Dockerfile -t docs-dotnet:local .
workspace="$root/artifacts/docs-preview"
mkdir -p "$workspace"
cp -a tests/fixtures/docs/. "$workspace/"
dotnet build "$workspace/src/Example" -c Release --nologo
dotnet build "$workspace/src/Support" -c Release --nologo

container="build-docs-preview-$$"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '\nDocumentation preview: http://localhost:%s/example/\n' "$port"
docker run --rm --init --name "$container" --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$workspace,target=/workspace" --workdir /workspace \
  -p "127.0.0.1:$port:5173" docs-dotnet:local serve \
  --source-ref 0123456789012345678901234567890123456789 &
wait "$!"
