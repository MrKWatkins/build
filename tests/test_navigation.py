# SPDX-License-Identifier: GPL-3.0-only
"""Test the VitePress menu builder through its JavaScript entry point."""

import json
import subprocess
from pathlib import Path

import pytest

NAVIGATION = Path(__file__).resolve().parents[1] / "docs/tooling/navigation.mjs"
PROGRAM = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const { apiNavigation } = await import(pathToFileURL(process.argv[1]));
const input = JSON.parse(readFileSync(0, 'utf8'));
const result = await apiNavigation(input.manifest, async file => {
  if (!(file in input.pages)) throw new Error('Unexpected page read: ' + file);
  return input.pages[file];
});
console.log(JSON.stringify(result));
"""


def entry(id, path, title, kind="member", parent="T:Example.Widget"):
    return {"id": id, "path": path, "title": title, "kind": kind, "parent": parent}


@pytest.fixture
def entries():
    return [
        entry("N:Example", "Example/index.md", "Example", "namespace", None),
        entry("T:Example.Widget", "Example/Widget/index.md", "Widget", "type", "N:Example"),
    ]


def navigation(entries, pages=None, *, check=True):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", PROGRAM, str(NAVIGATION)],
        input=json.dumps({"manifest": {"schemaVersion": 1, "entries": entries}, "pages": pages or {}}),
        text=True,
        capture_output=True,
        check=False,
    )
    if check:
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    return result


def test_type_menu_groups_members_like_csharp_documentation(entries):
    pages = {}
    members = [
        ("G:ctor", "-ctor", "Constructors", "Constructors"),
        ("F:Example.Widget.Empty", "Empty", "Empty", "Field"),
        ("P:Example.Widget.Count", "Count", "Count", "Property"),
        ("M:Example.Widget.Zed", "Zed", "Zed", "Method"),
        ("M:Example.Widget.Alpha", "Alpha", "Alpha", "Method"),
        ("G:op_Explicit", "op_Explicit", "Explicit", "Operator"),
        ("E:Example.Widget.Changed", "Changed", "Changed", "Event"),
    ]
    for id, name, title, heading in members:
        path = f"Example/Widget/{name}.md"
        entries.insert(0, entry(id, path, title))
        pages[path] = f"---\neditLink: false\n---\n\n# Widget.{name} {heading}\n"
    groups = navigation(entries, pages)[0]["items"][0]["items"]
    assert [group["text"] for group in groups] == [
        "Constructors",
        "Fields",
        "Properties",
        "Methods",
        "Operators",
        "Events",
    ]
    for group in groups:
        assert group["collapsed"] is True
        assert group["link"] == f"/api/Example/Widget/#{group['text'].lower()}"
    assert groups[0]["items"] == [{"text": "Widget", "link": "/api/Example/Widget/-ctor"}]
    assert groups[1]["items"] == [{"text": "Empty", "link": "/api/Example/Widget/Empty"}]
    assert groups[2]["items"] == [{"text": "Count", "link": "/api/Example/Widget/Count"}]
    assert groups[3]["items"] == [
        {"text": "Alpha", "link": "/api/Example/Widget/Alpha"},
        {"text": "Zed", "link": "/api/Example/Widget/Zed"},
    ]
    assert groups[4]["items"] == [{"text": "Explicit", "link": "/api/Example/Widget/op_Explicit"}]
    assert groups[5]["items"] == [{"text": "Changed", "link": "/api/Example/Widget/Changed"}]


def test_overload_groups_use_page_kind_and_first_heading(entries):
    entries += [entry("G:item", "Example/Widget/Item.md", "Item"), entry("G:read", "Example/Widget/Read.md", "Read")]
    pages = {
        "Example/Widget/Item.md": "# Widget.Item Property\r\n## Overloads\r\n",
        "Example/Widget/Read.md": "# Widget.Read Method\n```\n# Example Field\n```",
    }
    groups = navigation(entries, pages)[0]["items"][0]["items"]
    assert [(group["text"], group["items"][0]["text"]) for group in groups] == [
        ("Properties", "Item"),
        ("Methods", "Read"),
    ]


def test_compiler_extension_containers_hidden_but_real_methods_preserved(entries):
    generated = "<G>$" + "A" * 32
    marker = "<M>$" + "B" * 32
    entries += [
        entry("T:generated", f"Example/Widget/{generated}/index.md", f"Widget.{generated}", "type"),
        entry(
            "T:marker",
            f"Example/Widget/{generated}/{marker}/index.md",
            f"Widget.{generated}.{marker}",
            "type",
            "T:generated",
        ),
        entry("M:generated.Read", f"Example/Widget/{generated}/Read.md", "Read", parent="T:generated"),
        entry("G:Read", "Example/Widget/Read.md", "Read"),
    ]
    menu = navigation(entries, {"Example/Widget/Read.md": "# Widget.Read Method"})
    assert menu[0]["items"][0]["items"] == [
        {
            "text": "Methods",
            "link": "/api/Example/Widget/#methods",
            "collapsed": True,
            "items": [{"text": "Read", "link": "/api/Example/Widget/Read"}],
        }
    ]
    assert "$" not in json.dumps(menu)


def test_generic_and_real_nested_types_are_preserved_and_html_escaped(entries):
    entries[1]["title"] = "Widget<T>"
    entries += [entry("T:nested", "Example/Widget/Nested/index.md", "Widget<T>.Nested<U>", "type")]
    menu = navigation(entries)
    assert menu[0]["collapsed"] is False
    assert menu[0]["items"][0] == {
        "text": "Widget&lt;T&gt;",
        "link": "/api/Example/Widget/",
        "collapsed": True,
        "items": [{"text": "Widget&lt;T&gt;.Nested&lt;U&gt;", "link": "/api/Example/Widget/Nested/"}],
    }


def test_empty_types_have_no_empty_categories(entries):
    assert navigation(entries)[0]["items"] == [{"text": "Widget", "link": "/api/Example/Widget/"}]


def test_unrecognized_member_category_fails_clearly(entries):
    entries += [entry("M:Read", "Example/Widget/Read.md", "Read")]
    result = navigation(entries, {"Example/Widget/Read.md": "# Unexpected heading"}, check=False)
    assert result.returncode != 0
    assert "Cannot determine member category" in result.stderr


@pytest.mark.parametrize(
    "path", ["../escape.md", "/absolute.md", "a/./file.md", "a\\file.md", "file.md#anchor", "file.md?query"]
)
def test_unsafe_navigation_paths_are_rejected(entries, path):
    entries[1]["path"] = path
    result = navigation(entries, check=False)
    assert result.returncode != 0
    assert "Invalid or duplicate API navigation entry" in result.stderr


@pytest.mark.parametrize("invalid", ["duplicate", "missing-parent", "cycle"])
def test_invalid_navigation_trees_are_rejected(entries, invalid):
    if invalid == "duplicate":
        entries.append(entries[1].copy())
    else:
        entries[1]["parent"] = "T:Example.Widget" if invalid == "cycle" else "T:Missing"
    result = navigation(entries, check=False)
    assert result.returncode != 0
    assert ("Invalid or duplicate" if invalid == "duplicate" else "Missing or cyclic") in result.stderr
