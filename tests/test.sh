#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Integration tests: real SDK packing, isolated command doubles for publication.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
export DOTNET_CLI_HOME="$scratch/dotnet-home"
export DOTNET_NOLOGO=1 DOTNET_CLI_TELEMETRY_OPTOUT=1
unset GITHUB_OUTPUT GITHUB_STEP_SUMMARY
cp -R "$root/tests/fixtures/library" "$scratch/source with spaces"
cd -- "$scratch"

# Real SDK: pack must use the existing DLL and produce both package formats.
dotnet restore 'source with spaces' --ignore-failed-sources
dotnet build 'source with spaces' --no-restore -c Release -p:Version=1.2.3
dll='source with spaces/bin/Release/net10.0/BuildFixture.dll'
before=$(sha256sum "$dll")
BUILD_DIRECTORY='source with spaces' VERSION=1.2.3 bash "$root/dotnet/pack/pack.sh"
[[ $(sha256sum "$dll") == "$before" ]]
[[ -s artifacts/packages/BuildFixture.1.2.3.nupkg ]]
[[ -s artifacts/packages/BuildFixture.1.2.3.snupkg ]]
if BUILD_DIRECTORY='source with spaces' VERSION=1.2.3 bash "$root/dotnet/pack/pack.sh"; then
  echo 'Pack accepted a nonempty output directory.' >&2; exit 1
fi
rm -- "$dll"
if BUILD_DIRECTORY='source with spaces' PACKAGE_DIRECTORY=missing-output VERSION=1.2.3 bash "$root/dotnet/pack/pack.sh" > "$scratch/missing-output.log" 2>&1; then
  cat "$scratch/missing-output.log"
  echo 'Pack rebuilt a missing DLL.' >&2; exit 1
fi
if ! grep -Fq 'NU5026' "$scratch/missing-output.log"; then
  cat "$scratch/missing-output.log"
  echo 'Pack failed for an unexpected reason.' >&2; exit 1
fi
echo 'PASS: real pack creates packages and symbols without rebuilding; rejects stale output.'

# Nothing below can access NuGet or GitHub: PATH contains recording doubles.
mkdir bin
export COMMAND_LOG="$scratch/commands" EXPECTED_COMMIT=1111111111111111111111111111111111111111
cat > bin/dotnet <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf '%q ' "$@" >> "$COMMAND_LOG"
printf '\n' >> "$COMMAND_LOG"
case "$1" in
  format) exit 1 ;;
  test) exit "${TEST_EXIT:-0}" ;;
  tool) exit 9 ;;
esac
STUB
cat > bin/gh <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf '%q ' "$@" >> "$COMMAND_LOG"
printf '\n' >> "$COMMAND_LOG"
case "$*" in
  *'/commits/'*) echo "$EXPECTED_COMMIT" ;;
  *'/matching-refs/'*)
    if [[ -n ${TAG_TARGET:-} ]]; then printf 'commit\t%s\n' "$TAG_TARGET"; fi ;;
esac
STUB
chmod +x bin/dotnet bin/gh
export PATH="$scratch/bin:$PATH"

export BUILD_DIRECTORY='source with spaces' VERSION=1.2.3 COVERAGE=false
export TEST_FILTER='TestCategory!=Slow&TestCategory!=Integration'
: > "$COMMAND_LOG"
bash "$root/dotnet/build/build.sh"
grep -F -- '-p:Version=1.2.3' "$COMMAND_LOG"
grep -F -- 'test --no-restore --no-build --configuration Release --filter TestCategory\!=Slow\&TestCategory\!=Integration' "$COMMAND_LOG"
if grep -Eq -- '--coverage|tool install' "$COMMAND_LOG"; then exit 1; fi
status=0
TEST_EXIT=7 bash "$root/dotnet/build/build.sh" || status=$?
[[ $status == 7 ]]
status=0
TEST_EXIT=7 COVERAGE=true bash "$root/dotnet/build/build.sh" || status=$?
[[ $status == 7 ]] # Coverage installation fails too; retain the original test failure.
status=0
COVERAGE=true bash "$root/dotnet/build/build.sh" || status=$?
[[ $status == 9 ]] # Reporting failure also blocks a successful test run.
echo 'PASS: MTP arguments, advisory format check, version propagation and failure exits.'

: > "$COMMAND_LOG"
NUGET_API_KEY=test-key bash "$root/dotnet/publish/publish.sh"
[[ $(wc -l < "$COMMAND_LOG") == 1 ]]
grep -F 'nuget push ' "$COMMAND_LOG"
if NUGET_API_KEY='' bash "$root/dotnet/publish/publish.sh"; then exit 1; fi
if NUGET_API_KEY=test-key PACKAGE_DIRECTORY=missing-output bash "$root/dotnet/publish/publish.sh"; then exit 1; fi
echo 'PASS: publication only pushes prepared packages; empty inputs fail.'

export COMMIT="$EXPECTED_COMMIT" GH_REPO=example/library
: > "$COMMAND_LOG"
bash "$root/release/create/create.sh"
grep -F -- "-f sha=$COMMIT" "$COMMAND_LOG"
grep -F -- "--verify-tag --target $COMMIT --generate-notes" "$COMMAND_LOG"
: > "$COMMAND_LOG"
if TAG_TARGET=2222222222222222222222222222222222222222 bash "$root/release/create/create.sh"; then exit 1; fi
if grep -Eq -- 'release create|--method POST' "$COMMAND_LOG"; then exit 1; fi
if COMMIT=main bash "$root/release/create/create.sh"; then exit 1; fi
if VERSION=v1.2.3 bash "$root/release/create/create.sh"; then exit 1; fi
echo 'PASS: release pins the supplied commit and refuses conflicting tags or invalid inputs.'
