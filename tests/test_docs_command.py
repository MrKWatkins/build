# SPDX-License-Identifier: GPL-3.0-only
import os
from pathlib import Path

import pytest

from scripts import build


@pytest.fixture
def docs_command(tmp_path, monkeypatch, runner):
    monkeypatch.chdir(tmp_path)

    def handle(args, kwargs):
        if args[:2] == ("git", "rev-parse"):
            return 0, "1" * 40
        if args[:3] == ("docker", "image", "inspect"):
            return 0, "ghcr.io/mrkwatkins/docs-dotnet@sha256:" + "2" * 64
        return 0, ""

    runner.handler = handle
    return tmp_path


def test_docs_pulls_once_and_runs_resolved_digest(docs_command, monkeypatch, runner):
    monkeypatch.setenv("GITHUB_OUTPUT", str(docs_command / "output"))
    monkeypatch.setenv("VERSION", "1.2.3")
    build.docs(["build", "--output", "artifacts/custom"])
    assert runner.commands("docker", "pull") == [("docker", "pull", "ghcr.io/mrkwatkins/docs-dotnet:latest")]
    command = runner.commands("docker", "run")[0]
    assert "ghcr.io/mrkwatkins/docs-dotnet@sha256:" + "2" * 64 in command
    assert f"{os.getuid()}:{os.getgid()}" in command
    assert f"type=bind,source={Path.cwd()},target=/workspace" in command
    assert command[command.index("--version") + 1] == "1.2.3"
    assert command[command.index("--source-ref") + 1] == "1" * 40
    assert (docs_command / "output").read_text() == f"directory={docs_command}/artifacts/custom\n"


@pytest.mark.parametrize("port", ["1", "5180", "65535"])
def test_preview_binds_loopback_configured_port(docs_command, monkeypatch, runner, port):
    monkeypatch.setenv("DOCS_PORT", port)
    build.docs(["serve"])
    assert f"127.0.0.1:{port}:5173" in runner.commands("docker", "run")[0]


@pytest.mark.parametrize("port", ["0", "65536", "invalid", "-1"])
def test_preview_rejects_invalid_ports(docs_command, monkeypatch, runner, port):
    monkeypatch.setenv("DOCS_PORT", port)
    with pytest.raises(ValueError, match="DOCS_PORT"):
        build.docs(["serve"])
    assert not runner.commands("docker", "run")


def test_cli_does_not_log_publishing_credentials(monkeypatch, runner, capsys):
    import subprocess

    monkeypatch.setattr("sys.argv", ["build.py", "publish"])
    monkeypatch.setattr(
        build,
        "publish",
        lambda: (_ for _ in ()).throw(subprocess.CalledProcessError(7, ["dotnet", "--api-key", "secret-value"])),
    )
    assert build.main() == 7
    diagnostic = capsys.readouterr().err
    assert "7" in diagnostic
    assert "secret-value" not in diagnostic
