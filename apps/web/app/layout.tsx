import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Wasl AI",
  description:
    "Scores whether a business is legible to AI agents, then generates the MCP server that makes it legible.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>): React.ReactElement {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
