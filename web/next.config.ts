import type { NextConfig } from "next";

// Static export: `next build` emits a fully static site in web/out/, which the
// FastAPI launcher (`jobcut serve`) serves directly — no Node at runtime.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true, // so /applications/ resolves to applications/index.html when served as files
  images: { unoptimized: true },
};

export default nextConfig;
