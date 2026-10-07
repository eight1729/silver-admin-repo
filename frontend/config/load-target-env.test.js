const assert = require("node:assert/strict");
const test = require("node:test");

const { loadTargetEnv, targetEnvPath } = require("./load-target-env");

test("Admin target resolves only the repository-local Admin env path", () => {
  assert.match(targetEnvPath("admin"), /silver-admin-repo[\\/].env.admin$/);
  assert.throws(() => targetEnvPath("line"), /unsupported frontend target/);
});

test("Admin target loads only public variables", () => {
  const env = { APP_ENV: "local" };
  loadTargetEnv("admin", {
    env,
    envPath: "unused",
    existsSync: () => true,
    readFileSync: () => "NEXT_PUBLIC_ADMIN_API_BASE_URL=http://example.invalid\nPRIVATE_TOKEN=secret\n",
  });
  assert.equal(env.NEXT_PUBLIC_ADMIN_API_BASE_URL, "http://example.invalid");
  assert.equal(env.PRIVATE_TOKEN, undefined);
});

const { appEnvironment, rejectNextDotenv, validatePublicEnv } = require("./load-target-env");

test("production never stats or reads owner dotenv and cannot fill missing public values", () => {
  const env = { APP_ENV: "production" };
  const forbidden = () => { throw new Error("unexpected dotenv IO"); };
  loadTargetEnv("admin", { env, existsSync: forbidden, readFileSync: forbidden });
  assert.throws(() => validatePublicEnv(env), /API_BASE_URL/);
});

test("local owner dotenv cannot override process environment, even empty values", () => {
  const env = { APP_ENV: " LOCAL ", NEXT_PUBLIC_ADMIN_API_BASE_URL: "" };
  loadTargetEnv("admin", { env, existsSync: () => true,
    readFileSync: () => "APP_ENV=production\nNEXT_PUBLIC_ADMIN_API_BASE_URL=https://local.invalid\nNEXT_PUBLIC_GOOGLE_CLIENT_ID=fixture-client\n" });
  assert.equal(env.APP_ENV, "local");
  assert.equal(env.NEXT_PUBLIC_ADMIN_API_BASE_URL, "");
  assert.equal(env.NEXT_PUBLIC_GOOGLE_CLIENT_ID, "fixture-client");
  assert.throws(() => validatePublicEnv(env), /API_BASE_URL/);
});

test("unsupported or missing APP_ENV fails before owner IO", () => {
  for (const APP_ENV of [undefined, "", "staging", "development", "demo", "test", "unknown"]) {
    assert.throws(() => loadTargetEnv("admin", { env: { APP_ENV },
      existsSync: () => { assert.fail("dotenv access"); } }), /APP_ENV/);
  }
  assert.equal(appEnvironment(" Production "), "production");
});

test("Next standard dotenv is rejected by filename before Next starts", () => {
  const path = require("path");
  for (const name of [".env", ".env.local", ".env.production", ".env.production.local", ".env.development", ".env.test.local"]) {
    assert.throws(() => rejectNextDotenv("target", p => path.basename(p) === name), /dotenv files are unsupported/);
  }
  assert.doesNotThrow(() => rejectNextDotenv("target", () => false));
});

test("public settings require Google and explicit API URL; generic fallback is preserved", () => {
  const env = { APP_ENV: "local", NEXT_PUBLIC_ADMIN_API_BASE_URL: "http://127.0.0.1:8082", NEXT_PUBLIC_GOOGLE_CLIENT_ID: "public-fixture" };
  assert.doesNotThrow(() => validatePublicEnv(env));
  assert.throws(() => validatePublicEnv({ ...env, APP_ENV: "production" }), /HTTPS/);
  assert.throws(() => validatePublicEnv({ ...env, NEXT_PUBLIC_GOOGLE_CLIENT_ID: "" }), /GOOGLE_CLIENT_ID/);
  assert.doesNotThrow(() => validatePublicEnv({ ...env, NEXT_PUBLIC_ADMIN_API_BASE_URL: undefined, NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8082" }));
  assert.throws(() => validatePublicEnv({ ...env, NEXT_PUBLIC_ADMIN_API_BASE_URL: "", NEXT_PUBLIC_API_BASE_URL: "https://fallback.invalid" }), /API_BASE_URL/);
});
