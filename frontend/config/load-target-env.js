const fs = require("fs");
const path = require("path");

const TARGETS = new Set(["admin"]);
const PUBLIC_KEY = /^(?:APP_ENV|NEXT_PUBLIC_[A-Z0-9_]+)$/;

function targetEnvPath(target) {
  if (!TARGETS.has(target)) throw new Error("unsupported frontend target");
  return path.resolve(__dirname, "../..", `.env.${target}`);
}

function loadTargetEnv(target, options = {}) {
  const env = options.env ?? process.env;
  // APP_ENV must come from the launcher, never from a local file in production.
  const environment = appEnvironment(env.APP_ENV);
  env.APP_ENV = environment;
  const envPath = options.envPath ?? targetEnvPath(target);
  if (environment === "production") return envPath;
  const existsSync = options.existsSync ?? fs.existsSync;
  const readFileSync = options.readFileSync ?? fs.readFileSync;
  if (!existsSync(envPath)) return envPath;

  for (const line of readFileSync(envPath, "utf-8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const separator = trimmed.indexOf("=");
    if (separator <= 0) continue;
    const key = trimmed.slice(0, separator).trim();
    if (!PUBLIC_KEY.test(key) || Object.prototype.hasOwnProperty.call(env, key)) {
      continue;
    }
    const raw = trimmed.slice(separator + 1).trim();
    env[key] = raw.replace(/^(["'])(.*)\1$/, "$2");
  }
  return envPath;
}

function appEnvironment(value) {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (normalized !== "local" && normalized !== "production") {
    throw new Error("APP_ENV must be explicitly set to local or production");
  }
  return normalized;
}

function rejectNextDotenv(targetDirectory, existsSync = fs.existsSync) {
  // Next reads these BEFORE next.config.js. The canonical launcher checks only
  // filenames, before loading Next, so no standard dotenv is ever read.
  for (const name of [".env", ".env.local", ...["development", "production", "test"].flatMap(
    mode => [`.env.${mode}`, `.env.${mode}.local`])]) {
    if (existsSync(path.join(targetDirectory, name))) {
      throw new Error("Next target dotenv files are unsupported; use process env or the local owner dotenv");
    }
  }
}

function validatePublicEnv(env = process.env) {
  const environment = appEnvironment(env.APP_ENV);
  const base = env.NEXT_PUBLIC_ADMIN_API_BASE_URL ?? env.NEXT_PUBLIC_API_BASE_URL ?? "";
  if (!base || base !== base.trim()) throw new Error("NEXT_PUBLIC_ADMIN_API_BASE_URL is required");
  let url;
  try { url = new URL(base); } catch { throw new Error("Admin API URL is invalid"); }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash
      || (environment === "production" && url.protocol !== "https:")) {
    throw new Error("Admin API URL must use HTTPS in production and contain no credentials");
  }
  if (!env.NEXT_PUBLIC_GOOGLE_CLIENT_ID?.trim()) throw new Error("NEXT_PUBLIC_GOOGLE_CLIENT_ID is required");
}

module.exports = { loadTargetEnv, targetEnvPath, appEnvironment, rejectNextDotenv, validatePublicEnv };
