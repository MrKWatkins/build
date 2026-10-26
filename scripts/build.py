#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Shared build automation. Runtime dependencies: Python's standard library only."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
SHA_PATTERN = r"[0-9a-f]{40}"


def run(*args, capture=False, check=True, cwd=None, env=None):
    return subprocess.run(
        [str(arg) for arg in args],
        check=check,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def output(*args, **kwargs):
    return run(*args, capture=True, **kwargs).stdout.strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def version(value=None):
    value = os.environ.get("VERSION", "") if value is None else value
    require(
        re.fullmatch(VERSION_PATTERN, value), "VERSION must be a stable version such as 1.2.3 (without a v prefix)."
    )
    return value


def commit(value):
    require(re.fullmatch(SHA_PATTERN, value), "COMMIT must be a full, resolved commit SHA.")
    return value


def emit(**values):
    if target := os.environ.get("GITHUB_OUTPUT"):
        with open(target, "a") as file:
            file.writelines(f"{key}={value}\n" for key, value in values.items())


def summary(text):
    if target := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(target, "a") as file:
            file.write(text + "\n")


def boolean(name, default=True):
    value = os.environ.get(name, str(default).lower())
    require(value in ("true", "false"), f"{name} must be true or false.")
    return value == "true"


def prepare():
    if name := os.environ.get("PREPARE_SCRIPT"):
        root = Path.cwd().resolve()
        script = Path(name).resolve(strict=True)
        require(
            not Path(name).is_absolute()
            and script.is_relative_to(root)
            and script.is_file()
            and script.suffix == ".py",
            "PREPARE_SCRIPT must be a repository-relative Python file.",
        )
        run(sys.executable, script, cwd=root)


def build():
    directory = Path(os.environ.get("BUILD_DIRECTORY", "src")).resolve(strict=True)
    coverage = boolean("COVERAGE")
    test_report = boolean("TEST_REPORT")
    version_args = [f"-p:Version={version()}"] if os.environ.get("VERSION") else []
    prepare()
    run("dotnet", "--version", cwd=directory)
    run("dotnet", "restore", *version_args, cwd=directory)
    if run("dotnet", "format", "--no-restore", "--verify-no-changes", cwd=directory, check=False).returncode:
        print("Warning: format verification failed; continuing as configured.", file=sys.stderr)
    run(
        "dotnet",
        "build",
        "--no-restore",
        "--configuration",
        "Release",
        "-p:CopyLocalLockFileAssemblies=true",
        *version_args,
        cwd=directory,
    )
    test_args = ["--no-restore", "--no-build", "--configuration", "Release"]
    if expression := os.environ.get("TEST_FILTER"):
        test_args += ["--filter", expression]
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        if coverage:
            test_args += [
                "--coverage",
                "--coverage-output-format",
                "cobertura",
            ]
        if test_report:
            test_args += ["--report-trx"]
        if coverage or test_report:
            test_args += ["--results-directory", str(temporary / "results")]
        test = run("dotnet", "test", *test_args, cwd=directory, check=False)
        try:
            report_args = []
            destination = Path(os.environ.get("TEST_RESULTS_DIRECTORY", "artifacts/test-results")).resolve()
            if test_report:
                report_args += ["--tests", str(temporary / "results/**/*.trx"), "--test-directory", destination]
            if coverage:
                report_args += [
                    "--coverage",
                    str(temporary / "results/**/*.cobertura.xml"),
                    "--coverage-directory",
                    Path(os.environ.get("COVERAGE_DIRECTORY", "artifacts/coverage")).resolve(),
                    "--assembly-filters=" + os.environ.get("COVERAGE_ASSEMBLY_FILTERS", "+*"),
                    "--file-filters=" + os.environ.get("COVERAGE_FILE_FILTERS", "+*"),
                ]
            if report_args:
                run(sys.executable, ROOT / "scripts/reports.py", *report_args)
        finally:
            try:
                if (temporary / "results").is_dir():
                    raw = destination / "raw" / temporary.name
                    shutil.copytree(temporary / "results", raw)
                    print(f"Raw test and coverage results: {raw}")
            finally:
                # Preserve the original test failure even when reporting or copying also fails.
                test.check_returncode()


def pack():
    release_version = version()
    directory = Path(os.environ.get("BUILD_DIRECTORY", "src")).resolve(strict=True)
    destination = Path(os.environ.get("PACKAGE_DIRECTORY", "artifacts/packages")).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    require(
        not any(destination.iterdir()),
        "Package output directory must be empty; use a fresh directory for each release.",
    )
    run(
        "dotnet",
        "pack",
        "--no-build",
        "--no-restore",
        "--configuration",
        "Release",
        f"-p:Version={release_version}",
        "-p:SymbolPackageFormat=snupkg",
        "--include-symbols",
        "--output",
        destination,
        cwd=directory,
    )
    require(any(destination.glob("*.nupkg")), "Pack produced no NuGet packages.")
    emit(directory=destination)


def build_and_pack():
    version()
    build()
    pack()


def publish():
    key = os.environ.get("NUGET_API_KEY", "")
    require(key, "A short-lived credential from NuGet trusted publishing is required.")
    directory = Path(os.environ.get("PACKAGE_DIRECTORY", "artifacts/packages")).resolve(strict=True)
    packages = sorted(directory.glob("*.nupkg"))
    require(packages, "No prepared .nupkg files found; nothing was published.")
    for package in packages:
        # NuGet also pushes the adjacent .snupkg when present.
        run(
            "dotnet",
            "nuget",
            "push",
            package,
            "--source",
            "https://api.nuget.org/v3/index.json",
            "--api-key",
            key,
            "--skip-duplicate",
        )


def repository():
    value = (
        os.environ.get("GH_REPO")
        or os.environ.get("GITHUB_REPOSITORY")
        or output("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    )
    require(re.fullmatch(r"[\w.-]+/[\w.-]+", value, flags=re.ASCII), "Invalid GitHub repository; use owner/name.")
    return value


def latest_release(repo):
    tags = output("gh", "api", "--paginate", f"repos/{repo}/tags?per_page=100", "--jq", ".[].name").splitlines()
    versions = [tuple(map(int, match.groups())) for tag in tags if (match := re.fullmatch("v" + VERSION_PATTERN, tag))]
    require(versions, "No stable vX.Y.Z release tag was found; supply an explicit version for the first release.")
    return "v" + ".".join(map(str, max(versions)))


def release_version():
    if supplied := os.environ.get("VERSION"):
        resolved = version(supplied)
    else:
        major, minor, _ = map(int, latest_release(repository())[1:].split("."))
        resolved = f"{major}.{minor + 1}.0"
    print(f"Release version: {resolved}")
    summary(f"Release version: **{resolved}**")
    emit(version=resolved)


def validate_release():
    return version(), commit(os.environ.get("COMMIT", ""))


def create_release():
    release_version, sha = validate_release()
    tag = "v" + release_version
    repo = repository()
    require(
        output("gh", "api", f"repos/{repo}/commits/{sha}", "--jq", ".sha") == sha,
        "GitHub did not resolve the expected commit.",
    )
    existing = output(
        "gh",
        "api",
        f"repos/{repo}/git/matching-refs/tags/{tag}",
        "--jq",
        f'.[] | select(.ref == "refs/tags/{tag}") | [.object.type, .object.sha] | @tsv',
    )
    if existing:
        kind, target = existing.split()
        while kind == "tag":
            kind, target = output(
                "gh", "api", f"repos/{repo}/git/tags/{target}", "--jq", "[.object.type, .object.sha] | @tsv"
            ).split()
        require(
            kind == "commit" and target == sha, f"Tag {tag} already targets a different commit; refusing to move it."
        )
    else:
        run("gh", "api", "--method", "POST", f"repos/{repo}/git/refs", "-f", f"ref=refs/tags/{tag}", "-f", f"sha={sha}")
    run("gh", "release", "create", tag, "--repo", repo, "--verify-tag", "--target", sha, "--generate-notes")


def release_source():
    repo = repository()
    tag = latest_release(repo)
    ref = os.environ.get("API_REF") or tag
    sha = commit(output("gh", "api", f"repos/{repo}/commits/{quote(ref, safe='')}", "--jq", ".sha"))
    message = f"Released library: {tag}\n\nAPI source commit: {sha}\n\nDocumentation source commit: {output('git', 'rev-parse', 'HEAD')}"
    if os.environ.get("API_REF"):
        message += "\n\n**API source override is active; this may differ from the published package.**"
    print(message)
    summary(message)
    emit(version=tag[1:], commit=sha)


def freshness():
    expected = "v" + version()
    latest = latest_release(repository())
    require(expected == latest, f"Refusing to deploy {expected}: the latest release is {latest}.")
    print(f"Deploying documentation for the latest release: {latest}")


def build_api():
    release_version = version()
    root = Path.cwd().resolve()
    config = Path(os.environ.get("DOCS_CONFIG", "docs/site.json")).resolve(strict=True)
    api_root = Path(os.environ.get("API_DIRECTORY", "artifacts/api-source")).resolve(strict=True)
    require(
        config.is_relative_to(root) and api_root.is_relative_to(root) and api_root != root,
        "Config and API checkout must remain inside the documentation repository.",
    )
    settings = json.loads(config.read_text())
    api = settings.get("api", {})
    require(
        settings.get("schemaVersion") == 1
        and isinstance(api, dict)
        and api.get("generator") == "sesharp"
        and isinstance(api.get("assemblies"), list)
        and api["assemblies"],
        "Expected a schemaVersion 1 site with sesharp API assemblies.",
    )
    projects = set()
    for assembly in api["assemblies"]:
        require(
            isinstance(assembly, str) and "/bin/Release/" in assembly,
            "API assembly must use <project>/bin/Release/<framework>.",
        )
        directory = (api_root / assembly.split("/bin/Release/")[0]).resolve(strict=True)
        require(directory.is_relative_to(api_root), "API project escapes its source checkout.")
        candidates = list(directory.glob("*.csproj"))
        require(len(candidates) == 1, f"Expected one .csproj in {directory}.")
        project = candidates[0].resolve(strict=True)
        require(project.is_relative_to(api_root), "API project escapes its source checkout.")
        projects.add(project)
    for project in sorted(projects):
        # Historical build dependencies must not block rebuilding released documentation.
        run(
            "dotnet",
            "build",
            project,
            "--configuration",
            "Release",
            f"-p:Version={release_version}",
            "-p:CopyLocalLockFileAssemblies=true",
            "-p:NuGetAudit=false",
        )


def docs(arguments):
    require(arguments and arguments[0] in ("build", "serve"), "Expected docs build|serve [docs options].")
    arguments = list(arguments)
    defaults = {
        "--config": os.environ.get("CONFIG", "docs/site.json"),
        "--version": os.environ.get("VERSION", "dev"),
        "--source-ref": os.environ.get("SOURCE_REF") or output("git", "rev-parse", "HEAD"),
        "--api-directory": os.environ.get("API_DIRECTORY", "."),
        "--output": os.environ.get("OUTPUT", "artifacts/docs"),
    }
    for flag, value in defaults.items():
        if flag not in arguments:
            arguments += [flag, value]
    image = os.environ.get("DOCS_IMAGE", "ghcr.io/mrkwatkins/docs-dotnet:latest")
    run("docker", "pull", image)
    resolved = output("docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image)
    require(resolved, f"Cannot resolve image digest: {image}")
    print(f"Documentation image: {resolved}")
    args = [
        "--rm",
        "--init",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--mount",
        f"type=bind,source={Path.cwd()},target=/workspace",
        "--workdir",
        "/workspace",
    ]
    if arguments[0] == "serve":
        port = os.environ.get("DOCS_PORT", "5173")
        require(port.isdecimal() and 1 <= int(port) <= 65535, "DOCS_PORT must be between 1 and 65535.")
        args += ["-p", f"127.0.0.1:{port}:5173"]
    run("docker", "run", *args, resolved, *arguments)
    if arguments[0] == "build":
        emit(directory=Path(arguments[arguments.index("--output") + 1]).resolve())


def image_context():
    sha = output("git", "rev-parse", "HEAD", cwd=ROOT)
    image_version = os.environ.get("IMAGE_VERSION", f"sha-{sha}")
    require(image_version == f"sha-{sha}", "The image tag must be sha- followed by the checked-out source commit.")
    return sha, image_version


def inspect(image, expression):
    return output("docker", "image", "inspect", "--format", expression, image)


def verify_images(sha, image_version):
    base_id = inspect("docs-base:local", "{{.Id}}")
    require(
        inspect("docs-dotnet:local", '{{index .Config.Labels "io.mrkwatkins.build.base-image-id"}}') == base_id,
        "The .NET image must derive from this exact base image.",
    )
    for image in ("docs-base:local", "docs-dotnet:local"):
        require(
            inspect(image, '{{index .Config.Labels "org.opencontainers.image.revision"}}') == sha,
            f"Select the source commit that built {image}.",
        )
        require(
            inspect(image, '{{index .Config.Labels "org.opencontainers.image.version"}}') == image_version,
            f"The image version must match {image_version}: {image}",
        )


def build_images():
    sha, image_version = image_context()
    labels = [
        "--label",
        f"org.opencontainers.image.revision={sha}",
        "--label",
        f"org.opencontainers.image.version={image_version}",
    ]
    run("docker", "build", "-f", "images/docs-base/Dockerfile", *labels, "-t", "docs-base:local", ".", cwd=ROOT)
    base_id = inspect("docs-base:local", "{{.Id}}")
    run(
        "docker",
        "build",
        "-f",
        "images/docs-dotnet/Dockerfile",
        "--build-arg",
        "BASE_IMAGE=docs-base:local",
        *labels,
        "--label",
        f"io.mrkwatkins.build.base-image-id={base_id}",
        "-t",
        "docs-dotnet:local",
        ".",
        cwd=ROOT,
    )
    verify_images(sha, image_version)
    run(
        sys.executable,
        "-m",
        "pytest",
        "tests/test_docs.py",
        "--run-docker",
        cwd=ROOT,
        env={**os.environ, "DOCS_BASE_TEST_IMAGE": "docs-base:local", "DOCS_TEST_IMAGE": "docs-dotnet:local"},
    )


def publish_images():
    sha, image_version = image_context()
    registry = "ghcr.io/mrkwatkins"
    names = ("docs-base", "docs-dotnet")
    verify_images(sha, image_version)
    for name in names:
        image = f"{registry}/{name}:{image_version}"
        require(
            run("docker", "manifest", "inspect", image, check=False, capture=True).returncode,
            f"Immutable tag already exists: {image}",
        )
        tags = run(
            "gh",
            "api",
            "--paginate",
            f"/users/MrKWatkins/packages/container/{name}/versions?per_page=100",
            "--jq",
            ".[].metadata.container.tags[]",
            capture=True,
            check=False,
        )
        if tags.returncode:
            require("(HTTP 404)" in tags.stdout, f"Cannot establish whether {image} exists: {tags.stdout}")
        else:
            require(image_version not in tags.stdout.splitlines(), f"Immutable tag already exists: {image}")
    for name in names:
        image = f"{registry}/{name}:{image_version}"
        run("docker", "tag", f"{name}:local", image)
        run("docker", "push", image)
    with tempfile.TemporaryDirectory() as anonymous:
        for name in names:
            image = f"{registry}/{name}:{image_version}"
            require(
                not run(
                    "docker", "--config", anonymous, "manifest", "inspect", image, capture=True, check=False
                ).returncode,
                f"Make the GHCR package public in Package settings: {image}",
            )
    for name in names:
        image = f"{registry}/{name}:{image_version}"
        run("docker", "tag", image, f"{registry}/{name}:latest")
        run("docker", "push", f"{registry}/{name}:latest")
    for name in names:
        image = f"{registry}/{name}:{image_version}"
        print(inspect(image, "{{index .RepoDigests 0}}"))
        run("docker", "run", "--rm", "--entrypoint", "cat", image, "/opt/docs/versions.txt")


def preview_docs():
    run("docker", "build", "-f", "images/docs-base/Dockerfile", "-t", "docs-base:local", ".", cwd=ROOT)
    run("docker", "build", "-f", "images/docs-dotnet/Dockerfile", "-t", "docs-dotnet:local", ".", cwd=ROOT)
    workspace = ROOT / "artifacts/docs-preview"
    shutil.copytree(ROOT / "tests/fixtures/docs", workspace, dirs_exist_ok=True)
    for project in ("Example", "Support"):
        run("dotnet", "build", workspace / "src" / project, "-c", "Release", "--nologo")
    name = f"build-docs-preview-{os.getpid()}"
    port = os.environ.get("DOCS_PORT", "5173")
    require(port.isdecimal() and 1 <= int(port) <= 65535, "DOCS_PORT must be between 1 and 65535.")
    print(f"Documentation preview: http://localhost:{port}/example/")
    try:
        run(
            "docker",
            "run",
            "--rm",
            "--init",
            "--name",
            name,
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--mount",
            f"type=bind,source={workspace},target=/workspace",
            "--workdir",
            "/workspace",
            "-p",
            f"127.0.0.1:{port}:5173",
            "docs-dotnet:local",
            "serve",
            "--source-ref",
            "0123456789012345678901234567890123456789",
        )
    finally:
        run("docker", "rm", "-f", name, capture=True, check=False)


def main():
    commands = {
        "build": build,
        "prepare": prepare,
        "pack": pack,
        "build-and-pack": build_and_pack,
        "publish": publish,
        "create-release": create_release,
        "release-version": release_version,
        "release-source": release_source,
        "freshness": freshness,
        "build-api": build_api,
        "build-images": build_images,
        "publish-images": publish_images,
        "preview-docs": preview_docs,
        "docs": docs,
    }
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=commands)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.command == "docs":
            docs(args.arguments)
        else:
            require(not args.arguments, "Unexpected arguments; build options are environment variables.")
            commands[args.command]()
    except subprocess.CalledProcessError as error:
        # Don't print commands: NuGet pushes contain a short-lived credential.
        print(f"Command failed with exit code {error.returncode}.", file=sys.stderr)
        return error.returncode
    except (ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
