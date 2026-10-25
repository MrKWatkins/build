# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the published composite's actual guards, including string-valued inputs."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project():
    return yaml.safe_load((ROOT / "dotnet/project/action.yml").read_text())


def selected_steps(project, **overrides):
    inputs = {name: settings.get("default", "") for name, settings in project["inputs"].items()}
    inputs.update(overrides)
    result = []
    for step in project["runs"]["steps"]:
        condition = str(step.get("if", "True")).removeprefix("${{").removesuffix("}}").strip()
        condition = re.sub(r"inputs\.([\w-]+)", lambda match: repr(inputs[match[1]]), condition)
        condition = condition.replace("&&", " and ").replace("||", " or ")
        # Expressions come exclusively from the checked-in action, never user input.
        if eval(condition, {"__builtins__": {}}, {}):
            result.append(step)
    return result


@pytest.mark.parametrize("packages,docs", [("false", "false"), ("true", "true"), ("true", "false"), ("false", "true")])
def test_publication_modes_build_and_publish_only_selected_artifacts(project, packages, docs):
    steps = selected_steps(project, **{"publish-packages": packages, "publish-docs": docs})
    names = [step.get("name") for step in steps]
    uses = [step.get("uses", "") for step in steps]
    assert ("Build and test .NET" in names) == (packages == docs == "false")
    assert ("Build, test and pack .NET" in names) == (packages == "true")
    assert ("Build released API assemblies" in names) == (docs == "true" and packages == "false")
    assert "Build and validate documentation" in names
    assert ("Upload packages" in names) == (packages == "true")
    assert ("Upload validated site" in names) == (docs == "true")
    assert ("Publish NuGet packages" in names) == (packages == "true")
    assert ("Create GitHub release" in names) == (packages == "true")
    assert ("Deploy documentation" in names) == (docs == "true")
    # Prepared packages stay in the current job; no artifact download or publishing SDK install.
    assert not any("download-artifact" in action for action in uses)
    assert sum("setup-dotnet" in action for action in uses) == (docs == "true" and packages == "false")
    if packages == "true":
        assert (
            names.index("Build and validate documentation")
            < names.index("Publish NuGet packages")
            < names.index("Create GitHub release")
        )
    if docs == "true":
        assert (
            names.index("Build and validate documentation")
            < names.index("Upload validated site")
            < names.index("Deploy documentation")
        )


def test_project_defaults_never_publish(project):
    names = [step.get("name") for step in selected_steps(project)]
    assert "Build and test .NET" in names
    assert "Publish NuGet packages" not in names
    assert "Create GitHub release" not in names
    assert "Deploy documentation" not in names


def test_project_prepares_assets_for_all_build_modes(project):
    for packages, docs in [("false", "false"), ("true", "true"), ("true", "false"), ("false", "true")]:
        steps = selected_steps(
            project, prepare="scripts/prepare.py", **{"publish-packages": packages, "publish-docs": docs}
        )
        names = [step.get("name") for step in steps]
        assert (
            next(step for step in steps if step.get("name") == "Set up preparation Node")["with"]["node-version"]
            == "24"
        )
        if packages == "true":
            assert (
                next(step for step in steps if step.get("name") == "Build, test and pack .NET")["with"]["prepare"]
                == "${{ inputs.prepare }}"
            )
        elif docs == "true":
            assert (
                names.index("Install API build SDK")
                < names.index("Prepare project assets")
                < names.index("Build released API assemblies")
            )
            hook = next(step for step in steps if step.get("name") == "Prepare project assets")
            assert hook["env"]["VERSION"] == "${{ steps.api.outputs.version }}"
        else:
            assert (
                next(step for step in steps if step.get("name") == "Build and test .NET")["with"]["prepare"]
                == "${{ inputs.prepare }}"
            )
        assert ("Prepare project assets" in names) == (packages == "false" and docs == "true")


def test_package_release_without_site_skips_documentation(project):
    steps = selected_steps(project, docs="false", **{"publish-packages": "true"})
    names = [step.get("name") for step in steps]
    assert "Build, test and pack .NET" in names
    assert "Publish NuGet packages" in names
    assert "Build and validate documentation" not in names
    assert "Upload validated site" not in names
    assert "Deploy documentation" not in names


def test_release_pins_tested_version_commit_and_pages_artifact(project):
    steps = {step.get("name"): step for step in project["runs"]["steps"]}
    release = steps["Create GitHub release"]["with"]
    assert release == {
        "version": "${{ steps.version.outputs.version }}",
        "commit": "${{ steps.source.outputs.commit }}",
    }
    assert steps["Build, test and pack .NET"]["with"]["version"] == release["version"]
    assert (
        steps["Deploy documentation"]["with"]["version"]
        == "${{ steps.api.outputs.version || steps.version.outputs.version }}"
    )
    assert steps["Upload validated site"]["with"]["path"] == "artifacts/docs"
    assert steps["Publish NuGet packages"]["with"]["nuget-user"] == "${{ inputs.nuget-user }}"


def test_inline_action_code_compiles_and_references_existing_scripts():
    for action in ROOT.glob("*/*/action.yml"):
        settings = yaml.safe_load(action.read_text())
        for step in settings["runs"]["steps"]:
            if step.get("shell") == "python":
                compile(step["run"], str(action), "exec")
                if path := step.get("env", {}).get("BUILD_SCRIPT"):
                    assert (action.parent / path.split("}}/")[1]).resolve().is_file(), action
