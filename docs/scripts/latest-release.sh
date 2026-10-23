#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
repository=${1:?Expected owner/name}
gh api --paginate "repos/$repository/tags?per_page=100" --jq '.[].name' |
  python3 -c '
import re, sys
versions = []
for tag in sys.stdin.read().splitlines():
    match = re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag)
    if match:
        versions.append((tuple(map(int, match.groups())), tag))
if not versions:
    sys.exit("No stable vX.Y.Z release tag was found.")
print(max(versions)[1])
'
