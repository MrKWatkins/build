# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the prepared documentation images without publishing anything."""

import json
import os
import shutil
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from scripts import build

pytestmark = pytest.mark.docker
SOURCE_REF = "0123456789012345678901234567890123456789"
FIXTURES = Path(__file__).parent / "fixtures"


def checked(*args):
    result = build.run(*args, capture=True, check=False)
    assert result.returncode == 0, result.stdout
    return result.stdout.strip()


def container_arguments(workspace):
    return [
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--mount",
        f"type=bind,source={workspace},target=/workspace",
        "--workdir",
        "/workspace",
    ]


@pytest.fixture(scope="module")
def image():
    return os.environ.get("DOCS_TEST_IMAGE", "docs-dotnet:local")


@pytest.fixture(scope="module")
def prepared_source(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("docs-built") / "source with spaces"
    shutil.copytree(FIXTURES / "docs", workspace)
    for project in ("Example", "Support"):
        checked("dotnet", "build", workspace / "src" / project, "-c", "Release", "--nologo")
    return workspace


@pytest.fixture
def workspace(tmp_path, prepared_source):
    destination = tmp_path / "source with spaces"
    shutil.copytree(prepared_source, destination)
    return destination


def build_site(workspace, image, *arguments, check=True):
    result = build.run(
        "docker",
        "run",
        "--rm",
        *container_arguments(workspace),
        image,
        "build",
        "--version",
        "1.2.3",
        "--source-ref",
        SOURCE_REF,
        *arguments,
        capture=True,
        check=False,
    )
    if check:
        assert result.returncode == 0, result.stdout
    return result


def test_base_image_builds_guide_without_dotnet(tmp_path):
    workspace = tmp_path / "base"
    shutil.copytree(FIXTURES / "docs-base", workspace)
    image = os.environ.get("DOCS_BASE_TEST_IMAGE", "docs-base:local")
    checked("docker", "run", "--rm", *container_arguments(workspace), image, "build")
    assert (workspace / "artifacts/docs/index.html").is_file()
    checked(
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "node",
        image,
        "-e",
        "const fs = require('node:fs'); const assert = require('node:assert/strict'); "
        "for (const path of ['/usr/share/dotnet', '/usr/local/bin/dotnet', '/usr/local/bin/sesharp']) "
        "assert.equal(fs.existsSync(path), false, path);",
    )


def test_site_contains_versioned_api_source_links_and_nested_types(workspace, image):
    introduction = workspace / "docs/content/api/introduction.md"
    original = introduction.read_bytes()
    build_site(workspace, image)
    index = workspace / "artifacts/docs/index.html"
    assert index.stat().st_uid == os.getuid()
    assert "Example v1.2.3" in index.read_text()
    api = workspace / "artifacts/docs/api/Example"
    assert "Parses a string into a value" in (api / "Value-T/Parse.html").read_text()
    assert SOURCE_REF in (api / "Value-T/Read.html").read_text()
    assert (api / "Helper/index.html").is_file()
    assert (api / "Value-T/Nested-T/index.html").is_file()
    assert introduction.read_bytes() == original


def test_site_uses_api_assemblies_from_separate_checkout(workspace, image):
    released = workspace / "released"
    released.mkdir()
    (workspace / "src").rename(released / "src")
    build_site(workspace, image, "--api-directory", "released", "--output", "artifacts/released")
    assert (
        "Parses a string into a value" in (workspace / "artifacts/released/api/Example/Value-T/Parse.html").read_text()
    )
    assert not (workspace / "src").exists()


def test_public_assets_include_embedded_app_and_runtime(workspace, image):
    public = workspace / "artifacts/public assets"
    app = public / "converter"
    app.mkdir(parents=True)
    (app / "index.html").write_text(
        '<!doctype html><html><body><h1 id="app">Converter</h1><script src="app.js"></script><a href="engine.wasm">Runtime</a></body></html>'
    )
    (app / "app.js").write_text("document.title = 'Converter';\n")
    (app / "engine.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
    config = workspace / "docs/site.json"
    settings = json.loads(config.read_text())
    settings["publicDirectory"] = "artifacts/public assets"
    config.write_text(json.dumps(settings))
    page = workspace / "docs/content/index.md"
    page.write_text(page.read_text() + '\n<iframe src="./converter/index.html" title="Converter"></iframe>\n')
    build_site(workspace, image)
    output = workspace / "artifacts/docs"
    assert 'src="./converter/index.html"' in (output / "index.html").read_text()
    for name in ("index.html", "app.js", "engine.wasm"):
        assert (output / "converter" / name).read_bytes() == (app / name).read_bytes()


@pytest.mark.parametrize("escape", ["absolute", "parent", "symlink"])
def test_public_assets_reject_path_escapes(workspace, image, escape):
    assets = workspace / "assets"
    assets.mkdir()
    (assets / "escape").symlink_to(workspace / "src", target_is_directory=True)
    config = workspace / "docs/site.json"
    settings = json.loads(config.read_text())
    settings["publicDirectory"] = {"absolute": "/etc", "parent": "..", "symlink": "assets"}[escape]
    config.write_text(json.dumps(settings))
    result = build_site(workspace, image, check=False)
    assert result.returncode != 0
    expected = {
        "absolute": "repository-root-relative",
        "parent": "must remain inside",
        "symlink": "Symbolic links are not supported",
    }[escape]
    assert expected in result.stdout
    assert not (workspace / "artifacts/docs/index.html").exists()


def test_dotnet_image_has_runtime_without_sdk_or_package_cache(image):
    assert checked("docker", "run", "--rm", "--entrypoint", "dotnet", image, "--list-sdks") == ""
    checked(
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "node",
        image,
        "-e",
        "const fs = require('node:fs'); const assert = require('node:assert/strict'); "
        "const cp = require('node:child_process'); "
        "for (const path of ['/usr/share/dotnet/sdk', '/root/.nuget/packages']) "
        "assert.equal(fs.existsSync(path), false, path); "
        "const packs = '/usr/share/dotnet/packs/Microsoft.NETCore.App.Ref'; "
        "assert(fs.readdirSync(packs).some(version => fs.existsSync(packs + '/' + version + '/ref/net10.0/System.Runtime.xml'))); "
        "const runtimes = cp.execFileSync('dotnet', ['--list-runtimes'], {encoding: 'utf8'}); "
        "const runtime = runtimes.match(/^Microsoft.NETCore.App (\\S+)/m); "
        "assert(runtime); "
        "assert(fs.readFileSync('/opt/docs/versions.txt', 'utf8').includes('.NET runtime ' + runtime[1] + '\\n'));",
    )


def test_repeated_navigation_fits_bounded_heap(image):
    script = """
        import { mkdtemp, writeFile, rm } from 'node:fs/promises';
        import { validateLinks } from '/opt/docs/tooling/links.mjs';
        const directory = await mkdtemp('/tmp/repeated-navigation-');
        try {
          await writeFile(directory + '/target.html', '<h1 id="found">Target</h1>');
          const links = Array.from({length: 500}, (_, i) =>
            '<a href="target.html?padding=' + 'x'.repeat(1400) + i + '#found">Link</a>').join('');
          for (let i = 0; i < 40; i++) {
            await writeFile(directory + '/' + i + '.html', '<nav>' + links + '</nav>');
          }
          await validateLinks(directory, '/example/');
        } finally {
          await rm(directory, {recursive: true, force: true});
        }
    """
    output = checked(
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "node",
        image,
        "--max-old-space-size=128",
        "--input-type=module",
        "-e",
        script,
    )
    assert "Validated local links, assets and anchors in 41 HTML pages." in output


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        ("british-spelling", "Shared.BritishSpelling"),
        ("api-prose", "Shared.StronglyTyped"),
        ("dead-link", "dead link"),
        ("missing-anchor", "missing anchor"),
    ],
)
def test_invalid_documentation_does_not_produce_site(workspace, image, mutation, diagnostic):
    usage = workspace / "docs/content/usage.md"
    if mutation == "api-prose":
        xml = workspace / "src/Example/bin/Release/net10.0/Example.xml"
        original = xml.read_text()
        assert "A strongly typed value" in original
        xml.write_text(original.replace("A strongly typed value", "A strongly-typed value"))
    else:
        addition = {
            "british-spelling": "\nThe color is blue.\n",
            "dead-link": "\n[Broken](./missing.md)\n",
            "missing-anchor": "\n[Reading](./usage.md#missing)\n",
        }[mutation]
        usage.write_text(usage.read_text() + addition)
    result = build_site(workspace, image, "--output", "artifacts/failed", check=False)
    assert result.returncode != 0, result.stdout
    assert diagnostic in result.stdout
    assert not (workspace / "artifacts/failed/index.html").exists()


def test_preview_serves_vite_client_and_development_title(workspace, image):
    container = checked(
        "docker",
        "run",
        "-d",
        *container_arguments(workspace),
        "-p",
        "127.0.0.1::5173",
        image,
        "serve",
        "--source-ref",
        SOURCE_REF,
    )
    try:
        address = checked("docker", "port", container, "5173/tcp")
        base = f"http://{address}/example/"
        deadline = time.monotonic() + 30
        while True:
            try:
                with urlopen(base, timeout=2) as response:
                    html = response.read().decode()
                break
            except (URLError, TimeoutError, ConnectionError):
                if time.monotonic() >= deadline:
                    pytest.fail(build.run("docker", "logs", container, capture=True, check=False).stdout)
                time.sleep(1)
        assert "/example/@vite/client" in html
        with urlopen(base + "@siteData", timeout=5) as response:
            assert "Example (development)" in response.read().decode()
    finally:
        build.run("docker", "rm", "-f", container, capture=True, check=False)
