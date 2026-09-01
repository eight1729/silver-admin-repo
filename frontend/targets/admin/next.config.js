const { loadTargetEnv } = require("../../config/load-target-env");

loadTargetEnv("admin");

module.exports = { experimental: { externalDir: true }, distDir: ".next-admin" };
