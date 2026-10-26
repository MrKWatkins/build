#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Render Cobertura coverage and TRX/JUnit test results without reporting dependencies."""

import argparse
import fnmatch
import glob
import hashlib
import html
import os
import posixpath
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


def matching(value, patterns):
    """Semicolon-separated +include/-exclude globs; exclusions always win."""
    includes, excludes = [], []
    for pattern in patterns.split(";"):
        if not pattern:
            continue
        if pattern[0] not in "+-" or len(pattern) == 1:
            raise ValueError(f"Invalid coverage filter: {pattern!r}; use +pattern or -pattern.")
        (includes if pattern[0] == "+" else excludes).append(pattern[1:])
    return (not includes or any(fnmatch.fnmatchcase(value, p) for p in includes)) and not any(
        fnmatch.fnmatchcase(value, p) for p in excludes
    )


def test_library(name):
    return any(
        fnmatch.fnmatchcase(name, pattern) for pattern in ("*Tests", "*Tests.*", "*TestAssembly", "*TestAssembly.*")
    )


def test_file(name):
    return any(part.lower() in ("test", "tests") for part in name.split("/")) or any(
        fnmatch.fnmatchcase(name.rsplit("/", 1)[-1], pattern) for pattern in ("test_*.py", "*_test.py")
    )


def table_text(value):
    return html.escape(str(value)).replace("|", "&#124;").replace("\n", "<br>").replace("\r", "")


def xml_file(path, expected):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError(f"Invalid XML in {path}: {error}") from error
    # TRX uses an XML namespace; JUnit producers may use one too.
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    if root.tag not in expected:
        raise ValueError(f"Unsupported report in {path}: {root.tag}.")
    return root


def number(value, description):
    try:
        result = int(value)
    except (ValueError, TypeError) as error:
        raise ValueError(f"Invalid {description}: {value!r}.") from error
    if result < 0:
        raise ValueError(f"Invalid {description}: {value!r}.")
    return result


def filename(value, sources, root):
    if not value:
        raise ValueError("Coverage class has no filename.")
    value = value.replace("\\", "/")
    absolute = value.startswith("/") or re.match(r"^[A-Za-z]:/", value)
    if not absolute:
        candidates = [posixpath.join(source.replace("\\", "/"), value) for source in sources if source]
        value = next((p for p in candidates if Path(p).is_file()), candidates[0] if candidates else value)
    value = posixpath.normpath(value)
    prefix = root.as_posix().rstrip("/") + "/"
    return value.removeprefix(prefix)


@dataclass
class Line:
    hits: int = 0
    covered: int = 0
    branches: int = 0
    observations: int = 0

    def add(self, node):
        self.hits = max(self.hits, number(node.get("hits"), "line hits"))
        if node.get("branch", "false").lower() != "true":
            return
        match = re.fullmatch(r"[\d.]+% \((\d+)/(\d+)\)", node.get("condition-coverage", ""))
        if not match:
            raise ValueError("Branch coverage requires condition-coverage counts, for example 50% (1/2).")
        covered, total = map(int, match.groups())
        if covered > total or total == 0 or (self.branches and self.branches != total):
            raise ValueError("Inconsistent branch counts for the same source line; reports must cover the same source.")
        self.covered = max(self.covered, covered)
        self.branches = total
        self.observations += 1

    @property
    def lower_bound(self):
        # Cobertura counts and even 50% condition entries do not identify which side was covered.
        return self.observations > 1 and 0 < self.covered < self.branches


@dataclass
class Totals:
    lines: int = 0
    covered: int = 0
    branches: int = 0
    branches_covered: int = 0
    lower_bound: bool = False

    def add(self, lines):
        for line in lines:
            self.lines += 1
            self.covered += line.hits > 0
            self.branches += line.branches
            self.branches_covered += line.covered
            self.lower_bound |= line.lower_bound

    def attributes(self, counts=True):
        attributes = {
            "lines-valid": str(self.lines),
            "lines-covered": str(self.covered),
            "line-rate": str(self.covered / self.lines if self.lines else 0),
            "branches-valid": str(self.branches),
            "branches-covered": str(self.branches_covered),
            "branch-rate": str(self.branches_covered / self.branches if self.branches else 0),
            # Complexity is not measured; Cobertura requires this attribute (as does coverage.py's XML).
            "complexity": "0",
        }
        return (
            attributes if counts else {k: v for k, v in attributes.items() if k.endswith("-rate") or k == "complexity"}
        )

    def cells(self):
        return f"{percentage(self.covered, self.lines)} | {percentage(self.branches_covered, self.branches, self.lower_bound)}"


def percentage(covered, total, lower_bound=False):
    if not total:
        return "—"
    return f"{'≥' if lower_bound else ''}{100 * covered / total:.1f}% ({covered}/{total})"


