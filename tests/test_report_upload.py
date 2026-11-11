# SPDX-License-Identifier: GPL-3.0-only
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = yaml.safe_load((ROOT / "reports/upload/action.yml").read_text())


def enabled(step, status, **inputs):
    expression = step.get("if", "success()").removeprefix("${{").removesuffix("}}").strip()
    expression = re.sub(r"inputs\.([\w-]+)", lambda match: repr(inputs[match[1]]), expression)
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = expression.replace("steps.files.outputs.paths", "'available reports'")
    return eval(
        expression,
        {"__builtins__": {}},
        {"success": lambda: status == "success", "failure": lambda: status == "failure"},
    )


@pytest.mark.parametrize("status", ["success", "failure", "cancelled"])
@pytest.mark.parametrize("tests,coverage", [("true", "true"), ("true", "false"), ("false", "true"), ("false", "false")])
@pytest.mark.parametrize("action", ["dotnet/build", "dotnet/build-and-pack", "python/build"])
def test_upload_runs_after_failed_tests_and_respects_enabled_reports(action, status, tests, coverage):
    settings = yaml.safe_load((ROOT / action / "action.yml").read_text())
    step = next(s for s in settings["runs"]["steps"] if s.get("uses") == "MrKWatkins/build/reports/upload@main")
    expected = status != "cancelled" and (action == "python/build" or tests == "true" or coverage == "true")
    assert enabled(step, status, **{"test-report": tests, "coverage": coverage}) == expected
    assert step["with"]["coverage"] == "${{ inputs.coverage }}"
    if action != "python/build":
        assert step["with"]["tests"] == "${{ inputs.test-report }}"
    for nested in ACTION["runs"]["steps"]:
        assert enabled(nested, status) == (status != "cancelled")


@pytest.mark.parametrize("tests,coverage", [("true", "true"), ("true", "false"), ("false", "true"), ("false", "false")])
def test_upload_selects_only_enabled_files_and_uses_unique_names(tmp_path, monkeypatch, tests, coverage):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TEST_RESULTS_DIRECTORY", "custom test results")
    monkeypatch.setenv("COVERAGE_DIRECTORY", "custom coverage")
    monkeypatch.setenv("UPLOAD_TESTS", tests)
    monkeypatch.setenv("UPLOAD_COVERAGE", coverage)
    monkeypatch.setenv("GITHUB_JOB", "build")
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    test_files = {"SummaryGithub.md", "raw/run/failed.trx", "raw/run/tests.xml", "raw/run/screenshot.png"}
    raw_coverage = {"raw/run/example.cobertura.xml", "raw/run/coverage.xml", "raw/run/.coverage"}
    merged = {"Cobertura.xml", "SummaryGithub.md"}
    for directory, files in [("custom test results", test_files | raw_coverage), ("custom coverage", merged)]:
        for name in files:
            file = tmp_path / directory / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.touch()
    expected = set()
    if tests == "true":
        expected.update(str(tmp_path / "custom test results" / file) for file in test_files)
    if coverage == "true":
        expected.update(str(tmp_path / "custom test results" / file) for file in raw_coverage)
        expected.update(str(tmp_path / "custom coverage" / file) for file in merged)
    code = ACTION["runs"]["steps"][0]["run"]
    subprocess.run([sys.executable, "-c", code], check=True)
    first_name, paths = output.read_text().split("paths<<REPORT_PATHS\n", 1)
    assert set(paths.removesuffix("\nREPORT_PATHS\n").splitlines()) - {""} == expected
    output.write_text("")
    subprocess.run([sys.executable, "-c", code], check=True)
    assert output.read_text().splitlines()[0].startswith("name=build-results-build-")
    assert first_name.strip() != output.read_text().splitlines()[0]


def test_upload_skips_empty_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UPLOAD_TESTS", "true")
    monkeypatch.setenv("UPLOAD_COVERAGE", "true")
    monkeypatch.setenv("GITHUB_JOB", "build")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    subprocess.run([sys.executable, "-c", ACTION["runs"]["steps"][0]["run"]], check=True)
    assert "paths<<REPORT_PATHS\n\nREPORT_PATHS\n" in (tmp_path / "outputs").read_text()
    assert not enabled(
        ACTION["runs"]["steps"][1]
        | {"if": ACTION["runs"]["steps"][1]["if"].replace("steps.files.outputs.paths", "''")},
        "failure",
    )
