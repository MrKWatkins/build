# SPDX-License-Identifier: GPL-3.0-only
import subprocess

import pytest
import yaml

from scripts import build


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NUGET_PACKAGES", raising=False)
    subprocess.run(["git", "init", "--quiet"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/Library.csproj").write_text("<Project />\n")
    subprocess.run(["git", "add", "src/Library.csproj"], check=True)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner temp"))
    monkeypatch.setenv("RUNNER_OS", "Linux")
    monkeypatch.setenv("RUNNER_ARCH", "X64")
    monkeypatch.setenv("CACHE_SDK_VERSION", "10.0.403")
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "environment"))
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    return tmp_path


def settings(checkout):
    build.nuget_cache()
    return dict(line.split("=", 1) for line in (checkout / "outputs").read_text().splitlines())


def test_cache_uses_an_isolated_packages_folder_and_compatible_fallback(checkout, monkeypatch):
    first = settings(checkout)
    assert first["directory"] == str(checkout / "runner temp/nuget-packages")
    assert (checkout / "environment").read_text() == f"NUGET_PACKAGES={first['directory']}\n"
    assert first["prefix"] == "nuget-v1-Linux-X64-"
    assert first["key"].startswith(first["prefix"])
    monkeypatch.setenv("RUNNER_ARCH", "ARM64")
    assert settings(checkout)["prefix"] != first["prefix"]
    monkeypatch.setenv("RUNNER_OS", "Windows")
    assert settings(checkout)["prefix"] == "nuget-v1-Windows-ARM64-"


@pytest.mark.parametrize(
    "name",
    [
        "src/Library.csproj",
        "src/Library.fsproj",
        "src/Library.vbproj",
        "Directory.Packages.props",
        "src/Directory.Build.props",
        "src/Directory.Build.targets",
        "NuGet.Config",
        "nuget.config",
        "global.json",
        "src/packages.lock.json",
    ],
)
def test_dependency_changes_invalidate_the_cache_but_preserve_fallback(checkout, name):
    file = checkout / name
    file.write_text("original\n")
    subprocess.run(["git", "add", name], check=True)
    first = settings(checkout)
    file.write_text("updated\n")
    second = settings(checkout)
    assert second["key"] != first["key"]
    assert second["prefix"] == first["prefix"]


def test_source_changes_and_untracked_build_artifacts_do_not_invalidate_cache(checkout):
    (checkout / "src/Library.cs").write_text("original\n")
    subprocess.run(["git", "add", "src/Library.cs"], check=True)
    first = settings(checkout)
    (checkout / "src/Library.cs").write_text("updated\n")
    (checkout / "artifacts/api-source").mkdir(parents=True)
    (checkout / "artifacts/api-source/Old.csproj").write_text("<Project />")
    assert settings(checkout)["key"] == first["key"]


def test_cache_honours_an_existing_packages_directory(checkout, monkeypatch):
    monkeypatch.setenv("NUGET_PACKAGES", str(checkout / "custom packages"))
    assert settings(checkout)["directory"] == str(checkout / "custom packages")


def test_sdk_changes_refresh_the_cache_with_compatible_fallback(checkout, monkeypatch):
    first = settings(checkout)
    monkeypatch.setenv("CACHE_SDK_VERSION", "10.0.404")
    second = settings(checkout)
    assert second["key"] != first["key"]
    assert second["prefix"] == first["prefix"]


def test_docs_only_cache_hashes_the_selected_checkout(checkout, monkeypatch):
    first = settings(checkout)
    released = checkout / "artifacts/api-source"
    released.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(released)], check=True)
    (released / "Library.csproj").write_text("released dependencies\n")
    subprocess.run(["git", "-C", str(released), "add", "Library.csproj"], check=True)
    monkeypatch.setenv("CACHE_SOURCE_DIRECTORY", str(released))
    second = settings(checkout)
    assert second["key"] != first["key"]
    (checkout / "src/Library.csproj").write_text("current dependencies changed\n")
    assert settings(checkout)["key"] == second["key"]


def test_shared_build_paths_enable_caching():
    for action in ["dotnet/build", "dotnet/build-and-pack", "dotnet/project"]:
        configuration = yaml.safe_load((build.ROOT / action / "action.yml").read_text())
        step = next(s for s in configuration["runs"]["steps"] if s.get("uses") == "MrKWatkins/build/dotnet/setup@main")
        assert step["with"]["dotnet-version"] == "${{ inputs.dotnet-version }}"
        if action == "dotnet/project":
            assert step["with"]["directory"] == "artifacts/api-source"
    configuration = yaml.safe_load((build.ROOT / "dotnet/setup/action.yml").read_text())
    cache = next(s for s in configuration["runs"]["steps"] if s.get("uses") == "actions/cache@v6")
    assert cache["with"]["key"] == "${{ steps.cache.outputs.key }}"
    assert cache["with"]["restore-keys"] == "${{ steps.cache.outputs.prefix }}"
