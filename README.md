# build

Shared build infrastructure for MrKWatkins repositories. Consumers follow `MrKWatkins/build/<action>@main`; changes here should keep them consistent.

As this is just for personal projects I will not be accepting feature or pull requests. Use it if you want, but at your own risk with no support I'm afraid.

## Conventions

- Linux runners with Bash; .NET 10 and native Microsoft Testing Platform.
- Solutions live in `src`; documentation will use `docs`.
- Release builds use `Release` and one stable `major.minor.patch` version,  without a `v` prefix. Release tags use `v`.
- Generated outputs go under ignored `artifacts` directories.
- Consumers check out the intended commit before invoking these actions.  Actions never check out or reset the consumer workspace.

Consumer `global.json` must select native MTP:

```json
{
  "test": { "runner": "Microsoft.Testing.Platform" }
}
```

Test projects need the MTP runner and, when coverage is enabled, the
`Microsoft.Testing.Extensions.CodeCoverage` extension. The optional `test-filter`
input uses NUnit/MSTest filter expressions.

## Validation builds

```yaml
name: Build
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: MrKWatkins/build/dotnet/build@main
```

`dotnet/build` restores, checks formatting, builds and tests. Formatting remains advisory during consolidation; compilation, tests and coverage reporting must
succeed. Source changes should always run this workflow, including after docs validation is added.

Coverage is on by default. ReportGenerator 5.5.10 merges MTP Cobertura files and writes `artifacts/coverage/Cobertura.xml` and `SummaryGithub.md`, appending the
latter to the job summary. It is installed temporarily outside the checkout; no tool manifest is created or changed. There is no coverage percentage gate.
Set `coverage: 'false'` to skip collection, tool installation and reporting.

Build inputs: `directory` (default `src`), `version` (optional), `test-filter` (optional), `coverage` (default `true`), `coverage-assembly-filters` (default
`+*`, ReportGenerator syntax) and `dotnet-version` (default `10.0.x`).

## Preparing a release

The consumer owns the release sequence. Resolve the checked-out commit with `git rev-parse HEAD`; use that SHA and the same supplied version throughout.

1. Call `dotnet/build` with `version`.
2. Call `dotnet/pack` with the same `version` to prepare packages and symbols.
3. Prepare project assets, then validate and build the complete documentation.
4. Call `dotnet/publish` on the prepared package directory.
5. Call `release/create` with `version` and the resolved `commit`.
6. Deploy the exact validated documentation artifact.

The docs actions are not implemented yet. Do not wire package publication into a consumer release until that validation gate is in place.

| Action           | Inputs                                                                                       | Behaviour                                                                                                                                                                            |
|------------------|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `dotnet/pack`    | Required `version`; `directory` defaults to `src`; `output` defaults to `artifacts/packages` | Packs existing Release outputs with `--no-build --no-restore`; includes `.snupkg`; rejects nonempty output directories. Output `directory` is the absolute package path.             |
| `dotnet/publish` | Required `nuget-user`; `directory` defaults to `artifacts/packages`                          | Uses trusted publishing to push existing packages to nuget.org, including adjacent symbol packages. Uses `--skip-duplicate` for retries. Never compiles, packs or creates a release. |
| `release/create` | Required `version` and full `commit` SHA                                                     | Confirms the commit exists in the consumer repository, creates its tag and a release with generated notes. An existing lightweight or annotated tag must resolve to that commit.     |

Pack and publish expect the .NET SDK already installed by the preceding build. For separate publishing jobs, download the prepared package artifact and install
the SDK there. Upload packages and validated documentation before publication, with enough artifact retention for recovery.

NuGet trusted publishing uses `NuGet/login@v1` immediately before the push and requires `nuget-user` plus `id-token: write` on that job. Configure the matching
trusted-publishing policy on nuget.org for each consumer workflow. There is no long-lived API-key input or `NUGET_API_TOKEN` fallback.

Release creation uses the calling job's GitHub token and needs `contents: write`. Keep those permissions on publishing jobs and never invoke publication for
untrusted pull requests. Documentation containers will not receive these credentials.

Publishing packages, creating a release and deploying a site are separate operations. If only deployment fails, retry the retained site artifact or use the
future docs-only workflow without republishing packages or creating another tag. If a package push partially fails, retry the same package artifacts. An existing
GitHub release is not recreated by `release/create`; skip that step on recovery once it has succeeded. Tags are never moved.

## Local commands

Scripts run from the consumer repository root and use the same implementation as the actions. Replace `/path/to/build` with this repository's location:

```bash
VERSION=1.2.3 bash /path/to/build/dotnet/build/build.sh
VERSION=1.2.3 bash /path/to/build/dotnet/pack/pack.sh
```

`BUILD_DIRECTORY` defaults to `src` for build and pack. `PACKAGE_DIRECTORY` defaults to `artifacts/packages` for pack and publish. Build also accepts
`COVERAGE`, `COVERAGE_DIRECTORY` (default `artifacts/coverage`), `TEST_FILTER` and `COVERAGE_ASSEMBLY_FILTERS`. Relative directories are resolved from the
initial working directory. Omit `VERSION` for ordinary development builds.

The publishing action handles OIDC authentication; its push script consumes the short-lived `NUGET_API_KEY` output from `NuGet/login`, not a stored repository
secret. Local builds and packing need no publishing credentials.

`release/create/create.sh` requires `VERSION`, `COMMIT` and an authenticated `gh`; `GH_REPO=owner/name` selects the repository outside GitHub Actions. These
scripts perform real publication when invoked.

## Maintaining this repository

CI runs ShellCheck, actionlint, and `bash tests/test.sh`. The integration tests use the real SDK to prove package/symbol creation does not rebuild, then
recording command doubles to check build failure propagation, publication-only behaviour and commit/tag validation. They never push packages or create releases.

Locally, with .NET 10, ripgrep, ShellCheck and actionlint installed:

```bash
shellcheck -x -P SCRIPTDIR dotnet/*/*.sh release/create/*.sh scripts/*.sh tests/*.sh
actionlint
bash tests/test.sh
```

Dependabot maintains action references. Update the pinned ReportGenerator version in `dotnet/build/build.sh` centrally and validate before merging.

Original project code is licensed under **GPL-3.0-only**; see [LICENSE](LICENSE).
