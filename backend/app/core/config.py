"""Compatibility import; never load a second root dotenv configuration."""

from app.core.settings_admin import AdminSettings as Settings, admin_settings as settings
