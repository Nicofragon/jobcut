import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "jobcut",
  description: "A local, scored job pipeline — your daily ranked shortlist and funnel.",
};

// Inter via next/font: self-hosted at build time (no runtime network), exposed as
// the --font-inter CSS var that --font-sans (globals.css) consumes.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen antialiased">
        <Nav />
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
