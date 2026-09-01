
const fs = require("fs");
const path = require("path");


const ALLOWED_KEYS = ["APP_ENV", "NEXT_PUBLIC_LIFF_ID", "NEXT_PUBLIC_API_BASE_URL"];

const rootEnvPath = path.resolve(__dirname, "../.env");
if (fs.existsSync(rootEnvPath)) {
  const lines = fs.readFileSync(rootEnvPath, "utf-8").split("\n");
  for (const line of lines) {
    const trimmed = line.trim();

    if (!trimmed || trimmed.startsWith("#")) continue;
    for (const key of ALLOWED_KEYS) {
      if (!trimmed.startsWith(`${key}=`)) continue;

      if (process.env[key]) break;
      const raw = trimmed.slice(`${key}=`.length).trim();

      process.env[key] = raw.replace(/^["']|["']$/g, "");
      break;
    }
  }
}

const nextConfig = {};

module.exports = nextConfig;
