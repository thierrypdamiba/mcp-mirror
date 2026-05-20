"""Scorecard rendering — turns ToolDiffs into text the talk can show on stage."""

from __future__ import annotations

from collections import defaultdict

from mcp_mirror.types import Category, ToolDiff

_CATEGORY_GLYPHS = {
    Category.FAITHFUL: "=",
    Category.ADDITIVE: "+",
    Category.LOSSY: "-",
    Category.TRANSFORMATIVE: "~",
}


def render_summary(diffs: list[ToolDiff]) -> str:
    """One-line-per-tool-per-framework grid suitable for a slide."""
    by_tool: dict[str, list[ToolDiff]] = defaultdict(list)
    for d in diffs:
        by_tool[d.tool_name].append(d)

    frameworks = sorted({d.framework_name for d in diffs})
    col_width = max(12, max((len(f) for f in frameworks), default=12))
    name_width = max(20, max((len(t) for t in by_tool), default=20))

    header = "tool".ljust(name_width) + "  " + "  ".join(
        f.ljust(col_width) for f in frameworks
    )
    rule = "-" * len(header)
    rows: list[str] = []
    for tool, tool_diffs in by_tool.items():
        by_fw = {d.framework_name: d for d in tool_diffs}
        cells: list[str] = []
        for f in frameworks:
            d = by_fw.get(f)
            if d is None:
                cells.append("?".ljust(col_width))
            else:
                cells.append(_cell(d).ljust(col_width))
        rows.append(tool.ljust(name_width) + "  " + "  ".join(cells))

    legend = (
        "\nlegend:  = faithful   + additive   - lossy   ~ transformative\n"
        "         counts are field-level deltas vs. the server announcement\n"
    )
    return "\n".join([header, rule, *rows]) + legend


def _cell(d: ToolDiff) -> str:
    counts = d.counts_by_category()
    parts = []
    for cat in (Category.LOSSY, Category.TRANSFORMATIVE, Category.ADDITIVE):
        c = counts[cat]
        if c:
            parts.append(f"{_CATEGORY_GLYPHS[cat]}{c}")
    if not parts:
        return _CATEGORY_GLYPHS[Category.FAITHFUL]
    return " ".join(parts)


def render_detail(diff: ToolDiff) -> str:
    """Full per-tool-per-framework breakdown for the talk's deep-dive slides."""
    lines: list[str] = []
    lines.append(f"=== {diff.tool_name} @ {diff.framework_name} ===")
    lines.append(f"overall: {diff.overall_category.value}")
    if not diff.field_diffs:
        lines.append("(no differences detected)")
        return "\n".join(lines)
    counts = diff.counts_by_category()
    summary = ", ".join(
        f"{c.value}={counts[c]}" for c in Category if counts[c]
    )
    lines.append(f"deltas: {summary}")
    lines.append("")
    for fd in diff.field_diffs:
        glyph = _CATEGORY_GLYPHS[fd.category]
        lines.append(f"  {glyph} {fd.path}")
        if fd.note:
            lines.append(f"      {fd.note}")
    return "\n".join(lines)
