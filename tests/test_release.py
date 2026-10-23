# SPDX-License-Identifier: GPL-3.0-only
import subprocess

import pytest

from scripts import build

SHA = "1" * 40


@pytest.fixture
def release(tmp_path, monkeypatch, runner):
    monkeypatch.setenv("GH_REPO", "example/library")
    monkeypatch.setenv("VERSION", "1.2.3")
    monkeypatch.setenv("COMMIT", SHA)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))

    def handle(args, kwargs):
        if args[:2] == ("git", "rev-parse") or "/commits/" in " ".join(args):
            return 0, SHA
        if "/tags?" in " ".join(args):
            return 0, "v1.9.5\nv1.10.3\nv2.0.0-preview\nv1.8.9\nv01.99.0"
        return 0, ""

    runner.handler = handle
    return tmp_path


def test_next_minor_version_uses_highest_stable_tag(release, monkeypatch):
    monkeypatch.delenv("VERSION")
    build.release_version()
    assert (release / "output").read_text() == "version=1.11.0\n"
    assert "**1.11.0**" in (release / "summary").read_text()


def test_next_minor_version_orders_major_before_minor(release, monkeypatch, runner):
    monkeypatch.delenv("VERSION")
    runner.handler = lambda args, kwargs: (0, "v1.99.9\nv2.0.4\nv2.0.3")
    build.release_version()
    assert (release / "output").read_text() == "version=2.1.0\n"


def test_explicit_version_does_not_query_github(release, runner):
    build.release_version()
    assert (release / "output").read_text() == "version=1.2.3\n"
    assert not runner.calls


@pytest.mark.parametrize("value", ["v1.2.3", "1.2.3-preview", "01.2.3", "", "1.2.3\n", "1.2.3; echo unsafe"])
def test_invalid_versions_rejected(value):
    with pytest.raises(ValueError, match="stable version"):
        build.version(value)


@pytest.mark.parametrize("tags", ["", "v1.2.3-preview\nnot-a-tag", "1.2.3\nv01.2.3"])
def test_no_stable_tag_requires_explicit_version(release, monkeypatch, runner, tags):
    monkeypatch.delenv("VERSION")
    runner.handler = lambda args, kwargs: (0, tags)
    with pytest.raises(ValueError, match="No stable"):
        build.release_version()
    assert not (release / "output").exists()


def test_failed_tag_lookup_cannot_resolve_a_version(release, monkeypatch, runner):
    monkeypatch.delenv("VERSION")
    runner.handler = lambda args, kwargs: (7, "network failed")
    with pytest.raises(subprocess.CalledProcessError):
        build.release_version()
    assert not (release / "output").exists()


def test_release_tags_the_tested_commit(release, runner):
    build.create_release()
    post = runner.commands("gh", "api", "--method", "POST")
    assert post == [
        (
            "gh",
            "api",
            "--method",
            "POST",
            "repos/example/library/git/refs",
            "-f",
            "ref=refs/tags/v1.2.3",
            "-f",
            f"sha={SHA}",
        )
    ]
    assert runner.commands("gh", "release", "create") == [
        (
            "gh",
            "release",
            "create",
            "v1.2.3",
            "--repo",
            "example/library",
            "--verify-tag",
            "--target",
            SHA,
            "--generate-notes",
        )
    ]


@pytest.mark.parametrize("annotated", [True, False])
def test_existing_matching_tag_is_preserved(release, runner, annotated):
    previous = runner.handler

    def handle(args, kwargs):
        if "/matching-refs/" in " ".join(args):
            return 0, f"tag\t{'2' * 40}" if annotated else f"commit\t{SHA}"
        if "/git/tags/" in " ".join(args):
            return 0, f"commit\t{SHA}"
        return previous(args, kwargs)

    runner.handler = handle
    build.create_release()
    assert not runner.commands("gh", "api", "--method", "POST")
    assert len(runner.commands("gh", "release", "create")) == 1


def test_conflicting_tag_blocks_release(release, runner):
    previous = runner.handler
    runner.handler = lambda args, kwargs: (
        (0, f"commit\t{'2' * 40}") if "/matching-refs/" in " ".join(args) else previous(args, kwargs)
    )
    with pytest.raises(ValueError, match="refusing to move"):
        build.create_release()
    assert not runner.commands("gh", "api", "--method", "POST")
    assert not runner.commands("gh", "release")


def test_release_rejects_unresolved_commit_before_network(release, monkeypatch, runner):
    monkeypatch.setenv("COMMIT", "main")
    with pytest.raises(ValueError, match="full, resolved"):
        build.create_release()
    assert not runner.calls


@pytest.mark.parametrize("override", ["", "docs/fix", "docs/fix #summary"])
def test_documentation_update_resolves_released_version_and_encoded_source(release, monkeypatch, runner, override):
    monkeypatch.setenv("API_REF", override)
    build.release_source()
    ref = {"": "v1.10.3", "docs/fix": "docs%2Ffix", "docs/fix #summary": "docs%2Ffix%20%23summary"}[override]
    assert any(f"repos/example/library/commits/{ref}" in args for args, _ in runner.calls)
    assert (release / "output").read_text() == f"version=1.10.3\ncommit={SHA}\n"
    assert ("override is active" in (release / "summary").read_text()) == bool(override)
    assert not runner.commands("gh", "release")


@pytest.mark.parametrize("expected,allowed", [("1.10.3", True), ("1.10.2", False), ("1.11.0", False)])
def test_documentation_freshness_requires_latest_release(release, monkeypatch, expected, allowed):
    monkeypatch.setenv("VERSION", expected)
    if allowed:
        build.freshness()
    else:
        with pytest.raises(ValueError, match="Refusing to deploy"):
            build.freshness()
