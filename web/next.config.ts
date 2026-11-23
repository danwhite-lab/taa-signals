import type { NextConfig } from "next";
import { resolve } from "node:path";
import { healthRevision } from "./build/health-revision";

const development = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = development
  ? {
      async rewrites() {
        return [
          {
            source: "/api/:path*",
            destination: "http://127.0.0.1:8000/api/:path*",
          },
        ];
      },
    }
  : { output: "export", trailingSlash: true };

nextConfig.env = {
  NEXT_PUBLIC_STRATEGY_HEALTH_REVISION: healthRevision(resolve(__dirname, "..")),
};

export default nextConfig;
