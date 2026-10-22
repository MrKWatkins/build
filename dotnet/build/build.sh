#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/../../scripts/common.sh"

directory=$(absolute_directory "${BUILD_DIRECTORY:-src}")
coverage=${COVERAGE:-true}
[[ $coverage == true || $coverage == false ]] || fail 'COVERAGE must be true or false.'
version_args=()
if [[ -n ${VERSION:-} ]]; then
  require_version
  version_args=("-p:Version=$VERSION")
fi

coverage_directory=${COVERAGE_DIRECTORY:-artifacts/coverage}
if [[ $coverage == true ]]; then
  mkdir -p -- "$coverage_directory"
  coverage_directory=$(absolute_directory "$coverage_directory")
  # Isolate this run's reports so a local rebuild cannot merge stale coverage.
  temporary_directory=$(mktemp -d)
  trap 'rm -rf -- "$temporary_directory"' EXIT
fi

cd -- "$directory"
dotnet --version
dotnet restore "${version_args[@]}"
# Preserve the existing advisory format check during consolidation.
if ! dotnet format --no-restore --verify-no-changes; then
  printf 'Warning: format verification failed; continuing as configured.\n' >&2
fi
dotnet build --no-restore --configuration Release "${version_args[@]}"

test_args=(--no-restore --no-build --configuration Release)
if [[ -n ${TEST_FILTER:-} ]]; then
  test_args+=(--filter "$TEST_FILTER")
fi
if [[ $coverage == true ]]; then
  test_args+=(--coverage --coverage-output-format cobertura --results-directory "$temporary_directory/results")
fi
test_status=0
dotnet test "${test_args[@]}" || test_status=$?

if [[ $coverage == true ]]; then
  # Install outside the checkout; never create or edit a consumer tool manifest.
  coverage_status=0
  generate_coverage() {
    dotnet tool install dotnet-reportgenerator-globaltool --version 5.5.10 \
      --tool-path "$temporary_directory/tools" || return
    "$temporary_directory/tools/reportgenerator" \
      "-reports:$temporary_directory/results/**/*.cobertura.xml" \
      "-targetdir:$coverage_directory" \
      '-reporttypes:Cobertura;MarkdownSummaryGithub' \
      "-assemblyfilters:${COVERAGE_ASSEMBLY_FILTERS:-+*}" || return
    if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
      cat "$coverage_directory/SummaryGithub.md" >> "$GITHUB_STEP_SUMMARY" || return
    fi
  }
  generate_coverage || coverage_status=$?
  # A reporting failure must not mask a failed test run.
  if (( test_status != 0 )); then exit "$test_status"; fi
  exit "$coverage_status"
fi
exit "$test_status"
