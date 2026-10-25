# SPDX-License-Identifier: GPL-3.0-only
import json
import subprocess

import pytest

from scripts import build


@pytest.fixture
def api(tmp_path, monkeypatch):
    root = tmp_path / "source with spaces"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("VERSION", "1.7.0")
    source = root / "artifacts/api-source"
    for name in ("One", "Two"):
        project = source / "src" / name
        project.mkdir(parents=True)
        (project / f"{name}.csproj").touch()
    (root / "docs").mkdir()
    return root


def configure(api, assemblies):
    (api / "docs/site.json").write_text(
        json.dumps({"schemaVersion": 1, "api": {"generator": "sesharp", "assemblies": assemblies}})
    )


def test_api_builds_each_project_once_with_released_version(api, runner):
    configure(
        api,
        [
            "src/One/bin/Release/net10.0/One.dll",
            "src/One/bin/Release/net10.0/Extra.dll",
            "src/Two/bin/Release/net10.0/Two.dll",
        ],
    )
    build.build_api()
    assert [args for args, _ in runner.calls] == [
        (
            "dotnet",
            "build",
            str(api / f"artifacts/api-source/src/{name}/{name}.csproj"),
            "--configuration",
            "Release",
            "-p:Version=1.7.0",
            "-p:CopyLocalLockFileAssemblies=true",
            "-p:NuGetAudit=false",
        )
        for name in ("One", "Two")
    ]


@pytest.mark.parametrize(
    "path,diagnostic",
    [("src/Two/bin/Debug/net10.0/Two.dll", "bin/Release"), ("../outside/bin/Release/net10.0/Other.dll", "escapes")],
)
def test_invalid_api_paths_stop_before_building_any_project(api, runner, path, diagnostic):
    (api / "artifacts/outside").mkdir()
    configure(api, ["src/One/bin/Release/net10.0/One.dll", path])
    with pytest.raises(ValueError, match=diagnostic):
        build.build_api()
    assert not runner.calls


def test_api_rejects_symlink_outside_checkout(api, runner):
    outside = api / "artifacts/outside"
    outside.mkdir()
    (outside / "Other.csproj").touch()
    (api / "artifacts/api-source/src/Outside").symlink_to(outside)
    configure(api, ["src/Outside/bin/Release/net10.0/Other.dll"])
    with pytest.raises(ValueError, match="escapes"):
        build.build_api()
    assert not runner.calls


@pytest.mark.parametrize(
    "invalid", ["{invalid json", '{"schemaVersion":1,"api":{"generator":"sesharp","assemblies":[]}}']
)
def test_api_rejects_invalid_configuration(api, runner, invalid):
    (api / "docs/site.json").write_text(invalid)
    with pytest.raises(ValueError):
        build.build_api()
    assert not runner.calls


def test_api_stops_after_compilation_failure(api, runner):
    configure(api, ["src/One/bin/Release/net10.0/One.dll", "src/Two/bin/Release/net10.0/Two.dll"])
    runner.handler = lambda args, kwargs: (7, "")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        build.build_api()
    assert failure.value.returncode == 7
    assert len(runner.calls) == 1


def test_api_requires_one_project_per_directory(api, runner):
    (api / "artifacts/api-source/src/One/Extra.csproj").touch()
    configure(api, ["src/One/bin/Release/net10.0/One.dll"])
    with pytest.raises(ValueError, match="one .csproj"):
        build.build_api()
    assert not runner.calls
