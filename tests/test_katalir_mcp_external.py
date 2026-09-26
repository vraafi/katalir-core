"""External MCP client test: a REAL mcp SDK stdio client talks to katalir_server.

This is not a FastMCP self-test. The client is an external process using the
official `mcp.client.stdio` transport, exactly like Claude Desktop / Cursor would.
Identity is stubbed inside the child process (no live user JWT required), so the
test proves the MCP protocol surface: initialize, tools/list, tools/call.
"""
import os
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The child process is a REAL external MCP client scenario: identity comes from
# KATALIR_JWT (like a desktop client would), and the API layer is stubbed so the
# test needs no live account.
WRAPPER = textwrap.dedent(
    '''
    import sys
    sys.path.insert(0, r"{root}")
    import api_server
    USER = {{"id": "u-ext", "email": "ext@example.com"}}
    api_server.security.get_current_user = lambda auth: USER
    api_server.db.list_workflows = lambda uid: [
        {{"id": "wf-1", "name": "Daily Digest", "description": "Kirim ringkasan"}}
    ]
    api_server.db.get_workflow = lambda wid, uid: {{"id": wid, "flow_data": {{"nodes": []}}}}
    api_server.engine.launch_execution = lambda wid, flow, owner_email="": "exec-123"
    from mcp_gateway.katalir_server import mcp
    mcp.run(transport="stdio")
    '''
)


def test_external_mcp_client_lists_and_calls_workflow():
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    import anyio

    env = dict(os.environ, KATALIR_JWT="test-jwt", PYTHONIOENCODING="utf-8")
    params = StdioServerParameters(
        command=sys.executable, args=["-c", WRAPPER.format(root=str(ROOT))], env=env
    )

    async def run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.serverInfo.name == "katalir-workflows"
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                assert {"list_workflows", "run_workflow"} <= names
                result = await session.call_tool("run_workflow", {"tool": "katalir_workflow__daily-digest"})
                payload = json.loads(result.content[0].text)
                assert payload["execution_id"] == "exec-123"
                assert payload["status"] == "pending"
                return True

    assert anyio.run(run) is True
