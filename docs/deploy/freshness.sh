#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=../../scripts/common.sh
source "$script_directory/../../scripts/common.sh"
require_version
repository=${GH_REPO:-${GITHUB_REPOSITORY:-}}
[[ $repository =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail 'Set GH_REPO or GITHUB_REPOSITORY to owner/name.'
latest=$(bash "$script_directory/../scripts/latest-release.sh" "$repository")
[[ $latest == "v$VERSION" ]] || fail "Refusing to deploy v$VERSION: the latest release is $latest."
printf 'Deploying documentation for the latest release: %s\n' "$latest"
