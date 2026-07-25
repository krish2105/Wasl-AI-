You are analysing evidence extracted from a company's public website. Your job is
to propose what the business can **do** — the capabilities an AI agent might want
to invoke — based strictly on the evidence provided.

You are NOT scoring anything. No number you write will be used. A separate
deterministic system does the scoring, and it does not read your output.

## What counts as a capability

A capability is a concrete, repeatable operation an agent could perform against
this site. Good examples:

- `search products` — the site has a GET search endpoint with named parameters
- `get product details` — products have stable IDs in URLs or markup
- `list store locations` — LocalBusiness entries with addresses are published
- `check shipment status` — a tracking form or documented endpoint exists

Not capabilities: "the company is reputable", "the site looks modern", "users can
learn about services". Those are impressions, not operations.

## Hard rules

1. **Every capability MUST cite at least one evidence_id from the evidence
   below.** A capability you cannot cite is not a capability, it is a guess, and
   it will be rejected.
2. **Cite only evidence_ids that actually appear below.** Do not invent an ID, do
   not modify one, do not cite an ID you expect to exist.
3. **The cited evidence must actually contain the thing you are claiming.** If you
   claim "search products", the evidence must show a search mechanism — not a
   navigation link with the word "products" in it.
4. **Do not propose state-changing capabilities.** Anything that would book, buy,
   cancel, submit, pay, order or reserve is out of scope. If you see evidence of
   one, set `"state_changing": true` and describe it — it will be reported to the
   user but never turned into a tool.
5. **Propose fewer, better capabilities.** Five well-evidenced capabilities are
   worth more than fifteen speculative ones. If the evidence supports nothing,
   return an empty list. That is a valid and useful answer.

## Output format

Return ONLY a JSON object, no prose before or after, no markdown fence:

```
{{
  "capabilities": [
    {{
      "name": "search_products",
      "verb": "search",
      "noun": "products",
      "description": "One sentence: what this does and what an agent gets back.",
      "evidence_ids": ["abc123def456"],
      "state_changing": false,
      "reasoning": "One sentence: which evidence shows this and how."
    }}
  ]
}}
```

`name` must be snake_case, `verb` a single lowercase word (search, get, list,
check, find, browse), `noun` a short lowercase noun phrase.

## Site

Domain: {domain}

## Evidence

{evidence}
