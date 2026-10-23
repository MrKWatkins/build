# SPDX-License-Identifier: GPL-3.0-only
"""Real SDK proof that package preparation never rebuilds its inputs."""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import build

pytestmark = pytest.mark.dotnet
FIXTURE = Path(__file__).parent / "fixtures/library"


@pytest.fixture
def compiled_library(tmp_path, monkeypatch):
    directory = tmp_path / "source with spaces"
    shutil.copytree(FIXTURE, directory)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOTNET_CLI_HOME", str(tmp_path / "dotnet-home"))
    monkeypatch.setenv("DOTNET_NOLOGO", "1")
    monkeypatch.setenv("DOTNET_CLI_TELEMETRY_OPTOUT", "1")
    monkeypatch.setenv("BUILD_DIRECTORY", str(directory))
    monkeypatch.setenv("VERSION", "1.2.3")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    for args in [
        ("restore", directory, "--ignore-failed-sources"),
        ("build", directory, "--no-restore", "-c", "Release", "-p:Version=1.2.3"),
    ]:
        result = build.run("dotnet", *args, capture=True, check=False)
        assert result.returncode == 0, result.stdout
    return directory / "bin/Release/net10.0/BuildFixture.dll"


def test_real_pack_creates_packages_and_symbols_without_rebuilding(compiled_library, tmp_path):
    before = (hashlib.sha256(compiled_library.read_bytes()).digest(), compiled_library.stat().st_mtime_ns)
    build.pack()
    after = (hashlib.sha256(compiled_library.read_bytes()).digest(), compiled_library.stat().st_mtime_ns)
    assert after == before
    destination = tmp_path / "artifacts/packages"
    assert (destination / "BuildFixture.1.2.3.nupkg").stat().st_size > 0
    assert (destination / "BuildFixture.1.2.3.snupkg").stat().st_size > 0
    with pytest.raises(ValueError, match="must be empty"):
        build.pack()
    assert (hashlib.sha256(compiled_library.read_bytes()).digest(), compiled_library.stat().st_mtime_ns) == before


def test_real_pack_rejects_missing_binary_instead_of_rebuilding(compiled_library, monkeypatch, tmp_path):
    compiled_library.unlink()
    monkeypatch.setenv("PACKAGE_DIRECTORY", "missing-output")
    result = subprocess.run(
        [sys.executable, str(build.ROOT / "scripts/build.py"), "pack"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode != 0
    assert "NU5026" in result.stdout
    assert not compiled_library.exists()
    assert not list((tmp_path / "missing-output").glob("*.nupkg"))
