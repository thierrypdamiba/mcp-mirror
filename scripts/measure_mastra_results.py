import json, os, sys
sys.path.insert(0, "src")
from mcp_mirror.source import parse_server, call_source_tool
from mcp_mirror.renderers.mastra_renderer import get_renderer
from mcp_mirror.diff import diff_result

FIXTURE_PYTHON = os.environ.get("MCP_MIRROR_FIXTURE_PYTHON", sys.executable)
SERVER = f"{FIXTURE_PYTHON} fixtures/tricky_server.py"
CALLS = [
    {"tool": "search_records", "arguments": {"query": "x", "status": "active",
      "owner_email": "a@b.com", "created_after": "2026-01-01T00:00:00Z", "limit": 5}},
    {"tool": "delete_account", "arguments": {"account_id": "a", "confirm": False}},
]
handle = parse_server(SERVER)
r = get_renderer()
print("mastra @", r.versions()["framework"])
for call in CALLS:
    tool = call["tool"]
    src = call_source_tool(parse_server(SERVER), tool, call["arguments"])
    print(f"\n=== {tool} ===")
    print(f"  source  kinds={src.block_kinds} structured={src.structured_content is not None} isError={src.is_error}")
    try:
        rep = r.render_result(parse_server(SERVER), tool, call["arguments"])
    except Exception as exc:
        print(f"  mastra  FAILED: {type(exc).__name__}: {exc}"); continue
    print(f"  mastra  kinds={rep.block_kinds} structured={rep.structured_content is not None} isError={rep.is_error}")
    for i, b in enumerate(rep.blocks):
        sk = src.block_kinds[i] if i < len(src.block_kinds) else "?"
        print(f"      {sk:>14} -> {json.dumps(b)[:150]}")
    if not rep.blocks and rep.text:
        print(f"      {'(text only)':>14} -> {rep.text[:200]!r}")
    for d in diff_result(src, rep):
        print(f"      [{d.category}] {d.detail}")
