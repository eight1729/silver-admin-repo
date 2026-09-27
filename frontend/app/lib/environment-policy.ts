export type KnownAppEnvironment =
  | "local"
  | "development"
  | "demo"
  | "staging"
  | "production";

export function normalizedAppEnvironment(value: string | undefined): string {
  return value?.trim().toLowerCase() ?? "";
}

export function isStagingEnvironment(value: string | undefined): boolean {
  return normalizedAppEnvironment(value) === "staging";
}
