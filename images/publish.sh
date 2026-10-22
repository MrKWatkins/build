#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=../scripts/common.sh
source "$script_directory/../scripts/common.sh"
require_version
operation=${1:-}
[[ $operation == build || $operation == promote ]] || fail 'Expected build or promote.'
cd -- "$script_directory/.."
registry=ghcr.io/mrkwatkins
commit=$(git rev-parse HEAD)
base="$registry/docs-base:$VERSION"
dotnet="$registry/docs-dotnet:$VERSION"
labels=(--label "org.opencontainers.image.revision=$commit" --label "org.opencontainers.image.version=$VERSION")

if [[ $operation == build ]]; then
  for name in docs-base docs-dotnet; do
    if docker manifest inspect "$registry/$name:$VERSION" >/dev/null 2>&1; then
      fail "Immutable tag already exists: $registry/$name:$VERSION"
    fi
    # GHCR reports "denied" for both absent and inaccessible images. Use the
    # authenticated package API to distinguish absence from registry failures.
    if tags=$(gh api --paginate "/users/MrKWatkins/packages/container/$name/versions?per_page=100" --jq '.[].metadata.container.tags[]' 2>&1); then
      if grep -Fxq "$VERSION" <<< "$tags"; then fail "Immutable tag already exists: $registry/$name:$VERSION"; fi
    elif ! grep -Fq '(HTTP 404)' <<< "$tags"; then
      fail "Cannot establish whether $registry/$name:$VERSION exists: $tags"
    fi
  done
  docker build -f images/docs-base/Dockerfile "${labels[@]}" -t docs-base:local .
  docker build -f images/docs-dotnet/Dockerfile "${labels[@]}" -t docs-dotnet:local .
  bash tests/docs.sh
  docker tag docs-base:local "$base"
  docker push "$base"
  base_digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$base")
  [[ $base_digest == "$registry/docs-base@sha256:"* ]] || fail 'Could not resolve published base digest.'
  docker build -f images/docs-dotnet/Dockerfile --build-arg "BASE_IMAGE=$base_digest" \
    "${labels[@]}" --label "org.opencontainers.image.base.name=$base_digest" -t "$dotnet" .
  DOCS_BASE_TEST_IMAGE="$base" DOCS_TEST_IMAGE="$dotnet" bash tests/docs.sh
  docker push "$dotnet"
else
  anonymous=$(mktemp -d)
  trap 'rm -rf -- "$anonymous"' EXIT
  for image in "$base" "$dotnet"; do
    # A public source repository does not make new GHCR packages public.
    docker --config "$anonymous" manifest inspect "$image" >/dev/null ||
      fail "Make the GHCR package public in Package settings before promoting: $image"
    docker pull "$image"
  done
  base_digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$base")
  used_base=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.base.name"}}' "$dotnet")
  [[ $used_base == "$base_digest" ]] || fail 'The .NET image must derive from this exact base release digest.'
  for image in "$base" "$dotnet"; do
    [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image") == "$commit" ]] ||
      fail "Select the source commit that built $image before promoting it."
  done
  DOCS_BASE_TEST_IMAGE="$base" DOCS_TEST_IMAGE="$dotnet" bash tests/docs.sh
  for name in docs-base docs-dotnet; do
    docker tag "$registry/$name:$VERSION" "$registry/$name:latest"
    docker push "$registry/$name:latest"
  done
fi
for image in "$base" "$dotnet"; do
  docker image inspect --format '{{index .RepoDigests 0}}' "$image"
  docker run --rm --entrypoint cat "$image" /opt/docs/versions.txt
done
