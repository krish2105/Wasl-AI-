"""Crawl policy: what may be fetched, how fast, and how much.

Why the limits are module constants and not settings: a rate limit that lives in
configuration is a rate limit someone raises at 2am to make a demo faster. These
are not tunable. There is no code path in this repository that fetches at more
than 0.5 requests per second per domain or reads more than 40 pages from one
domain, and that is enforced here rather than promised in a README.

Order of checks matters and is deliberate:

    1. exclusion registry   — someone asked not to be crawled. Always wins.
    2. allowlist            — is this domain in the seed file, or did the user
                              submit it themselves?
    3. scheme / path / ext  — is this specific URL fetchable at all?
    4. robots.txt           — checked separately, at fetch time, per URL.

The exclusion list is first because an opt-out that can be overridden by an
allowlist entry is not an opt-out.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import yaml

# --- hard limits. Not configurable. Do not parameterise. ---------------------

REQUESTS_PER_SECOND = 0.5
MIN_REQUEST_INTERVAL_SECONDS = 1.0 / REQUESTS_PER_SECOND  # 2.0s

INTERACTIVE_PAGE_CAP = 12
BATCH_PAGE_CAP = 40
HARD_PAGE_CAP = 40

REQUEST_TIMEOUT_SECONDS = 20
MAX_REDIRECT_DEPTH = 3

# Bodies above this are recorded but not handed to the detectors. Detection is
# roughly linear in document size with a large constant — the injection scanner
# alone takes ~13s on a 50 MB document, and fifteen detectors then compound it.
# A page that large is never article content; it is a feed, a dump or a sitemap,
# and parsing it costs minutes for no evidence.
MAX_PARSEABLE_BYTES = 3_000_000

ALLOWED_SCHEMES = frozenset({"https"})

# Refused regardless of what robots.txt permits. These are the paths where a
# careless GET stops being read-only: session creation, cart mutation, anything
# behind an account.
HARD_EXCLUDED_PATH_PREFIXES = (
    "/checkout",
    "/cart",
    "/login",
    "/signin",
    "/sign-in",
    "/register",
    "/signup",
    "/sign-up",
    "/account",
    "/payment",
    "/admin",
    "/logout",
    "/wp-admin",
)

# We score markup, not media.
SKIP_EXTENSIONS = frozenset(
    {
        ".pdf", ".zip", ".mp4", ".mp3", ".dmg", ".exe", ".apk",
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".css", ".js", ".map", ".xml.gz", ".tar", ".gz", ".rar", ".7z",
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    }
)


class Budget(StrEnum):
    """Which page cap applies.

    INTERACTIVE exists because 40 pages at 0.5 req/s is an 80-second throttle
    floor, which cannot fit inside a 90-second end-to-end target. 12 pages is
    24 seconds of throttle and still clears the 8-page floor below which the
    rubric suppresses its confidence.
    """

    INTERACTIVE = "interactive"
    BATCH = "batch"

    @property
    def page_cap(self) -> int:
        return INTERACTIVE_PAGE_CAP if self is Budget.INTERACTIVE else BATCH_PAGE_CAP


# --- site-level probes -------------------------------------------------------
#
# Correction to the Phase 0 plan, which costed the crawl at "12 pages x 2s = 24s"
# and quietly forgot that probing for llms.txt, sitemaps, .well-known manifests
# and OpenAPI specs are *also* requests to the same rate-limited domain. They are
# not free, and pretending otherwise would have blown the latency budget in a way
# that only showed up during the first live crawl.
#
# The probe list is therefore deliberately short. Every entry has to earn its
# two seconds, so these are the paths with the highest scoring value per request:
# llms.txt is 4 points on its own, an agent manifest is 6, a spec is 6.
#
# Blind probing stops here. Anything else — an /api-docs link seen in a page, a
# sitemap declared in robots.txt — is followed only when the site itself pointed
# at it, which is both politer and more accurate than guessing.

PROBE_PATHS: tuple[str, ...] = (
    "/llms.txt",
    "/sitemap.xml",
    "/.well-known/mcp.json",
    "/.well-known/agent.json",
    "/.well-known/ai-plugin.json",
    "/.well-known/security.txt",
    "/openapi.json",
    "/swagger.json",
    "/api-docs",
)

# robots.txt is fetched separately and always, so it is counted on its own.
ROBOTS_REQUEST_COUNT = 1


def total_request_estimate(budget: "Budget") -> int:
    """Every request a crawl will make, probes included.

    Used by the dry-run plan so the wall-clock estimate shown to a user is the
    real one rather than the page count alone.
    """
    return budget.page_cap + len(PROBE_PATHS) + ROBOTS_REQUEST_COUNT


class Verdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class Decision:
    """A policy answer, with the rule that produced it.

    Carries `rule` so a refusal can be explained to a user precisely — "excluded
    on request" and "not on the allowlist" are very different messages.
    """

    verdict: Verdict
    rule: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


def _allow(rule: str, reason: str) -> Decision:
    return Decision(Verdict.ALLOW, rule, reason)


def _deny(rule: str, reason: str) -> Decision:
    return Decision(Verdict.DENY, rule, reason)


# --- seed registry -----------------------------------------------------------


def repo_root() -> Path:
    """The repository root, found by walking up for a marker.

    Searched rather than counted with `parents[n]`: the index is silently wrong
    the moment a module moves a directory, and it fails at runtime rather than at
    import, which is the worst combination.
    """
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "seeds" / "seed_urls.yaml").exists() or (candidate / ".git").is_dir():
            return candidate
    raise FileNotFoundError(
        f"Could not locate the repository root above {here}. "
        "Expected to find seeds/seed_urls.yaml or a .git directory."
    )


def normalise_domain(value: str) -> str:
    """Reduce a URL or hostname to a comparable registrable-ish domain.

    Strips scheme, port, a leading `www.`, and lowercases. Deliberately does not
    use the public-suffix list: `uae.sharafdg.com` and `sharafdg.com` are
    different entries in the seed file and must stay distinguishable.
    """
    value = value.strip().lower()
    if "://" in value:
        value = urlparse(value).netloc
    value = value.split("@")[-1].split(":")[0]
    return value[4:] if value.startswith("www.") else value


@dataclass(frozen=True, slots=True)
class SeedEntry:
    name: str
    url: str
    domain: str
    group_key: str
    group_label: str
    golden: bool


class SeedRegistry:
    """The allowlist and the exclusion registry, loaded from seeds/seed_urls.yaml."""

    def __init__(self, data: dict) -> None:
        self._raw = data
        self.entries: dict[str, SeedEntry] = {}
        for group_key, group in (data.get("groups") or {}).items():
            for site in group.get("sites", []):
                domain = normalise_domain(site["url"])
                self.entries[domain] = SeedEntry(
                    name=site["name"],
                    url=site["url"],
                    domain=domain,
                    group_key=group_key,
                    group_label=group.get("label", group_key),
                    golden=bool(site.get("golden", False)),
                )
        excluded = (data.get("excluded") or {}).get("domains") or []
        self.excluded: dict[str, str] = {
            normalise_domain(d): ((data.get("excluded") or {}).get("reasons") or {}).get(
                d, "removal requested"
            )
            for d in excluded
        }

    @classmethod
    def load(cls, path: Path | None = None) -> SeedRegistry:
        path = path or repo_root() / "seeds" / "seed_urls.yaml"
        return cls(yaml.safe_load(path.read_text()))

    @property
    def expected_counts(self) -> dict[str, int]:
        return self._raw.get("expected_counts", {})

    @property
    def actual_counts(self) -> dict[str, int]:
        groups = self._raw.get("groups") or {}
        sites = [s for g in groups.values() for s in g.get("sites", [])]
        return {
            "total_sites": len(sites),
            "golden_sites": sum(1 for s in sites if s.get("golden")),
            "groups": len(groups),
        }

    def is_excluded(self, domain: str) -> bool:
        return normalise_domain(domain) in self.excluded

    def is_allowlisted(self, domain: str) -> bool:
        return normalise_domain(domain) in self.entries

    def entry_for(self, domain: str) -> SeedEntry | None:
        return self.entries.get(normalise_domain(domain))

    def golden_domains(self) -> list[str]:
        return [d for d, e in self.entries.items() if e.golden]


@lru_cache(maxsize=1)
def get_seed_registry() -> SeedRegistry:
    return SeedRegistry.load()


# --- the policy --------------------------------------------------------------


class CrawlPolicy:
    """Decides what may be fetched. Holds no state about what has been."""

    def __init__(self, registry: SeedRegistry | None = None) -> None:
        self._registry = registry or get_seed_registry()

    def check_domain(self, domain_or_url: str, *, user_submitted: bool = False) -> Decision:
        """May we crawl this domain at all?

        `user_submitted` covers the runtime case: a user pasting their own URL
        into the app. It bypasses the allowlist — that is the whole point of the
        product — but it does NOT bypass the exclusion registry.
        """
        domain = normalise_domain(domain_or_url)
        if not domain:
            return _deny("malformed", "Could not determine a domain from the input.")

        if self._registry.is_excluded(domain):
            reason = self._registry.excluded[domain]
            return _deny("excluded", f"{domain} is on the exclusion registry: {reason}")

        if self._registry.is_allowlisted(domain):
            return _allow("allowlist", f"{domain} is in seeds/seed_urls.yaml")

        if user_submitted:
            return _allow(
                "user_submitted",
                f"{domain} was submitted at runtime by a user for their own property",
            )

        return _deny(
            "not_allowlisted",
            f"{domain} is not in seeds/seed_urls.yaml and was not submitted by a user",
        )

    def check_url(self, url: str) -> Decision:
        """May we fetch this specific URL, ignoring robots (checked separately)?"""
        parsed = urlparse(url)

        if parsed.scheme not in ALLOWED_SCHEMES:
            return _deny("scheme", f"Scheme {parsed.scheme!r} is not allowed; https only.")

        path = (parsed.path or "/").lower().rstrip("/") or "/"
        for prefix in HARD_EXCLUDED_PATH_PREFIXES:
            if path == prefix or path.startswith(prefix + "/"):
                return _deny(
                    "hard_excluded_path",
                    f"{prefix} is never fetched — state-changing or account surface.",
                )

        suffix = Path(parsed.path).suffix.lower()
        if suffix in SKIP_EXTENSIONS:
            return _deny("skip_extension", f"{suffix} is a binary or asset; we score markup.")

        return _allow("ok", "URL is fetchable")

    def page_cap(self, budget: Budget) -> int:
        """The page cap for a budget, clamped to the hard cap regardless."""
        return min(budget.page_cap, HARD_PAGE_CAP)

    @staticmethod
    def throttle_seconds(page_count: int) -> float:
        """Wall-clock floor imposed by the rate limit alone."""
        return page_count * MIN_REQUEST_INTERVAL_SECONDS
