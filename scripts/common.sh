#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Shared conventions for build and release scripts.

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

require_version() {
  [[ ${VERSION:-} =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] ||
    fail 'VERSION must be a stable version such as 1.2.3 (without a v prefix).'
}

absolute_directory() {
  (cd -- "$1" && pwd -P)
}
