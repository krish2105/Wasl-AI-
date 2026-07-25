"""FastMCP server emitter.

Follows the `mcp-builder` skill's Python guide: `{service}_mcp` server name,
`{prefix}_{verb}_{noun}` snake_case tools, Pydantic input models with described
and bounded fields, full docstrings stating when to use a tool and what it
returns, and annotations marking everything read-only.

Two decisions specific to generating code for a site we do not own:

**Every tool body is written by this module, not by a model.** The model proposes
a tool's *shape* — name, parameters, description. The implementation is a fixed
lookup over the cached snapshot, emitted from a template. A model writing
executable code that someone then runs is a different risk category than a model
writing a JSON schema, and there is no reason to take it.

**Parameters are clamped at emission.** Whatever bounds the model suggested, the
generated Pydantic field gets a hard `max_length`, and every value is escaped
before it reaches a lookup. A generated tool is a security boundary for whoever
runs the server.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from wasl.graph.state import Capability, ToolSchema

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Hard ceilings applied regardless of what the model proposed.
MAX_STRING_LENGTH = 500
MAX_LIMIT = 100
DEFAULT_LIMIT = 20

_IDENT = re.compile(r"[^a-z0-9_]")
_RESERVED = frozenset(
    {
        "and", "as", "assert", "async", "await", "break", "class", "continue", "def",
        "del", "elif", "else", "except", "finally", "for", "from", "global", "if",
        "import", "in", "is", "lambda", "none", "nonlocal", "not", "or", "pass",
        "raise", "return", "try", "while", "with", "yield", "true", "false",
    }
)


def safe_identifier(value: str, fallback: str = "field") -> str:
    """Coerce a model-proposed name into a valid, non-reserved Python identifier."""
    cleaned = _IDENT.sub("_", value.strip().lower()).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}" if cleaned else fallback
    if cleaned in _RESERVED:
        cleaned = f"{cleaned}_"
    return cleaned[:60]


def _py_literal(value: object) -> str:
    """Render a value as a Python literal. Used for defaults only."""
    return json.dumps(value, ensure_ascii=False) if not isinstance(value, bool) else str(value)


@dataclass(frozen=True, slots=True)
class EmittedTool:
    name: str
    code: str
    parameter_names: tuple[str, ...]


def _field(name: str, spec: dict) -> tuple[str, str]:
    """Render one Pydantic field. Returns (field name, source line)."""
    field_name = safe_identifier(name)
    description = str(spec.get("description", "")).strip() or f"Value for {field_name}."
    required = bool(spec.get("required", False))
    kind = str(spec.get("type", "string")).lower()

    if kind in {"integer", "number"}:
        minimum = spec.get("minimum", 0)
        maximum = min(int(spec.get("maximum", MAX_LIMIT) or MAX_LIMIT), MAX_LIMIT)
        default = spec.get("default", DEFAULT_LIMIT if field_name == "limit" else minimum)
        annotation = "int" if kind == "integer" else "float"
        return field_name, (
            f"    {field_name}: {annotation} = Field(\n"
            f"        default={_py_literal(default)},\n"
            f"        description={json.dumps(description)},\n"
            f"        ge={minimum}, le={maximum},\n"
            f"    )"
        )

    if kind == "boolean":
        return field_name, (
            f"    {field_name}: bool = Field(\n"
            f"        default={_py_literal(bool(spec.get('default', False)))},\n"
            f"        description={json.dumps(description)},\n"
            f"    )"
        )

    # Strings. Bound them whatever the model said.
    max_length = min(int(spec.get("maxLength", MAX_STRING_LENGTH) or MAX_STRING_LENGTH), MAX_STRING_LENGTH)
    if required:
        return field_name, (
            f"    {field_name}: str = Field(\n"
            f"        ...,\n"
            f"        description={json.dumps(description)},\n"
            f"        min_length=1, max_length={max_length},\n"
            f"    )"
        )
    return field_name, (
        f"    {field_name}: str = Field(\n"
        f"        default={json.dumps(str(spec.get('default', '')))},\n"
        f"        description={json.dumps(description)},\n"
        f"        max_length={max_length},\n"
        f"    )"
    )


def emit_tool(capability: Capability, schema: ToolSchema) -> EmittedTool:
    """Emit one tool: input model, decorator, docstring, and a fixed body."""
    tool_name = safe_identifier(schema.name, fallback="tool")
    model_name = "".join(part.title() for part in tool_name.split("_")) + "Input"

    fields: list[str] = []
    names: list[str] = []
    for raw_name, spec in (schema.parameters or {}).items():
        if not isinstance(spec, dict):
            continue
        field_name, source = _field(raw_name, spec)
        if field_name in names:
            continue
        names.append(field_name)
        fields.append(source)

    # Every listing tool gets pagination whether the model asked for it or not.
    if "limit" not in names:
        names.append("limit")
        fields.append(
            "    limit: int = Field(\n"
            f"        default={DEFAULT_LIMIT},\n"
            '        description="Maximum number of results to return.",\n'
            f"        ge=1, le={MAX_LIMIT},\n"
            "    )"
        )
    if "offset" not in names:
        names.append("offset")
        fields.append(
            "    offset: int = Field(\n"
            "        default=0,\n"
            '        description="Number of results to skip, for pagination.",\n'
            "        ge=0,\n"
            "    )"
        )
    names.append("response_format")
    fields.append(
        "    response_format: ResponseFormat = Field(\n"
        "        default=ResponseFormat.MARKDOWN,\n"
        '        description="markdown for human reading, json for machine processing.",\n'
        "    )"
    )

    # The primary query parameter, used by the emitted body.
    query_field = next(
        (n for n in names if n not in {"limit", "offset", "response_format"}), None
    )
    query_expression = f"params.{query_field}" if query_field else '""'

    description = (schema.description or capability.description).strip().replace('"""', "'''")
    returns = (schema.returns or "Matching records from the cached snapshot.").strip()
    evidence_line = ", ".join(capability.evidence_ids)

    code = f'''
class {model_name}(BaseModel):
    """Validated input for {tool_name}."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

{chr(10).join(fields)}


@mcp.tool(
    name="{tool_name}",
    annotations={{
        "title": {json.dumps(capability.description[:60] or tool_name)},
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }},
)
async def {tool_name}(params: {model_name}) -> str:
    """{description}

    Reads the cached snapshot of {{SITE_DOMAIN}} taken when this server was
    generated. Sends no network requests.

    Args:
        params ({model_name}): validated input containing:
{chr(10).join(f"            - {n}" for n in names)}

    Returns:
        str: {returns}
        On no match, an explanatory message naming the snapshot size.

    EVIDENCE:
        This tool was induced from evidence {evidence_line} collected during the
        Wasl crawl. Reasoning: {capability.reasoning[:200] or "see the Wasl report."}
    """
    records = _records()
    query = {query_expression}
    matched = [r for r in records if _match(r, str(query))]

    if not matched:
        return _no_results(str(query))

    payload = _paginate(matched, params.limit, params.offset)
    return _format(payload, params.response_format, {json.dumps(capability.description[:60] or tool_name)})
'''

    return EmittedTool(name=tool_name, code=code, parameter_names=tuple(names))


