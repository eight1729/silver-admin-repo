const { loadTargetEnv, rejectNextDotenv, validatePublicEnv } = require("../../config/load-target-env");

rejectNextDotenv(__dirname);
loadTargetEnv("admin");
validatePublicEnv();

module.exports = {
  experimental: { externalDir: true },
  distDir: ".next-admin",
  ...(process.env.APP_ENV === "local" ? { allowedDevOrigins: ["127.0.0.1"] } : {}),
};
