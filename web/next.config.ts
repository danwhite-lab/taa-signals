import type { NextConfig } from "next";

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

export default nextConfig;
