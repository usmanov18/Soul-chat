/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    // The browser only ever talks to this origin; /api is proxied to FastAPI.
    // In Docker the nginx edge does the same thing for production traffic.
    const target = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${target}/api/:path*` },
      { source: "/openapi.json", destination: `${target}/openapi.json` },
    ];
  },
};

export default nextConfig;