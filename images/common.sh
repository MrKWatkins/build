#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
image_script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=../scripts/common.sh
source "$image_script_directory/../scripts/common.sh"

cd -- "$image_script_directory/.." || fail 'Cannot find the shared build repository.'
commit=$(git rev-parse HEAD)
# MSBuild imports VERSION as its package version; image tags use a separate name.
IMAGE_VERSION=${IMAGE_VERSION:-sha-$commit}
[[ $IMAGE_VERSION == "sha-$commit" ]] || fail 'The image tag must be sha- followed by the checked-out source commit.'

verify_image_pair() {
  local base_image=$1 dotnet_image=$2 base_id used_base image
  base_id=$(docker image inspect --format '{{.Id}}' "$base_image")
  used_base=$(docker image inspect --format '{{index .Config.Labels "io.mrkwatkins.build.base-image-id"}}' "$dotnet_image")
  [[ $used_base == "$base_id" ]] || fail 'The .NET image must derive from this exact base image.'
  for image in "$base_image" "$dotnet_image"; do
    [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image") == "$commit" ]] ||
      fail "Select the source commit that built $image."
    [[ $(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.version"}}' "$image") == "$IMAGE_VERSION" ]] ||
      fail "The image version must match $IMAGE_VERSION: $image"
  done
}
