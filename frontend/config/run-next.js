// Supported dev/build/start entrypoint: establish the dotenv boundary before Next.
const path = require("path");
const { loadTargetEnv, rejectNextDotenv, validatePublicEnv } = require("./load-target-env");
const command = process.argv[2];
if (!["dev", "build", "start", "lint"].includes(command)) throw new Error("Unsupported Next command");
const target = path.resolve(__dirname, "../targets/admin");
rejectNextDotenv(target);
loadTargetEnv("admin");
validatePublicEnv();
const next = require.resolve("next/dist/bin/next");
process.argv = [process.execPath, next, command, target, ...process.argv.slice(3)];
require(next);
