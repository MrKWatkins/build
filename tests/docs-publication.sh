#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
mkdir "$temporary/bin"
export COMMAND_LOG="$temporary/commands" GH_REPO=example/library
export API_COMMIT=1111111111111111111111111111111111111111
export GITHUB_OUTPUT="$temporary/output" GITHUB_STEP_SUMMARY="$temporary/summary"
cat > "$temporary/bin/gh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$COMMAND_LOG"
if [[ ${API_FAILURE:-false} == true ]]; then exit 7; fi
case "$*" in
  */tags\?*) printf '%s\n' "${RELEASE_TAGS:-${LATEST_TAG:-v1.2.3}}" ;;
  */commits/*) echo "$API_COMMIT" ;;
  *) exit 1 ;;
esac
STUB
chmod +x "$temporary/bin/gh"
export PATH="$temporary/bin:$PATH"
bash "$root/docs/release-source/resolve.sh"
grep -Fxq 'version=1.2.3' "$GITHUB_OUTPUT"
grep -Fxq "commit=$API_COMMIT" "$GITHUB_OUTPUT"
grep -Fq 'commits/v1.2.3' "$COMMAND_LOG"
RELEASE_TAGS=$'v1.9.0\nv1.10.0\nv1.10.1-preview\nv1.8.0' bash "$root/docs/release-source/resolve.sh"
grep -Fq 'commits/v1.10.0' "$COMMAND_LOG"
API_REF=docs/fix bash "$root/docs/release-source/resolve.sh"
grep -Fq 'commits/docs%2Ffix' "$COMMAND_LOG"
grep -Fq 'API source override is active' "$GITHUB_STEP_SUMMARY"
if LATEST_TAG=v1.2.3-preview bash "$root/docs/release-source/resolve.sh" > "$temporary/failure" 2>&1; then exit 1; fi
if API_FAILURE=true bash "$root/docs/release-source/resolve.sh" > "$temporary/failure" 2>&1; then exit 1; fi
echo 'PASS: docs-only builds resolve stable released APIs and report explicit overrides.'

VERSION=1.2.3 bash "$root/docs/deploy/freshness.sh"
if VERSION=1.2.3 LATEST_TAG=v1.2.4 bash "$root/docs/deploy/freshness.sh" > "$temporary/failure" 2>&1; then exit 1; fi
grep -Fq 'Refusing to deploy v1.2.3' "$temporary/failure"
if VERSION=1.2.3 API_FAILURE=true bash "$root/docs/deploy/freshness.sh" > "$temporary/failure" 2>&1; then exit 1; fi
echo 'PASS: newer releases and API failures prevent stale deployments.'
