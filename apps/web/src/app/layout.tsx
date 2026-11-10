import type { Metadata } from "next";
import { Bricolage_Grotesque, IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const display = Bricolage_Grotesque({ subsets: ["latin"], variable: "--font-bricolage" });
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex",
});
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });

export const metadata: Metadata = {
  title: { default: "FirstWeek", template: "%s | FirstWeek" },
  description:
    "Try an AI job before you take it: what the role really involves, from real postings and practitioners, then a week doing it with AI colleagues.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`h-full antialiased ${display.variable} ${sans.variable} ${mono.variable}`}>
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-paper focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <header className="border-b border-line bg-paper">
          <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
            <Link href="/" className="flex items-center gap-2.5 font-display text-lg font-semibold tracking-tight">
              <span aria-hidden className="grid h-7 w-7 place-items-center rounded-md bg-brand text-sm text-on-brand">
                F
              </span>
              FirstWeek
            </Link>
            <nav className="text-sm text-muted">
              <Link href="/#roles" className="hover:text-ink">
                Roles
              </Link>
            </nav>
          </div>
        </header>
        <div id="main" className="flex flex-1 flex-col">
          {children}
        </div>
        <footer className="border-t border-line">
          <p className="mx-auto w-full max-w-7xl px-4 py-6 text-sm text-muted sm:px-6">
            FirstWeek is a portfolio project. The companies in the practice weeks are made up; the
            reports quote real postings and practitioners.
          </p>
        </footer>
      </body>
    </html>
  );
}
