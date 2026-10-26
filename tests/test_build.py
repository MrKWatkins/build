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
    monkeypatch.setenv("TEST_REPORT", "false")
    return tmp_path


def test_build_preserves_mtp_filter_and_version(workspace, monkeypatch, runner):
    expression = "TestCategory!=Slow&TestCategory!=Integration"
    monkeypatch.setenv("TEST_FILTER", expression)
    runner.handler = lambda args, kwargs: (1 if args[:2] == ("dotnet", "format") else 0, "")
    build.build()
    assert runner.commands("dotnet", "restore") == [("dotnet", "restore", "-p:Version=1.2.3")]
    assert runner.commands("dotnet", "build") == [
        (
            "dotnet",
            "build",
            "--no-restore",
            "--configuration",
            "Release",
            "-p:CopyLocalLockFileAssemblies=true",
            "-p:Version=1.2.3",
        )
    ]
    assert runner.commands("dotnet", "test") == [
        ("dotnet", "test", "--no-restore", "--no-build", "--configuration", "Release", "--filter", expression)
    ]
    assert not runner.commands("dotnet", "tool")
    assert all(kwargs["cwd"] == workspace / "source with spaces" for _, kwargs in runner.calls)


def test_preparation_runs_before_restore(workspace, monkeypatch, runner):
    script = workspace / "prepare assets.py"
    script.write_text("# Project-specific asset preparation.\n")
    monkeypatch.setenv("PREPARE_SCRIPT", script.name)
    build.build()
    assert runner.calls[0][0] == (build.sys.executable, str(script))
    assert runner.calls[0][1]["cwd"] == workspace
    assert runner.commands("dotnet", "restore")


def test_preparation_failure_stops_build(workspace, monkeypatch, runner):
    (workspace / "prepare.py").write_text("raise RuntimeError('asset build failed')\n")
    monkeypatch.setenv("PREPARE_SCRIPT", "prepare.py")
    runner.handler = lambda args, kwargs: (9, "")
    with pytest.raises(subprocess.CalledProcessError) as failure:
        build.build()
    assert failure.value.returncode == 9
    assert not runner.commands("dotnet", "restore")


@pytest.mark.parametrize("name", ["../outside.py", "absolute", "prepare.sh", "symlink.py"])
def test_preparation_rejects_invalid_paths(workspace, monkeypatch, runner, name):
    outside = workspace.parent / "outside.py"
    outside.write_text("# Outside the project.\n")
    (workspace / "prepare.sh").touch()
    (workspace / "symlink.py").symlink_to(outside)
    monkeypatch.setenv("PREPARE_SCRIPT", str(outside) if name == "absolute" else name)
    with pytest.raises(ValueError, match="repository-relative Python"):
        build.prepare()
    assert not runner.calls


@pytest.mark.parametrize("test_exit,report_exit,expected", [(7, 9, 7), (7, 0, 7), (0, 9, 9)])
def test_test_failure_takes_precedence_over_reporting(workspace, monkeypatch, runner, test_exit, report_exit, expected):
    monkeypatch.setenv("COVERAGE", "true")

    def handle(args, kwargs):
        if args[:2] == ("dotnet", "test"):
            return test_exit, ""
        if args[:2] == (build.sys.executable, str(build.ROOT / "scripts/reports.py")):
            return report_exit, ""
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
    monkeypatch.setenv("COVERAGE_FILE_FILTERS", "+*;-*/generated/*")

    def handle(args, kwargs):
        if args[:2] == ("dotnet", "test"):
            results = Path(args[-1])
            results.mkdir()
            (results / "example.cobertura.xml").write_text("<coverage />")
        if args[:2] == (build.sys.executable, str(build.ROOT / "scripts/reports.py")):
            Path(workspace / "summary").write_text("Coverage: 90%\n")
        return 0, ""

    runner.handler = handle
    build.build()
    assert (workspace / "summary").read_text() == "Coverage: 90%\n"
    report = runner.commands(build.sys.executable, str(build.ROOT / "scripts/reports.py"))[0]
    assert "--assembly-filters=+Library;-Tests" in report
    assert "--file-filters=+*;-*/generated/*" in report
    assert report[report.index("--coverage-directory") + 1] == str(workspace / "artifacts/coverage")
    assert not runner.commands("dotnet", "tool")
    results = runner.commands("dotnet", "test")[0][-1]
    assert not Path(results).exists()
    retained = list((workspace / "artifacts/test-results/raw").glob("*/example.cobertura.xml"))
    assert len(retained) == 1 and retained[0].read_text() == "<coverage />"


@pytest.mark.parametrize("setting", [None, "true", "false"])
def test_trx_reporting_defaults_on_and_can_be_disabled_without_coverage(workspace, monkeypatch, runner, setting):
    if setting is None:
        monkeypatch.delenv("TEST_REPORT")
    else:
        monkeypatch.setenv("TEST_REPORT", setting)
    monkeypatch.setenv("TEST_RESULTS_DIRECTORY", "custom test results")
    build.build()
    test = runner.commands("dotnet", "test")[0]
    assert ("--report-trx" in test) == (setting != "false")
    assert "--coverage" not in test
    reports = runner.commands(build.sys.executable, str(build.ROOT / "scripts/reports.py"))
    if setting == "false":
        assert not reports
        return
    report = reports[0]
    assert report[report.index("--tests") + 1].endswith("results/**/*.trx")
    assert report[report.index("--test-directory") + 1] == str(workspace / "custom test results")
    assert "--coverage" not in report


def test_raw_results_survive_failed_tests_and_failed_reporting(workspace, monkeypatch, runner):
    monkeypatch.setenv("TEST_REPORT", "true")

    def handle(args, kwargs):
        if args[:2] == ("dotnet", "test"):
            results = Path(args[-1])
            results.mkdir()
            (results / "failed.trx").write_text("partial results")
            return 7, ""
        if args[:2] == (build.sys.executable, str(build.ROOT / "scripts/reports.py")):
            return 9, ""
        return 0, ""

    runner.handler = handle
    with pytest.raises(subprocess.CalledProcessError) as failure:
        build.build()
    assert failure.value.returncode == 7
    retained = list((workspace / "artifacts/test-results/raw").glob("*/failed.trx"))
    assert len(retained) == 1 and retained[0].read_text() == "partial results"


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
