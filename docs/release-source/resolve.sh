#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=../../scripts/common.sh
source "$script_directory/../../scripts/common.sh"
repository=${GH_REPO:-${GITHUB_REPOSITORY:-}}
[[ $repository =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail 'Set GH_REPO or GITHUB_REPOSITORY to owner/name.'
tag=$(bash "$script_directory/../scripts/latest-release.sh" "$repository")
[[ $tag == v* ]] || fail "Expected a stable v-prefixed release tag, got: $tag"
VERSION=${tag#v}
require_version
ref=${API_REF:-$tag}
encoded_ref=$(REF_TO_ENCODE="$ref" python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["REF_TO_ENCODE"], safe=""))')
commit=$(gh api "repos/$repository/commits/$encoded_ref" --jq .sha)
[[ $commit =~ ^[a-f0-9]{40}$ ]] || fail "Could not resolve API source commit: $ref"
printf 'Released library: %s\nAPI source: %s (%s)\nDocumentation source: %s\n' "$tag" "$ref" "$commit" "$(git rev-parse HEAD)"
if [[ -n ${API_REF:-} ]]; then
  printf 'API source override selected; generated APIs may differ from the published package.\n'
fi
if [[ -n ${GITHUB_OUTPUT:-} ]]; then
  printf 'version=%s\ncommit=%s\nrelease-tag=%s\n' "$VERSION" "$commit" "$tag" >> "$GITHUB_OUTPUT"
fi
if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
  {
    printf 'Released library: %s\n\nAPI source commit: %s\n\nDocumentation source commit: %s\n' "$tag" "$commit" "$(git rev-parse HEAD)"
    if [[ -n ${API_REF:-} ]]; then printf '\n**API source override is active; this may differ from the published package.**\n'; fi
  } >> "$GITHUB_STEP_SUMMARY"
fi
