/**
 * Icon set — hand-drawn on a 24px grid, 1.6px strokes, `currentColor` throughout.
 *
 * No icon library. Not out of purism: this product needs a handful of icons that
 * mean something specific to it — "suppressed", "refused", "evidence", "the
 * machine/human split" — and none of those exist in a general set. Drawing the
 * six that matter beats installing 1,400 to get four generic ones.
 *
 * Every icon is decorative by default (`aria-hidden`) because it always sits
 * beside a label. Pass a `title` on the rare occasion one stands alone.
 */

type IconProps = {
  size?: number;
  className?: string;
  strokeWidth?: number;
  title?: string;
};

function Svg({
  size = 16,
  className,
  strokeWidth = 1.6,
  title,
  children,
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      {title && <title>{title}</title>}
      {children}
    </svg>
  );
}

/**
 * The Wasl mark. "Wasl" is Arabic for connection or link, so the mark is two
 * nodes and the line between them — with the left node hollow and the right one
 * filled, which is the product in one glyph: something unreadable becoming
 * something readable.
 */
export function WaslMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      role="img"
      aria-label="Wasl"
    >
      <title>Wasl</title>
      {/* the link */}
      <path
        d="M11 16h10"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.55"
      />
      {/* unreadable: hollow, dashed */}
      <circle
        cx="7"
        cy="16"
        r="4.4"
        stroke="currentColor"
        strokeWidth="2"
        strokeDasharray="2.2 2.6"
        opacity="0.7"
      />
      {/* readable: solid */}
      <circle cx="25" cy="16" r="4.4" fill="currentColor" />
    </svg>
  );
}

export const CheckIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 6 9 17l-5-5" />
  </Svg>
);

/** Partial credit — deliberately not a half-filled circle, which reads as loading. */
export const PartialIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12h14" />
    <path d="M12 5v14" opacity="0.35" />
  </Svg>
);

export const RefusedIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M18 6 6 18M6 6l12 12" />
  </Svg>
);

/**
 * Suppressed — "we could not evaluate this", which is NOT a failure. A dashed
 * ring rather than a cross, because those two states must never look alike.
 */
export const SuppressedIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" strokeDasharray="2.4 2.8" />
    <path d="M9 12h6" opacity="0.6" />
  </Svg>
);

/** Evidence — a document with a marked line, the citation itself. */
export const EvidenceIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 3h8l4 4v14H6z" />
    <path d="M14 3v4h4" />
    <path d="M9 13h6M9 16.5h4" />
  </Svg>
);

export const DownloadIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 4v11" />
    <path d="M7.5 10.5 12 15l4.5-4.5" />
    <path d="M5 19h14" />
  </Svg>
);

export const ExternalIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 5h5v5" />
    <path d="M19 5l-8 8" />
    <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
  </Svg>
);

export const ArrowLeftIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M19 12H5" />
    <path d="M11 6l-6 6 6 6" />
  </Svg>
);

export const ArrowRightIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12h14" />
    <path d="M13 6l6 6-6 6" />
  </Svg>
);

/** The pre-JS / post-JS split — the measurement at the heart of the product. */
export const SplitIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="7.5" height="16" rx="1" strokeDasharray="2.4 2.4" />
    <rect x="13.5" y="4" width="7.5" height="16" rx="1" />
    <path d="M16 9h2.5M16 12h2.5M16 15h1.5" opacity="0.55" />
  </Svg>
);

export const ShieldIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l7 3v6c0 4.4-2.9 8.2-7 9-4.1-.8-7-4.6-7-9V6z" />
    <path d="M9.5 12l1.8 1.8 3.4-3.6" />
  </Svg>
);

export const ChevronIcon = ({ open, ...p }: IconProps & { open?: boolean }) => (
  <Svg {...p} className={`${p.className ?? ""} transition-transform duration-200`}>
    <g style={{ transformOrigin: "center", transform: open ? "rotate(90deg)" : "none" }}>
      <path d="M9 6l6 6-6 6" />
    </g>
  </Svg>
);
