#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=common.sh
source "$script_directory/common.sh"
labels=(--label "org.opencontainers.image.revision=$commit" --label "org.opencontainers.image.version=$IMAGE_VERSION")
docker build -f images/docs-base/Dockerfile "${labels[@]}" -t docs-base:local .
base_id=$(docker image inspect --format '{{.Id}}' docs-base:local)
docker build -f images/docs-dotnet/Dockerfile --build-arg BASE_IMAGE=docs-base:local \
  "${labels[@]}" --label "io.mrkwatkins.build.base-image-id=$base_id" -t docs-dotnet:local .
verify_image_pair docs-base:local docs-dotnet:local
DOCS_BASE_TEST_IMAGE=docs-base:local DOCS_TEST_IMAGE=docs-dotnet:local bash tests/docs.sh
