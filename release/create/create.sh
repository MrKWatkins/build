#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/../../scripts/common.sh"
require_version
[[ ${COMMIT:-} =~ ^[0-9a-f]{40}$ ]] || fail 'COMMIT must be a full, resolved commit SHA.'
repository=${GH_REPO:-${GITHUB_REPOSITORY:-}}
[[ -n $repository ]] || repository=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
[[ $repository =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$ ]] || fail 'Invalid GitHub repository; use owner/name.'

# Confirm the commit exists in the target repository before creating anything.
resolved=$(gh api "repos/$repository/commits/$COMMIT" --jq .sha)
[[ $resolved == "$COMMIT" ]] || fail 'GitHub did not resolve the expected commit.'
tag="v$VERSION"
existing=$(gh api "repos/$repository/git/matching-refs/tags/$tag" \
  --jq ".[] | select(.ref == \"refs/tags/$tag\") | [.object.type, .object.sha] | @tsv")
if [[ -n $existing ]]; then
  read -r kind target <<< "$existing"
  while [[ $kind == tag ]]; do
    existing=$(gh api "repos/$repository/git/tags/$target" --jq '[.object.type, .object.sha] | @tsv')
    read -r kind target <<< "$existing"
  done
  [[ $kind == commit && $target == "$COMMIT" ]] || fail "Tag $tag already targets a different commit; refusing to move it."
else
  gh api --method POST "repos/$repository/git/refs" \
    -f "ref=refs/tags/$tag" -f "sha=$COMMIT" > /dev/null
fi
printf 'Creating %s at %s in %s\n' "$tag" "$COMMIT" "$repository"
gh release create "$tag" --repo "$repository" --verify-tag \
  --target "$COMMIT" --generate-notes
