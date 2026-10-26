# SPDX-License-Identifier: GPL-3.0-only
import subprocess

import pytest

from scripts import build


def pytest_addoption(parser):
    parser.addoption("--run-docker", action="store_true", help="Run real documentation image integration tests.")
    parser.addoption("--run-dotnet", action="store_true", help="Run real SDK packaging integration tests.")


def pytest_collection_modifyitems(config, items):
    for item in items:
        for marker in ("docker", "dotnet"):
            if marker in item.keywords and not config.getoption(f"--run-{marker}"):
                item.add_marker(pytest.mark.skip(reason=f"Use --run-{marker} for integration tests."))


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in (
        "VERSION",
        "COMMIT",
        "GH_REPO",
        "GITHUB_REPOSITORY",
        "GITHUB_OUTPUT",
        "GITHUB_STEP_SUMMARY",
        "BUILD_DIRECTORY",
        "PREPARE_SCRIPT",
        "PACKAGE_DIRECTORY",
        "COVERAGE",
        "COVERAGE_DIRECTORY",
        "TEST_FILTER",
        "COVERAGE_ASSEMBLY_FILTERS",
        "COVERAGE_FILE_FILTERS",
        "TEST_REPORT",
        "TEST_RESULTS_DIRECTORY",
        "API_DIRECTORY",
        "DOCS_CONFIG",
        "API_REF",
        "DOCS_PORT",
        "IMAGE_VERSION",
        "NUGET_API_KEY",
        "CONFIG",
        "OUTPUT",
        "SOURCE_REF",
        "DOCS_IMAGE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def runner(monkeypatch):
    class Runner:
        def __init__(self):
            self.calls = []
            self.handler = lambda args, kwargs: (0, "")

        def __call__(self, *args, **kwargs):
            args = tuple(map(str, args))
            self.calls.append((args, kwargs))
            code, text = self.handler(args, kwargs)
            result = subprocess.CompletedProcess(args, code, text)
            if kwargs.get("check", True):
                result.check_returncode()
            return result

        def commands(self, *prefix):
            return [args for args, _ in self.calls if args[: len(prefix)] == prefix]

    fake = Runner()
    monkeypatch.setattr(build, "run", fake)
    return fake
