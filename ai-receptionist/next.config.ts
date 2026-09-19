import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        // The widget is embedded on a client's own website, so it must be
        // framable from anywhere. Everything else keeps the default headers.
        source: "/widget",
        headers: [{ key: "Content-Security-Policy", value: "frame-ancestors *" }],
      },
      {
        source: "/embed.js",
        headers: [{ key: "Access-Control-Allow-Origin", value: "*" }],
      },
    ];
  },
};

export default nextConfig;
