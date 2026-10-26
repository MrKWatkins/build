# SPDX-License-Identifier: GPL-3.0-only
"""Reporting contracts, using XML rather than mocks of XML parsing."""

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from scripts import reports

SCRIPT = Path(reports.__file__)


def coverage(path, packages):
    root = ET.Element("coverage")
    elements = ET.SubElement(root, "packages")
    for name, filename, lines, *types in packages:
        package = ET.SubElement(elements, "package", name=name)
        cls = ET.SubElement(
            ET.SubElement(package, "classes"), "class", name=types[0] if types else "Example", filename=filename
        )
        nodes = ET.SubElement(cls, "lines")
        for line in lines:
            ET.SubElement(nodes, "line", {key: str(value) for key, value in line.items()})
    ET.ElementTree(root).write(path, encoding="utf-8")
    return path


def line(number=1, hits=1, branches=None):
    result = {"number": number, "hits": hits}
    if branches:
        covered, total = branches
        result.update(branch="true", **{"condition-coverage": f"{100 * covered / total:g}% ({covered}/{total})"})
    return result


def test_coverage_excludes_test_libraries_and_python_test_files_by_default(tmp_path):
    source = coverage(
        tmp_path / "input.xml",
        [
            ("Library", "src/Library.cs", [line()]),
            ("Library.Tests", "src/Test.cs", [line(hits=0)]),
            ("Library.IntegrationTests", "src/Test.cs", [line(hits=0)]),
            ("Example.TestAssembly", "src/Test.cs", [line(hits=0)]),
            ("Library.Tests.Support", "src/Test.cs", [line(hits=0)]),
            ("python", "tests/something.py", [line(hits=0)]),
            ("python", "src/pkg/test_example.py", [line(hits=0)]),
            ("python", "src/pkg/example_test.py", [line(hits=0)]),
            ("python", "src/pkg/main.py", [line(hits=0)]),
        ],
    )
    output = tmp_path / "output"
    markdown = reports.coverage_report([source], output)
    merged = ET.parse(output / "Cobertura.xml").getroot()
    assert merged.get("lines-valid") == "2"
    assert merged.get("lines-covered") == "1"
    assert {p.get("name") for p in merged.findall("./packages/package")} == {"Library", "python"}
    assert "50.0% (1/2)" in markdown
    assert "Tests" not in markdown


def test_configured_filters_apply_to_totals_and_merged_xml(tmp_path):
    source = coverage(
        tmp_path / "input.xml",
        [
            ("App.Core", "src/main.py", [line()]),
            ("App.Core", "src/generated/code.py", [line(hits=0)]),
            ("App.Other", "src/other.py", [line(hits=0)]),
            ("App.Unwanted", "src/unwanted.py", [line(hits=0)]),
            ("Dependency", "src/dep.py", [line(hits=0)]),
        ],
    )
    output = tmp_path / "output"
    markdown = reports.coverage_report([source], output, "+App.*;-App.Unwanted", "+*;-*/generated/*")
    merged = ET.parse(output / "Cobertura.xml").getroot()
    assert merged.get("lines-valid") == "2"
    assert merged.get("lines-covered") == "1"
    assert {p.get("name") for p in merged.findall("./packages/package")} == {"App.Core", "App.Other"}
    assert "generated" not in ET.tostring(merged, encoding="unicode")
    assert "Dependency" not in markdown and "App.Unwanted" not in markdown


def test_coverage_merges_overlapping_lines_without_counting_method_duplicates(tmp_path):
    first = coverage(tmp_path / "first.xml", [("Library", "src/Value.cs", [line(1, 0), line(2, 1)])])
    second = coverage(tmp_path / "second.xml", [("Library", "src/Value.cs", [line(1, 3), line(2, 0), line(3, 0)])])
    root = ET.parse(first).getroot()
    cls = root.find(".//class")
    ET.SubElement(ET.SubElement(cls, "methods"), "method").append(
        ET.fromstring('<lines><line number="99" hits="1"/></lines>')
    )
    ET.ElementTree(root).write(first)
    reports.coverage_report([first, second], tmp_path / "output")
    merged = ET.parse(tmp_path / "output/Cobertura.xml").getroot()
    assert (merged.get("lines-covered"), merged.get("lines-valid")) == ("2", "3")
    assert [(n.get("number"), n.get("hits")) for n in merged.findall(".//line")] == [("1", "3"), ("2", "1"), ("3", "0")]


