"""Core types for mcp-mirror.

A ToolView captures a single representation of a tool — either as the MCP server
announces it, or as a framework reshapes it on the way to the LLM. Comparing
two ToolViews produces a ToolDiff: a structured account of where the framework
preserved, dropped, added, or transformed information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Category(str, Enum):
    """How a framework's representation compares to the server's announcement."""

    FAITHFUL = "faithful"
    LOSSY = "lossy"
    ADDITIVE = "additive"
    TRANSFORMATIVE = "transformative"


# Severity order for "overall" computation across many field diffs.
_CATEGORY_SEVERITY = {
    Category.FAITHFUL: 0,
    Category.ADDITIVE: 1,
    Category.TRANSFORMATIVE: 2,
    Category.LOSSY: 3,
}


@dataclass(frozen=True)
class ToolView:
    """One representation of a tool, from one observer's POV.

    For an MCP server's announcement, this is what the server publishes via
    tools/list. For a framework adapter, this is what the framework hands to
    the LLM at inference time.
    """

    name: str
    description: str
    parameters_schema: dict[str, Any]
    response_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FieldDiff:
    """A single point of difference between two ToolViews."""

    path: str
    server_value: Any
    framework_value: Any
    category: Category
    note: str = ""


@dataclass
class ToolDiff:
    """The full comparison for one tool under one framework."""

    tool_name: str
    framework_name: str
    server_view: ToolView
    framework_view: ToolView
    field_diffs: list[FieldDiff] = field(default_factory=list)

    @property
    def overall_category(self) -> Category:
        if not self.field_diffs:
            return Category.FAITHFUL
        worst = max(self.field_diffs, key=lambda d: _CATEGORY_SEVERITY[d.category])
        return worst.category

    @property
    def is_faithful(self) -> bool:
        return self.overall_category == Category.FAITHFUL

    def counts_by_category(self) -> dict[Category, int]:
        out = {c: 0 for c in Category}
        for d in self.field_diffs:
            out[d.category] += 1
        return out
