"""mcp-mirror: see what your MCP server looks like after every framework gets done with it."""

from mcp_mirror.types import Category, FieldDiff, ToolDiff, ToolView
from mcp_mirror.diff import diff_views

__version__ = "0.1.0"
__all__ = ["Category", "FieldDiff", "ToolDiff", "ToolView", "diff_views", "__version__"]
