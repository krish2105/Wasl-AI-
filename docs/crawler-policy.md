# Wasl AI — Crawler Policy

**This is the page the crawler's User-Agent points at.** If you have arrived here
because you saw `WaslAI-Research` in your server logs, this document explains
exactly what it did and how to make it stop.

**To opt out:** email the address in the User-Agent string. Removal is applied
within 24 hours and is permanent. You do not need to give a reason.

---

## What Wasl is

Wasl AI is a research and portfolio project that measures how legible a public
website is to AI agents. It scores a site on a published 100-point rubric and
generates an example [MCP](https://modelcontextprotocol.io) server describing the
capabilities it found.

It exists because businesses across the UAE are being told to "become agentic"
under government programmes with real deadlines, while their websites remain
largely unreadable to any automated client. Wasl measures that gap.

It is not a commercial product, it does not resell data, and it does not
republish your content.

---

## What the crawler does

| | |
|---|---|
| **Method** | `GET` only. No `POST`, `PUT`, `PATCH`, `DELETE`, or any other verb. |
| **Rate** | 0.5 requests per second per domain — one request every two seconds. |
| **Volume** | 12 pages per interactive scan, 40 per batch crawl. Never more. |
| **Scheme** | `https` only. |
| **Identity** | `WaslAI-Research/<version> (+<this page>)`. Never spoofed. |
| **JavaScript** | Headless Chromium, to measure what renders before and after hydration. |
| **Assets** | Images, fonts and media are blocked at the network layer. We read markup. |

These are constants in the source code (`wasl/crawler/policy.py`), not
configuration. There is no setting, environment variable or API parameter that
raises them.

## What the crawler never does

- **Never authenticates.** No login, no credentials, no session, no cookies
  carried between crawls.
- **Never submits a form.** `POST` forms are recorded as markup and left alone.
  `GET` search forms are noted as a capability, not exercised.
- **Never touches** `/checkout`, `/cart`, `/login`, `/signin`, `/register`,
  `/account`, `/payment`, or `/admin` — regardless of what `robots.txt` permits.
- **Never bypasses** a paywall, a CAPTCHA, a bot wall, or a rate limit. If you
  block us, we record that you blocked us and move on.
- **Never probes for rate limits.** We read `Retry-After` and `RateLimit-*`
  headers only when a server volunteers them during an ordinary crawl. We do not
  send bursts to discover your limits.
- **Never collects personal data.** If personal data is encountered incidentally,
  it is not stored.

## robots.txt

`robots.txt` is authoritative. Disallowed paths are not fetched.

One thing worth knowing, because it is counter-intuitive: **a `Disallow` does not
lower your score.** Wasl scores whether a site has made a legible decision about
agent access. A site with an explicit `User-agent: GPTBot / Disallow: /` stanza
scores the same as one that allows it — both are clear. Silence scores nothing.
You are never penalised for telling automated clients to go away.

If you want to block Wasl specifically:

```
User-agent: WaslAI-Research
Disallow: /
```

This is honoured immediately, on the next crawl. Emailing the opt-out address is
faster and also removes any existing published score.

---

## Which sites are crawled

Only two categories:

1. Domains on a reviewed list committed in the repository at
   `seeds/seed_urls.yaml`.
2. A domain a user explicitly submits through the web interface, for a site they
   are checking themselves.

There is no open crawl, no link-following off-domain, and no discovery of new
domains. An **exclusion registry is checked before the allowlist**, so an opt-out
cannot be overridden by a later seed-list entry.

## Caching

Pages are cached by URL and date. Development and testing run against saved
copies, not live requests, so a site is not re-fetched every time the code
changes. Generated MCP servers read from that cache by default — running one
sends no traffic to your site.

## Published results

Wasl publishes a leaderboard of scores.

- **Government and public-sector entities are anonymised** by default, shown as a
  sector and a band rather than a name.
- Commercial entities are named.
- **Any entity is removed on request, within 24 hours, without argument.**
- We publish scores, findings and short evidence snippets. We do not republish
  substantial content from any site.

## Data we keep

Per crawled page: the URL, HTTP status, response headers, response time, and the
HTML as fetched. Snippets of that HTML are stored as evidence so any score we
publish can be traced to the exact markup that produced it — this is what makes
the score auditable rather than an opinion.

No personal data. No credentials. Nothing behind a login, because we never log in.

---

## Contact

Opt-out requests, complaints and corrections go to the address published in the
crawler's User-Agent string. Removal requests are actioned within 24 hours and
are not negotiated.

*Not legal advice. This document describes what the software does, which is
verifiable from the source.*
