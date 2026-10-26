# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "docs/python-api/generate.py"
spec = importlib.util.spec_from_file_location("python_api", SCRIPT)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


@pytest.fixture
def package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src/example").mkdir(parents=True)
    (tmp_path / "src/example/__init__.py").write_text('''"""Example public package."""
from .value import Value
__all__ = ["Value"]
raise RuntimeError("Static documentation must never import this package")
''')
    (tmp_path / "src/example/value.py").write_text('''class Value:
    """A public value."""
    def __init__(self, value: int = 1):
        self._value = value

    @property
    def value(self) -> int:
        """The stored integer."""
        return self._value

    def double_value(self) -> int:
        """Return twice the stored integer."""
        return self._value * 2

    def _hidden(self):
        pass
''')
    config = {
        "repository": "https://github.com/Example/Library",
        "api": {"generator": "griffe2md", "packages": ["example"], "directory": "artifacts/python-api"},
    }
    (tmp_path / "site.json").write_text(json.dumps(config))
    return tmp_path


def test_python_api_is_static_and_documents_reexports_properties_methods_and_source_links(package):
    api.generate("site.json", ".", "1" * 40)
    output = package / "artifacts/python-api"
    page = (output / "example/Value.md").read_text()
    assert "Value(value: int = 1)" in page
    assert "## Properties" in page and "### `value`" in page
    assert "## Methods" in page and "double_value() -> int" in page
    assert "### `double_value` {#member-double-value}" in page
    assert "_hidden" not in page
    assert "/blob/" + "1" * 40 + "/src/example/value.py#L" in page
    manifest = json.loads((output / "navigation.json").read_text())
    member = manifest["items"][0]["items"][0]
    assert member["text"] == "Value"
    assert [section["text"] for section in member["items"]] == ["Properties", "Methods"]
    assert member["items"][1]["items"][0]["link"].endswith("#member-double-value")


@pytest.mark.parametrize("directory", ["src", "artifacts", "../outside"])
def test_python_api_rejects_output_that_could_delete_source(package, directory):
    p = package / "site.json"
    config = json.loads(p.read_text())
    config["api"]["directory"] = directory
    p.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="inside artifacts"):
        api.generate("site.json", ".", "1" * 40)
    assert (package / "src/example/value.py").exists()


def test_python_api_uses_the_released_source_checkout(package):
    released = package / "released"
    (released / "src/example").mkdir(parents=True)
    (released / "src/example/__init__.py").write_text('"""Released API."""\nVERSION = 1\n__all__ = ["VERSION"]\n')
    api.generate("site.json", "released", "2" * 40)
    page = (package / "artifacts/python-api/example/index.md").read_text()
    assert "Released API" in page and "VERSION" in page
    assert "Value" not in page


def test_python_api_requires_a_pinned_source_commit(package):
    with pytest.raises(ValueError, match="full commit SHA"):
        api.generate("site.json", ".", "main")


def test_recursive_api_nests_modules_and_ignores_imported_helpers(package):
    config_path = package / "site.json"
    config = json.loads(config_path.read_text())
    config["api"].update(recursive=True, docstringStyle="sphinx")
    config_path.write_text(json.dumps(config))
    (package / "src/example/value.py").write_text('''from pathlib import Path

class Value:
    """A stored value."""

    def scale(self, factor: int) -> int:
        """Scale the value.

        :param factor: The multiplier.
        :return: The scaled value.
        """
        return factor
''')
    api.generate("site.json", ".", "1" * 40)
    output = package / "artifacts/python-api"
    assert not (output / "example/value/Path.md").exists()
    page = (output / "example/value/Value.md").read_text()
    assert "The multiplier" in page and ":param factor:" not in page
    assert "- `factor` (`int`)" in page
    assert "[int](#int)" not in page
    manifest = json.loads((output / "navigation.json").read_text())
    child = next(item for item in manifest["items"][0]["items"] if item["text"] == "value")
    assert child["link"] == "/api/example/value/"
    assert child["items"][0]["text"] == "Value"


def test_python_type_alias_is_rendered_without_importing_dependencies(package):
    (package / "src/example/__init__.py").write_text('''type Number = int | float
"""A numeric input."""
__all__ = ["Number"]
''')
    api.generate("site.json", ".", "1" * 40)
    page = (package / "artifacts/python-api/example/Number.md").read_text()
    assert "# `Number`" in page
    assert "type Number = int | float" in page
    assert "A numeric input" in page
    manifest = json.loads((package / "artifacts/python-api/navigation.json").read_text())
    assert "items" not in manifest["items"][0]["items"][0]


def test_recursive_loading_preserves_same_named_class_reexports(package):
    config = json.loads((package / "site.json").read_text())
    config["api"]["recursive"] = True
    (package / "site.json").write_text(json.dumps(config))
    (package / "src/example/__init__.py").write_text('from .Value import Value\n__all__ = ["Value"]\n')
    (package / "src/example/Value.py").write_text('class Value:\n    """A same-named exported class."""\n')
    api.generate("site.json", ".", "1" * 40)
    output = package / "artifacts/python-api"
    assert "A same-named exported class" in (output / "example/Value.md").read_text()
    assert "A same-named exported class" in (output / "example/Value/Value.md").read_text()
    manifest = json.loads((output / "navigation.json").read_text())
    assert any(item["link"] == "/api/example/Value" for item in manifest["items"][0]["items"])
