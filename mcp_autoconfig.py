"""Auto-config planning for MCP installs.

Two hard rules, encoded here so no endpoint can bypass them:
  1. The ToolSDK catalog is metadata-only. Installing catalog metadata must
     NEVER be treated as installing a runnable server.
  2. Only servers on RUNTIME_ALLOWLIST (the 5 targets actually deployed on the
     gateway VPS) may be planned for execution.

Planning is pure: it never touches credentials, network, or tenant state.
Applying is an explicit, separate step that the user must confirm.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp_gateway import policy

# Gateways deployed on the VPS (docs/architecture/mcp-gateway-vps.md).
RUNTIME_ALLOWLIST: dict[str, dict[str, Any]] = {
    "time": {"transport": "stdio", "package": "mcp-server-time", "command": "uvx", "args": ["mcp-server-time"], "required_config": ["timezone"], "credential_keys": []},
    "fetch": {"transport": "stdio", "package": "mcp-server-fetch", "command": "uvx", "args": ["mcp-server-fetch"], "required_config": [], "credential_keys": []},
    "memory": {"transport": "stdio", "package": "mcp-server-memory", "command": "uvx", "args": ["mcp-server-memory"], "required_config": [], "credential_keys": []},
    "filesystem": {"transport": "stdio", "package": "mcp-server-filesystem", "command": "uvx", "args": ["mcp-server-filesystem"], "required_config": ["roots"], "credential_keys": []},
    "everything": {"transport": "stdio", "package": "mcp-server-everything", "command": "uvx", "args": ["mcp-server-everything"], "required_config": [], "credential_keys": []},
}

SECRET_KEY_HINTS = ("token", "secret", "password", "api_key", "apikey", "private_key")


class AutoConfigError(ValueError):
    """Raised when a server cannot be planned (not allowlisted / metadata-only)."""


@dataclass
class AutoConfigPlan:
    mcp_id: str
    runtime: str
    executable: bool
    transport: str
    package: str
    command: str
    args: list[str]
    required_config: list[str] = field(default_factory=list)
    missing_config: list[str] = field(default_factory=list)
    credential_keys: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mcp_id": self.mcp_id,
            "runtime": self.runtime,
            "executable": self.executable,
            "transport": self.transport,
            "package": self.package,
            "command": self.command,
            "args": self.args,
            "required_config": self.required_config,
            "missing_config": self.missing_config,
            "credential_keys": self.credential_keys,
            "warnings": self.warnings,
        }


def _normalize(mcp_id: str) -> str:
    return (mcp_id or "").strip().casefold()


def resolve_runtime(mcp_id: str) -> str | None:
    """Map a registry id (e.g. `@modelcontextprotocol/server-time`) to a runtime key."""
    key = _normalize(mcp_id)
    if not key:
        return None
    if key in RUNTIME_ALLOWLIST:
        return key
    tail = key.rsplit("/", 1)[-1]
    tail = tail.removeprefix("server-")
    return tail if tail in RUNTIME_ALLOWLIST else None


def _redact(config: dict[str, Any]) -> dict[str, Any]:
    """Secrets are referenced by name, never stored in the plan."""
    return {k: "***" for k in config if any(h in k.casefold() for h in SECRET_KEY_HINTS)}


def plan(mcp_id: str, config: dict[str, Any] | None = None) -> AutoConfigPlan:
    config = dict(config or {})
    runtime = resolve_runtime(mcp_id)
    if runtime is None:
        raise AutoConfigError(
            f"{mcp_id} tidak punya runtime tervalidasi. Entry katalog bersifat metadata-only "
            "dan tidak bisa dieksekusi. Katalog 4.548 integrasi bukan server executable."
        )
    spec = RUNTIME_ALLOWLIST[runtime]
    validated = policy.validate_upstream(spec["transport"])  # stdio -> no URL
    missing = [k for k in spec["required_config"] if not str(config.get(k, "")).strip()]
    warnings: list[str] = []
    supplied = _redact(config)
    if supplied:
        warnings.append("Credential yang dikirim hanya direferensikan, tidak disimpan di plan.")
    if missing:
        warnings.append(f"Konfigurasi belum lengkap: {', '.join(missing)}")
    return AutoConfigPlan(
        mcp_id=(mcp_id or "").strip(),
        runtime=runtime,
        executable=True,
        transport=validated["transport"],
        package=spec["package"],
        command=spec["command"],
        args=list(spec["args"]),
        required_config=list(spec["required_config"]),
        missing_config=missing,
        credential_keys=list(spec["credential_keys"]),
        warnings=warnings,
    )
