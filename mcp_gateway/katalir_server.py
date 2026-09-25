"""Katalir workflow MCP server (stdio adapter).

The server is a separate process. It uses the owner's Supabase JWT from
KATALIR_JWT and only calls existing owner-scoped Katalir services.
"""
from __future__ import annotations
import os
from typing import Any
from mcp.server.fastmcp import FastMCP
import api_server

mcp = FastMCP("katalir-workflows")

def _auth() -> str:
    token = os.environ.get("KATALIR_JWT", "").strip()
    if not token:
        raise RuntimeError("KATALIR_JWT wajib untuk workflow owner-scoped")
    return f"Bearer {token}"

@mcp.tool()
def list_workflows() -> list[dict[str, Any]]:
    user = api_server.security.get_current_user(_auth())
    return api_server._mcp_workflow_tools(str(user["id"]))

@mcp.tool()
def run_workflow(tool: str) -> dict[str, Any]:
    user = api_server.security.get_current_user(_auth())
    row = next((r for r in (api_server.db.list_workflows(str(user["id"])) or []) if api_server._mcp_workflow_tool_name(r.get("name"), str(r.get("id"))) == tool), None)
    if row is None:
        raise ValueError("workflow not found")
    detail = api_server.db.get_workflow(str(row["id"]), str(user["id"]))
    if not detail:
        raise ValueError("workflow not found")
    execution_id = api_server.engine.launch_execution(str(row["id"]), detail.get("flow_data") or {}, owner_email=str(user.get("email") or ""))
    return {"execution_id": execution_id, "workflow_id": str(row["id"]), "status": "pending"}

if __name__ == "__main__":
    mcp.run(transport="stdio")
