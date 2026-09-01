const assert = require("node:assert/strict");
const test = require("node:test");

const { loadTargetEnv, targetEnvPath } = require("./load-target-env");

test("Admin target resolves only the repository-local Admin env path", () => {
  assert.match(targetEnvPath("admin"), /silver-admin-repo[\\/].env.admin$/);
  assert.throws(() => targetEnvPath("line"), /unsupported frontend target/);
});

test("Admin target loads only public variables", () => {
  const env = {};
  loadTargetEnv("admin", {
    env,
    envPath: "unused",
    existsSync: () => true,
    readFileSync: () => "NEXT_PUBLIC_ADMIN_API_BASE_URL=http://example.invalid\nPRIVATE_TOKEN=secret\n",
  });
  assert.equal(env.NEXT_PUBLIC_ADMIN_API_BASE_URL, "http://example.invalid");
  assert.equal(env.PRIVATE_TOKEN, undefined);
});
