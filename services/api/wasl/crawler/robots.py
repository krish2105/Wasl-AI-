"""robots.txt: fetch, obey, and record as evidence.

Two jobs, and the second is easy to forget. The first is compliance — parse the
file and never fetch what it disallows. The second is *measurement*: whether a
site has thought about agent access at all is one of the things Wasl scores, and
the signal lives in this file.

The scoring nuance worth stating plainly, because it is counter-intuitive: an
explicit stanza naming an AI crawler earns points **whether it allows or
disallows**. A site that writes `User-agent: GPTBot / Disallow: /` has made a
deliberate, legible decision about agents. A site with no such stanza has not
decided anything. Axis 1 rewards the clarity, not the verdict — so a site is
never penalised for telling us to go away.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from wasl.crawler.policy import REQUEST_TIMEOUT_SECONDS
from wasl.crawler.types import RobotsInfo

# User-agent tokens that identify an AI/LLM crawler or agent. Compiled from the
# tokens these operators publish. Matched case-insensitively as substrings,
# because sites write them inconsistently.
AI_AGENT_TOKENS: tuple[str, ...] = (
    "gptbot",
    "chatgpt-user",
    "oai-searchbot",
    "claudebot",
    "claude-web",
    "claude-searchbot",
    "anthropic-ai",
    "google-extended",
    "googleother",
    "perplexitybot",
    "perplexity-user",
    "ccbot",
    "bytespider",
    "applebot-extended",
    "meta-externalagent",
    "meta-externalfetcher",
    "facebookbot",
    "cohere-ai",
    "cohere-training-data-crawler",
    "diffbot",
    "omgilibot",
    "omgili",
    "imagesiftbot",
    "youbot",
    "timpibot",
    "amazonbot",
    "ai2bot",
    "petalbot",
    "mistralai-user",
    "duckassistbot",
    "wasl",
)

_USER_AGENT_LINE = re.compile(r"^\s*user-agent\s*:\s*(.+?)\s*(?:#.*)?$", re.IGNORECASE | re.MULTILINE)
_SITEMAP_LINE = re.compile(r"^\s*sitemap\s*:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


def robots_url_for(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def _extract_agent_stanzas(raw: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (all user-agent tokens, the subset that name AI crawlers)."""
    agents: list[str] = []
    for match in _USER_AGENT_LINE.finditer(raw):
        token = match.group(1).strip()
        if token and token not in agents:
            agents.append(token)

    ai = [a for a in agents if any(t in a.lower() for t in AI_AGENT_TOKENS)]
    return tuple(agents), tuple(ai)


def parse_robots(raw: str, *, url: str) -> RobotsInfo:
    """Parse robots.txt text into structured data.

    A file that exists but cannot be parsed is a distinct outcome from one that
    is absent — Axis 1 scores presence and parseability as separate signals.
    """
    parser = RobotFileParser()
    parseable = True
    try:
        parser.parse(raw.splitlines())
    except Exception:
        parseable = False

    agents, ai_agents = _extract_agent_stanzas(raw)
    sitemaps = tuple(dict.fromkeys(_SITEMAP_LINE.findall(raw)))

    crawl_delay: float | None = None
    if parseable:
        try:
            delay = parser.crawl_delay("*")
            crawl_delay = float(delay) if delay is not None else None
        except Exception:
            crawl_delay = None

    return RobotsInfo(
        url=url,
        present=True,
        parseable=parseable,
        raw=raw,
        sitemaps=sitemaps,
        agent_stanzas=agents,
        ai_agent_stanzas=ai_agents,
        crawl_delay=crawl_delay,
    )


class RobotsCache:
    """Fetches and caches robots.txt, one entry per origin.

    Cached for the lifetime of the crawl. Re-fetching robots.txt for every page
    would be its own small act of rudeness.
    """

    def __init__(self, client: httpx.AsyncClient, *, user_agent: str) -> None:
        self._client = client
        self._user_agent = user_agent
        self._cache: dict[str, tuple[RobotsInfo, RobotFileParser | None]] = {}

    async def get(self, url: str) -> RobotsInfo:
        origin = robots_url_for(url)
        if origin in self._cache:
            return self._cache[origin][0]

        info, parser = await self._fetch(origin)
        self._cache[origin] = (info, parser)
        return info

    async def _fetch(self, robots_url: str) -> tuple[RobotsInfo, RobotFileParser | None]:
        try:
            response = await self._client.get(
                robots_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": self._user_agent},
            )
        except Exception as exc:
            return (
                RobotsInfo(
                    url=robots_url,
                    present=False,
                    parseable=False,
                    fetch_error=f"{type(exc).__name__}: {exc}",
                ),
                None,
            )

        if response.status_code >= 400:
            # No robots.txt is not an error and not a refusal. RFC 9309 treats a
            # 404 as "everything allowed". We record the absence as a finding
            # because Axis 1 scores its presence.
            return (
                RobotsInfo(
                    url=robots_url,
                    present=False,
                    parseable=False,
                    fetch_error=f"HTTP {response.status_code}",
                ),
                None,
            )

        raw = response.text
        info = parse_robots(raw, url=robots_url)

        parser = RobotFileParser()
        try:
            parser.parse(raw.splitlines())
        except Exception:
            parser = None  # type: ignore[assignment]

        return info, parser

    async def is_allowed(self, url: str) -> bool:
        """May we fetch this URL under our own User-Agent?

        Defaults to allowed when robots.txt is absent or unparseable, which is
        what RFC 9309 specifies. Every other ambiguity in this codebase resolves
        toward not fetching; this one follows the standard instead, because
        treating a missing file as a blanket refusal would make most of the web
        uncrawlable and is not what site operators mean.
        """
        origin = robots_url_for(url)
        if origin not in self._cache:
            await self.get(url)

        _, parser = self._cache[origin]
        if parser is None:
            return True

        try:
            return bool(parser.can_fetch(self._user_agent, url))
        except Exception:
            return True

    async def sitemaps_for(self, url: str) -> tuple[str, ...]:
        """Sitemap URLs declared in robots.txt, absolutised."""
        info = await self.get(url)
        return tuple(urljoin(info.url, s) for s in info.sitemaps)
