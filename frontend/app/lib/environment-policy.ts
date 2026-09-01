export type KnownAppEnvironment =
  | "local"
  | "development"
  | "demo"
  | "staging"
  | "production";

export function normalizedAppEnvironment(value: string | undefined): string {
  return value?.trim().toLowerCase() ?? "";
}

export function allowsLiffTokenCheck(value: string | undefined): boolean {
  const environment = normalizedAppEnvironment(value);
  return environment === "local" || environment === "development";
}

export function isStagingEnvironment(value: string | undefined): boolean {
  return normalizedAppEnvironment(value) === "staging";
}

export function requiresLiffAuthentication(value: string | undefined): boolean {
  const environment = normalizedAppEnvironment(value);
  return environment === "staging" || environment === "production";
}

export function allowsDemoReset(value: string | undefined): boolean {
  const environment = normalizedAppEnvironment(value);
  return (
    environment === "local" ||
    environment === "development" ||
    environment === "demo"
  );
}

export type LegacyLiffRouteAction = "next" | "redirect" | "not_found";

export function legacyLiffRouteAction(
  value: string | undefined,
): LegacyLiffRouteAction {
  const environment = normalizedAppEnvironment(value);
  if (environment === "staging") return "redirect";
  if (
    environment === "local" ||
    environment === "development" ||
    environment === "demo"
  ) {
    return "next";
  }
  return "not_found";
}
