#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/../../scripts/common.sh"

[[ -n ${NUGET_API_KEY:-} ]] || fail 'A short-lived credential from NuGet trusted publishing is required.'
package_directory=$(absolute_directory "${PACKAGE_DIRECTORY:-artifacts/packages}")
shopt -s nullglob
packages=("$package_directory"/*.nupkg)
(( ${#packages[@]} > 0 )) || fail 'No prepared .nupkg files found; nothing was published.'
for package in "${packages[@]}"; do
  # NuGet also pushes the adjacent .snupkg when present.
  dotnet nuget push "$package" --source https://api.nuget.org/v3/index.json \
    --api-key "$NUGET_API_KEY" --skip-duplicate
done
