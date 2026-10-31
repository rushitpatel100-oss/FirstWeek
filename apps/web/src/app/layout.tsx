import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FirstWeek",
  description:
    "Live your first week in a new AI role: an evidence-based report on the job, then a hands-on simulation with AI colleagues.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
