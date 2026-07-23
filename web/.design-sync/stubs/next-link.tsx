// design-sync render stub for next/link — renders a plain anchor so components
// that use <Link> mount correctly in standalone previews (no Next router needed).
import * as React from "react";

type LinkProps = {
  href: string | { pathname?: string };
  children?: React.ReactNode;
} & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href">;

export default function Link({ href, children, ...rest }: LinkProps) {
  const url = typeof href === "string" ? href : (href?.pathname ?? "#");
  return (
    <a href={url} {...rest}>
      {children}
    </a>
  );
}
