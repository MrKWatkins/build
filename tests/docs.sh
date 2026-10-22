#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=${DOCS_TEST_IMAGE:-docs-dotnet:local}
base_image=${DOCS_BASE_TEST_IMAGE:-docs-base:local}
temporary=$(mktemp -d)
preview=
cleanup() {
  if [[ -n $preview ]]; then docker rm -f "$preview" >/dev/null; fi
  rm -rf -- "$temporary"
}
trap cleanup EXIT
mkdir -p "$temporary/base"
cp -a "$root/tests/fixtures/docs-base/." "$temporary/base/"
docker run --rm --user "$(id -u):$(id -g)" --mount "type=bind,source=$temporary/base,target=/workspace" -w /workspace "$base_image" build
test -f "$temporary/base/artifacts/docs/index.html"
docker run --rm --entrypoint sh "$base_image" -c '! command -v dotnet && ! command -v sesharp'
workspace="$temporary/source with spaces"
mkdir -p "$workspace"
cp -a "$root/tests/fixtures/docs/." "$workspace/"
dotnet build "$workspace/src/Example" -c Release --nologo
dotnet build "$workspace/src/Support" -c Release --nologo
args=(--rm --user "$(id -u):$(id -g)" --mount "type=bind,source=$workspace,target=/workspace" -w /workspace)
source_ref=0123456789012345678901234567890123456789
build() { docker run "${args[@]}" "$image" build --version 1.2.3 --source-ref "$source_ref" "$@"; }
build
test -f "$workspace/artifacts/docs/index.html"
test "$(stat -c %u "$workspace/artifacts/docs/index.html")" = "$(id -u)"
grep -q 'Example v1.2.3' "$workspace/artifacts/docs/index.html"
grep -q 'Parses a string into a value' "$workspace/artifacts/docs/api/Example/Value-T/Parse.html"
grep -q "$source_ref" "$workspace/artifacts/docs/api/Example/Value-T/Read.html"
test -f "$workspace/artifacts/docs/api/Example/Helper/index.html"
test -f "$workspace/artifacts/docs/api/Example/Value-T/Nested-T/index.html"
test -f "$workspace/docs/content/api/introduction.md"
docker run --rm --entrypoint sh "$image" -c 'test ! -d /usr/share/dotnet/sdk && test -z "$(dotnet --list-sdks)" && test ! -e /root/.nuget/packages'

expect_failure() {
  local diagnostic=$1
  if build --output artifacts/failed > "$temporary/failure.log" 2>&1; then
    echo "Expected docs failure: $diagnostic" >&2
    exit 1
  fi
  if ! grep -q "$diagnostic" "$temporary/failure.log"; then cat "$temporary/failure.log" >&2; exit 1; fi
  test ! -f "$workspace/artifacts/failed/index.html"
}
cp "$workspace/docs/content/usage.md" "$temporary/usage.md"
printf '\nThe color is blue.\n' >> "$workspace/docs/content/usage.md"
expect_failure Shared.BritishSpelling
cp "$temporary/usage.md" "$workspace/docs/content/usage.md"
xml="$workspace/src/Example/bin/Release/net10.0/Example.xml"
cp "$xml" "$temporary/Example.xml"
sed -i 's/A strongly typed value/A strongly-typed value/' "$xml"
expect_failure Shared.StronglyTyped
cp "$temporary/Example.xml" "$xml"
printf '\n[Broken](./missing.md)\n' >> "$workspace/docs/content/usage.md"
expect_failure 'dead link'
cp "$temporary/usage.md" "$workspace/docs/content/usage.md"
printf '\n[Reading](./usage.md#missing)\n' >> "$workspace/docs/content/usage.md"
expect_failure 'missing anchor'
cp "$temporary/usage.md" "$workspace/docs/content/usage.md"

preview=$(docker run -d --user "$(id -u):$(id -g)" --mount "type=bind,source=$workspace,target=/workspace" -w /workspace -p 127.0.0.1::5173 "$image" serve --source-ref "$source_ref")
port=$(docker port "$preview" 5173/tcp)
ready=false
for ((attempt=0; attempt<30; attempt++)); do
  if curl -fsS "http://$port/example/" -o "$temporary/preview.html" 2>/dev/null; then ready=true; break; fi
  sleep 1
done
if [[ $ready != true ]]; then docker logs "$preview" >&2; exit 1; fi
grep -q '/example/@vite/client' "$temporary/preview.html"
curl -fsS "http://$port/example/@siteData" -o "$temporary/site-data.js"
grep -q 'Example (development)' "$temporary/site-data.js"
echo 'Documentation integration tests passed.'
