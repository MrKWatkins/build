"""Merge verified Dependabot minor/patch PRs only after their latest CI run passes."""

import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml

BOT = "dependabot[bot]"
AUTOMATIC_UPDATES = {"version-update:semver-minor", "version-update:semver-patch"}


class GitHub:
    def __init__(self, repository, token):
        self.base = f"https://api.github.com/repos/{repository}"
        self.token = token

    def request(self, path, data=None, method=None):
        request = Request(
            self.base + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method or ("PUT" if data is not None else "GET"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urlopen(request, timeout=30) as response:
            return None if response.status == 204 else json.load(response)

    def pages(self, path):
        for page in range(1, 101):
            items = self.request(f"{path}?per_page=100&page={page}")
            yield from items
            if len(items) < 100:
                return
        raise RuntimeError("GitHub pagination limit exceeded; refusing to merge.")


def minor_or_patch(commit):
    if (commit.get("author") or {}).get("login") != BOT:
        return False
    details = commit["commit"]
    if not details.get("verification", {}).get("verified"):
        return False
    fragment = re.search(r"^---\n(.*?)^\.\.\.\s*$", details["message"], re.MULTILINE | re.DOTALL)
    if not fragment:
        return False
    try:
        metadata = yaml.safe_load(fragment[1])
    except yaml.YAMLError:
        return False
    dependencies = metadata.get("updated-dependencies") if isinstance(metadata, dict) else None
    return (
        bool(dependencies)
        and isinstance(dependencies, list)
        and all(
            isinstance(dependency, dict) and dependency.get("update-type") in AUTOMATIC_UPDATES
            for dependency in dependencies
        )
    )


def delete_merged_branch(github, branch, tested_sha):
    # GitHub may already have deleted it through the repository's automatic cleanup setting.
    ref = "heads/" + quote(branch, safe="/")
    try:
        current = github.request("/git/ref/" + ref)
        if current["object"]["sha"] != tested_sha:
            print(f"Branch {branch} has changed since the tested merge; leaving it intact.")
            return
        github.request("/git/refs/" + ref, method="DELETE")
        print(f"Deleted merged branch {branch}.")
    except HTTPError as error:
        if error.code != 404:
            raise
        print(f"Merged branch {branch} is already deleted.")


def merge_updates(event, github, dispatch_build=False):
    run = event.get("workflow_run", {})
    repository = event["repository"]
    name = repository["full_name"]
    if (
        run.get("event") != "pull_request"
        or run.get("conclusion") != "success"
        or (run.get("head_repository") or {}).get("full_name") != name
    ):
        print("No successful same-repository pull request build; nothing to merge.")
        return
    latest = github.request(f"/actions/runs/{run['id']}")
    if (
        latest.get("conclusion") != "success"
        or latest.get("status") != "completed"
        or latest.get("head_sha") != run["head_sha"]
        or latest.get("run_attempt") != run.get("run_attempt")
    ):
        print("The successful build has been superseded; nothing to merge.")
        return
    associated = run.get("pull_requests") or list(github.pages(f"/commits/{run['head_sha']}/pulls"))
    for reference in associated:
        number = reference["number"]
        pr = github.request(f"/pulls/{number}")
        if (
            pr.get("state") != "open"
            or pr.get("draft")
            or pr.get("user", {}).get("login") != BOT
            or pr["base"]["ref"] != repository["default_branch"]
            or (pr["head"].get("repo") or {}).get("full_name") != name
            or pr["head"]["sha"] != run["head_sha"]
            or not pr["head"]["ref"].startswith("dependabot/")
        ):
            print(f"PR #{number} is not an eligible tested Dependabot PR.")
            continue
        commits = list(github.pages(f"/pulls/{number}/commits"))
        if (
            len(commits) != pr["commits"]
            or not commits
            or commits[-1]["sha"] != run["head_sha"]
            or not all(minor_or_patch(commit) for commit in commits)
        ):
            print(f"PR #{number} contains a major, unknown, or unverified update; leaving it for review.")
            continue
        settings = github.request("")
        methods = {"squash": "allow_squash_merge", "merge": "allow_merge_commit", "rebase": "allow_rebase_merge"}
        method = next((method for method, setting in methods.items() if settings.get(setting)), None)
        if method is None:
            raise RuntimeError("No permitted merge method; refusing to merge.")
        result = github.request(f"/pulls/{number}/merge", {"sha": run["head_sha"], "merge_method": method})
        if not result.get("merged"):
            raise RuntimeError(f"GitHub did not merge PR #{number}: {result.get('message')}")
        print(f"Merged tested minor/patch updates in PR #{number}.")
        delete_merged_branch(github, pr["head"]["ref"], run["head_sha"])
        if dispatch_build:
            # GITHUB_TOKEN merges do not generate push workflow runs. Build's main run publishes its tested images.
            github.request(
                f"/actions/workflows/{run['workflow_id']}/dispatches",
                {"ref": repository["default_branch"]},
                method="POST",
            )


if __name__ == "__main__":
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    merge_updates(
        event,
        GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]),
        dispatch_build=os.environ.get("DEPENDABOT_DISPATCH_BUILD") == "true",
    )
