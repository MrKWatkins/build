# SPDX-License-Identifier: GPL-3.0-only
"""Real collectors exercise the same reporting path used by consumers."""

import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import build, reports


@pytest.mark.dotnet
@pytest.mark.parametrize("failed", [False, True])
def test_real_mtp_coverage_trx_and_original_test_exit(tmp_path, monkeypatch, failed):
    fixture = Path(__file__).parent / "fixtures/reporting"
    shutil.copytree(fixture, tmp_path / "source with spaces")
    monkeypatch.chdir(tmp_path / "source with spaces")
    monkeypatch.setenv("REPORTING_FAIL", str(failed).lower())
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    if failed:
        with pytest.raises(subprocess.CalledProcessError) as failure:
            build.build()
        assert failure.value.returncode == 2
    else:
        build.build()

    output = Path("artifacts/test-results")
    trx = list((output / "raw").glob("**/*.trx"))
    raw_coverage = list((output / "raw").glob("**/*.cobertura.xml"))
    assert len(trx) == 1 and len(raw_coverage) >= 1
    assert {p.name for p in raw_coverage} == {raw_coverage[0].name}
    tests = reports.read_tests(trx[0])
    assert (tests.passed, tests.failed, tests.skipped) == ((2, 1, 1) if failed else (3, 0, 1))
    if failed:
        assert "Example failure for the reporter." in (output / "SummaryGithub.md").read_text()
    coverage = ET.parse("artifacts/coverage/Cobertura.xml").getroot()
    assert [n.get("name") for n in coverage.findall("./packages/package")] == ["Library"]
    assert int(coverage.get("lines-covered")) == int(coverage.get("lines-valid")) > 0
    assert int(coverage.get("branches-covered")) == int(coverage.get("branches-valid")) > 0
    summary = (tmp_path / "summary.md").read_text()
    assert "## Tests" in summary and "## Coverage" in summary


@pytest.mark.parametrize("failed", [False, True])
def test_real_pytest_junit_and_coverage_xml(tmp_path, failed):
    (tmp_path / "example.py").write_text("def choose(flag):\n    return 2 if flag else 1\n")
    (tmp_path / "test_example.py").write_text(
        "import pytest\nfrom example import choose\n"
        "@pytest.mark.parametrize('flag, expected', [(True, 2), (False, 1)])\n"
        "def test_choose(flag, expected):\n    assert choose(flag) == expected\n"
        "@pytest.mark.skip(reason='Example skip')\n"
        "def test_skip():\n    pass\n"
        f"def test_result():\n    assert {not failed}\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source=example",
            "-m",
            "pytest",
            "--junitxml=junit.xml",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (1 if failed else 0), result.stdout + result.stderr
    subprocess.run(
        [sys.executable, "-m", "coverage", "xml", "-o", "coverage.xml"], cwd=tmp_path, capture_output=True, check=True
    )
    report = subprocess.run(
        [sys.executable, reports.__file__, "--tests", "junit.xml", "--coverage", "coverage.xml"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert report.returncode == (1 if failed else 0), report.stdout + report.stderr
    assert f"| **Total** | {2 if failed else 3} | {1 if failed else 0} | 1 |" in report.stdout
    coverage = ET.parse(tmp_path / "artifacts/coverage/Cobertura.xml").getroot()
    assert int(coverage.get("lines-covered")) == int(coverage.get("lines-valid")) > 0
