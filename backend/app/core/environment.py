"""Business runtime environments; independent of test runners and NODE_ENV."""

LOCAL_MAX_SELECTED_RECIPIENTS = 10


def application_environment(value: str | None) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if normalized not in {"local", "production"}:
        raise ValueError("APP_ENV must be explicitly set to local or production")
    return normalized