def test_merged_cobertura_has_the_required_schema_structure(tmp_path):
    source = coverage(tmp_path / "input.xml", [("Library", "Value.cs", [line()])])
    reports.coverage_report([source], tmp_path / "output")
    root = ET.parse(tmp_path / "output/Cobertura.xml").getroot()
    assert {
        "version",
        "timestamp",
        "complexity",
        "lines-covered",
        "lines-valid",
        "branches-covered",
        "branches-valid",
    } <= root.attrib.keys()
    package = root.find("./packages/package")
    cls = package.find("./classes/class")
    assert set(package.attrib) == {"name", "line-rate", "branch-rate", "complexity"}
    assert set(cls.attrib) == {"name", "filename", "line-rate", "branch-rate", "complexity"}
    assert [node.tag for node in cls] == ["methods", "lines"]


def test_source_roots_normalise_absolute_and_relative_paths(tmp_path):
    first = coverage(tmp_path / "first.xml", [("Library", "src/Value.cs", [line(hits=0)])])
    second = coverage(tmp_path / "second.xml", [("Library", str(tmp_path / "src/Value.cs"), [line()])])
    root = ET.parse(first).getroot()
    ET.SubElement(ET.SubElement(root, "sources"), "source").text = str(tmp_path)
    ET.ElementTree(root).write(first)
    reports.coverage_report([first, second], tmp_path / "output", root=tmp_path)
    merged = ET.parse(tmp_path / "output/Cobertura.xml").getroot()
    assert merged.get("lines-valid") == "1"
    assert merged.find(".//class").get("filename") == "src/Value.cs"
    assert merged.get("lines-covered") == "1"


def test_partial_branch_union_is_explicitly_a_lower_bound(tmp_path):
    paths = [
        coverage(tmp_path / f"{i}.xml", [("Library", "Value.cs", [line(hits=i + 1, branches=(1, 2))])])
        for i in range(2)
    ]
    markdown = reports.coverage_report(paths, tmp_path / "output")
    root = ET.parse(tmp_path / "output/Cobertura.xml").getroot()
    assert (root.get("branches-covered"), root.get("branches-valid")) == ("1", "2")
    assert "≥50.0% (1/2)" in markdown
    assert "lower bound" in markdown


def test_duplicate_coverage_attachments_do_not_make_branch_counts_ambiguous(tmp_path):
    paths = [coverage(tmp_path / f"{i}.xml", [("Library", "Value.cs", [line(branches=(1, 2))])]) for i in range(2)]
    markdown = reports.coverage_report(paths, tmp_path / "output")
    assert "50.0% (1/2)" in markdown and "≥" not in markdown
    merged = ET.parse(tmp_path / "output/Cobertura.xml").getroot()
    assert merged.get("lines-valid") == "1"


def test_full_branch_observation_resolves_overlap(tmp_path):
    paths = [coverage(tmp_path / f"{i}.xml", [("Library", "Value.cs", [line(branches=(i + 1, 2))])]) for i in range(2)]
    markdown = reports.coverage_report(paths, tmp_path / "output")
    root = ET.parse(tmp_path / "output/Cobertura.xml").getroot()
    assert (root.get("branches-covered"), root.get("branches-valid")) == ("2", "2")
    assert "100.0% (2/2)" in markdown
    assert "lower bound" not in markdown


@pytest.mark.parametrize("branches", [(0, 2), (1, 2), (2, 2)])
def test_single_report_branch_counts_are_exact(tmp_path, branches):
    source = coverage(tmp_path / "input.xml", [("Library", "Value.cs", [line(branches=branches)])])
    markdown = reports.coverage_report([source], tmp_path / "output")
    assert f"{100 * branches[0] / 2:.1f}% ({branches[0]}/2)" in markdown
    assert "≥" not in markdown


def test_zero_coverage_has_no_percentage_gate_and_empty_denominators_are_not_100_percent(tmp_path):
    source = coverage(tmp_path / "input.xml", [("Library", "Value.cs", [line(hits=0)])])
    assert reports.main(["--coverage", str(source), "--coverage-directory", str(tmp_path / "output")]) == 0
    markdown = (tmp_path / "output/SummaryGithub.md").read_text()
    assert "0.0% (0/1) | —" in markdown
    reports.coverage_report([source], tmp_path / "empty", "-*")
    empty = ET.parse(tmp_path / "empty/Cobertura.xml").getroot()
    assert empty.get("lines-valid") == "0"
    assert "No source lines remain" in (tmp_path / "empty/SummaryGithub.md").read_text()


@pytest.mark.parametrize("pattern", ["Library", "+", "-", "+*;Library"])
def test_invalid_filters_fail_clearly(tmp_path, pattern):
    source = coverage(tmp_path / "input.xml", [])
    with pytest.raises(ValueError, match="Invalid coverage filter"):
        reports.coverage_report([source], tmp_path / "output", pattern)


