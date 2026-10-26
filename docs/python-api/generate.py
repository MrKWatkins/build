#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# /// script
# requires-python = ">=3.13"
# dependencies = ["griffe2md==1.5.1"]
# ///
"""Generate VitePress API pages with Griffe2md, without importing the documented package."""

import argparse
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote

from griffe import GriffeLoader, Parser
from griffe2md import render_object_docs

OPTIONS = {
    "show_root_full_path": False,
    "show_root_members_full_path": False,
    "show_object_full_path": False,
    "show_signature_annotations": True,
    "show_bases": False,
    "inherited_members": False,
    "members": False,
    "summary": False,
}
SPECIAL_METHODS = {"__getitem__", "__setitem__", "__iter__", "__len__", "__enter__", "__exit__"}


def inside(root, path):
    resolved = (root / path).resolve(strict=True)
    if Path(path).is_absolute() or not resolved.is_relative_to(root):
        raise ValueError(f"Path must remain inside its source checkout: {path}")
    return resolved


def generate(config_path, source_root, source_ref):
    if not re.fullmatch(r"[a-fA-F0-9]{40}", source_ref):
        raise ValueError("source-ref must be a full commit SHA.")
    root = Path.cwd().resolve()
    config = json.loads(inside(root, config_path).read_text())
    api = config["api"]
    if api["generator"] != "griffe2md":
        raise ValueError("Expected the griffe2md API generator.")
    repository = config["repository"].rstrip("/")
    if not re.fullmatch(r"https://github.com/[\w.-]+/[\w.-]+", repository):
        raise ValueError("repository must be an HTTPS GitHub repository URL.")
    checkout = Path(source_root).resolve(strict=True)
    source = inside(checkout, api.get("sourceDirectory", "src"))
    output = (root / api["directory"]).resolve()
    if (
        Path(api["directory"]).is_absolute()
        or not output.is_relative_to(root / "artifacts")
        or output == root / "artifacts"
        or checkout.is_relative_to(output)
    ):
        raise ValueError("Generated Python API must be inside artifacts/.")
    packages = api["packages"]
    if (
        not isinstance(packages, list)
        or not packages
        or not all(isinstance(name, str) and re.fullmatch(r"\w+(\.\w+)*", name) for name in packages)
    ):
        raise ValueError("api.packages must be a nonempty list of Python module names.")
    parser = Parser(api.get("docstringStyle", "google"))
    loader = GriffeLoader(search_paths=[source], allow_inspection=False, docstring_parser=parser)
    modules = {}

    def collect(module):
        if module.path in modules:
            return
        modules[module.path] = module
        if api.get("recursive", False):
            for name, child in sorted(module.modules.items()):
                if not name.startswith("_"):
                    collect(child)

    for name in packages:
        collect(loader.load(name))
    loader.resolve_aliases(external=False)

    def source_link(obj):
        path = Path(obj.filepath).resolve()
        if not path.is_relative_to(source):
            raise ValueError(f"Export is outside the configured Python source: {obj.path}")
        return f"[Source]({repository}/blob/{source_ref}/{quote(path.relative_to(checkout).as_posix())}#L{obj.lineno or 1})"

    def member_anchor(name):
        return "member-" + name.lower().replace("_", "-").strip("-")

    def render(obj, level):
        if obj.kind.value == "type alias":
            # Griffe2md has no template for Python's `type` statements yet.
            description = obj.docstring.value if obj.docstring else ""
            markdown = (
                f"{'#' * level} `{obj.name}`\n\n```python\ntype {obj.name} = {obj.value}\n```\n\n{description}".strip()
            )
        else:
            markdown = render_object_docs(obj, {**OPTIONS, "heading_level": level}).strip()
        # Griffe2md emits Markdown links inside HTML code spans; VitePress displays
        # those literally. Keep annotations as code until cross-reference resolution exists.
        markdown = re.sub(
            r"<code>(.*?)</code>",
            lambda match: "`" + re.sub(r"\[([^\]]+)\]\(#[^)]+\)", r"\1", match[1]) + "`",
            markdown,
            flags=re.DOTALL,
        )
        markdown = re.sub(r"(?m)^- \*\*([\w*]+)\*\*", r"- `\1`", markdown)
        markdown = re.sub(r"(?<!`)``([^`]+)``(?!`)", r"`\1`", markdown)
        markdown = re.sub(r":(?:\w+:)?\w+:`([^`]+)`", lambda match: "`" + match[1].lstrip("~") + "`", markdown)
        # reStructuredText docstrings commonly leave Python identifiers unquoted.
        # Quote underscored identifiers as code, keeping existing code blocks intact.
        chunks = re.split(r"(```.*?```|`[^`\n]*`)", markdown, flags=re.DOTALL)
        for position in range(0, len(chunks), 2):
            chunks[position] = re.sub(r"(?<![\w/])\b[A-Za-z]\w*_\w+\b", r"`\g<0>`", chunks[position])
        markdown = "".join(chunks)
        if level == 3:
            # Keep anchor IDs free of Markdown emphasis delimiters, including dunder names.
            heading, separator, body = markdown.partition("\n")
            markdown = heading + f" {{#{member_anchor(obj.name)}}}" + separator + body
        return markdown + "\n\n" + source_link(obj) + "\n"

    def write(path, text):
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    navigation, index = [], ["# Python API\n", "Public packages and their exported classes, functions and constants.\n"]
    entries_by_module = {}
    for module in modules.values():
        folder = module.path.replace(".", "/")
        link = f"/api/{folder}/"
        parent = entries_by_module.get(module.path.rpartition(".")[0])
        entry = {"text": module.name if parent else module.path, "link": link, "collapsed": True, "items": []}
        entries_by_module[module.path] = entry
        index.append(f"- [`{module.path}`]({link})")
        overview = [
            f"# `{module.path}`\n",
            module.docstring.value if module.docstring else "",
            "\n## Classes and functions\n",
        ]
        exports = module.exports
        names = list(
            exports
            if exports is not None
            else [n for n, member in module.members.items() if not n.startswith("_") and not member.is_alias]
        )
        if any(not isinstance(n, str) or not n.isidentifier() for n in names):
            raise ValueError(f"{module.path}.__all__ must contain strings.")
        names.sort()
        constants = []
        for name in names:
            obj = module.members[name]
            if obj.is_alias:
                obj = obj.final_target
            if obj.is_module and exports is not None and name in obj.members:
                # Loading a same-named submodule can shadow its class re-export in Griffe.
                obj = obj.members[name]
            if obj.is_module:
                continue
            if obj.is_attribute:
                constants.append(render(obj, 3))
                continue
            page_link = link + name
            overview.append(f"- [`{name}`]({page_link})")
            page = [render(obj, 1)]
            item = {"text": name, "link": page_link}
            if obj.is_class:
                groups = {"Properties": [], "Methods": [], "Values": []}
                for member_name, member in sorted(obj.members.items()):
                    if member_name.startswith("_") and member_name not in SPECIAL_METHODS:
                        continue
                    if member.is_alias:
                        continue
                    group = (
                        "Methods" if member.is_function else "Properties" if "property" in member.labels else "Values"
                    )
                    groups[group].append((member_name, member))
                sections = []
                for group, members in groups.items():
                    if not members:
                        continue
                    page.append(f"\n## {group}\n")
                    entries = []
                    for member_name, member in members:
                        page.append(render(member, 3))
                        entries.append({"text": member_name, "link": page_link + "#" + member_anchor(member_name)})
                    sections.append(
                        {"text": group, "link": page_link + "#" + group.lower(), "collapsed": True, "items": entries}
                    )
                if sections:
                    item.update(collapsed=True, items=sections)
            write(folder + "/" + name + ".md", "\n".join(page))
            entry["items"].append(item)
        if constants:
            overview += ["\n## Constants\n", *constants]
        write(folder + "/index.md", "\n".join(overview) + "\n")
        (parent["items"] if parent else navigation).append(entry)

    def remove_empty_groups(items):
        for item in items:
            if item.get("items"):
                remove_empty_groups(item["items"])
            else:
                item.pop("items", None)
                item.pop("collapsed", None)

    remove_empty_groups(navigation)
    write("index.md", "\n".join(index) + "\n")
    write("navigation.json", json.dumps({"schemaVersion": 1, "items": navigation}, indent=2) + "\n")
    print(f"Python API: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="docs/site.json")
    parser.add_argument("--source-root", default=".")
    parser.add_argument("--source-ref", required=True)
    args = parser.parse_args()
    generate(args.config, args.source_root, args.source_ref)
