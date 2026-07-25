"""The ship gate: if it does not import, it does not ship.

A generated server that fails to import is worse than no server — it wastes the
user's time and makes the whole report look unreliable. So nothing is offered for
download until it has been imported in a **clean subprocess** and its tools
listed.

Subprocess rather than in-process, for three reasons. The generated module could
have a name that collides with something already imported; a syntax error would
otherwise raise inside the API worker; and only a fresh interpreter proves the
file works for the person who downloads it, which is the actual claim being made.

This produces `schema_validity`, one of the eval harness's hard gates at 1.00.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

VERIFY_TIMEOUT_SECONDS = 60

# Runs inside the generated server's own directory, in a fresh interpreter.
_PROBE = r"""
import asyncio, importlib.util, json, sys
from pathlib import Path

target = Path(sys.argv[1])
report = {"imported": False, "tools": [], "errors": []}

try:
    spec = importlib.util.spec_from_file_location("generated_wasl_server", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report["imported"] = True
except BaseException as exc:
    report["errors"].append(f"import failed: {type(exc).__name__}: {exc}")
    print(json.dumps(report))
    raise SystemExit(0)

try:
    mcp = getattr(module, "mcp")
    tools = asyncio.run(mcp.list_tools())
    for tool in tools:
        schema = getattr(tool, "inputSchema", None) or {}
        report["tools"].append({
            "name": getattr(tool, "name", "?"),
            "description": (getattr(tool, "description", "") or "")[:400],
            "parameters": sorted((schema.get("properties") or {}).keys()),
            "required": sorted(schema.get("required") or []),
        })
except BaseException as exc:
    report["errors"].append(f"tool introspection failed: {type(exc).__name__}: {exc}")

print(json.dumps(report))
"""


@dataclass(slots=True)
class VerificationResult:
    """What a clean subprocess made of the generated server."""

    imported: bool = False
    tools: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stderr: str = ""

    @property
    def tool_count(self) -> int:
        return len(self.tools)

    @property
    def ships(self) -> bool:
        """The gate. Import cleanly, expose at least one usable tool, or no download."""
        return self.imported and self.tool_count > 0 and not self.errors

    def quality_problems(self) -> list[str]:
        """Tools that import but would frustrate an agent using them."""
        problems: list[str] = []
        for tool in self.tools:
            name = tool.get("name", "?")
            if not tool.get("description", "").strip():
                problems.append(f"{name}: no description — an agent selects tools by description")
            if not tool.get("parameters"):
                problems.append(f"{name}: no parameters exposed")
        return problems

    def summary(self) -> str:
        if self.ships:
            lines = [f"VERIFIED — imports cleanly, exposes {self.tool_count} tool(s):"]
            for tool in self.tools:
                params = ", ".join(tool.get("parameters", [])) or "none"
                lines.append(f"  + {tool['name']}({params})")
            for problem in self.quality_problems():
                lines.append(f"  ! {problem}")
            return "\n".join(lines)

        lines = ["FAILED VERIFICATION — not offered for download:"]
        if not self.imported:
            lines.append("  - the module does not import")
        elif self.tool_count == 0:
            lines.append("  - it imports but exposes no tools")
        lines.extend(f"  - {error}" for error in self.errors)
        if self.stderr.strip():
            lines.append(f"  stderr: {self.stderr.strip()[:400]}")
        return "\n".join(lines)


async def verify_server(server_path: Path, *, timeout: int = VERIFY_TIMEOUT_SECONDS) -> VerificationResult:
    """Import a generated server in a clean subprocess and list its tools."""
    server_path = Path(server_path).resolve()
    if not server_path.exists():
        return VerificationResult(errors=[f"no such file: {server_path}"])

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _PROBE,
            str(server_path),
            cwd=str(server_path.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        return VerificationResult(
            errors=[f"verification timed out after {timeout}s — the module may block on import"]
        )
    except Exception as exc:
        return VerificationResult(errors=[f"could not start verification subprocess: {exc}"])

    stderr_text = stderr.decode(errors="replace")
    raw = stdout.decode(errors="replace").strip()

    if not raw:
        return VerificationResult(
            errors=["the verification subprocess produced no output"], stderr=stderr_text
        )

    try:
        # The probe prints one JSON object on its last line.
        payload = json.loads(raw.splitlines()[-1])
    except json.JSONDecodeError as exc:
        return VerificationResult(
            errors=[f"unparseable verification output: {exc}"], stderr=stderr_text
        )

    return VerificationResult(
        imported=bool(payload.get("imported")),
        tools=list(payload.get("tools") or []),
        errors=list(payload.get("errors") or []),
        stderr=stderr_text,
    )


def verify_server_sync(server_path: Path, *, timeout: int = VERIFY_TIMEOUT_SECONDS) -> VerificationResult:
    return asyncio.run(verify_server(server_path, timeout=timeout))
