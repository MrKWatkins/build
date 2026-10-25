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

## Project workflows

For the standard `src` and `docs/site.json` layout, both workflows call `dotnet/project`. The build workflow validates everything without publishing:

```yaml
name: Build and Test
on: [push, pull_request]
permissions:
  contents: read
concurrency:
  group: build-${{ github.ref }}
  cancel-in-progress: true
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: MrKWatkins/build/dotnet/project@main
```

Release uses the same action in one job, with publication enabled by the selected options:

```yaml
name: Release
on:
  workflow_dispatch:
    inputs:
      version:
        description: Optional version without v; blank increments the latest stable tag minor version
        type: string
        required: false
      publish-packages:
        description: Publish NuGet packages and create a release
        type: boolean
        default: true
      publish-docs:
        description: Publish documentation
        type: boolean
        default: true
      api-ref:
        description: Optional API source override for docs-only XML comment corrections
        type: string
permissions:
  contents: read
concurrency:
  group: github-pages
  cancel-in-progress: false
jobs:
  release:
    runs-on: ubuntu-latest
    environment: github-pages
    permissions:
      contents: write
      pages: write
      id-token: write
    steps:
      - uses: MrKWatkins/build/dotnet/project@main
        with:
          version: ${{ inputs.version }}
          publish-packages: ${{ inputs.publish-packages }}
          publish-docs: ${{ inputs.publish-docs }}
          api-ref: ${{ inputs.api-ref }}
```

The shared action checks out the selected commit, installs the SDK, builds and tests, and validates documentation before any publication. Package releases compile
once and pack existing outputs. Packages and the validated Pages artifact are retained for 14 days; publication uses the files prepared in the same job.
There is no separate publishing job, package download or second SDK setup. `nuget-user` defaults to `MrKWatkins`.

Both release options default to `true`. Leave `version` blank to increment the minor version of the highest stable `vX.Y.Z` tag, resetting the patch
(for example, `v1.7.3` becomes `1.8.0`). An explicit version overrides this; the first release requires one because there is no previous tag. The resolved version
is shown in the job summary and used for packages, documentation and the release tag.

For a documentation update, turn **publish-packages** off, leave **publish-docs** on and leave the version blank. The action uses current handwritten pages with
API assemblies built from the highest stable release tag in a separate checkout. The site keeps the released version; no NuGet package, tag or GitHub release
is created. The optional `api-ref` overrides API source for XML comment corrections. There is no separate documentation workflow.

Turning **publish-docs** off skips deployment; package builds still validate documentation. Turning both options off runs ordinary build, test and documentation
validation without publishing anything. For projects without a site, set `docs: 'false'` and disable the documentation publication option. Other optional inputs
are `directory`, `dotnet-version`, `coverage`, `coverage-assembly-filters`, `test-filter` and `docs-config`.

