"""The automatic merge boundary must reject untested or untrusted changes."""

import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "dependabot_merge", Path(__file__).parents[1] / "dependabot/merge/merge.py"
)
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)


def commit(update="minor", sha="tested"):
    return {
        "sha": sha,
        "author": {"login": merge.BOT},
        "commit": {
            "verification": {"verified": True},
            "message": f"Bump dependencies\n\n---\nupdated-dependencies:\n- dependency-name: example\n"
            f"  update-type: version-update:semver-{update}\n...\n",
        },
    }


@pytest.fixture
def scenario():
    repository = {"full_name": "owner/repo", "default_branch": "main"}
    run = {
        "id": 4,
        "workflow_id": 5,
        "run_attempt": 1,
        "status": "completed",
        "event": "pull_request",
        "conclusion": "success",
        "head_repository": repository,
        "head_sha": "tested",
        "pull_requests": [{"number": 2}],
    }
    pr = {
        "state": "open",
        "draft": False,
        "user": {"login": merge.BOT},
        "base": {"ref": "main"},
        "head": {"repo": repository, "sha": "tested", "ref": "dependabot/nuget/minor-and-patch-123"},
        "commits": 1,
    }

    class GitHub:
        def __init__(self):
            self.values = {
                "/actions/runs/4": copy.deepcopy(run),
                "/pulls/2": pr,
                "/pulls/2/commits": [commit()],
                "/commits/tested/pulls": [{"number": 2}],
                "": {"allow_squash_merge": True},
                "/pulls/2/merge": {"merged": True},
                "/actions/workflows/5/dispatches": None,
            }
            self.writes = []

        def request(self, path, data=None, method=None):
            if data is not None:
                self.writes.append((path, data, method))
            return self.values[path]

        def pages(self, path):
            return self.values[path]

    return {"repository": repository, "workflow_run": run}, GitHub()


@pytest.mark.parametrize("update", ["minor", "patch"])
def test_merge_passed_minor_updates_at_exact_tested_commit(scenario, update):
    event, github = scenario
    github.values["/pulls/2/commits"] = [commit(update)]
    merge.merge_updates(event, github)
    assert github.writes == [("/pulls/2/merge", {"sha": "tested", "merge_method": "squash"}, None)]


@pytest.mark.parametrize("update", ["major", "unknown"])
def test_leave_major_or_unknown_updates_for_review(scenario, update):
    event, github = scenario
    github.values["/pulls/2/commits"] = [commit(update)]
    merge.merge_updates(event, github)
    assert github.writes == []


@pytest.mark.parametrize("change", ["failure", "push", "fork", "missing-head-repository"])
def test_reject_ineligible_build(scenario, change):
    event, github = scenario
    run = event["workflow_run"]
    if change == "failure":
        run["conclusion"] = "failure"
    elif change == "push":
        run["event"] = "push"
    else:
        run["head_repository"] = {"full_name": "fork/repo"} if change == "fork" else None
    merge.merge_updates(event, github)
    assert github.writes == []


@pytest.mark.parametrize(
    "field,value", [("conclusion", "failure"), ("status", "in_progress"), ("run_attempt", 2), ("head_sha", "other")]
)
def test_reject_superseded_build(scenario, field, value):
    event, github = scenario
    github.values["/actions/runs/4"][field] = value
    merge.merge_updates(event, github)
    assert github.writes == []


@pytest.mark.parametrize("change", ["human", "closed", "draft", "branch", "fork", "head", "base"])
def test_reject_ineligible_pull_request(scenario, change):
    event, github = scenario
    pr = github.values["/pulls/2"]
    if change == "human":
        pr["user"]["login"] = "human"
    elif change == "closed":
        pr["state"] = "closed"
    elif change == "draft":
        pr["draft"] = True
    elif change == "base":
        pr["base"]["ref"] = "release"
    elif change == "branch":
        pr["head"]["ref"] = "human-branch"
    elif change == "head":
        pr["head"]["sha"] = "untested"
    else:
        pr["head"]["repo"] = {"full_name": "fork/repo"}
    merge.merge_updates(event, github)
    assert github.writes == []


@pytest.mark.parametrize("change", ["human", "unsigned", "missing-metadata", "malformed-metadata", "missing-author"])
def test_reject_untrusted_commit(scenario, change):
    event, github = scenario
    value = github.values["/pulls/2/commits"][0]
    if change == "human":
        value["author"]["login"] = "human"
    elif change == "unsigned":
        value["commit"]["verification"]["verified"] = False
    elif change == "missing-author":
        value["author"] = None
    else:
        value["commit"]["message"] = "no metadata" if change == "missing-metadata" else "---\n[\n...\n"
    merge.merge_updates(event, github)
    assert github.writes == []


def test_reject_major_dependency_in_mixed_group(scenario):
    event, github = scenario
    details = github.values["/pulls/2/commits"][0]["commit"]
    details["message"] = details["message"].replace(
        "...", "- dependency-name: breaking\n  update-type: version-update:semver-major\n..."
    )
    merge.merge_updates(event, github)
    assert github.writes == []


def test_reject_major_update_in_earlier_commit(scenario):
    event, github = scenario
    github.values["/pulls/2"]["commits"] = 2
    github.values["/pulls/2/commits"].insert(0, commit("major", "older"))
    merge.merge_updates(event, github)
    assert github.writes == []


def test_reject_incomplete_commit_list(scenario):
    event, github = scenario
    github.values["/pulls/2"]["commits"] = 2
    merge.merge_updates(event, github)
    assert github.writes == []


def test_find_pull_request_when_run_association_is_empty(scenario):
    event, github = scenario
    event["workflow_run"]["pull_requests"] = []
    merge.merge_updates(event, github)
    assert github.writes[0][1]["sha"] == "tested"


@pytest.mark.parametrize("setting,method", [("allow_merge_commit", "merge"), ("allow_rebase_merge", "rebase")])
def test_respect_repository_merge_method(scenario, setting, method):
    event, github = scenario
    github.values[""] = {setting: True}
    merge.merge_updates(event, github)
    assert github.writes[0][1]["merge_method"] == method


def test_reject_repository_without_permitted_merge_method(scenario):
    event, github = scenario
    github.values[""] = {}
    with pytest.raises(RuntimeError, match="No permitted merge method"):
        merge.merge_updates(event, github)
    assert github.writes == []


def test_respect_github_refusal_to_merge(scenario):
    event, github = scenario
    github.values["/pulls/2/merge"] = {"merged": False, "message": "Review required"}
    with pytest.raises(RuntimeError, match="Review required"):
        merge.merge_updates(event, github)
    assert len(github.writes) == 1


def test_dispatch_default_branch_build_only_after_merge(scenario):
    event, github = scenario
    merge.merge_updates(event, github, dispatch_build=True)
    assert github.writes[-1] == ("/actions/workflows/5/dispatches", {"ref": "main"}, "POST")


def test_never_dispatch_build_for_major_update(scenario):
    event, github = scenario
    github.values["/pulls/2/commits"] = [commit("major")]
    merge.merge_updates(event, github, dispatch_build=True)
    assert github.writes == []
