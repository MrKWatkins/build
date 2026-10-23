#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Recording command doubles exercise publication gates without registry access.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$scratch/"{bin,images,scripts,tests}
cp "$root/images/"*.sh "$scratch/images/"
cp "$root/scripts/common.sh" "$scratch/scripts/"
export COMMAND_LOG="$scratch/commands"
export EXPECTED_COMMIT=1111111111111111111111111111111111111111
export IMAGE_VERSION="sha-$EXPECTED_COMMIT"
export BASE_DIGEST=ghcr.io/mrkwatkins/docs-base@sha256:2222222222222222222222222222222222222222222222222222222222222222
export BASE_ID=sha256:4444444444444444444444444444444444444444444444444444444444444444
cat > "$scratch/bin/docker" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\n' "$*" >> "$COMMAND_LOG"
if [[ $1 == --config ]]; then exit "${PUBLIC_EXIT:-0}"; fi
case "$1 $2" in
  'manifest inspect') exit "${MANIFEST_EXIT:-1}" ;;
  'image inspect')
    case "$*" in
      *base-image-id*) echo "${USED_BASE:-$BASE_ID}" ;;
      *image.revision*) echo "${IMAGE_COMMIT:-$EXPECTED_COMMIT}" ;;
      *image.version*) echo "$IMAGE_VERSION" ;;
      *'{{.Id}}'*) echo "$BASE_ID" ;;
      *) echo "$BASE_DIGEST" ;;
    esac ;;
esac
STUB
cat > "$scratch/bin/git" <<'STUB'
#!/usr/bin/env bash
echo "$EXPECTED_COMMIT"
STUB
cat > "$scratch/bin/gh" <<'STUB'
#!/usr/bin/env bash
# No existing version tags.
exit 0
STUB
cat > "$scratch/tests/docs.sh" <<'STUB'
#!/usr/bin/env bash
# Image tags must not become MSBuild's Version environment property.
if [[ -n ${VERSION:-} ]]; then echo 'Image version leaked into MSBuild.' >&2; exit 1; fi
printf 'validate %s %s\n' "$DOCS_BASE_TEST_IMAGE" "$DOCS_TEST_IMAGE" >> "$COMMAND_LOG"
exit "${TEST_EXIT:-0}"
STUB
chmod +x "$scratch/bin/"*
export PATH="$scratch/bin:$PATH"

run() {
  : > "$COMMAND_LOG"
  if [[ $1 == build ]]; then
    bash "$scratch/images/build.sh" > "$scratch/output" 2>&1 || return $?
    bash "$scratch/images/publish.sh" >> "$scratch/output" 2>&1
  else
    bash "$scratch/images/publish.sh" > "$scratch/output" 2>&1
  fi
}
no_latest() {
  if grep -q ':latest' "$COMMAND_LOG"; then cat "$COMMAND_LOG" >&2; exit 1; fi
}

run build
[[ $(grep -c '^docker build ' "$COMMAND_LOG") == 2 ]]
[[ $(grep -c '^validate ' "$COMMAND_LOG") == 1 ]]
grep -Fq -- "--label io.mrkwatkins.build.base-image-id=$BASE_ID" "$COMMAND_LOG"
grep -Fq 'validate docs-base:local docs-dotnet:local' "$COMMAND_LOG"
grep -Fxq 'docker push ghcr.io/mrkwatkins/docs-base:latest' "$COMMAND_LOG"
grep -Fxq 'docker push ghcr.io/mrkwatkins/docs-dotnet:latest' "$COMMAND_LOG"
grep -Fxq "docker push ghcr.io/mrkwatkins/docs-dotnet:sha-$EXPECTED_COMMIT" "$COMMAND_LOG"
awk '/^validate / { validated=1 } /^docker push / { if (!validated) exit 1 }' "$COMMAND_LOG"
echo 'PASS: one build per image and one validation pass publish both latest tags.'

if IMAGE_VERSION=sha-invalid run build; then echo 'Accepted an invalid commit tag.' >&2; exit 1; fi
test ! -s "$COMMAND_LOG"
if IMAGE_VERSION=sha-3333333333333333333333333333333333333333 run build; then echo 'Accepted a tag for a different source commit.' >&2; exit 1; fi
test ! -s "$COMMAND_LOG"
echo 'PASS: automatic commit tags publish successfully; malformed tags stop before registry access.'

if TEST_EXIT=7 run build; then echo 'Published after failed validation.' >&2; exit 1; fi
no_latest
if grep -q '^docker push ' "$COMMAND_LOG"; then exit 1; fi
if PUBLIC_EXIT=1 run build; then echo 'Updated latest to private images.' >&2; exit 1; fi
no_latest
grep -q 'Make the GHCR package public' "$scratch/output"
if MANIFEST_EXIT=0 run build; then echo 'Accepted an existing version tag.' >&2; exit 1; fi
no_latest
grep -q 'Immutable tag already exists' "$scratch/output"
echo 'PASS: failed validation, private images and existing tags block latest updates.'

run publish
if grep -Eq '^(docker build |validate )' "$COMMAND_LOG"; then echo 'Publication rebuilt or retested images.' >&2; exit 1; fi
if IMAGE_COMMIT=wrong run publish; then echo 'Published images from another commit.' >&2; exit 1; fi
if grep -q '^docker push ' "$COMMAND_LOG"; then exit 1; fi
echo 'PASS: publication uploads the prepared image pair without rebuilding or retesting.'

if USED_BASE=wrong run publish; then echo 'Published an incompatible image pair.' >&2; exit 1; fi
if grep -q '^docker push ' "$COMMAND_LOG"; then exit 1; fi
echo 'PASS: mismatched base images are rejected before publication.'
