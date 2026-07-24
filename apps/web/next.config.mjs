/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Build fails on a type error rather than shipping one. The alternative
  // setting exists and is a trap.
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },
};

export default nextConfig;
