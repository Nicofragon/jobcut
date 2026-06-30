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

// Applied synchronously in <head>, before the first paint, so a saved dark
// preference never flashes light on load (Next: "preventing flash before
// hydration"). suppressHydrationWarning on <html> lets this win over the SSR
// default of data-theme="light".
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("theme");if(t==="dark"||t==="light")document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning className={inter.variable}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-screen antialiased">
        <Nav />
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
