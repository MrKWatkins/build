# SPDX-License-Identifier: GPL-3.0-only
import subprocess
from pathlib import Path

import pytest

from scripts import build


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "source with spaces").mkdir()
    monkeypatch.setenv("BUILD_DIRECTORY", "source with spaces")
    monkeypatch.setenv("VERSION", "1.2.3")
    monkeypatch.setenv("COVERAGE", "false")
    return tmp_path


def test_build_preserves_mtp_filter_and_version(workspace, monkeypatch, runner):
    expression = "TestCategory!=Slow&TestCategory!=Integration"
    monkeypatch.setenv("TEST_FILTER", expression)
    runner.handler = lambda args, kwargs: (1 if args[:2] == ("dotnet", "format") else 0, "")
    build.build()
    assert runner.commands("dotnet", "restore") == [("dotnet", "restore", "-p:Version=1.2.3")]
    assert runner.commands("dotnet", "build") == [
        ("dotnet", "build", "--no-restore", "--configuration", "Release", "-p:Version=1.2.3")
    ]
    assert runner.commands("dotnet", "test") == [
        ("dotnet", "test", "--no-restore", "--no-build", "--configuration", "Release", "--filter", expression)
    ]
    assert not runner.commands("dotnet", "tool")
    assert all(kwargs["cwd"] == workspace / "source with spaces" for _, kwargs in runner.calls)


@pytest.mark.parametrize("test_exit,report_exit,expected", [(7, 9, 7), (7, 0, 7), (0, 9, 9)])
def test_test_failure_takes_precedence_over_reporting(workspace, monkeypatch, runner, test_exit, report_exit, expected):
    monkeypatch.setenv("COVERAGE", "true")

    def handle(args, kwargs):
        if args[:2] == ("dotnet", "test"):
            return test_exit, ""
        if args[:2] == ("dotnet", "tool"):
            return report_exit, ""
        if "reportgenerator" in args[0]:
            target = next(arg.removeprefix("-targetdir:") for arg in args if arg.startswith("-targetdir:"))
            Path(target, "SummaryGithub.md").write_text("Coverage summary")
        return 0, ""

    runner.handler = handle
    with pytest.raises(subprocess.CalledProcessError) as failure:
        build.build()
    assert failure.value.returncode == expected
    test = runner.commands("dotnet", "test")[0]
    assert "--coverage" in test and test[test.index("--coverage-output-format") + 1] == "cobertura"


def test_coverage_summary_and_isolated_output(workspace, monkeypatch, runner):
    monkeypatch.setenv("COVERAGE", "true")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(workspace / "summary"))
    monkeypatch.setenv("COVERAGE_ASSEMBLY_FILTERS", "+Library;-Tests")

    def handle(args, kwargs):
        if "reportgenerator" in args[0]:
            (workspace / "artifacts/coverage/SummaryGithub.md").write_text("Coverage: 90%")
        return 0, ""

    runner.handler = handle
    build.build()
    assert (workspace / "summary").read_text() == "Coverage: 90%\n"
    report = next(args for args, _ in runner.calls if "reportgenerator" in args[0])
    assert "-assemblyfilters:+Library;-Tests" in report
    results = runner.commands("dotnet", "test")[0][-1]
    assert not Path(results).exists()


def test_build_and_pack_once_without_rebuild(workspace, monkeypatch, runner):
    monkeypatch.setenv("GITHUB_OUTPUT", str(workspace / "output"))

    def handle(args, kwargs):
        if args[:2] == ("dotnet", "pack"):
            Path(args[-1], "Library.1.2.3.nupkg").touch()
        return 0, ""

    runner.handler = handle
    build.build_and_pack()
    assert (
        len(runner.commands("dotnet", "build"))
        == len(runner.commands("dotnet", "test"))
        == len(runner.commands("dotnet", "pack"))
        == 1
    )
    args = runner.commands("dotnet", "pack")[0]
    assert args[2:6] == ("--no-build", "--no-restore", "--configuration", "Release")
    assert "--include-symbols" in args and "-p:SymbolPackageFormat=snupkg" in args
    assert (workspace / "output").read_text() == f"directory={workspace}/artifacts/packages\n"


@pytest.mark.parametrize("operation", ["restore", "build", "test", "pack"])
def test_combined_failures_stop_publication(workspace, runner, operation):
    runner.handler = lambda args, kwargs: (7 if args[:2] == ("dotnet", operation) else 0, "")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        build.build_and_pack()
    assert failure.value.returncode == 7
    if operation != "pack":
        assert not runner.commands("dotnet", "pack")


def test_pack_rejects_stale_output(workspace, runner):
    destination = workspace / "artifacts/packages"
    destination.mkdir(parents=True)
    (destination / "stale.txt").touch()
    with pytest.raises(ValueError, match="empty"):
        build.pack()
    assert not runner.calls


def test_pack_requires_packages(workspace, runner):
    with pytest.raises(ValueError, match="no NuGet"):
        build.pack()


def test_publish_only_pushes_existing_packages(workspace, monkeypatch, runner):
    destination = workspace / "artifacts/packages"
    destination.mkdir(parents=True)
    package = destination / "Library.1.2.3.nupkg"
    package.touch()
    package.with_suffix(".snupkg").touch()
    monkeypatch.setenv("NUGET_API_KEY", "temporary-key")
    build.publish()
    assert [args for args, _ in runner.calls] == [
        (
            "dotnet",
            "nuget",
            "push",
            str(package),
            "--source",
            "https://api.nuget.org/v3/index.json",
            "--api-key",
            "temporary-key",
            "--skip-duplicate",
        )
    ]


@pytest.mark.parametrize("credential,files", [("", True), ("temporary-key", False)])
def test_empty_publication_stops_before_network(workspace, monkeypatch, runner, credential, files):
    monkeypatch.setenv("NUGET_API_KEY", credential)
    destination = workspace / "artifacts/packages"
    destination.mkdir(parents=True)
    if files:
        (destination / "Library.nupkg").touch()
    with pytest.raises(ValueError):
        build.publish()
    assert not runner.calls
