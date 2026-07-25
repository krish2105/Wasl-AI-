You are converting an accepted capability into an MCP tool definition.

The tool will be shipped in a generated FastMCP server that someone runs against
a cached snapshot of a website. Treat every parameter as a security boundary: it
will be interpolated into a lookup, so anything unbounded is a liability.

## Rules

1. **Read-only tools only.** The verb must be one of: search, get, list, check,
   find, browse. If the capability implies anything else, return
   `{{"tool": null, "reason": "..."}}`.
2. **Every parameter needs a type, a description and bounds.** A string parameter
   with no `maxLength` or no description will be rejected. Say what the parameter
   is for and give an example value in the description.
3. **No free-text parameter without constraints.** If a parameter is genuinely
   open-ended, give it a `maxLength` and describe exactly what belongs there.
4. **Name the tool `{prefix}_{{verb}}_{{noun}}`** in snake_case, using the domain
   prefix supplied below. This avoids collisions when several MCP servers are
   loaded together.
5. **The description states when an agent should reach for this tool and what it
   gets back.** An agent chooses tools by description alone.

## Output format

Return ONLY a JSON object, no prose, no markdown fence:

```
{{
  "tool": {{
    "name": "{prefix}_search_products",
    "description": "Search the product catalogue by keyword. Use when the user names a product or category. Returns matching products with id, name, price and availability.",
    "parameters": {{
      "query": {{
        "type": "string",
        "description": "Search keywords, e.g. 'brass elbow 22mm'",
        "required": true,
        "maxLength": 200
      }},
      "limit": {{
        "type": "integer",
        "description": "Maximum results to return",
        "required": false,
        "default": 20,
        "minimum": 1,
        "maximum": 100
      }}
    }},
    "returns": "A list of products, each with id, name, price, currency and availability."
  }}
}}
```

## Capability

name: {name}
verb: {verb}
noun: {noun}
description: {description}
domain prefix: {prefix}

## Evidence this capability rests on

{evidence}
