#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=common.sh
source "$script_directory/common.sh"
registry=ghcr.io/mrkwatkins
base="$registry/docs-base:$IMAGE_VERSION"
dotnet="$registry/docs-dotnet:$IMAGE_VERSION"
verify_image_pair docs-base:local docs-dotnet:local
for name in docs-base docs-dotnet; do
  if docker manifest inspect "$registry/$name:$IMAGE_VERSION" >/dev/null 2>&1; then
    fail "Immutable tag already exists: $registry/$name:$IMAGE_VERSION"
  fi
  # GHCR reports "denied" for both absent and inaccessible images. Use the
  # authenticated package API to distinguish absence from registry failures.
  if tags=$(gh api --paginate "/users/MrKWatkins/packages/container/$name/versions?per_page=100" --jq '.[].metadata.container.tags[]' 2>&1); then
    if grep -Fxq "$IMAGE_VERSION" <<< "$tags"; then fail "Immutable tag already exists: $registry/$name:$IMAGE_VERSION"; fi
  elif ! grep -Fq '(HTTP 404)' <<< "$tags"; then
    fail "Cannot establish whether $registry/$name:$IMAGE_VERSION exists: $tags"
  fi
done
for name in docs-base docs-dotnet; do
  docker tag "$name:local" "$registry/$name:$IMAGE_VERSION"
  docker push "$registry/$name:$IMAGE_VERSION"
done

# Neither a failed build nor a private image may advance latest.
anonymous=$(mktemp -d)
trap 'rm -rf -- "$anonymous"' EXIT
for image in "$base" "$dotnet"; do
  docker --config "$anonymous" manifest inspect "$image" >/dev/null ||
    fail "Make the GHCR package public in Package settings: $image"
done
for name in docs-base docs-dotnet; do
  docker tag "$registry/$name:$IMAGE_VERSION" "$registry/$name:latest"
  docker push "$registry/$name:latest"
done
for image in "$base" "$dotnet"; do
  docker image inspect --format '{{index .RepoDigests 0}}' "$image"
  docker run --rm --entrypoint cat "$image" /opt/docs/versions.txt
done
