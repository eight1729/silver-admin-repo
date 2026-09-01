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
  const envPath = options.envPath ?? targetEnvPath(target);
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

module.exports = { loadTargetEnv, targetEnvPath };
