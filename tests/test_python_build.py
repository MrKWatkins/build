# SPDX-License-Identifier: GPL-3.0-only
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import build


@pytest.fixture
def project(tmp_path, monkeypatch, runner):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname="example"\ndynamic=["version"]\n')

    def handle(args, kwargs):
        if args[:2] == ("uv", "build"):
            destination = Path(args[args.index("--out-dir") + 1])
            (destination / "example-1.2.3.whl").touch()
            (destination / "example-1.2.3.tar.gz").touch()
        if args[:4] == ("git", "ls-remote", "--tags", "origin"):
            return 0, "1" * 40 + "\trefs/tags/v1.2.3\n"
        if args[:2] == ("git", "rev-parse"):
            return 0, "2" * 40
        return 0, ""

    runner.handler = handle
    return tmp_path


def test_python_build_checks_tests_and_reports_before_packaging(project, runner):
    build.python_build()
    commands = [args for args, _ in runner.calls]
    assert commands[:4] == [
        ("uv", "sync", "--locked"),
        ("uv", "run", "--frozen", "ruff", "check"),
        ("uv", "run", "--frozen", "ruff", "format", "--check"),
        ("uv", "run", "--frozen", "ty", "check"),
    ]
    test = next(c for c in commands if "pytest" in c)
    assert "--source=src" in test and "--branch" in test
    report = next(c for c in commands if str(build.ROOT / "scripts/reports.py") in c)
    pack = next(c for c in commands if c[:2] == ("uv", "build"))
    assert commands.index(test) < commands.index(report) < commands.index(pack)
    assert list((project / "artifacts/test-results/raw").iterdir())


@pytest.mark.parametrize("test_exit,report_exit,expected", [(7, 9, 7), (0, 9, 9)])
def test_python_test_failure_precedes_reporting_failure_and_blocks_packaging(
    project, runner, test_exit, report_exit, expected
):
    original = runner.handler

    def handle(args, kwargs):
        if "pytest" in args:
            return test_exit, ""
        if str(build.ROOT / "scripts/reports.py") in args:
            return report_exit, ""
        return original(args, kwargs)

    runner.handler = handle
    with pytest.raises(subprocess.CalledProcessError) as failure:
        build.python_build()
    assert failure.value.returncode == expected
    assert not runner.commands("uv", "build")


def test_python_coverage_can_be_disabled_without_disabling_junit_reports(project, monkeypatch, runner):
    monkeypatch.setenv("COVERAGE", "false")
    build.python_build()
    test = next(args for args, _ in runner.calls if "pytest" in args)
    assert "coverage" not in test
    report = next(args for args, _ in runner.calls if str(build.ROOT / "scripts/reports.py") in args)
    assert "--tests" in report and "--coverage" not in report


def test_python_release_version_is_supplied_to_hatch_without_changing_source(project, monkeypatch, runner):
    monkeypatch.setenv("VERSION", "2.0.0")
    before = (project / "pyproject.toml").read_bytes()
    build.python_pack()
    assert (project / "pyproject.toml").read_bytes() == before
    assert not runner.commands("uv", "version")
    kwargs = next(kwargs for args, kwargs in runner.calls if args[:2] == ("uv", "build"))
    assert kwargs["cwd"] == project
    assert kwargs["env"]["SETUPTOOLS_SCM_PRETEND_VERSION"] == "2.0.0"


def test_python_local_packaging_leaves_version_detection_to_git(project, monkeypatch, runner):
    monkeypatch.delenv("SETUPTOOLS_SCM_PRETEND_VERSION", raising=False)
    build.python_pack()
    kwargs = next(kwargs for args, kwargs in runner.calls if args[:2] == ("uv", "build"))
    assert "SETUPTOOLS_SCM_PRETEND_VERSION" not in kwargs["env"]


def test_python_release_rejects_a_static_version(project, monkeypatch, runner):
    (project / "pyproject.toml").write_text('[project]\nname="example"\nversion="1.2.3"\n')
    monkeypatch.setenv("VERSION", "2.0.0")
    with pytest.raises(ValueError, match="dynamic project version"):
        build.python_pack()
    assert not runner.commands("uv", "build")


@pytest.mark.parametrize(
    "publish,tag,expected",
    [(True, True, "1.3.0"), (True, False, "0.1.0"), (False, True, "1.2.3"), (False, False, "0.0.0")],
)
def test_python_release_defaults_and_docs_only_without_initial_git_tags(
    project, runner, monkeypatch, publish, tag, expected
):
    monkeypatch.setenv("PUBLISH_PACKAGES", str(publish).lower())
    monkeypatch.setenv("GITHUB_OUTPUT", str(project / "outputs"))
    original = runner.handler
    runner.handler = lambda args, kwargs: (
        (0, "") if not tag and args[:2] == ("git", "ls-remote") else original(args, kwargs)
    )
    build.python_release_source()
    assert f"version={expected}" in (project / "outputs").read_text()
    assert "commit=" + "2" * 40 in (project / "outputs").read_text()


def test_python_stale_documentation_is_rejected(project, monkeypatch):
    monkeypatch.setenv("VERSION", "1.2.2")
    with pytest.raises(ValueError, match="latest release is 1.2.3"):
        build.python_freshness()


def test_python_publishing_only_uses_prepared_distributions_and_trusted_publishing(project, runner):
    build.python_pack()
    build.python_publish()
    command = runner.commands("uv", "publish")[0]
    assert command[2:4] == ("--trusted-publishing", "always")
    assert {Path(p).suffix for p in command[4:]} == {".whl", ".gz"}


@pytest.mark.parametrize("packages,docs", [("false", "false"), ("true", "true"), ("false", "true"), ("true", "false")])
def test_python_project_publication_modes_keep_docs_only_separate(packages, docs):
    from test_project import selected_steps

    action = yaml.safe_load((build.ROOT / "python/project/action.yml").read_text())
    steps = selected_steps(action, **{"publish-packages": packages, "publish-docs": docs})
    names = [step.get("name") for step in steps]
    assert ("Build and test Python" in names) == (packages == "true" or docs == "false")
    assert ("Check out released API source" in names) == (docs == "true" and packages == "false")
    assert ("Publish Python packages" in names) == (packages == "true")
    assert ("Create GitHub release" in names) == (packages == "true")
    if packages == "true":
        assert names.index("Build and validate documentation") < names.index("Publish Python packages")


def test_python_api_uses_the_pinned_standalone_generator(project, monkeypatch, runner):
    monkeypatch.setenv("SOURCE_REF", "3" * 40)
    monkeypatch.setenv("API_DIRECTORY", "released source")
    build.python_api()
    command = runner.commands("uv", "run", "--script")[0]
    assert str(build.ROOT / "docs/python-api/generate.py") in command
    assert command[command.index("--source-root") + 1] == "released source"
    assert command[-1] == "3" * 40