def coverage_report(paths, output, assembly_filters="+*", file_filters="+*", root=None):
    root = Path(root or Path.cwd()).resolve()
    # Validate filters even when the report is empty or every package is excluded.
    matching("", assembly_filters)
    matching("", file_filters)
    packages = {}
    seen = set()
    for path in paths:
        # TRX exporters can copy coverage attachments into a second nested directory.
        with Path(path).open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").digest()
        if digest in seen:
            continue
        seen.add(digest)
        document = xml_file(path, {"coverage"})
        sources = [node.text for node in document.findall("./sources/source") if node.text]
        for package in document.findall("./packages/package"):
            name = package.get("name", "")
            if test_library(name) or not matching(name, assembly_filters):
                continue
            for cls in package.findall("./classes/class"):
                source = filename(cls.get("filename"), sources, root)
                if test_file(source) or not matching(source, file_filters):
                    continue
                # Read only class-level lines; method-level lines repeat the same coverage.
                for node in cls.findall("./lines/line"):
                    line_number = number(node.get("number"), "line number")
                    if line_number == 0:
                        raise ValueError("Coverage line numbers must start at one.")
                    lines = packages.setdefault(name, {}).setdefault(source, {})
                    lines.setdefault(line_number, Line()).add(node)

    document = ET.Element("coverage", version="1", timestamp=str(int(time.time())))
    ET.SubElement(ET.SubElement(document, "sources"), "source").text = root.as_posix()
    package_nodes = ET.SubElement(document, "packages")
    total = Totals()
    rows = []
    for name, files in sorted(packages.items()):
        package_total = Totals()
        for lines in files.values():
            package_total.add(lines.values())
        total.add(line for lines in files.values() for line in lines.values())
        package_node = ET.SubElement(package_nodes, "package", name=name, **package_total.attributes(counts=False))
        classes = ET.SubElement(package_node, "classes")
        for source, lines in sorted(files.items()):
            file_total = Totals()
            file_total.add(lines.values())
            cls = ET.SubElement(classes, "class", name=source, filename=source, **file_total.attributes(counts=False))
            ET.SubElement(cls, "methods")
            line_nodes = ET.SubElement(cls, "lines")
            for line_number, line in sorted(lines.items()):
                attrs = {"number": str(line_number), "hits": str(line.hits), "branch": str(bool(line.branches)).lower()}
                if line.branches:
                    attrs["condition-coverage"] = (
                        f"{100 * line.covered / line.branches:g}% ({line.covered}/{line.branches})"
                    )
                ET.SubElement(line_nodes, "line", attrs)
        rows.append(f"| {table_text(name) or '(root)'} | {package_total.cells()} |")
    document.attrib.update(total.attributes())
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    ET.indent(document)
    ET.ElementTree(document).write(output / "Cobertura.xml", encoding="utf-8", xml_declaration=True)
    markdown = "## Coverage\n\n| Library/package | Lines | Branches |\n| --- | --- | --- |\n"
    markdown += "\n".join([*rows, f"| **Total** | {total.cells()} |\n"])
    if total.lower_bound:
        markdown += (
            "\n≥ marks a lower bound: overlapping Cobertura reports do not identify individual covered branches. "
            "The merged XML also uses these conservative counts.\n"
        )
    if not packages:
        markdown += "\nNo source lines remain after filtering.\n"
    (output / "SummaryGithub.md").write_text(markdown, encoding="utf-8")
    return markdown


@dataclass
class TestResults:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    seconds: float = 0
    failures: list = field(default_factory=list)


def duration(value):
    try:
        if ":" not in value:
            result = float(value)
        else:
            hours, minutes, seconds = value.split(":")
            days, hours = hours.split(".") if "." in hours else ("0", hours)
            result = float(days) * 86400 + float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        if not 0 <= result < float("inf"):
            raise ValueError()
        return result
    except ValueError as error:
        raise ValueError(f"Invalid test duration: {value!r}.") from error


