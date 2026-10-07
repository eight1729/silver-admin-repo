from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from app.core.environment import application_environment

class SharedSettings(BaseSettings):
    app_env: str
    database_url: str

    _environment = field_validator("app_env", mode="before")(application_environment)

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )
