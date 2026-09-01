from pydantic_settings import BaseSettings, SettingsConfigDict

class SharedSettings(BaseSettings):
    app_env: str = "local"
    database_url: str

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )
