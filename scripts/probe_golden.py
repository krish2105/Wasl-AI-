#!/usr/bin/env python
"""Gather raw, objective facts about the 30 golden sites.

Deliberately does NOT use Wasl's detectors. It issues plain HTTP requests and
records what came back, so the four boolean label fields rest on an independent
observation rather than on the output of the system those labels are meant to
evaluate. That does not fix the circularity of model-authored labels, but it
does mean `has_llms_txt` is a fact rather than a tautology.

Read-only, GET only, one domain at a time per host with a delay between
requests, concurrent only across different domains. Writes
`seeds/golden/observations.json`.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
from wasl.crawler.policy import repo_root  # noqa: E402

TIMEOUT = 12.0
PER_DOMAIN_DELAY = 1.5
MAX_CONCURRENT_DOMAINS = 6

UA = "WaslAI-Research/0.1.0 (+https://wasl-ai-eight.vercel.app/crawler)"

JSONLD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
HTML_SHELL = re.compile(r"<\s*(html|!doctype|head|body)\b", re.I)
MD_H1 = re.compile(r"^\s{0,3}#\s+\S", re.M)
AGENT_KEYS = ("mcp", "tools", "skills", "capabilities", "agent", "protocolversion", "schema_version")


async def get(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    try:
        r = await client.get(url, timeout=TIMEOUT, follow_redirects=True)
        return {"status": r.status_code, "ct": r.headers.get("content-type", "")[:60], "text": r.text[:60000]}
    except Exception as exc:
        return {"status": 0, "ct": "", "text": "", "error": f"{type(exc).__name__}"}


def looks_like_llms_txt(body: str) -> bool:
    if not body.strip() or HTML_SHELL.search(body[:2000]):
        return False
    return bool(MD_H1.search(body)) or body.count("](") >= 2


def looks_like_spec(body: str) -> bool:
    b = body.strip()
    if not b.startswith("{"):
        return bool(re.search(r"^\s*(openapi|swagger)\s*:\s*[\"']?\d", b, re.M))
    try:
        d = json.loads(b)
    except json.JSONDecodeError:
        return False
    return isinstance(d, dict) and ("openapi" in d or "swagger" in d)


def looks_like_manifest(body: str) -> bool:
    if HTML_SHELL.search(body[:500]):
        return False
    try:
        d = json.loads(body)
    except json.JSONDecodeError:
        return False
    return isinstance(d, dict) and bool({k.lower() for k in d} & set(AGENT_KEYS))


def jsonld_types(html: str) -> list[str]:
    found: list[str] = []
    for block in JSONLD.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                t = node.get("@type")
                for v in ([t] if isinstance(t, str) else t or []):
                    if isinstance(v, str) and v not in found:
                        found.append(v)
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return found[:12]


async def probe(site: dict, sem: asyncio.Semaphore) -> dict[str, Any]:
    url = site["url"].rstrip("/")
    out: dict[str, Any] = {"name": site["name"], "url": site["url"], "sector": site["sector"]}

    async with sem, httpx.AsyncClient(headers={"User-Agent": UA}, verify=False) as client:
        root = await get(client, url + "/")
        out["root_status"] = root["status"]
        out["root_error"] = root.get("error")
        out["blocked"] = root["status"] in (401, 403, 429) or root["status"] == 0

        types = jsonld_types(root["text"]) if root["status"] == 200 else []
        out["jsonld_types"] = types
        out["has_jsonld"] = bool(types)

        await asyncio.sleep(PER_DOMAIN_DELAY)
        llms = await get(client, f"{url}/llms.txt")
        out["llms_status"] = llms["status"]
        out["has_llms_txt"] = llms["status"] == 200 and looks_like_llms_txt(llms["text"])
        out["llms_head"] = llms["text"][:160].replace("\n", " ") if out["has_llms_txt"] else ""

        spec = False
        for path in ("/openapi.json", "/swagger.json"):
            await asyncio.sleep(PER_DOMAIN_DELAY)
            r = await get(client, url + path)
            if r["status"] == 200 and looks_like_spec(r["text"]):
                spec = True
                out["spec_path"] = path
                break
        out["has_openapi_spec"] = spec

        manifest = False
        for path in ("/.well-known/mcp.json", "/.well-known/agent.json", "/.well-known/ai-plugin.json"):
            await asyncio.sleep(PER_DOMAIN_DELAY)
            r = await get(client, url + path)
            if r["status"] == 200 and looks_like_manifest(r["text"]):
                manifest = True
                out["manifest_path"] = path
                break
        out["has_agent_manifest"] = manifest

        await asyncio.sleep(PER_DOMAIN_DELAY)
        robots = await get(client, f"{url}/robots.txt")
        out["robots_status"] = robots["status"]
        body = robots["text"].lower() if robots["status"] == 200 else ""
        out["ai_stanza"] = any(
            t in body for t in ("gptbot", "claudebot", "google-extended", "ccbot", "perplexitybot", "anthropic-ai")
        )

    return out


async def main() -> int:
    import warnings

    warnings.filterwarnings("ignore")

    seeds = yaml.safe_load((repo_root() / "seeds" / "seed_urls.yaml").read_text())
    labels = yaml.safe_load((repo_root() / "seeds" / "golden" / "labels.yaml").read_text())
    wanted = {s["url"] for s in labels["sites"]}

    sites = [
        {"name": s["name"], "url": s["url"], "sector": next(
            (l["sector"] for l in labels["sites"] if l["url"] == s["url"]), "?")}
        for g in seeds["groups"].values()
        for s in g["sites"]
        if s["url"] in wanted
    ]

    print(f"probing {len(sites)} golden sites (GET only, {PER_DOMAIN_DELAY}s between requests per domain)\n")
    sem = asyncio.Semaphore(MAX_CONCURRENT_DOMAINS)
    results = await asyncio.gather(*(probe(s, sem) for s in sites))

    out = repo_root() / "seeds" / "golden" / "observations.json"
    out.write_text(json.dumps(results, indent=2))

    for r in sorted(results, key=lambda x: x["sector"]):
        flags = "".join([
            "J" if r["has_jsonld"] else "·",
            "L" if r["has_llms_txt"] else "·",
            "S" if r["has_openapi_spec"] else "·",
            "M" if r["has_agent_manifest"] else "·",
            "A" if r["ai_stanza"] else "·",
        ])
        note = "BLOCKED" if r["blocked"] else f"{r['root_status']}"
        print(f"  {flags}  {note:>7}  {r['name']:<26} {','.join(r['jsonld_types'][:4])}")

    print("\n  J=json-ld  L=llms.txt  S=openapi spec  M=agent manifest  A=ai robots stanza")
    print(f"\nwrote {out.relative_to(repo_root())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