@pytest.mark.parametrize(
    "attributes,message",
    [
        ({"number": "0", "hits": "1"}, "start at one"),
        ({"number": "1", "hits": "-1"}, "line hits"),
        ({"number": "oops", "hits": "1"}, "line number"),
        ({"number": "1", "hits": "1", "branch": "true"}, "condition-coverage"),
        ({"number": "1", "hits": "1", "branch": "true", "condition-coverage": "150% (3/2)"}, "branch counts"),
    ],
)
def test_invalid_coverage_fails_instead_of_publishing_invented_totals(tmp_path, attributes, message):
    source = coverage(tmp_path / "input.xml", [("Library", "Value.cs", [attributes])])
    with pytest.raises(ValueError, match=message):
        reports.coverage_report([source], tmp_path / "output")


def test_incompatible_branch_denominators_are_rejected(tmp_path):
    paths = [coverage(tmp_path / f"{i}.xml", [("Library", "Value.cs", [line(branches=(1, i + 2))])]) for i in range(2)]
    with pytest.raises(ValueError, match="same source"):
        reports.coverage_report(paths, tmp_path / "output")


@pytest.mark.parametrize("generated_total", [2, 4])
def test_generated_types_keep_distinct_branches_on_a_shared_source_line(tmp_path, generated_total):
    paths = [
        coverage(
            tmp_path / f"{i}.xml",
            [
                ("Library", "Value.cs", [line(hits=i, branches=(i * 2, 2))], "Value"),
                ("Library", "Value.cs", [line(branches=(1, generated_total))], "Value.<>c"),
            ],
        )
        for i in range(2)
    ]
    markdown = reports.coverage_report(paths, tmp_path / "output")
    root = ET.parse(tmp_path / "output/Cobertura.xml").getroot()
    assert (root.get("lines-covered"), root.get("lines-valid")) == ("1", "1")
    assert (root.get("branches-covered"), root.get("branches-valid")) == ("3", str(2 + generated_total))
    assert "lower bound" in markdown
    assert root.find(".//line").get("condition-coverage").endswith(f"(3/{2 + generated_total})")


def test_junit_handles_nested_suites_failures_setup_errors_skips_and_durations(tmp_path):
    source = tmp_path / "junit.xml"
    source.write_text("""<testsuites><testsuite name="outer"><testsuite name="inner">
      <testcase classname="pkg" name="pass" time="1.5" />
      <testcase classname="pkg" name="fail" time="0.25"><failure message="Wrong value">Traceback</failure></testcase>
      <testcase classname="pkg" name="setup"><error message="Fixture failed">Setup stack</error></testcase>
      <testcase classname="pkg" name="skip"><skipped message="not available" /></testcase>
    </testsuite></testsuite></testsuites>""")
    results = reports.read_tests(source)
    assert (results.passed, results.failed, results.skipped, results.seconds) == (1, 2, 1, 1.75)
    assert results.failures == [("pkg.fail", "Wrong value\nTraceback"), ("pkg.setup", "Fixture failed\nSetup stack")]
    markdown, failed = reports.test_report([source], tmp_path / "output")
    assert failed == 2
    assert "| **Total** | 1 | 2 | 1 | 1.750s |" in markdown
    assert "Setup stack" in (tmp_path / "output/SummaryGithub.md").read_text()


def test_trx_namespaces_outcomes_and_failure_stack(tmp_path):
    source = tmp_path / "results.trx"
    source.write_text("""<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010"><Results>
      <UnitTestResult testName="pass" outcome="Passed" duration="00:00:01.5" />
      <UnitTestResult testName="fail" outcome="Failed" duration="00:00:00.25">
        <Output><ErrorInfo><Message>Expected 2</Message><StackTrace>Test.cs:42</StackTrace></ErrorInfo></Output>
      </UnitTestResult>
      <UnitTestResult testName="skip" outcome="NotExecuted" />
      <UnitTestResult testName="timeout" outcome="Timeout" />
    </Results><ResultSummary outcome="Failed" /></TestRun>""")
    results = reports.read_tests(source)
    assert (results.passed, results.failed, results.skipped, results.seconds) == (1, 2, 1, 1.75)
    assert results.failures[0] == ("fail", "Expected 2\nTest.cs:42")
    assert results.failures[1] == ("timeout", "Outcome: timeout")


@pytest.mark.parametrize(
    "xml,message",
    [
        (
            '<TestRun><ResultSummary outcome="Aborted"><Output>Host crashed</Output></ResultSummary></TestRun>',
            "Host crashed",
        ),
        ('<testsuite name="collection" errors="1"><system-err>Import failed</system-err></testsuite>', "Import failed"),
    ],
)
def test_host_and_collection_failures_without_cases_are_not_success(tmp_path, xml, message):
    source = tmp_path / "failed.xml"
    source.write_text(xml)
    result = reports.read_tests(source)
    assert result.failed == 1
    assert message in result.failures[0][1]


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "invalid", "a:b:c"])
def test_invalid_durations_are_rejected(value):
    with pytest.raises(ValueError, match="duration"):
        reports.duration(value)


