// Node worker that drives Mastra's REAL MCP client (@mastra/mcp) so mcp-mirror can
// capture the tool actions returned by MCPClient.listTools, never a reimplementation
// (decision D1). It does not invoke an AI SDK provider or capture a provider request.
//
// Usage: node _mastra_worker.mjs '<json-server-config>'
//   stdio: {"transport":"stdio","command":"python","args":["server.py"]}
//   http : {"transport":"http","url":"https://host/mcp","headers":{...}}
// Emits a JSON array of {name, description, parameters, annotations} on stdout.

import { MCPClient } from '@mastra/mcp';

// Mastra wraps a tool's schema in a Standard-Schema JsonSchemaWrapper. Extract the
// JSON Schema represented by that wrapper at the declared capture boundary.
function extractJsonSchema(inputSchema) {
  if (!inputSchema || typeof inputSchema !== 'object') return {};
  if (typeof inputSchema.getSchema === 'function') {
    try {
      const s = inputSchema.getSchema();
      if (s && typeof s === 'object') return s;
    } catch { /* fall through */ }
  }
  const std = inputSchema['~standard'];
  if (std && std.jsonSchema && typeof std.jsonSchema === 'object' && Object.keys(std.jsonSchema).length) {
    return std.jsonSchema;
  }
  if (inputSchema.type || inputSchema.properties) return inputSchema;
  return {};
}

async function main() {
  const raw = process.argv[2];
  if (!raw) {
    process.stderr.write('mastra worker: missing server config argument\n');
    process.exit(2);
  }
  const cfg = JSON.parse(raw);

  let serverConfig;
  if (cfg.transport === 'http') {
    serverConfig = { url: new URL(cfg.url) };
    if (cfg.headers && Object.keys(cfg.headers).length) {
      serverConfig.requestInit = { headers: cfg.headers };
    }
  } else {
    serverConfig = { command: cfg.command, args: cfg.args || [] };
  }

  const mcp = new MCPClient({
    id: `mcp-mirror-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    servers: { src: serverConfig },
  });

  try {
    const tools = await mcp.listTools();
    const out = [];
    for (const [name, tool] of Object.entries(tools)) {
      out.push({
        name, // Mastra namespaces this captured action as `<server>_<tool>`
        description: tool && tool.description != null ? String(tool.description) : null,
        parameters: extractJsonSchema(tool && tool.inputSchema),
        annotations: {}, // Mastra does not carry MCP annotations onto the tool
      });
    }
    // @mastra/mcp does not expose the negotiated version publicly. Its pinned MCP
    // client stores the initialize result here; fail closed if that evidence seam
    // moves rather than copying the direct source connection's version by assumption.
    const negotiatedMcpSpecVersion =
      mcp.mcpClientsById.get('src')?.client?._negotiatedProtocolVersion;
    if (typeof negotiatedMcpSpecVersion !== 'string' || !negotiatedMcpSpecVersion) {
      throw new Error('mastra worker: negotiated MCP protocol version was not observable');
    }
    process.stdout.write(JSON.stringify({
      tools: out,
      negotiatedMcpSpecVersion,
    }));
  } finally {
    try {
      await mcp.disconnect();
    } catch { /* best effort */ }
  }
}

main().catch((err) => {
  process.stderr.write(String((err && err.stack) || err) + '\n');
  process.exit(1);
});
