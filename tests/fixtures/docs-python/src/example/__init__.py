"""Public example package."""

__all__ = ["Value"]


class Value:
    """A small public value."""

    @property
    def value(self) -> int:
        """The stored integer."""
        return 1

    def __getitem__(self, index: int) -> int:
        """Read a value by index."""
        return index

    def reset_value(self) -> None:
        """Reset the stored value."""


raise RuntimeError("Documentation must use static analysis, never import this package.")
