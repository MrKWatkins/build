#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/../../scripts/common.sh"
require_version

directory=$(absolute_directory "${BUILD_DIRECTORY:-src}")
package_directory=${PACKAGE_DIRECTORY:-artifacts/packages}
mkdir -p -- "$package_directory"
package_directory=$(absolute_directory "$package_directory")
[[ -z $(ls -A -- "$package_directory") ]] || fail 'Package output directory must be empty; use a fresh directory for each release.'

cd -- "$directory"
dotnet pack --no-build --no-restore --configuration Release \
  "-p:Version=$VERSION" -p:SymbolPackageFormat=snupkg --include-symbols \
  --output "$package_directory"
shopt -s nullglob
packages=("$package_directory"/*.nupkg)
(( ${#packages[@]} > 0 )) || fail 'Pack produced no NuGet packages.'
printf 'Packages prepared in %s\n' "$package_directory"
if [[ -n ${GITHUB_OUTPUT:-} ]]; then
  printf 'directory=%s\n' "$package_directory" >> "$GITHUB_OUTPUT"
fi
