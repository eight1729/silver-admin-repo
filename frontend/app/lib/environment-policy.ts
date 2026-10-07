export type KnownAppEnvironment =
  | "local"
  | "production";

export function normalizedAppEnvironment(value: string | undefined): KnownAppEnvironment {
  const normalized = value?.trim().toLowerCase();
  if (normalized !== "local" && normalized !== "production") {
    throw new Error("APP_ENV must be explicitly set to local or production");
  }
  return normalized;
}

export function environmentLabel(value: string | undefined): string {
  return normalizedAppEnvironment(value) === "local" ? "ローカル開発環境" : "本番環境";
}