def generate_server(
    *,
    capabilities: list[Capability],
    domain: str,
    site_name: str,
    score_line: str,
    snapshot_records: list[dict] | None = None,
) -> tuple[str, str]:
    """Render server.py and snapshot.json. Returns (server source, snapshot json)."""
    emitted = [
        emit_tool(capability, capability.tool_schema)
        for capability in capabilities
        if capability.tool_schema and capability.accepted and not capability.implies_state_change()
    ]

    template = Template((TEMPLATE_DIR / "server.py.tmpl").read_text())
    server_name = safe_identifier(domain.replace(".", "_")) + "_mcp"

    source = template.substitute(
        site_name=site_name,
        domain=domain,
        server_name=server_name,
        score=score_line,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d"),
        abs_path_placeholder="/absolute/path/to/this/directory",
        tools="\n".join(tool.code for tool in emitted)
        or (
            "# No tools were generated. Every candidate capability was rejected by the\n"
            "# critic, or none were proposed. That is a real result, not a failure —\n"
            "# see the 'what we refused to generate' section of the Wasl report.\n"
        ),
    )

    snapshot = json.dumps(
        {
            "domain": domain,
            "generated_at": datetime.now(UTC).isoformat(),
            "records": snapshot_records or [],
        },
        indent=2,
        ensure_ascii=False,
    )

    return source, snapshot
