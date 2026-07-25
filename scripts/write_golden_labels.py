#!/usr/bin/env python
"""Assemble seeds/golden/labels.yaml from probe observations plus authored judgement.

READ THE HEADER THIS WRITES INTO THE FILE BEFORE TRUSTING ANY METRIC DERIVED
FROM IT. These labels are model-authored, at the explicit direction of the
repository owner, after the circularity objection was raised and overruled.

The split is deliberate and is recorded per-field in the output:

  observed  has_jsonld, has_llms_txt, has_openapi_spec, has_agent_manifest
            — taken verbatim from scripts/probe_golden.py, which issues plain
              HTTP requests and does NOT use Wasl's detectors. Facts, not
              tautologies.

  authored  capabilities, expected_band, notes
            — model judgement. These are the fields that make the three
              dependent metrics circular, and they are flagged as such.

Sites that blocked observation get `observable: false` and a null band. Guessing
a band for a site we could not read would be inventing ground truth twice over.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
from wasl.crawler.policy import repo_root  # noqa: E402

# --- authored judgement ------------------------------------------------------
# capabilities follow the granularity rule: one distinct (verb, noun) pair
# reachable through one mechanism. Pagination, sorting and output format are
# parameters, never separate capabilities.

AUTHORED: dict[str, dict] = {
    # --- SaaS / API-first ----------------------------------------------------
    "Stripe": {
        "capabilities": ["search documentation", "get api reference", "list products", "get pricing"],
        "band": "Agent-Ready",
        "notes": "Public OpenAPI spec exists but is published on GitHub, not at a conventional path — "
                 "Wasl probes /openapi.json and /swagger.json only, so it will miss this and lose 6 "
                 "points on Axis 3. A real recall gap in the prober, not a gap in the site.",
    },
    "Twilio": {
        "capabilities": ["search documentation", "get api reference", "list products", "get pricing"],
        "band": "Agent-Ready",
        "notes": "OpenAPI spec published on GitHub rather than at a conventional path. Same prober "
                 "limitation as Stripe.",
    },
    "GitHub": {
        "capabilities": ["search repositories", "get repository", "search documentation", "get api reference"],
        "band": "Agent-Ready",
        "notes": "No JSON-LD on the marketing homepage, which understates a site whose entire product "
                 "is a documented API. OpenAPI spec lives in github/rest-api-description.",
    },
    "Shopify": {
        "capabilities": ["search documentation", "get api reference", "list pricing plans"],
        "band": "Agent-Ready",
        "notes": "GraphQL and REST admin APIs are documented; neither is discoverable at a conventional "
                 "spec path.",
    },
    # --- automotive ----------------------------------------------------------
    "DubiCars": {
        "capabilities": ["search cars", "get car listing", "list dealers"],
        "band": "Readable",
        "notes": "Listing IDs appear in URLs and Organization JSON-LD is present, but there is no "
                 "documented API and no llms.txt.",
    },
    "YallaMotor": {
        "capabilities": ["search cars", "get car listing", "get car specifications", "list dealers"],
        "band": "Readable",
        "notes": "SearchAction in JSON-LD advertises a machine-usable search endpoint, and an llms.txt "
                 "is published — unusually strong Axis 1 for a regional classifieds site.",
    },
    "Arabian Automobiles": {"capabilities": None, "band": None, "notes": None},
    # --- e-commerce ----------------------------------------------------------
    "Noon": {"capabilities": None, "band": None, "notes": None},
    "Amazon.ae": {
        "capabilities": ["search products", "get product details", "list categories"],
        "band": "Readable",
        "notes": "Homepage carries no JSON-LD; product pages do. A 12-page interactive crawl that lands "
                 "mostly on category pages will understate Axis 2.",
    },
    "Namshi": {"capabilities": None, "band": None, "notes": None},
    "Ounass": {
        "capabilities": ["search products", "get product details", "list brands"],
        "band": "Readable",
        "notes": "OnlineStore JSON-LD on the homepage. No API, no llms.txt.",
    },
    "Sharaf DG": {
        "capabilities": ["search products", "get product details", "list store locations"],
        "band": "Emerging",
        "notes": "Names AI crawlers in robots.txt but publishes no structured data on the homepage — "
                 "aware of agents without being readable by them.",
    },
    "Lulu Hypermarket": {
        "capabilities": ["search products", "get product details", "list store locations"],
        "band": "Readable",
        "notes": "WebSite + SearchAction JSON-LD gives a constructible search URL.",
    },
    # --- government / public -------------------------------------------------
    "UAE Government Portal": {
        "capabilities": ["search services", "get service details", "list government entities"],
        "band": "Emerging",
        "notes": "No structured data, no llms.txt, no AI-agent stanza. Notable given the federal "
                 "directive to move half of government services to autonomous agents by 2028 — the "
                 "portal that indexes those services is not currently machine-readable.",
    },
    "MOHRE": {
        "capabilities": ["search services", "get service details"],
        "band": "Emerging",
        "notes": "No structured data or agent-facing metadata observed on the public homepage.",
    },
    "Federal Tax Authority": {
        "capabilities": ["search services", "get service details", "list tax rates"],
        "band": "Emerging",
        "notes": "Substantial public guidance, none of it structured. Relevant to the e-invoicing "
                 "rollout, where machine-readable guidance would matter most.",
    },
    "Dubai Land Department": {
        "capabilities": ["search services", "get service details", "list transactions"],
        "band": "Emerging",
        "notes": "Names AI crawlers in robots.txt but publishes no structured data. DLD does release "
                 "open transaction data through Dubai Pulse — not linked from here in a machine-"
                 "discoverable way.",
    },
    # --- hospitality / travel ------------------------------------------------
    "Emirates": {"capabilities": None, "band": None, "notes": None},
    "flydubai": {"capabilities": None, "band": None, "notes": None},
    "Jumeirah": {
        "capabilities": ["list hotels", "get hotel details", "search availability"],
        "band": "Readable",
        "notes": "Organization + PostalAddress JSON-LD. Availability sits behind a booking engine, so "
                 "the capability is detected but not machine-reachable.",
    },
    "Atlantis The Palm": {"capabilities": None, "band": None, "notes": None},
    "Visit Dubai (DET)": {
        "capabilities": ["search attractions", "get attraction details", "list events", "search hotels"],
        "band": "Readable",
        "notes": "Publishes an llms.txt and names AI crawlers — the most agent-aware government-linked "
                 "site in this set. No structured data on the homepage, which caps Axis 2.",
    },
    # --- logistics -----------------------------------------------------------
    "DP World": {
        "capabilities": ["search services", "get service details", "list ports"],
        "band": "Readable",
        "notes": "Organization JSON-LD. Cargo tracking exists but is JS-gated and unreachable without "
                 "a browser, which is the hypothesis this sector was chosen to test.",
    },
    "Aramex": {"capabilities": None, "band": None, "notes": None},
    "Emirates Post": {
        "capabilities": ["track shipment", "search services", "get service details", "list post offices"],
        "band": "Readable",
        "notes": "Strongest Axis 1 and 2 in the government group: llms.txt, an AI-agent stanza, and "
                 "GovernmentOrganization/Service/ItemList JSON-LD. Tracking is a genuine capability, "
                 "though it is form-driven rather than documented.",
    },
    # --- real estate ---------------------------------------------------------
    "Bayut": {
        "capabilities": ["search properties", "get property listing", "list agents", "get area guide"],
        "band": "Readable",
        "notes": "Publishes an llms.txt. Homepage carries no JSON-LD; listing pages do. Returned 401 to "
                 "a HEAD request during seed verification but serves GET normally.",
    },
    "Property Finder": {
        "capabilities": ["search properties", "get property listing", "list agents"],
        "band": "Readable",
        "notes": "WebSite + SearchAction + Organization JSON-LD gives a constructible search URL.",
    },
    "Emaar Properties": {
        "capabilities": ["list developments", "get development details"],
        "band": "Emerging",
        "notes": "Names AI crawlers in robots.txt but publishes no structured data. Developer sites "
                 "score lower than listing portals, as the sector hypothesis predicted.",
    },
    "DAMAC Properties": {"capabilities": None, "band": None, "notes": None},
    "Betterhomes": {
        "capabilities": ["search properties", "get property listing", "list agents"],
        "band": "Readable",
        "notes": "llms.txt, AI-agent stanza and SearchAction JSON-LD together — the most complete "
                 "Axis 1 in the real-estate group.",
    },
}

HEADER = """# WASL AI — GOLDEN EVAL SET (30 sites)
#
# =============================================================================
# ⚠  THESE LABELS ARE MODEL-AUTHORED, NOT HAND-LABELLED BY A HUMAN.
# =============================================================================
#
# Written by Claude at the explicit direction of the repository owner, after the
# circularity objection was raised and overruled. What that costs, stated plainly
# so nobody has to work it out:
#
#   capability_precision, capability_recall and band_accuracy are computed
#   against these labels. Because a model authored the judgement fields, those
#   three metrics measure "does Wasl agree with the labelling model" rather than
#   "is Wasl correct". They are reported under judge_labelled_* names and carry
#   an asterisk everywhere they appear.
#
#   The four boolean fields are NOT circular. They come from
#   scripts/probe_golden.py, which issues plain HTTP requests and does not use
#   Wasl's detectors — so has_llms_txt is an observation, not a tautology.
#
# To make these metrics mean what they claim: replace the authored fields by
# hand, set label_source to "human", and rename the metrics back. The
# observations in seeds/golden/observations.json make that a review task rather
# than a research task.
#
# -----------------------------------------------------------------------------
# CAPABILITY GRANULARITY RULE
#
#   A capability is ONE distinct (verb, noun) pair reachable through ONE
#   mechanism.
#
#   * "search products" and "filter products by price" are ONE capability when
#     the filter is a parameter on the same endpoint or form.
#   * "get product details" and "get product reviews" are TWO — different nouns.
#   * Pagination, sorting and output format are NEVER separate capabilities.
#
# -----------------------------------------------------------------------------
# UNOBSERVABLE SITES
#
#   Eight of the thirty blocked automated access (401/403/timeout) at labelling
#   time. They carry observable: false and a null band. Guessing a band for a
#   site nobody could read would be inventing ground truth twice over, so the
#   eval excludes them from band accuracy and reports the reduced denominator.
#
# COMPOSITION: 6 e-commerce | 5 real estate | 5 hospitality/travel
#              4 government/public | 4 SaaS/API-first | 3 automotive | 3 logistics
# -----------------------------------------------------------------------------
"""


def main() -> int:
    root = repo_root()
    observations = {o["name"]: o for o in json.loads((root / "seeds" / "golden" / "observations.json").read_text())}
    existing = yaml.safe_load((root / "seeds" / "golden" / "labels.yaml").read_text())

    sites = []
    for entry in existing["sites"]:
        name = entry["name"]
        obs = observations.get(name, {})
        authored = AUTHORED.get(name, {"capabilities": None, "band": None, "notes": None})
        observable = not obs.get("blocked", True)

        sites.append(
            {
                "name": name,
                "url": entry["url"],
                "sector": entry["sector"],
                "group": entry["group"],
                "observable": observable,
                # observed — from probe_golden.py, not from Wasl
                "has_jsonld": obs.get("has_jsonld") if observable else None,
                "has_llms_txt": obs.get("has_llms_txt") if observable else None,
                "has_openapi_spec": obs.get("has_openapi_spec") if observable else None,
                "has_agent_manifest": obs.get("has_agent_manifest") if observable else None,
                "has_ai_robots_stanza": obs.get("ai_stanza") if observable else None,
                "jsonld_types": obs.get("jsonld_types") or [] if observable else None,
                # authored — model judgement
                "capabilities": authored["capabilities"],
                "expected_band": authored["band"],
                "notes": authored["notes"] or (
                    f"Blocked automated access at labelling time (HTTP "
                    f"{obs.get('root_status', 0) or 'timeout'}); not observable, so not labelled."
                    if not observable else None
                ),
            }
        )

    payload = {
        "version": 2,
        "label_source": "model",
        "labelled_by": "Claude Opus 5, at repository owner's direction",
        "labelled_at": "2026-07-25",
        "circular": True,
        "circularity_note": (
            "capabilities, expected_band and notes are model-authored, so metrics computed "
            "against them measure agreement with the labelling model rather than correctness. "
            "The boolean fields are independent observations from scripts/probe_golden.py."
        ),
        "granularity_rule": "one distinct (verb, noun) pair reachable through one mechanism",
        "observable_sites": sum(1 for s in sites if s["observable"]),
        "sites": sites,
    }

    out = root / "seeds" / "golden" / "labels.yaml"
    out.write_text(HEADER + "\n" + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100))

    observable = [s for s in sites if s["observable"]]
    from collections import Counter

    print(f"wrote {out.relative_to(root)}")
    print(f"  {len(sites)} sites | {len(observable)} observable | {len(sites) - len(observable)} blocked")
    print(f"  bands: {dict(Counter(s['expected_band'] for s in observable))}")
    print(f"  llms.txt: {sum(1 for s in observable if s['has_llms_txt'])}/{len(observable)}")
    print(f"  json-ld:  {sum(1 for s in observable if s['has_jsonld'])}/{len(observable)}")
    print(f"  ai stanza:{sum(1 for s in observable if s['has_ai_robots_stanza'])}/{len(observable)}")
    print(f"  capabilities labelled: {sum(len(s['capabilities'] or []) for s in sites)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