The job stays in the project workflow because [NuGet validates `job_workflow_ref`](https://github.com/NuGet/NuGetGallery/blob/dev/src/NuGetGallery.Services/Authentication/Federated/GitHubTokenPolicyValidator.cs) against that repository and workflow filename.
A composite action preserves that identity. Configure trusted publishing for the project's `release.yml`. The caller declares permissions, the `github-pages`
environment and concurrency; allow the release branch in that environment's deployment rules. Configure Pages to publish using **GitHub Actions**.

Rerunning Release reruns the whole job. A blank version is recalculated from the current tags; after package publication, use **publish-packages** off for a
subsequent documentation update. Existing tags are never moved.

The shared Python helper reads API project paths from the site configuration using only the standard library. The convention is
`<project>/bin/Release/<framework>/<assembly>.dll`, with one `.csproj` per project directory; assembly paths do not need repeating in workflow YAML.

The individual actions remain available for workflows that need custom preparation:

`dotnet/build` restores, checks formatting, builds and tests. Formatting remains advisory during consolidation; compilation, tests and coverage reporting must
succeed. Source changes should always run this workflow, including after docs validation is added.

Coverage is on by default. ReportGenerator 5.5.10 merges MTP Cobertura files and writes `artifacts/coverage/Cobertura.xml` and `SummaryGithub.md`, appending the
latter to the job summary. It is installed temporarily outside the checkout; no tool manifest is created or changed. There is no coverage percentage gate.
Set `coverage: 'false'` to skip collection, tool installation and reporting.

Build inputs: `directory` (default `src`), `version` (optional), `test-filter` (optional), `coverage` (default `true`), `coverage-assembly-filters` (default
`+*`, ReportGenerator syntax) and `dotnet-version` (default `10.0.x`).

## Preparing a release

The standard workflow above handles this sequence. When composing actions directly, resolve the checked-out commit with `git rev-parse HEAD`; use that SHA and the same supplied version throughout.

1. Call `dotnet/build-and-pack` with `version` to build, test and prepare packages and symbols.
2. Prepare project assets, then validate and build the complete documentation.
3. Upload the validated artifacts.
4. Publish the prepared packages, create the matching release and deploy the exact validated site.

Use `docs/build` for the documentation validation gate and `docs/deploy` for the validated Pages artifact.

| Action           | Inputs                                                                                       | Behaviour                                                                                                                                                                            |
|------------------|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `dotnet/build-and-pack` | Required `version`; other build inputs plus package `output` | Builds and tests once, then calls pack with `--no-build --no-restore`. Output `directory` is the prepared package path. |
| `dotnet/pack`    | Required `version`; `directory` defaults to `src`; `output` defaults to `artifacts/packages` | Packs existing Release outputs with `--no-build --no-restore`; includes `.snupkg`; rejects nonempty output directories. Output `directory` is the absolute package path.             |
| `dotnet/publish` | Required `nuget-user`; `directory` defaults to `artifacts/packages`                          | Uses trusted publishing to push existing packages to nuget.org, including adjacent symbol packages. Uses `--skip-duplicate` for retries. Never compiles, packs or creates a release. |
| `release/create` | Required `version` and full `commit` SHA                                                     | Confirms the commit exists in the consumer repository, creates its tag and a release with generated notes. An existing lightweight or annotated tag must resolve to that commit.     |

Pack and publish use the SDK installed by the preceding build. Upload packages and validated documentation before publication, with 14-day artifact retention.

NuGet trusted publishing uses `NuGet/login@v1` immediately before the push and requires `nuget-user` plus `id-token: write` on that job. Configure the matching
trusted-publishing policy on nuget.org for each consumer workflow. There is no long-lived API-key input or `NUGET_API_TOKEN` fallback.

Release creation uses the calling job's GitHub token and needs `contents: write`. Keep those permissions on publishing jobs and never invoke publication for
untrusted pull requests. Documentation containers will not receive these credentials.

If documentation deployment fails after packages are published, run **Release** with **publish-packages** off and **publish-docs** on. It rebuilds and validates
updated documentation for the existing release without publishing another package or creating a tag.

## Local commands

Scripts run from the consumer repository root and use the same implementation as the actions. Replace `/path/to/build` with this repository's location:

```bash
VERSION=1.2.3 python3 /path/to/build/scripts/build.py build
VERSION=1.2.3 python3 /path/to/build/scripts/build.py pack
VERSION=1.2.3 python3 /path/to/build/scripts/build.py build-and-pack
```

`BUILD_DIRECTORY` defaults to `src` for build and pack. `PACKAGE_DIRECTORY` defaults to `artifacts/packages` for pack and publish. Build also accepts
`COVERAGE`, `COVERAGE_DIRECTORY` (default `artifacts/coverage`), `TEST_FILTER` and `COVERAGE_ASSEMBLY_FILTERS`. Relative directories are resolved from the
initial working directory. Omit `VERSION` for ordinary development builds.

The publishing action handles OIDC authentication; its push script consumes the short-lived `NUGET_API_KEY` output from `NuGet/login`, not a stored repository
secret. Local builds and packing need no publishing credentials.

`python3 scripts/build.py create-release` requires `VERSION`, `COMMIT` and an authenticated `gh`; `GH_REPO=owner/name` selects the repository outside GitHub Actions. These
scripts perform real publication when invoked.

## Maintaining this repository

The automation lives in `scripts/build.py` and uses Python 3.12+ with no runtime packages. Composite actions invoke it with the Python runner.
Local development uses `uv`, with Pytest and Ruff locked in `uv.lock`. CI checks Python formatting, linting, workflow syntax and tests. Pytest command doubles
exercise publication boundaries without credentials; integration tests use the real SDK and Docker images.

The workflow has two jobs. **Build and Test** runs all checks and image tests on pushes to every branch, pull requests and manual dispatches. **Publish** runs only
after that job succeeds on a push to `main`. It downloads and uploads the exact tested images without rebuilding or retesting them. Runs on `main` are serialised;
new pushes do not cancel an active publication. Manual workflow runs only build and test.

Locally, with uv installed:

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Use `uv run pytest --run-dotnet` for the real .NET 10 packaging tests. `uv run python scripts/build.py build-images` builds both Docker images and runs the
Docker documentation tests; `uv run pytest tests/test_docs.py --run-docker` reruns those tests against prepared images. Ordinary tests need no .NET SDK,
Docker or publishing credentials. Navigation unit tests also use Node, which is provided by GitHub’s runners. CI also runs actionlint. Dependabot maintains action references. ReportGenerator is pinned centrally in `scripts/build.py`.

## Documentation

`docs/build` generates APIs, runs Vale at error level, builds VitePress and validates local links, assets and HTML anchors. It returns the validated site's absolute
`directory` output. Run it after compiling Release assemblies and before publishing packages:

```yaml
- uses: MrKWatkins/build/docs/build@main
  with:
    version: '1.2.3'
```

Inputs are `config` (default `docs/site.json`), `version` (default `dev`), `source-ref` (default the checked-out commit), `api-directory` (default `.`), `output` (default `artifacts/docs`) and
`image` (default `ghcr.io/mrkwatkins/docs-dotnet:latest`). Output must be empty; upload it as an artifact before publication and retain it for deployment retries.
This action needs only `contents: read`, Docker and prepared assemblies. It passes no publishing credentials to the container.

Put handwritten pages in `docs/content` and configure the site in `docs/site.json`:

```json
{
  "schemaVersion": 1,
  "title": "Example",
  "description": "A strongly typed library.",
  "repository": "https://github.com/MrKWatkins/Example",
  "base": "/Example/",
  "guide": [{ "text": "Overview", "link": "/" }],
  "api": {
    "generator": "sesharp",
    "assemblies": ["src/Example/bin/Release/net10.0/Example.dll"]
  }
}
```

Paths are repository-root-relative. `contentDirectory` defaults to `docs/content`. Guide links are site-root-relative and omit the deployment base. The API section
uses `/api/`, showing namespaces, types and collapsible Constructors, Fields, Properties, Methods, Operators and Events sections. Empty sections and compiler-generated extension containers are omitted from the menu; real nested types remain visible. Multiple assemblies can share namespaces. Keep each assembly's XML documentation,
PDB and dependencies alongside it. The image supplies matching framework XML documentation for inherited summaries.

Optional `api.introductions` is an array of `{ "text": "Introduction", "link": "/api/introduction" }` entries pointing to handwritten pages under
`docs/content/api`. Generation uses temporary storage and refuses to overwrite handwritten pages. Static files live alongside Markdown; VitePress processes relative
asset links. API generation is optional: use `ghcr.io/mrkwatkins/docs-base:latest` for a guide without .NET.

Vale uses shared British spelling and technical-prose rules, including `strongly typed`. Add project terms through an optional `vocabularyDirectory` containing
`accept.txt` and `reject.txt`. Identifiers belong in inline code. Shared style packages and dictionaries are bundled; builds need no `vale sync` or npm install.

Local builds and previews need Docker, with no Node or .NET installation beyond preparing the assemblies:

```bash
python3 /path/to/build/scripts/build.py docs build --version 1.2.3 --source-ref "$(git rev-parse HEAD)"
python3 /path/to/build/scripts/build.py docs serve --source-ref "$(git rev-parse HEAD)"
```

The wrapper pulls the selected image and resolves it once to a digest for execution. Set `DOCS_IMAGE` to a version tag or digest to diagnose an older toolchain.
Outputs use your UID/GID. Preview listens at `http://localhost:5173/<base>/`; `DOCS_PORT` changes the host port. It uses a prepared copy: restart after source edits.
The header displays the supplied release version, or an explicit development label when omitted.

## Documentation publishing

The project action uploads `artifacts/docs` with `actions/upload-pages-artifact@v5`, then calls `docs/deploy` with the library `version` in the same job. That job needs `contents: read`, `pages: write`, `id-token: write`, the `github-pages` environment and a shared `github-pages` concurrency group with
`cancel-in-progress: false`. The Release workflow uses this group for both full releases and documentation updates. Set the consumer's Pages source to **GitHub Actions**.

`docs/deploy` checks the highest stable `vX.Y.Z` tag immediately before deployment and refuses a different version. Tags mark published library releases; the check
uses semantic version order and ignores prereleases. This also works for older repositories that published a package and tag without creating a GitHub release.

The Release workflow handles documentation updates with **publish-packages** off. Internally, `docs/release-source` resolves the existing release version and
API commit, and `docs/build-api` builds the API projects from that commit in a separate checkout. This keeps the site on the released API while handwritten pages
come from the selected branch. There is no separate documentation workflow.

The optional `api-ref` input to `docs/release-source` selects an explicit source override for XML comment corrections. It keeps the released version in the header and
reports both API and handwritten-documentation commits, prominently identifying overrides. Existing releases may have XML comments that fail a newly enabled Vale
rule: correct those comments and select the override explicitly until a release includes them. No style rules are bypassed for old API documentation.

## Documentation images

The Linux amd64 images contain Node 24, VitePress 1.6.4, Vue, Vale and shared styles. The .NET variant adds Sesharp 1.14.0, runtime 10.0.13 and framework XML,
with no SDK or WASM workload. npm dependencies are locked; Vite is overridden to a compatible patched release. Third-party licences remain in the image.

Build and test locally with Docker and the .NET 10 SDK:

```bash
uv run python scripts/build.py build-images
```

To view the example site, select **Preview documentation** in a JetBrains IDE's run configurations, or run `uv run python scripts/build.py preview-docs`.
It builds the local images and fixture assemblies, then serves `http://localhost:5173/example/`. Stop the run to remove the preview container.
Set `DOCS_PORT` to use another port. Restart the run after editing the fixtures.

Tests exercise both images, multiple API assemblies, generic/nested types, inherited framework prose, subpath links/assets, user-owned output and preview.
Deliberate prose, dead-link and anchor failures must return nonzero without producing a deployable site.

Successful pushes to `main` automatically publish both images with immutable `sha-<full commit SHA>` tags and update `latest`. Both images are built and tested
together without registry credentials. The .NET image records the exact base image ID; publication checks that identity, source commit and image version after loading
the tested Docker archive. The archive is retained for one day. Publication verifies public access before updating `latest`. The workflow uses `GITHUB_TOKEN` with
`packages: write` and logs digests and tool versions. Existing immutable tags are never replaced.

Build and test failures prevent the Publish job from running. Image publication happens only on pushes to `main`; there are no manual release, promotion or rollback
workflows. Registry maintenance can be performed directly in GHCR. Both GHCR packages must be public before `latest` is updated.

Image tags are independent of library versions. Update pinned tools here and merge to `main`; consumers following `latest` need no configuration change.

Original project code is licensed under **GPL-3.0-only**; see [LICENSE](LICENSE).