def test_empty_report_and_matrix_results_are_separate_executions(tmp_path):
    paths = [tmp_path / f"{i}.xml" for i in range(3)]
    paths[0].write_text('<testsuite><testcase name="same" time="1" /></testsuite>')
    paths[1].write_text('<testsuite><testcase name="same" time="2" /></testsuite>')
    paths[2].write_text('<testsuites><testsuite tests="0" /></testsuites>')
    markdown, failed = reports.test_report(paths, tmp_path / "output")
    assert failed == 0
    assert "| **Total** | 2 | 0 | 0 | 3.000s |" in markdown


def test_markdown_escapes_input_and_limits_failure_details(tmp_path):
    source = tmp_path / "junit.xml"
    root = ET.Element("testsuite")
    for i in range(51):
        case = ET.SubElement(root, "testcase", name=f"<bad>|{i}")
        ET.SubElement(case, "failure").text = "<script>unsafe</script>" + "a" * 9000
    ET.ElementTree(root).write(source)
    markdown, failed = reports.test_report([source], tmp_path / "output")
    assert failed == 51
    assert "<script>" not in markdown and "&lt;script&gt;" in markdown
    assert "<bad>" not in markdown
    assert markdown.count("<details>") == 50
    assert "Showing 50 of 51 failures" in markdown
    assert len(markdown) < 410000


def test_cli_from_another_directory_handles_spaces_globs_and_read_only_github_context(tmp_path):
    source = coverage(tmp_path / "coverage one.xml", [("Library", "Value.cs", [line(hits=0)])])
    tests = tmp_path / "tests.xml"
    tests.write_text('<testsuite><testcase name="passes" /></testsuite>')
    result = subprocess.run(
        [sys.executable, SCRIPT, "--coverage", str(source), "--tests", str(tests)],
        cwd=tmp_path,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "artifacts/coverage/Cobertura.xml").is_file()
    assert "| **Total** | 1 | 0 | 0 |" in result.stdout
    assert "0.0% (0/1)" in result.stdout
    assert reports.find_reports([str(tmp_path / "coverage*.xml"), str(source)]) == [source.resolve()]


def test_cli_fails_for_test_failures_and_preserves_test_summary_if_coverage_is_missing(tmp_path, monkeypatch):
    source = tmp_path / "failed.xml"
    source.write_text('<testsuite><testcase name="fails"><failure>Wrong value</failure></testcase></testsuite>')
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    args = ["--tests", str(source), "--test-directory", str(tmp_path / "output")]
    assert reports.main(args) == 1
    assert "Wrong value" in summary.read_text()
    assert reports.main([*args, "--coverage", str(tmp_path / "missing*.xml")]) == 1
    assert summary.read_text().count("## Tests") == 2


def test_coverage_still_reports_when_test_results_are_missing(tmp_path, monkeypatch):
    source = coverage(tmp_path / "coverage.xml", [("Library", "Value.cs", [line(hits=0)])])
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert (
        reports.main(
            [
                "--tests",
                str(tmp_path / "missing.trx"),
                "--coverage",
                str(source),
                "--coverage-directory",
                str(tmp_path / "out"),
            ]
        )
        == 1
    )
    assert "0.0% (0/1)" in summary.read_text()


@pytest.mark.parametrize("xml,message", [("<coverage", "Invalid XML"), ("<other/>", "Unsupported report")])
def test_malformed_or_unsupported_reports_fail_clearly(tmp_path, xml, message, capsys):
    source = tmp_path / "input.xml"
    source.write_text(xml)
    assert reports.main(["--coverage", str(source)]) == 1
    assert message in capsys.readouterr().err


def test_missing_input_is_a_reporting_error(capsys):
    assert reports.main([]) == 1
    assert "Supply --coverage and/or --tests" in capsys.readouterr().err


def test_reporting_action_executes_the_real_entrypoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = coverage(tmp_path / "coverage.xml", [("Library", "Value.cs", [line()])])
    action_dir = SCRIPT.parents[1] / "reports"
    action = yaml.safe_load((action_dir / "action.yml").read_text())
    inputs = {name: config["default"] for name, config in action["inputs"].items()}
    inputs["coverage"] = str(source)
    inputs["coverage-assembly-filters"] = "-Unwanted"
    inputs["coverage-file-filters"] = "-*/generated/*"
    step = action["runs"]["steps"][0]
    for name, value in step["env"].items():
        value = value.replace("${{ github.action_path }}", str(action_dir))
        for key, replacement in inputs.items():
            value = value.replace("${{ inputs." + key + " }}", replacement)
        monkeypatch.setenv(name, value)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    result = subprocess.run([sys.executable, "-c", step["run"]], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "100.0% (1/1)" in summary.read_text()
