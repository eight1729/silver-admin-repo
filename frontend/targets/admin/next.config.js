const { loadTargetEnv, rejectNextDotenv, validatePublicEnv } = require("../../config/load-target-env");

rejectNextDotenv(__dirname);
loadTargetEnv("admin");
validatePublicEnv();

module.exports = { experimental: { externalDir: true }, distDir: ".next-admin" };
