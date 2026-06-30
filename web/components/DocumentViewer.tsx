"use client";

import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

// Strip a leading YAML frontmatter block (Obsidian/authoring metadata). Without this,
// `---\nkey: val\n---` renders as an ugly setext heading at the top of the doc.
const FRONTMATTER = /^﻿?---\r?\n[\s\S]*?\r?\n---\r?\n/;

// Renders a prep/debrief/study document body as sanitised markdown. `rehype-sanitize`
// (GitHub default schema) is non-negotiable: doc bodies travel in the portable jobcut.db
// and could be shared, so raw HTML (`<img onerror=…>`) must never execute. The default
// schema already permits GFM task-list checkboxes and `language-*` code classes, so no
// custom schema is needed. react-markdown v10 dropped the `className` prop — the `.md-doc`
// wrapper (styled in globals.css with the theme tokens) carries the typography.
export default function DocumentViewer({ body }: { body: string }) {
  const clean = body.replace(FRONTMATTER, "");
  return (
    <div className="md-doc">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
        {clean}
      </ReactMarkdown>
    </div>
  );
}
