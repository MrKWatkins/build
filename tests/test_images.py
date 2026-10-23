# SPDX-License-Identifier: GPL-3.0-only
"""Image publication gates exercised without contacting Docker or GHCR."""

import subprocess
import sys

import pytest

from scripts import build

SHA = "1" * 40
IMAGE_VERSION = f"sha-{SHA}"
BASE_ID = "sha256:" + "4" * 64
REGISTRY = "ghcr.io/mrkwatkins"
NAMES = ("docs-base", "docs-dotnet")


@pytest.fixture
def images(runner):
    state = {
        "used_base": BASE_ID,
        "revision": SHA,
        "version": IMAGE_VERSION,
        "manifest_existing": None,
        "api_tags": "",
        "api_status": 0,
        "private": None,
        "validation_status": 0,
        "build_status": 0,
    }

    def handle(args, kwargs):
        if args[:3] == ("git", "rev-parse", "HEAD"):
            return 0, SHA
        if args[:3] == ("docker", "image", "inspect"):
            expression = args[4]
            if expression == "{{.Id}}":
                return 0, BASE_ID
            if "base-image-id" in expression:
                return 0, state["used_base"]
            if "image.revision" in expression:
                return 0, state["revision"]
            if "image.version" in expression:
                return 0, state["version"]
            if "RepoDigests" in expression:
                return 0, f"{REGISTRY}/docs-base@sha256:" + "2" * 64
            pytest.fail(f"Unexpected Docker inspection: {args}")
        if args[:3] == ("docker", "manifest", "inspect"):
            return (0 if state["manifest_existing"] in (args[-1], "all") else 1), ""
        if args[:2] == ("docker", "--config"):
            return (1 if state["private"] in (args[-1], "all") else 0), ""
        if args[:2] == ("gh", "api"):
            return state["api_status"], state["api_tags"]
        if args[:2] == ("docker", "build"):
            return state["build_status"], ""
        if args[:3] == (sys.executable, "-m", "pytest"):
            return state["validation_status"], ""
        if args[:2] in (("docker", "tag"), ("docker", "push"), ("docker", "run")):
            return 0, ""
        pytest.fail(f"Unexpected external command: {args}")

    runner.handler = handle
    return state


def test_builds_each_image_once_and_validates_exact_local_pair(runner, images):
    build.build_images()

    builds = runner.commands("docker", "build")
    assert len(builds) == 2
    assert builds[0][builds[0].index("-f") + 1] == "images/docs-base/Dockerfile"
    assert builds[1][builds[1].index("-f") + 1] == "images/docs-dotnet/Dockerfile"
    assert "BASE_IMAGE=docs-base:local" in builds[1]
    assert f"io.mrkwatkins.build.base-image-id={BASE_ID}" in builds[1]
    for command in builds:
        assert f"org.opencontainers.image.revision={SHA}" in command
        assert f"org.opencontainers.image.version={IMAGE_VERSION}" in command
    tests = runner.commands(sys.executable, "-m", "pytest")
    assert tests == [(sys.executable, "-m", "pytest", "tests/test_docs.py", "--run-docker")]
    environment = next(kwargs["env"] for args, kwargs in runner.calls if args == tests[0])
    assert environment["DOCS_BASE_TEST_IMAGE"] == "docs-base:local"
    assert environment["DOCS_TEST_IMAGE"] == "docs-dotnet:local"
    assert "VERSION" not in environment
    assert not runner.commands("docker", "push")


def test_build_validation_failure_stops_before_publication(runner, images):
    images["validation_status"] = 7
    with pytest.raises(subprocess.CalledProcessError) as failure:
        build.build_images()
        build.publish_images()
    assert failure.value.returncode == 7
    assert not runner.commands("docker", "push")
    assert not runner.commands("docker", "manifest")


def test_image_build_failure_stops_before_validation(runner, images):
    images["build_status"] = 8
    with pytest.raises(subprocess.CalledProcessError) as failure:
        build.build_images()
    assert failure.value.returncode == 8
    assert len(runner.commands("docker", "build")) == 1
    assert not runner.commands(sys.executable, "-m", "pytest")
    assert not runner.commands("docker", "push")


@pytest.mark.parametrize("image_version", ["sha-invalid", "sha-" + "3" * 40, "latest", "1.2.3"])
@pytest.mark.parametrize("operation", [build.build_images, build.publish_images])
def test_malformed_or_wrong_commit_tag_stops_before_docker(monkeypatch, runner, images, image_version, operation):
    monkeypatch.setenv("IMAGE_VERSION", image_version)
    with pytest.raises(ValueError, match="checked-out source commit"):
        operation()
    assert not runner.commands("docker")
    assert not runner.commands("gh")


