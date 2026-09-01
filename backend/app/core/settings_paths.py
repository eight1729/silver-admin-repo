"""Canonical source-based paths used by backend settings."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ROOT_ENV_FILE = REPOSITORY_ROOT / ".env"
LINE_ENV_FILE = REPOSITORY_ROOT / ".env.line"
ADMIN_ENV_FILE = REPOSITORY_ROOT / ".env.admin"
