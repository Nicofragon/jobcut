"use client";

import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

// Strip a leading YAML frontmatter block (Obsidian/authoring metadata). Without this,
// `---\nkey: val\n---` renders as an ugly setext heading and pollutes the in-doc TOC.
const FRONTMATTER = /^﻿?---\r?\n[\s\S]*?\r?\n---\r?\n/;

// Renders a prep/debrief/study document body as sanitised markdown.
// - `rehype-sanitize` (GitHub default schema) is non-negotiable: doc bodies travel in the
//   portable jobcut.db and could be shared, so raw HTML (`<img onerror=…>`) must never run.
//   The default schema already permits GFM task-list checkboxes and `language-*` code classes.
// - `rehype-slug` runs AFTER sanitize (so its ids survive) and gives headings stable ids the
//   reader's "On this page" TOC scrolls to.
// react-markdown v10 dropped the `className` prop — the `.md-doc` wrapper (styled in
// globals.css with the theme tokens) carries the typography.
export default function DocumentViewer({ body }: { body: string }) {
  const clean = body.replace(FRONTMATTER, "");
  return (
    <div className="md-doc">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize, rehypeSlug]}>
        {clean}
      </ReactMarkdown>
    </div>
  );
}