def read_tests(path):
    root = xml_file(path, {"TestRun", "testsuite", "testsuites"})
    results = TestResults()
    trx = root.tag == "TestRun"
    cases = root.findall("./Results/UnitTestResult") if trx else list(root.iter("testcase"))
    for case in cases:
        name = case.get("testName", "") if trx else ".".join(filter(None, [case.get("classname"), case.get("name")]))
        results.seconds += duration(case.get("duration" if trx else "time", "0"))
        if trx:
            outcome = case.get("outcome", "").lower()
            passed = outcome == "passed"
            skipped = outcome in ("notexecuted", "skipped", "inconclusive")
            failure = case.find("./Output/ErrorInfo")
            message = "\n".join(failure.itertext()).strip() if failure is not None else f"Outcome: {outcome}"
        else:
            failure = case.find("failure")
            if failure is None:
                failure = case.find("error")
            skipped = case.find("skipped") is not None and failure is None
            passed = failure is None and not skipped
            message = ""
            if failure is not None:
                message = "\n".join(filter(None, [failure.get("message"), "".join(failure.itertext()).strip()]))
        if passed:
            results.passed += 1
        elif skipped:
            results.skipped += 1
        else:
            results.failed += 1
            results.failures.append((name or "Unnamed test", message))

    # A host/collection failure can have no test cases. Do not turn that into an empty successful report.
    if trx:
        summary = root.find("ResultSummary")
        if (
            summary is not None
            and summary.get("outcome", "").lower() in ("failed", "error", "aborted")
            and not results.failed
        ):
            results.failed += 1
            results.failures.append(("Test run", "\n".join(summary.itertext()).strip() or summary.get("outcome")))
    else:
        for suite in root.iter("testsuite"):
            if not list(suite.iter("testcase")):
                failed = number(suite.get("failures", "0"), "test failures") + number(
                    suite.get("errors", "0"), "test errors"
                )
                if failed:
                    results.failed += failed
                    results.failures.append((suite.get("name", "Test suite"), "\n".join(suite.itertext()).strip()))
    return results


def test_report(paths, output):
    total = TestResults()
    rows, failures = [], []
    for path in paths:
        result = read_tests(path)
        for attr in ("passed", "failed", "skipped", "seconds"):
            setattr(total, attr, getattr(total, attr) + getattr(result, attr))
        rows.append(
            f"| {table_text(Path(path).name)} | {result.passed} | {result.failed} | {result.skipped} | {result.seconds:.3f}s |"
        )
        failures.extend((Path(path).name, name, message) for name, message in result.failures)
    markdown = "## Tests\n\n| Report | Passed | Failed | Skipped | Duration¹ |\n| --- | --- | --- | --- | --- |\n"
    markdown += "\n".join(rows)
    markdown += (
        f"\n| **Total** | {total.passed} | {total.failed} | {total.skipped} | {total.seconds:.3f}s |\n"
        "\n¹ Sum of test durations; parallel tests can exceed wall-clock time.\n"
    )
    for report, name, message in failures[:50]:
        markdown += (
            f"\n<details>\n<summary>{html.escape(name)} ({html.escape(report)})</summary>\n\n"
            f"<pre>{html.escape(message[:8000])}</pre>\n</details>\n"
        )
    if len(failures) > 50:
        markdown += f"\nShowing 50 of {len(failures)} failures; see the raw results for the remainder.\n"
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "SummaryGithub.md").write_text(markdown, encoding="utf-8")
    return markdown, total.failed


def find_reports(patterns):
    paths = set()
    for pattern in patterns:
        # One glob per line makes paths containing spaces unambiguous in action inputs.
        for item in pattern.splitlines():
            if not item.strip():
                continue
            matches = [Path(p).resolve() for p in glob.glob(item.strip(), recursive=True) if Path(p).is_file()]
            if not matches:
                raise ValueError(f"No reports matched {item!r}.")
            paths.update(matches)
    return sorted(paths)


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", action="append", default=[])
    parser.add_argument("--tests", action="append", default=[])
    parser.add_argument("--coverage-directory", default="artifacts/coverage")
    parser.add_argument("--test-directory", default="artifacts/test-results")
    parser.add_argument("--assembly-filters", default="+*")
    parser.add_argument("--file-filters", default="+*")
    args = parser.parse_args(arguments)
    failed = 0
    reporting_failed = False
    summaries = []
    if not args.coverage and not args.tests:
        print("Reporting failed: Supply --coverage and/or --tests report globs.", file=sys.stderr)
        return 1
    for kind, patterns in (("tests", args.tests), ("coverage", args.coverage)):
        if not patterns:
            continue
        try:
            paths = find_reports(patterns)
            if kind == "tests":
                markdown, failed = test_report(paths, args.test_directory)
            else:
                markdown = coverage_report(paths, args.coverage_directory, args.assembly_filters, args.file_filters)
            summaries.append(markdown)
        except (ValueError, OSError) as error:
            print(f"Reporting failed ({kind}): {error}", file=sys.stderr)
            reporting_failed = True
    # Preserve available summaries even when another input is missing or malformed.
    if summaries:
        markdown = "\n".join(summaries)
        print(markdown)
        if target := os.environ.get("GITHUB_STEP_SUMMARY"):
            try:
                with open(target, "a", encoding="utf-8") as file:
                    file.write(markdown + "\n")
            except OSError as error:
                print(f"Cannot write job summary: {error}", file=sys.stderr)
                reporting_failed = True
    return 1 if failed or reporting_failed else 0


if __name__ == "__main__":
    sys.exit(main())
