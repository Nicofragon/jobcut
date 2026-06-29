"use client";

import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

// Renders a prep/debrief/study document body as sanitised markdown. `rehype-sanitize`
// (GitHub default schema) is non-negotiable: doc bodies travel in the portable jobcut.db
// and could be shared, so raw HTML (`<img onerror=…>`) must never execute. The default
// schema already permits GFM task-list checkboxes and `language-*` code classes, so no
// custom schema is needed. react-markdown v10 dropped the `className` prop — the `.md-doc`
// wrapper (styled in globals.css with the theme tokens) carries the typography.
export default function DocumentViewer({ body }: { body: string }) {
  return (
    <div className="md-doc">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
        {body}
      </ReactMarkdown>
    </div>
  );
}
