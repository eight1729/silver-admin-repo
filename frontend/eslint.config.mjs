import next from "@next/eslint-plugin-next";
import tsParser from "@typescript-eslint/parser";
import reactHooks from "eslint-plugin-react-hooks";

// eslint-config-next's React/import/a11y plugins do not yet declare ESLint 10 support.
// Keep Next recommendations and the traditional Hooks rules without compiler rules.
export default [
  { ignores: ["**/node_modules/**", "**/.next/**", "**/.next-admin/**", "**/.next-line/**"] },
  {
    files: ["**/*.{js,mjs,cjs,ts,tsx}"],
    languageOptions: { parser: tsParser, parserOptions: { ecmaFeatures: { jsx: true } } },
    plugins: { "@next/next": next, "react-hooks": reactHooks },
    settings: { next: { rootDir: "targets/admin/" } },
    rules: {
      ...next.configs.recommended.rules,
      ...next.configs["core-web-vitals"].rules,
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
  {
    // These tests create a local CommonJS module object inside an isolated VM.
    // They do not overwrite Next's module binding; keep every other rule active.
    files: ["app/admin/*.test.ts"],
    rules: { "@next/next/no-assign-module-variable": "off" },
  },
];
