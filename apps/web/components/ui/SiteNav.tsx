"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { WaslMark } from "./Icons";
import { ThemeToggle } from "./ThemeToggle";

/**
 * Shared nav.
 *
 * Sticky with a blurred backdrop — the one place `backdrop-filter` is used, per
 * the brief. Applied here and on modals only, never on the hero, where it costs
 * a compositing layer for no legibility gain.
 */

const LINKS = [
  { href: "/scan", label: "scan" },
  { href: "/leaderboard", label: "leaderboard" },
  { href: "/crawler", label: "crawler" },
];

export function SiteNav(): React.ReactElement {
  const pathname = usePathname();

  return (
    <header
      className="sticky top-0 z-40"
      style={{
        // Pinned so the header and the scroll-padding derived from it in
        // globals.css cannot drift apart. Matches the natural height.
        minHeight: "var(--header-h)",
        borderBottom: "1px solid var(--border)",
        background: "color-mix(in srgb, var(--surface) 82%, transparent)",
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
      }}
    >
      <nav
        className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3"
        aria-label="Primary"
      >
        <Link
          href="/"
          className="flex items-center gap-2.5"
          style={{ color: "var(--text)" }}
          aria-label="Wasl AI, home"
        >
          <WaslMark size={22} />
          <span
            className="mono"
            style={{ letterSpacing: "0.16em", fontWeight: 500, fontSize: "0.82rem" }}
          >
            WASL
          </span>
        </Link>

        <ul className="mono m-0 ml-auto flex list-none items-center gap-5 p-0">
          {LINKS.map((link) => {
            const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  style={{
                    color: active ? "var(--text)" : "var(--text-faint)",
                    borderBottom: active ? "1px solid var(--signal)" : "1px solid transparent",
                    paddingBottom: 2,
                    transition: "color 140ms ease",
                  }}
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
          <li>
            <ThemeToggle />
          </li>
        </ul>
      </nav>
    </header>
  );
}