def test_publication_uploads_prepared_pair_without_building_or_testing(runner, images):
    build.publish_images()

    assert not runner.commands("docker", "build")
    assert not runner.commands(sys.executable, "-m", "pytest")
    assert runner.commands("docker", "push") == [
        ("docker", "push", f"{REGISTRY}/docs-base:{IMAGE_VERSION}"),
        ("docker", "push", f"{REGISTRY}/docs-dotnet:{IMAGE_VERSION}"),
        ("docker", "push", f"{REGISTRY}/docs-base:latest"),
        ("docker", "push", f"{REGISTRY}/docs-dotnet:latest"),
    ]
    assert runner.commands("docker", "tag") == [
        ("docker", "tag", f"{name}:local", f"{REGISTRY}/{name}:{IMAGE_VERSION}") for name in NAMES
    ] + [("docker", "tag", f"{REGISTRY}/{name}:{IMAGE_VERSION}", f"{REGISTRY}/{name}:latest") for name in NAMES]
    first_push = next(index for index, (args, _) in enumerate(runner.calls) if args[:2] == ("docker", "push"))
    checked_packages = [args[3] for args, _ in runner.calls[:first_push] if args[:3] == ("gh", "api", "--paginate")]
    assert checked_packages == [f"/users/MrKWatkins/packages/container/{name}/versions?per_page=100" for name in NAMES]
    public_checks = [
        (index, args) for index, (args, _) in enumerate(runner.calls) if args[:2] == ("docker", "--config")
    ]
    assert [args[-1] for _, args in public_checks] == [f"{REGISTRY}/{name}:{IMAGE_VERSION}" for name in NAMES]
    first_latest = next(
        index for index, (args, _) in enumerate(runner.calls) if any(arg.endswith(":latest") for arg in args)
    )
    assert all(index < first_latest for index, _ in public_checks)


@pytest.mark.parametrize(
    "state_key,value,diagnostic",
    [
        ("used_base", "wrong", "exact base image"),
        ("revision", "wrong", "source commit"),
        ("version", "wrong", "image version"),
    ],
)
def test_incompatible_image_pair_stops_before_registry(runner, images, state_key, value, diagnostic):
    images[state_key] = value
    with pytest.raises(ValueError, match=diagnostic):
        build.publish_images()
    assert not runner.commands("docker", "manifest")
    assert not runner.commands("gh", "api")
    assert not runner.commands("docker", "push")


@pytest.mark.parametrize("existing_source", ["manifest", "package-api"])
def test_existing_immutable_tag_on_either_registry_source_blocks_all_pushes(runner, images, existing_source):
    if existing_source == "manifest":
        images["manifest_existing"] = f"{REGISTRY}/docs-dotnet:{IMAGE_VERSION}"
    else:
        images["api_tags"] = f"latest\n{IMAGE_VERSION}\n"
    with pytest.raises(ValueError, match="Immutable tag already exists"):
        build.publish_images()
    assert not runner.commands("docker", "tag")
    assert not runner.commands("docker", "push")


def test_private_image_never_advances_latest(runner, images):
    images["private"] = f"{REGISTRY}/docs-dotnet:{IMAGE_VERSION}"
    with pytest.raises(ValueError, match="Make the GHCR package public"):
        build.publish_images()
    assert runner.commands("docker", "push") == [
        ("docker", "push", f"{REGISTRY}/{name}:{IMAGE_VERSION}") for name in NAMES
    ]
    assert not any(arg.endswith(":latest") for args, _ in runner.calls for arg in args)


def test_inaccessible_package_api_blocks_all_pushes(runner, images):
    images.update(api_status=1, api_tags="gh: Forbidden (HTTP 403)")
    with pytest.raises(ValueError, match="Cannot establish"):
        build.publish_images()
    assert not runner.commands("docker", "push")


def test_absent_package_api_can_publish(runner, images):
    images.update(api_status=1, api_tags="gh: Not Found (HTTP 404)")
    build.publish_images()
    assert len(runner.commands("docker", "push")) == 4


def test_similar_but_different_existing_tag_does_not_block_publication(runner, images):
    images["api_tags"] = f"{IMAGE_VERSION}-other\n"
    build.publish_images()
    assert len(runner.commands("docker", "push")) == 4
